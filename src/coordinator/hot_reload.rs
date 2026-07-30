use super::{
    config::CoordinatorConfig,
    invalid,
    output::{detail, emphasis, status, status_with_details, Tone},
    Result,
};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeSet, path::PathBuf, process::Stdio};
#[cfg(unix)]
use tokio::time::{timeout, Duration};
use tokio::{
    io::AsyncWriteExt,
    process::{Child, ChildStdin, Command},
};

const DISCOVER_IMPORTS: &str = include_str!("../coordinator_assets/discover_imports.py");
#[cfg(unix)]
const FORK_PARENT: &str = include_str!("../coordinator_assets/fork_parent.py");
#[cfg(unix)]
const IMPORT_SAFETY_PROBE: &str = include_str!("../coordinator_assets/import_safety_probe.py");
#[cfg(windows)]
const WARM_WORKER: &str = include_str!("../coordinator_assets/warm_worker.py");

#[derive(Debug, Serialize)]
#[serde(tag = "command", rename_all = "snake_case")]
enum LayerCommand {
    Start {
        generation: u64,
        payload_path: PathBuf,
    },
    #[cfg(unix)]
    Stop { generation: u64 },
    #[cfg(unix)]
    Exit,
}

pub(super) struct PythonHotReload {
    pub(super) imports: BTreeSet<String>,
    #[cfg(unix)]
    strategy: ForkStrategy,
    #[cfg(windows)]
    strategy: WarmPoolStrategy,
}

pub(super) struct ActiveWorker {
    #[cfg(unix)]
    generation: u64,
    #[cfg(windows)]
    child: Child,
}

#[cfg(unix)]
#[derive(Deserialize)]
struct ImportSafetyProbe {
    safe: BTreeSet<String>,
    excluded: Vec<ExcludedImport>,
}

#[cfg(unix)]
#[derive(Deserialize)]
struct ExcludedImport {
    module: String,
    thread_count: Option<usize>,
    reason: String,
}

impl PythonHotReload {
    pub(super) async fn new(config: &CoordinatorConfig, imports: BTreeSet<String>) -> Result<Self> {
        let libraries = discovered_libraries(&imports);
        if !libraries.is_empty() {
            let noun = if libraries.len() == 1 {
                "library"
            } else {
                "libraries"
            };
            status(
                Tone::Muted,
                "Found",
                format!(
                    "{} Python {noun} for warm reload: {}",
                    emphasis(libraries.len()),
                    detail(libraries.join(", "))
                ),
            );
        }
        #[cfg(unix)]
        let strategy = {
            let safe_imports = fork_safe_imports(config, &imports).await?;
            ForkStrategy::spawn(config, &safe_imports)?
        };
        #[cfg(windows)]
        let strategy = WarmPoolStrategy::spawn(config, &imports)?;

        Ok(Self { imports, strategy })
    }

    pub(super) async fn start(
        &mut self,
        generation: u64,
        payload_path: PathBuf,
    ) -> Result<ActiveWorker> {
        #[cfg(unix)]
        {
            self.strategy
                .send(&LayerCommand::Start {
                    generation,
                    payload_path,
                })
                .await?;
            Ok(ActiveWorker { generation })
        }
        #[cfg(windows)]
        {
            let child = self.strategy.activate(generation, payload_path).await?;
            Ok(ActiveWorker { child })
        }
    }

    pub(super) async fn stop(&mut self, worker: ActiveWorker) -> Result<()> {
        #[cfg(unix)]
        self.strategy
            .send(&LayerCommand::Stop {
                generation: worker.generation,
            })
            .await?;
        #[cfg(windows)]
        {
            let mut worker = worker;
            worker.child.start_kill()?;
            worker.child.wait().await?;
        }
        Ok(())
    }

    pub(super) async fn shutdown(&mut self) -> Result<()> {
        self.strategy.shutdown().await
    }
}

#[cfg(unix)]
struct ForkStrategy {
    child: Child,
    stdin: ChildStdin,
}

#[cfg(unix)]
impl ForkStrategy {
    fn spawn(config: &CoordinatorConfig, imports: &BTreeSet<String>) -> Result<Self> {
        let mut child = Command::new(&config.python)
            .args(["-c", FORK_PARENT])
            .arg(serde_json::to_string(imports)?)
            .current_dir(&config.project_root)
            .stdin(Stdio::piped())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .kill_on_drop(true)
            .spawn()?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| invalid("failed to open fork-template stdin"))?;
        Ok(Self { child, stdin })
    }

    async fn send(&mut self, command: &LayerCommand) -> Result<()> {
        send_json_line(&mut self.stdin, command).await
    }

    async fn shutdown(&mut self) -> Result<()> {
        let _ = self.send(&LayerCommand::Exit).await;
        if timeout(Duration::from_secs(5), self.child.wait())
            .await
            .is_err()
        {
            self.child.start_kill()?;
            self.child.wait().await?;
        }
        Ok(())
    }
}

#[cfg(windows)]
struct WarmPoolStrategy {
    python: String,
    project_root: PathBuf,
    imports_json: String,
    target_size: usize,
    idle: Vec<WarmProcess>,
}

#[cfg(windows)]
struct WarmProcess {
    child: Child,
    stdin: ChildStdin,
}

#[cfg(windows)]
impl WarmPoolStrategy {
    fn spawn(config: &CoordinatorConfig, imports: &BTreeSet<String>) -> Result<Self> {
        let mut strategy = Self {
            python: config.python.clone(),
            project_root: config.project_root.clone(),
            imports_json: serde_json::to_string(imports)?,
            target_size: config.warm_processes.max(1),
            idle: Vec::new(),
        };
        strategy.replenish()?;
        Ok(strategy)
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
                .ok_or_else(|| invalid("failed to open warm-worker stdin"))?;
            self.idle.push(WarmProcess { child, stdin });
        }
        Ok(())
    }

    async fn activate(&mut self, generation: u64, payload_path: PathBuf) -> Result<Child> {
        let mut process = self
            .idle
            .pop()
            .ok_or_else(|| invalid("warm process pool is empty"))?;
        send_json_line(
            &mut process.stdin,
            &LayerCommand::Start {
                generation,
                payload_path,
            },
        )
        .await?;
        drop(process.stdin);
        self.replenish()?;
        Ok(process.child)
    }

    async fn shutdown(&mut self) -> Result<()> {
        for process in &mut self.idle {
            process.child.start_kill()?;
            process.child.wait().await?;
        }
        self.idle.clear();
        Ok(())
    }
}

pub(super) async fn discover_imports(config: &CoordinatorConfig) -> Result<BTreeSet<String>> {
    let output = Command::new(&config.python)
        .args(["-c", DISCOVER_IMPORTS])
        .arg(&config.python_package_root)
        .arg(&config.package)
        .current_dir(&config.project_root)
        .output()
        .await?;
    if !output.status.success() {
        return Err(invalid(format!(
            "Python import discovery exited with {}:\n{}",
            output.status,
            String::from_utf8_lossy(&output.stderr)
        )));
    }
    let imports: Vec<String> = serde_json::from_slice(&output.stdout)?;
    Ok(imports.into_iter().collect())
}

fn discovered_libraries(imports: &BTreeSet<String>) -> Vec<String> {
    imports
        .iter()
        .filter_map(|module| module.split('.').next())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .map(str::to_string)
        .collect()
}

#[cfg(unix)]
async fn fork_safe_imports(
    config: &CoordinatorConfig,
    imports: &BTreeSet<String>,
) -> Result<BTreeSet<String>> {
    if imports.is_empty() {
        return Ok(BTreeSet::new());
    }
    let output = Command::new(&config.python)
        .args(["-c", IMPORT_SAFETY_PROBE])
        .arg(serde_json::to_string(imports)?)
        .current_dir(&config.project_root)
        .output()
        .await?;
    if !output.status.success() {
        return Err(invalid(format!(
            "fork-safety probe exited with {}:\n{}",
            output.status,
            String::from_utf8_lossy(&output.stderr)
        )));
    }

    let result: ImportSafetyProbe = serde_json::from_slice(&output.stdout)?;
    if !result.excluded.is_empty() {
        let noun = if result.excluded.len() == 1 {
            "library"
        } else {
            "libraries"
        };
        let details = result
            .excluded
            .iter()
            .map(|excluded| match excluded.thread_count {
                Some(threads) => {
                    format!("- {} ({threads} threads after import)", excluded.module)
                }
                None => format!("- {} ({})", excluded.module, excluded.reason),
            })
            .collect::<Vec<_>>();
        status_with_details(
            Tone::Warning,
            "Ignored",
            format!("{} Python {noun} for warm reload", details.len()),
            &details,
        );
    }
    Ok(result.safe)
}

async fn send_json_line(stdin: &mut ChildStdin, command: &LayerCommand) -> Result<()> {
    let mut payload = serde_json::to_vec(command)?;
    payload.push(b'\n');
    stdin.write_all(&payload).await?;
    stdin.flush().await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::coordinator::config::RuntimeMode;
    use std::fs;

    fn test_config(project_root: PathBuf, package_root: PathBuf) -> CoordinatorConfig {
        CoordinatorConfig {
            mode: RuntimeMode::Development,
            package: "example".to_string(),
            webcontroller: "example.app:controller".to_string(),
            host: "127.0.0.1".to_string(),
            port: 5006,
            python: "python".to_string(),
            debounce_ms: 100,
            warm_processes: 2,
            frontend_root: package_root.join("views"),
            project_root,
            python_package_root: package_root,
        }
    }

    #[tokio::test]
    async fn import_discovery_returns_only_third_party_modules() {
        let project = tempfile::tempdir().unwrap();
        let package_root = project.path().join("example");
        fs::create_dir_all(package_root.join("views")).unwrap();
        fs::write(
            package_root.join("app.py"),
            "import os\nimport pydantic.fields\nfrom fastapi import FastAPI\n\
             from example.local import value\n",
        )
        .unwrap();
        let config = test_config(project.path().to_path_buf(), package_root);

        assert_eq!(
            discover_imports(&config).await.unwrap(),
            BTreeSet::from(["fastapi".to_string(), "pydantic.fields".to_string()])
        );
    }

    #[test]
    fn library_names_are_deduplicated() {
        assert_eq!(
            discovered_libraries(&BTreeSet::from([
                "fastapi".to_string(),
                "pydantic.fields".to_string(),
                "pydantic.main".to_string(),
            ])),
            vec!["fastapi".to_string(), "pydantic".to_string()]
        );
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn fork_probe_excludes_thread_starting_imports() {
        let project = tempfile::tempdir().unwrap();
        fs::write(project.path().join("safe_import.py"), "VALUE = 1\n").unwrap();
        fs::write(
            project.path().join("threaded_import.py"),
            "import threading, time\n\
             threading.Thread(target=lambda: time.sleep(5), daemon=True).start()\n",
        )
        .unwrap();
        let package_root = project.path().join("example");
        fs::create_dir_all(package_root.join("views")).unwrap();
        let config = test_config(project.path().to_path_buf(), package_root);

        let safe = fork_safe_imports(
            &config,
            &BTreeSet::from(["safe_import".to_string(), "threaded_import".to_string()]),
        )
        .await
        .unwrap();

        assert_eq!(safe, BTreeSet::from(["safe_import".to_string()]));
    }
}
