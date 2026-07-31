use crate::cli::{
    config::LaunchConfig,
    output::{detail, emphasis, status, status_with_details, Tone},
    Result,
};
use mountaineer_hot_reload_discover::{discover, Config as DiscoverConfig};
#[cfg(unix)]
use mountaineer_hot_reload_fork::{
    Config as ForkConfig, ExcludedImport, Spawned as SpawnedFork, Strategy as ForkStrategy,
};
#[cfg(windows)]
use mountaineer_hot_reload_pool::{Config as PoolConfig, Pool};
use std::{collections::BTreeSet, path::PathBuf, process::ExitStatus};

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
    pub(super) async fn new(
        config: &LaunchConfig,
        imports: BTreeSet<String>,
        warm_processes: usize,
    ) -> Result<Self> {
        report_discovered_libraries(&imports);

        #[cfg(unix)]
        let strategy = {
            let _ = warm_processes;
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
            size: warm_processes,
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

pub(super) async fn discover_imports(config: &LaunchConfig) -> Result<BTreeSet<String>> {
    Ok(discover(DiscoverConfig {
        python: config.python.clone(),
        project_root: config.project_root.clone(),
        package_root: config.python_package_root.clone(),
        package: config.package.clone(),
    })
    .await?)
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
