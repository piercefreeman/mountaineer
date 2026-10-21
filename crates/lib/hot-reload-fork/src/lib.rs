//! Fork-based Python hot reload with preloaded, fork-safe imports.

#![cfg(unix)]
#![warn(missing_docs)]

use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeSet,
    io,
    path::PathBuf,
    process::{ExitStatus, Stdio},
};
use tokio::{
    io::AsyncWriteExt,
    process::{Child, ChildStdin, Command},
    time::{timeout, Duration},
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
        self.send(&CommandMessage::Start {
            generation,
            payload_path,
        })
        .await?;
        Ok(Worker { generation })
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
    /// Fork workers are supervised by their parent, so this waits forever.
    pub async fn wait(&mut self) -> Result<ExitStatus> {
        std::future::pending().await
    }
}

#[derive(Serialize)]
#[serde(tag = "command", rename_all = "snake_case")]
enum CommandMessage {
    Start {
        generation: u64,
        payload_path: PathBuf,
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
