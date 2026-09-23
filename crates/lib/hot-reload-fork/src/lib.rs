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

    #[cfg(target_os = "macos")]
    fn write_completed_thread_imports(project: &std::path::Path) -> BTreeSet<String> {
        let modules = [
            (
                "python_thread",
                "import threading\n\
                 thread = threading.Thread(target=lambda: None)\n\
                 thread.start()\n\
                 thread.join()\n",
            ),
            (
                "executor_thread",
                r#"
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor() as executor:
    executor.submit(lambda: None).result()
"#,
            ),
            (
                "native_thread",
                r#"
import ctypes

lib = ctypes.CDLL(None)
callback_type = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)
callback = callback_type(lambda _: None)
lib.pthread_create.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                              callback_type, ctypes.c_void_p]
lib.pthread_create.restype = ctypes.c_int
lib.pthread_join.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
lib.pthread_join.restype = ctypes.c_int
thread = ctypes.c_void_p()
assert lib.pthread_create(ctypes.byref(thread), None, callback, None) == 0
assert lib.pthread_join(thread, None) == 0
"#,
            ),
        ];
        for (name, code) in modules {
            fs::write(project.join(format!("{name}.py")), code).unwrap();
        }
        modules.iter().map(|(name, _)| name.to_string()).collect()
    }

    #[cfg(target_os = "macos")]
    #[tokio::test]
    async fn probe_excludes_imports_whose_threads_have_exited() {
        let project = tempfile::tempdir().unwrap();
        let threaded = write_completed_thread_imports(project.path());
        // Sorting after the rejected imports also checks that probes stay isolated.
        fs::write(project.path().join("safe_import.py"), "VALUE = 1\n").unwrap();
        let mut imports = threaded.clone();
        imports.insert("safe_import".to_string());
        let Spawned {
            mut strategy,
            excluded_imports,
        } = Strategy::spawn(Config {
            python: "python".to_string(),
            project_root: project.path().to_path_buf(),
            imports,
        })
        .await
        .unwrap();
        strategy.shutdown().await.unwrap();

        assert_eq!(
            excluded_imports
                .iter()
                .map(|item| item.module.clone())
                .collect::<BTreeSet<_>>(),
            threaded,
        );
        for excluded in excluded_imports {
            assert_eq!(excluded.thread_count, Some(1));
            assert!(!excluded.reason.is_empty());
        }
    }

    #[cfg(target_os = "macos")]
    #[tokio::test]
    async fn forked_workers_defer_threaded_imports_and_use_system_proxies() {
        let project = tempfile::tempdir().unwrap();
        let threaded = write_completed_thread_imports(project.path());
        fs::write(
            project.path().join("safe_import.py"),
            "import os\nPID = os.getpid()\n",
        )
        .unwrap();
        let runtime = project.path().join("mountaineer");
        fs::create_dir(&runtime).unwrap();
        fs::write(runtime.join("__init__.py"), "").unwrap();
        fs::write(
            runtime.join("runtime.py"),
            r#"
import json
import os
import signal
import sys
from pathlib import Path
from urllib.request import getproxies_macosx_sysconf

class RuntimePayload:
    model_validate_json = staticmethod(json.loads)

def serve_runtime(payload):
    assert "safe_import" in sys.modules
    import safe_import
    assert safe_import.PID == os.getppid()
    assert not {"python_thread", "executor_thread", "native_thread"} & sys.modules.keys()
    import python_thread, executor_thread, native_thread
    getproxies_macosx_sysconf()
    result = Path(payload["result"])
    pending = result.with_suffix(".tmp")
    pending.write_text(str(os.getpid()))
    pending.replace(result)
    signal.pause()
"#,
        )
        .unwrap();
        let mut imports = threaded;
        imports.insert("safe_import".to_string());
        let Spawned { mut strategy, .. } = Strategy::spawn(Config {
            python: "python".to_string(),
            project_root: project.path().to_path_buf(),
            imports,
        })
        .await
        .unwrap();
        let mut pids = BTreeSet::new();
        for generation in 1..=2 {
            let result = project.path().join(format!("result-{generation}"));
            let payload = project.path().join(format!("payload-{generation}.json"));
            fs::write(&payload, serde_json::json!({"result": result}).to_string()).unwrap();
            let worker = strategy.start(generation, payload).await.unwrap();
            let ready = timeout(Duration::from_secs(5), async {
                while !result.exists() {
                    if let Some(status) = strategy.child.try_wait().unwrap() {
                        return Err(format!("fork parent exited with {status}"));
                    }
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
                Ok(())
            })
            .await;
            if !matches!(ready, Ok(Ok(()))) {
                strategy.shutdown().await.unwrap();
                panic!("worker failed to use macOS system proxies: {ready:?}");
            }
            pids.insert(fs::read_to_string(result).unwrap());
            strategy.stop(worker).await.unwrap();
        }
        strategy.shutdown().await.unwrap();
        assert_eq!(pids.len(), 2);
    }

    #[cfg(target_os = "macos")]
    #[tokio::test]
    async fn parent_refuses_imports_that_start_threads_only_when_combined() {
        let project = tempfile::tempdir().unwrap();
        fs::write(project.path().join("a_marker.py"), "").unwrap();
        fs::write(
            project.path().join("b_conditional.py"),
            r#"
import sys
import threading

if "a_marker" in sys.modules:
    thread = threading.Thread(target=lambda: None)
    thread.start()
    thread.join()
"#,
        )
        .unwrap();
        let runtime = project.path().join("mountaineer");
        fs::create_dir(&runtime).unwrap();
        fs::write(runtime.join("__init__.py"), "").unwrap();
        fs::write(
            runtime.join("runtime.py"),
            "from pathlib import Path\nPath('worker_started').touch()\n",
        )
        .unwrap();
        let Spawned {
            mut strategy,
            excluded_imports,
        } = Strategy::spawn(Config {
            python: "python".to_string(),
            project_root: project.path().to_path_buf(),
            imports: BTreeSet::from(["a_marker".to_string(), "b_conditional".to_string()]),
        })
        .await
        .unwrap();
        assert!(excluded_imports.is_empty(), "individual probes should pass");
        strategy
            .start(1, project.path().join("unused.json"))
            .await
            .unwrap();
        let status = timeout(Duration::from_secs(5), strategy.wait()).await;
        strategy.shutdown().await.unwrap();
        assert!(!status.unwrap().unwrap().success());
        assert!(!project.path().join("worker_started").exists());
    }

    #[tokio::test]
    async fn probe_excludes_thread_starting_imports() {
        let project = tempfile::tempdir().unwrap();
        fs::write(project.path().join("safe_import.py"), "VALUE = 1\n").unwrap();
        fs::write(
            project.path().join("threaded_import.py"),
            "import threading, time\n\
             threading.Thread(target=lambda: time.sleep(30)).start()\n",
        )
        .unwrap();
        let config = Config {
            python: "python".to_string(),
            project_root: project.path().to_path_buf(),
            imports: BTreeSet::from(["safe_import".to_string(), "threaded_import".to_string()]),
        };
        let probe = timeout(Duration::from_secs(5), probe_imports(&config))
            .await
            .expect("probe waited for an import's non-daemon thread")
            .unwrap();

        assert_eq!(probe.safe, BTreeSet::from(["safe_import".to_string()]));
    }

    #[tokio::test]
    async fn probe_isolates_failed_imports_and_import_output() {
        let project = tempfile::tempdir().unwrap();
        fs::write(
            project.path().join("broken_import.py"),
            "raise RuntimeError('broken')\n",
        )
        .unwrap();
        fs::write(
            project.path().join("exiting_import.py"),
            "import os\nos._exit(0)\n",
        )
        .unwrap();
        fs::write(
            project.path().join("noisy_import.py"),
            "print('import message')\n",
        )
        .unwrap();
        let probe = probe_imports(&Config {
            python: "python".to_string(),
            project_root: project.path().to_path_buf(),
            imports: BTreeSet::from([
                "broken_import".to_string(),
                "exiting_import".to_string(),
                "missing_import".to_string(),
                "noisy_import".to_string(),
            ]),
        })
        .await
        .unwrap();
        assert_eq!(probe.safe, BTreeSet::from(["noisy_import".to_string()]));
        assert_eq!(probe.excluded.len(), 3);
        assert!(probe
            .excluded
            .iter()
            .all(|item| item.thread_count.is_none()));
    }

    #[tokio::test]
    async fn parent_exits_when_an_active_backend_dies() {
        let project = tempfile::tempdir().unwrap();
        let Spawned { mut strategy, .. } = Strategy::spawn(Config {
            python: "python".to_string(),
            project_root: project.path().to_path_buf(),
            imports: BTreeSet::new(),
        })
        .await
        .unwrap();
        strategy
            .start(1, project.path().join("missing.json"))
            .await
            .unwrap();

        let status = timeout(Duration::from_secs(3), strategy.wait())
            .await
            .expect("fork parent did not notice its failed backend")
            .unwrap();

        assert!(!status.success());
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
            strategy.stop(Worker { generation: 1 }).await.unwrap();
            strategy.shutdown().await.unwrap();
        })
        .await
        .expect("fork parent stalled with buffered commands");
    }
}
