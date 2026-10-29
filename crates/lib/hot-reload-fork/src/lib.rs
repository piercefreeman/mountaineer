//! Fork-based Python hot reload with preloaded, fork-safe imports.

#![cfg(unix)]
#![warn(missing_docs)]

use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeSet,
    io,
    os::unix::process::ExitStatusExt,
    path::PathBuf,
    process::{ExitStatus, Stdio},
};
use tokio::{
    io::AsyncWriteExt,
    process::{Child, ChildStdin, Command},
    time::{sleep, timeout, Duration},
};

const FORK_PARENT: &str = include_str!("../assets/fork_parent.py");
const IMPORT_SAFETY_PROBE: &str = include_str!("../assets/import_safety_probe.py");

/// Error returned by the fork reload strategy.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// A child-process or pipe operation failed.
    #[error(transparent)]
    Io(#[from] io::Error),

    /// A reload command or probe result could not be encoded or decoded.
    #[error(transparent)]
    Serialize(#[from] serde_json::Error),

    /// The fork reload protocol could not be started.
    #[error("{0}")]
    Invalid(String),
}

/// Result returned by the fork reload strategy.
pub type Result<T> = std::result::Result<T, Error>;

/// Typed configuration for the fork reload strategy.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Config {
    /// Python interpreter used for the probe and fork parent.
    pub python: String,

    /// Working directory inherited by Python processes.
    pub project_root: PathBuf,

    /// Python modules requested for pre-import.
    pub imports: BTreeSet<String>,
}

/// An import excluded because it was unsafe to retain across `fork`.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
pub struct ExcludedImport {
    /// Python module name.
    pub module: String,

    /// Number of live threads observed after import, when measurable.
    pub thread_count: Option<usize>,

    /// Human-readable exclusion reason.
    pub reason: String,
}

/// Result of starting the fork reload strategy.
pub struct Spawned {
    /// Running fork strategy.
    pub strategy: Strategy,

    /// Requested imports omitted from the fork template.
    pub excluded_imports: Vec<ExcludedImport>,
}

/// Running Python fork parent.
pub struct Strategy {
    child: Child,
    stdin: ChildStdin,
}

/// Active backend generation owned by the fork parent.
pub struct Worker {
    generation: u64,
    exit_status_path: PathBuf,
}

impl Strategy {
    /// Probes requested imports and starts the fork parent.
    pub async fn spawn(config: Config) -> Result<Spawned> {
        let probe = probe_imports(&config).await?;
        let mut child = Command::new(&config.python)
            .args(["-c", FORK_PARENT])
            .arg(serde_json::to_string(&probe.safe)?)
            .current_dir(&config.project_root)
            .stdin(Stdio::piped())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .kill_on_drop(true)
            .spawn()?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| Error::Invalid("failed to open fork-template stdin".to_string()))?;

        Ok(Spawned {
            strategy: Self { child, stdin },
            excluded_imports: probe.excluded,
        })
    }

    /// Starts a backend generation from a serialized runtime payload.
    pub async fn start(&mut self, generation: u64, payload_path: PathBuf) -> Result<Worker> {
        let exit_status_path = payload_path.with_extension(format!("{generation}.exit"));
        self.send(&CommandMessage::Start {
            generation,
            payload_path,
            exit_status_path: exit_status_path.clone(),
        })
        .await?;
        Ok(Worker {
            generation,
            exit_status_path,
        })
    }

    /// Stops one active backend generation.
    pub async fn stop(&mut self, worker: Worker) -> Result<()> {
        self.send(&CommandMessage::Stop {
            generation: worker.generation,
        })
        .await
    }

    /// Waits for an unexpected fork-parent exit.
    pub async fn wait(&mut self) -> Result<ExitStatus> {
        Ok(self.child.wait().await?)
    }

    /// Stops the fork parent and all backend generations.
    pub async fn shutdown(&mut self) -> Result<()> {
        let _ = self.send(&CommandMessage::Exit).await;
        if self.child.try_wait()?.is_none() {
            match timeout(Duration::from_secs(5), self.child.wait()).await {
                Ok(status) => {
                    status?;
                }
                Err(_) => {
                    self.child.start_kill()?;
                    self.child.wait().await?;
                }
            }
        }
        Ok(())
    }

    async fn send(&mut self, command: &CommandMessage) -> Result<()> {
        let mut payload = serde_json::to_vec(command)?;
        payload.push(b'\n');
        self.stdin.write_all(&payload).await?;
        self.stdin.flush().await?;
        Ok(())
    }
}

impl Worker {
    /// Waits for this backend's exit status, reported by the fork parent.
    pub async fn wait(&mut self) -> Result<ExitStatus> {
        loop {
            match tokio::fs::read(&self.exit_status_path).await {
                Ok(contents) => {
                    return Ok(ExitStatus::from_raw(serde_json::from_slice(&contents)?));
                }
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => return Err(error.into()),
            }
            sleep(Duration::from_millis(50)).await;
        }
    }
}

#[derive(Serialize)]
#[serde(tag = "command", rename_all = "snake_case")]
enum CommandMessage {
    Start {
        generation: u64,
        payload_path: PathBuf,
        exit_status_path: PathBuf,
    },
    Stop {
        generation: u64,
    },
    Exit,
}

struct ImportProbe {
    safe: BTreeSet<String>,
    excluded: Vec<ExcludedImport>,
}

#[derive(Deserialize)]
struct ImportProbeResult {
    safe: bool,
    #[serde(flatten)]
    import: ExcludedImport,
}

async fn probe_imports(config: &Config) -> Result<ImportProbe> {
    let mut probe = ImportProbe {
        safe: BTreeSet::new(),
        excluded: Vec::new(),
    };
    for module in &config.imports {
        let output = Command::new(&config.python)
            .args(["-c", IMPORT_SAFETY_PROBE, module])
            .current_dir(&config.project_root)
            .kill_on_drop(true)
            .output()
            .await?;
        if !output.status.success() || output.stdout.is_empty() {
            probe.excluded.push(ExcludedImport {
                module: module.clone(),
                thread_count: None,
                reason: format!("probe exited before reporting ({})", output.status),
            });
            continue;
        }
        let result: ImportProbeResult = serde_json::from_slice(&output.stdout)?;
        if result.safe {
            probe.safe.insert(module.clone());
        } else {
            probe.excluded.push(result.import);
        }
    }
    Ok(probe)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[tokio::test]
    async fn probe_excludes_thread_starting_imports() {
        let project = tempfile::tempdir().unwrap();
        fs::write(project.path().join("safe_import.py"), "VALUE = 1\n").unwrap();
        fs::write(
            project.path().join("threaded_import.py"),
            "import threading, time\n\
             threading.Thread(target=lambda: time.sleep(5), daemon=True).start()\n",
        )
        .unwrap();
        let probe = probe_imports(&Config {
            python: "python".to_string(),
            project_root: project.path().to_path_buf(),
            imports: BTreeSet::from(["safe_import".to_string(), "threaded_import".to_string()]),
        })
        .await
        .unwrap();

        assert_eq!(probe.safe, BTreeSet::from(["safe_import".to_string()]));
    }

    // macOS remembers that a process once had threads, and a forked child then aborts
    // when it first initializes an Objective-C class (grpc's import does this).
    #[cfg(target_os = "macos")]
    #[tokio::test]
    async fn probe_excludes_imports_whose_threads_already_exited_on_macos() {
        let project = tempfile::tempdir().unwrap();
        fs::write(
            project.path().join("joined_thread_import.py"),
            "import threading\n\
             thread = threading.Thread(target=lambda: None)\n\
             thread.start()\n\
             thread.join()\n",
        )
        .unwrap();
        let probe = probe_imports(&Config {
            python: "python".to_string(),
            project_root: project.path().to_path_buf(),
            imports: BTreeSet::from(["joined_thread_import".to_string()]),
        })
        .await
        .unwrap();

        assert!(probe.safe.is_empty());
        assert_eq!(probe.excluded[0].thread_count, Some(1));
    }

    #[tokio::test]
    async fn worker_reports_failure_without_stopping_parent() {
        let project = tempfile::tempdir().unwrap();
        let Spawned { mut strategy, .. } = Strategy::spawn(Config {
            python: "python".to_string(),
            project_root: project.path().to_path_buf(),
            imports: BTreeSet::new(),
        })
        .await
        .unwrap();
        let mut worker = strategy
            .start(1, project.path().join("missing.json"))
            .await
            .unwrap();

        let status = timeout(Duration::from_secs(3), worker.wait())
            .await
            .expect("worker did not report its exit")
            .unwrap();

        assert_eq!(status.code(), Some(1));
        assert_eq!(worker.wait().await.unwrap(), status);
        assert!(timeout(Duration::from_millis(200), strategy.wait())
            .await
            .is_err());
        strategy.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn import_error_preserves_running_backend_and_allows_recovery() {
        let project = tempfile::tempdir().unwrap();
        let package = project.path().join("mountaineer");
        fs::create_dir(&package).unwrap();
        fs::write(package.join("__init__.py"), "").unwrap();
        fs::write(
            package.join("runtime.py"),
            r#"
import json
import signal
from pathlib import Path

class RuntimePayload:
    model_validate_json = staticmethod(json.loads)

def serve_runtime(payload):
    from app import VALUE
    Path(payload).write_text(VALUE)
    signal.pause()
"#,
        )
        .unwrap();
        let app = project.path().join("app.py");
        let dependency = project.path().join("dependency.py");
        fs::write(&app, "from dependency import VALUE\n").unwrap();
        fs::write(&dependency, "VALUE = 'original'\n").unwrap();
        let ready = project.path().join("ready.txt");
        let payload = project.path().join("payload.json");
        fs::write(&payload, serde_json::to_vec(&ready).unwrap()).unwrap();

        let Spawned { mut strategy, .. } = Strategy::spawn(Config {
            python: "python".to_string(),
            project_root: project.path().to_path_buf(),
            imports: BTreeSet::new(),
        })
        .await
        .unwrap();
        let mut active = strategy.start(1, payload.clone()).await.unwrap();
        wait_for_contents(&ready, "original").await;

        fs::write(&app, "from dependency import RENAMED as VALUE\n").unwrap();
        let mut failed = strategy.start(2, payload.clone()).await.unwrap();
        let status = timeout(Duration::from_secs(3), failed.wait())
            .await
            .expect("failed import did not produce a worker exit")
            .unwrap();
        assert_eq!(status.code(), Some(1));
        assert!(timeout(Duration::from_millis(200), strategy.wait())
            .await
            .is_err());
        assert!(timeout(Duration::from_millis(200), active.wait())
            .await
            .is_err());
        strategy.stop(failed).await.unwrap();

        fs::write(&dependency, "RENAMED = 'recovered'\n").unwrap();
        let mut recovered = strategy.start(3, payload).await.unwrap();
        wait_for_contents(&ready, "recovered").await;
        strategy.stop(active).await.unwrap();
        assert!(timeout(Duration::from_millis(200), recovered.wait())
            .await
            .is_err());
        strategy.stop(recovered).await.unwrap();
        strategy.shutdown().await.unwrap();
    }

    async fn wait_for_contents(path: &std::path::Path, expected: &str) {
        timeout(Duration::from_secs(3), async {
            while fs::read_to_string(path).ok().as_deref() != Some(expected) {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .expect("backend did not finish importing the application");
    }

    #[tokio::test]
    async fn parent_processes_back_to_back_commands() {
        let project = tempfile::tempdir().unwrap();
        let Spawned { mut strategy, .. } = Strategy::spawn(Config {
            python: "python".to_string(),
            project_root: project.path().to_path_buf(),
            imports: BTreeSet::new(),
        })
        .await
        .unwrap();

        timeout(Duration::from_secs(1), async {
            strategy
                .stop(Worker {
                    generation: 1,
                    exit_status_path: project.path().join("unused.exit"),
                })
                .await
                .unwrap();
            strategy.shutdown().await.unwrap();
        })
        .await
        .expect("fork parent stalled with buffered commands");
    }
}
