use super::{
    config::CoordinatorConfig,
    invalid,
    output::{detail, emphasis, status, status_with_details, Tone},
    Result,
};
#[cfg(unix)]
use mountaineer_hot_reload_fork::{
    Config as ForkConfig, ExcludedImport, Spawned as SpawnedFork, Strategy as ForkStrategy,
};
#[cfg(windows)]
use mountaineer_hot_reload_pool::{Config as PoolConfig, Pool};
use std::{collections::BTreeSet, path::PathBuf, process::ExitStatus};
use tokio::process::Command;

const DISCOVER_IMPORTS: &str = include_str!("hot_reload/discover_imports.py");

#[cfg(unix)]
type Strategy = ForkStrategy;
#[cfg(windows)]
type Strategy = Pool;

#[cfg(unix)]
pub(super) type ActiveWorker = mountaineer_hot_reload_fork::Worker;
#[cfg(windows)]
pub(super) type ActiveWorker = mountaineer_hot_reload_pool::Worker;

pub(super) struct PythonHotReload {
    pub(super) imports: BTreeSet<String>,
    strategy: Strategy,
}

impl PythonHotReload {
    pub(super) async fn new(config: &CoordinatorConfig, imports: BTreeSet<String>) -> Result<Self> {
        report_discovered_libraries(&imports);

        #[cfg(unix)]
        let strategy = {
            let SpawnedFork {
                strategy,
                excluded_imports,
            } = ForkStrategy::spawn(ForkConfig {
                python: config.python.clone(),
                project_root: config.project_root.clone(),
                imports: imports.clone(),
            })
            .await?;
            report_excluded_imports(&excluded_imports);
            strategy
        };
        #[cfg(windows)]
        let strategy = Pool::spawn(PoolConfig {
            python: config.python.clone(),
            project_root: config.project_root.clone(),
            imports: imports.clone(),
            size: config.warm_processes,
        })?;

        Ok(Self { imports, strategy })
    }

    pub(super) async fn start(
        &mut self,
        generation: u64,
        payload_path: PathBuf,
    ) -> Result<ActiveWorker> {
        Ok(self.strategy.start(generation, payload_path).await?)
    }

    pub(super) async fn stop(&mut self, worker: ActiveWorker) -> Result<()> {
        Ok(self.strategy.stop(worker).await?)
    }

    pub(super) async fn shutdown(&mut self) -> Result<()> {
        Ok(self.strategy.shutdown().await?)
    }

    pub(super) async fn wait(&mut self) -> Result<ExitStatus> {
        Ok(self.strategy.wait().await?)
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

fn report_discovered_libraries(imports: &BTreeSet<String>) {
    let libraries = discovered_libraries(imports);
    if libraries.is_empty() {
        return;
    }
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
fn report_excluded_imports(excluded_imports: &[ExcludedImport]) {
    if excluded_imports.is_empty() {
        return;
    }
    let noun = if excluded_imports.len() == 1 {
        "library"
    } else {
        "libraries"
    };
    let details = excluded_imports
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
}
