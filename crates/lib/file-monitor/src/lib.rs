//! Debounced, classified file changes for Mountaineer development.

#![warn(missing_docs)]

use notify_debouncer_full::{
    new_debouncer,
    notify::{Error as NotifyError, RecommendedWatcher, RecursiveMode},
    DebounceEventResult, DebouncedEvent, Debouncer, RecommendedCache,
};
use std::{
    fmt,
    path::{Component, Path, PathBuf},
    time::Duration,
};
use tokio::sync::mpsc::{self, UnboundedReceiver};

/// Filesystem roots and debounce interval monitored during development.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Config {
    /// Python package root monitored recursively.
    pub python_root: PathBuf,

    /// Frontend root monitored recursively when it is outside `python_root`.
    pub frontend_root: PathBuf,

    /// Quiet period used to combine related filesystem events.
    pub debounce: Duration,
}

/// A semantic category of source change.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ChangeKind {
    /// Python source changed.
    Python,

    /// JavaScript, TypeScript, or JSON changed.
    Frontend,

    /// CSS or a CSS preprocessor source changed.
    Style,
}

/// One or more filesystem watcher errors.
#[derive(Debug)]
pub struct Error(Vec<NotifyError>);

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        for (index, error) in self.0.iter().enumerate() {
            if index > 0 {
                formatter.write_str("\n")?;
            }
            write!(formatter, "watch error: {error}")?;
        }
        Ok(())
    }
}

impl std::error::Error for Error {}

impl From<NotifyError> for Error {
    fn from(error: NotifyError) -> Self {
        Self(vec![error])
    }
}

/// Result returned by the file monitor.
pub type Result<T> = std::result::Result<T, Error>;

/// Active debounced filesystem monitor.
pub struct Monitor {
    _debouncer: Debouncer<RecommendedWatcher, RecommendedCache>,
    events: UnboundedReceiver<DebounceEventResult>,
}

impl Monitor {
    /// Starts monitoring the configured roots.
    pub fn start(config: Config) -> Result<Self> {
        let (sender, events) = mpsc::unbounded_channel();
        let mut debouncer = new_debouncer(config.debounce, None, move |event| {
            let _ = sender.send(event);
        })?;
        debouncer.watch(&config.python_root, RecursiveMode::Recursive)?;
        if !config.frontend_root.starts_with(&config.python_root) {
            debouncer.watch(&config.frontend_root, RecursiveMode::Recursive)?;
        }
        Ok(Self {
            _debouncer: debouncer,
            events,
        })
    }

    /// Waits for the next relevant source change or watcher error.
    pub async fn next(&mut self) -> Option<Result<ChangeKind>> {
        loop {
            match self.events.recv().await? {
                Ok(events) => {
                    if let Some(change) = classify(&events) {
                        return Some(Ok(change));
                    }
                }
                Err(errors) => return Some(Err(Error(errors))),
            }
        }
    }
}

fn classify(events: &[DebouncedEvent]) -> Option<ChangeKind> {
    let mut change = None;
    for path in events
        .iter()
        .filter(|event| !event.event.kind.is_access())
        .flat_map(|event| &event.event.paths)
    {
        if ignored_path(path) {
            continue;
        }
        match path.extension().and_then(|extension| extension.to_str()) {
            Some("py") => return Some(ChangeKind::Python),
            Some("js" | "jsx" | "ts" | "tsx" | "mjs" | "cjs" | "json") => {
                change = Some(ChangeKind::Frontend)
            }
            Some("css" | "scss" | "sass") if change.is_none() => change = Some(ChangeKind::Style),
            _ => {}
        }
    }
    change
}

fn ignored_path(path: &Path) -> bool {
    path.components().any(|component| {
        matches!(
            component,
            Component::Normal(name)
                if matches!(
                    name.to_str(),
                    Some(
                        ".git"
                            | ".venv"
                            | ".mountaineer"
                            | ".mountaineer-vite"
                            | "node_modules"
                            | "__pycache__"
                    )
                )
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn event(path: &str) -> DebouncedEvent {
        DebouncedEvent {
            event: notify_debouncer_full::notify::Event::new(
                notify_debouncer_full::notify::EventKind::Any,
            )
            .add_path(PathBuf::from(path)),
            time: std::time::Instant::now(),
        }
    }

    #[test]
    fn classifies_relevant_changes_and_ignores_dependencies() {
        assert_eq!(
            classify(&[event("example/views/home/page.tsx")]),
            Some(ChangeKind::Frontend)
        );
        assert_eq!(
            classify(&[event("example/views/app/main.css")]),
            Some(ChangeKind::Style)
        );
        assert_eq!(
            classify(&[
                event("example/views/app/main.css"),
                event("example/controllers/home.py")
            ]),
            Some(ChangeKind::Python)
        );
        assert_eq!(
            classify(&[event("example/views/node_modules/react/index.js")]),
            None
        );
    }

    #[test]
    fn ignores_source_file_reads() {
        let mut read = event("example/controllers/home.py");
        read.event.kind = notify_debouncer_full::notify::EventKind::Access(
            notify_debouncer_full::notify::event::AccessKind::Open(
                notify_debouncer_full::notify::event::AccessMode::Read,
            ),
        );

        assert_eq!(classify(&[read]), None);
    }

    #[tokio::test]
    async fn monitors_a_separate_frontend_root() {
        let python_root = tempfile::tempdir().unwrap();
        let frontend_root = tempfile::tempdir().unwrap();
        let mut monitor = Monitor::start(Config {
            python_root: python_root.path().to_path_buf(),
            frontend_root: frontend_root.path().to_path_buf(),
            debounce: Duration::from_millis(20),
        })
        .unwrap();

        fs::write(
            frontend_root.path().join("page.tsx"),
            "export default null;\n",
        )
        .unwrap();

        let change = tokio::time::timeout(Duration::from_secs(5), monitor.next())
            .await
            .unwrap()
            .unwrap()
            .unwrap();
        assert_eq!(change, ChangeKind::Frontend);
    }
}
