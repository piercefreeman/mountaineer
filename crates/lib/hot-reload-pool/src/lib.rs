//! Warm Python process pool for platforms without `fork`.

#![warn(missing_docs)]

use serde::Serialize;
use std::{
    collections::BTreeSet,
    io,
    path::PathBuf,
    process::{ExitStatus, Stdio},
};
use tokio::{
    io::AsyncWriteExt,
    process::{Child, ChildStdin, Command},
};

const WARM_WORKER: &str = include_str!("../assets/warm_worker.py");

/// Error returned by the warm reload pool.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// A child-process or pipe operation failed.
    #[error(transparent)]
    Io(#[from] io::Error),

    /// A reload command or import set could not be encoded.
    #[error(transparent)]
    Serialize(#[from] serde_json::Error),

    /// The warm pool could not satisfy a lifecycle operation.
    #[error("{0}")]
    Invalid(String),
}

/// Result returned by the warm reload pool.
pub type Result<T> = std::result::Result<T, Error>;

/// Typed configuration for the warm reload pool.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Config {
    /// Python interpreter used for warm workers.
    pub python: String,

    /// Working directory inherited by Python processes.
    pub project_root: PathBuf,

    /// Python modules each worker should pre-import.
    pub imports: BTreeSet<String>,

    /// Number of idle workers kept warm.
    pub size: usize,
}

/// Pool of idle, pre-imported Python workers.
pub struct Pool {
    python: String,
    project_root: PathBuf,
    imports_json: String,
    target_size: usize,
    idle: Vec<WarmProcess>,
}

/// Activated Python backend worker.
pub struct Worker {
    child: Child,
}

struct WarmProcess {
    child: Child,
    stdin: ChildStdin,
}

impl Pool {
    /// Starts and fills a warm worker pool.
    pub fn spawn(config: Config) -> Result<Self> {
        let mut pool = Self {
            python: config.python,
            project_root: config.project_root,
            imports_json: serde_json::to_string(&config.imports)?,
            target_size: config.size.max(1),
            idle: Vec::new(),
        };
        pool.replenish()?;
        Ok(pool)
    }

    /// Activates one worker and replenishes the idle pool.
    pub async fn start(&mut self, generation: u64, payload_path: PathBuf) -> Result<Worker> {
        let mut process = self
            .idle
            .pop()
            .ok_or_else(|| Error::Invalid("warm process pool is empty".to_string()))?;
        send_json_line(
            &mut process.stdin,
            &CommandMessage::Start {
                generation,
                payload_path,
            },
        )
        .await?;
        drop(process.stdin);
        self.replenish()?;
        Ok(Worker {
            child: process.child,
        })
    }

    /// Stops one activated worker.
    pub async fn stop(&mut self, mut worker: Worker) -> Result<()> {
        if worker.child.try_wait()?.is_none() {
            worker.child.start_kill()?;
        }
        worker.child.wait().await?;
        Ok(())
    }

    /// The pool has no persistent supervisor process, so this waits forever.
    pub async fn wait(&mut self) -> Result<ExitStatus> {
        std::future::pending().await
    }

    /// Stops every idle worker.
    pub async fn shutdown(&mut self) -> Result<()> {
        for process in &mut self.idle {
            if process.child.try_wait()?.is_none() {
                process.child.start_kill()?;
            }
            process.child.wait().await?;
        }
        self.idle.clear();
        Ok(())
    }

    fn replenish(&mut self) -> Result<()> {
        while self.idle.len() < self.target_size {
            let mut child = Command::new(&self.python)
                .args(["-c", WARM_WORKER])
                .arg(&self.imports_json)
                .current_dir(&self.project_root)
                .stdin(Stdio::piped())
                .stdout(Stdio::inherit())
                .stderr(Stdio::inherit())
                .kill_on_drop(true)
                .spawn()?;
            let stdin = child
                .stdin
                .take()
                .ok_or_else(|| Error::Invalid("failed to open warm-worker stdin".to_string()))?;
            self.idle.push(WarmProcess { child, stdin });
        }
        Ok(())
    }
}

impl Worker {
    /// Waits for the activated backend process to exit.
    pub async fn wait(&mut self) -> Result<ExitStatus> {
        Ok(self.child.wait().await?)
    }
}

#[derive(Serialize)]
#[serde(tag = "command", rename_all = "snake_case")]
enum CommandMessage {
    Start {
        generation: u64,
        payload_path: PathBuf,
    },
}

async fn send_json_line(stdin: &mut ChildStdin, command: &CommandMessage) -> Result<()> {
    let mut payload = serde_json::to_vec(command)?;
    payload.push(b'\n');
    stdin.write_all(&payload).await?;
    stdin.flush().await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn idle_workers_shutdown_cleanly() {
        let project = tempfile::tempdir().unwrap();
        let mut pool = Pool::spawn(Config {
            python: "python".to_string(),
            project_root: project.path().to_path_buf(),
            imports: BTreeSet::new(),
            size: 2,
        })
        .unwrap();

        pool.shutdown().await.unwrap();
    }
}
