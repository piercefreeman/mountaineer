use notify_debouncer_full::DebouncedEvent;
use std::path::{Component, Path};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum ChangeKind {
    Python,
    Frontend,
    Style,
}

pub(super) fn restart_kind(events: &[DebouncedEvent]) -> Option<ChangeKind> {
    let mut change_kind = None;
    for path in events.iter().flat_map(|event| &event.event.paths) {
        if ignored_path(path) {
            continue;
        }
        match path.extension().and_then(|extension| extension.to_str()) {
            Some("py") => return Some(ChangeKind::Python),
            Some("js" | "jsx" | "ts" | "tsx" | "mjs" | "cjs" | "json") => {
                change_kind = Some(ChangeKind::Frontend)
            }
            Some("css" | "scss" | "sass") if change_kind.is_none() => {
                change_kind = Some(ChangeKind::Style)
            }
            _ => {}
        }
    }
    change_kind
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
    use std::path::PathBuf;

    #[test]
    fn watcher_ignores_generated_and_dependency_files() {
        let event = |path| DebouncedEvent {
            event: notify_debouncer_full::notify::Event::new(
                notify_debouncer_full::notify::EventKind::Any,
            )
            .add_path(PathBuf::from(path)),
            time: std::time::Instant::now(),
        };

        assert_eq!(
            restart_kind(&[event("example/views/home/page.tsx")]),
            Some(ChangeKind::Frontend)
        );
        assert_eq!(
            restart_kind(&[event("example/views/app/main.css")]),
            Some(ChangeKind::Style)
        );
        assert_eq!(
            restart_kind(&[
                event("example/views/app/main.css"),
                event("example/controllers/home.py")
            ]),
            Some(ChangeKind::Python)
        );
        assert_eq!(
            restart_kind(&[event("example/views/node_modules/react/index.js")]),
            None
        );
    }
}
