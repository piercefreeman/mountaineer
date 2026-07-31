mod hot_reload;
mod proxy;

use self::{
    hot_reload::{discover_imports, ActiveWorker, PythonHotReload},
    proxy::{reserve_loopback_port, serve_proxy, wait_until_ready},
};
use super::{
    config::{write_payload, LaunchConfig, RuntimeMode, ServerConfig},
    invalid,
    output::{finish_startup_spinner, link, start_startup_spinner, status, timing, Tone},
    CommonArgs, Error, Result,
};
use clap::Parser;
use mountaineer_file_monitor::{ChangeKind, Config as FileMonitorConfig, Monitor as FileMonitor};
use mountaineer_vite::{DevelopmentConfig as ViteConfig, DevelopmentServer as ViteDevServer};
use std::{
    ffi::OsString,
    net::{IpAddr, Ipv4Addr, SocketAddr},
    process::ExitStatus,
    sync::Arc,
    time::Duration,
};
use tempfile::TempDir;
use tokio::{net::TcpListener, signal, sync::RwLock, time::Instant};

#[derive(Parser, Debug)]
#[command(
    name = "mountaineer-dev",
    version,
    about = "Mountaineer development server"
)]
struct DevArgs {
    #[command(flatten)]
    common: CommonArgs,

    /// Filesystem debounce
    #[arg(long, default_value_t = 100, value_name = "MILLIS")]
    debounce_ms: u64,

    /// Windows warm pool size
    #[arg(long, default_value_t = 2, value_name = "COUNT")]
    warm_processes: usize,
}

fn parse(args: &[String]) -> std::result::Result<DevArgs, clap::Error> {
    let args =
        std::iter::once(OsString::from("mountaineer-dev")).chain(args.iter().map(OsString::from));
    DevArgs::try_parse_from(args)
}

pub(super) async fn run(args: &[String], python: String) -> Result<()> {
    let DevArgs {
        common,
        debounce_ms,
        warm_processes,
    } = parse(args)?;
    let config = LaunchConfig::resolve(common, python)?;

    start_startup_spinner();
    let listener = TcpListener::bind((config.host.as_str(), config.port)).await?;
    let public_address = listener.local_addr()?;
    let active_target = Arc::new(RwLock::new(None));

    let payload_dir = tempfile::tempdir()?;
    let mut vite = ViteDevServer::spawn(ViteConfig {
        frontend_root: config.frontend_root.clone(),
        host: config.host.clone(),
    })
    .await?;
    let mut generation = 1;
    let imports = discover_imports(&config).await?;
    let backend_started = Instant::now();
    let mut hot_reload = PythonHotReload::new(&config, imports, warm_processes).await?;
    let (active_worker, initial_target) = start_candidate(
        &config,
        &payload_dir,
        &mut hot_reload,
        generation,
        vite.origin(),
        true,
    )
    .await?;
    let mut active_worker = Some(active_worker);
    *active_target.write().await = Some(initial_target);

    let mut file_monitor = FileMonitor::start(FileMonitorConfig {
        python_root: config.python_package_root.clone(),
        frontend_root: config.frontend_root.clone(),
        debounce: Duration::from_millis(debounce_ms),
    })?;

    let mut proxy_task = tokio::spawn(serve_proxy(listener, active_target.clone()));
    finish_startup_spinner();
    status(
        Tone::Accent,
        "Started",
        format!(
            "app {} @ {}",
            timing(backend_started),
            link(format!("http://{public_address}"))
        ),
    );

    let run_result: Result<()> = async {
        loop {
            tokio::select! {
                _ = signal::ctrl_c() => break Ok(()),
                result = &mut proxy_task => {
                    let error = match result {
                        Ok(Ok(())) => invalid("backend proxy stopped unexpectedly"),
                        Ok(Err(error)) => error,
                        Err(error) => error.into(),
                    };
                    break Err(error);
                }
                status = vite.wait() => {
                    break Err(unexpected_exit("Vite development server", status));
                }
                status = hot_reload.wait() => {
                    break Err(unexpected_exit("Python reload parent", status));
                }
                status = active_worker.as_mut().expect("active worker").wait() => {
                    break Err(unexpected_exit("Python backend", status));
                }
                result = file_monitor.next() => {
                    let Some(result) = result else {
                        break Err(invalid("file monitor stopped unexpectedly"));
                    };
                    let change_kind = match result {
                        Ok(change_kind) => change_kind,
                        Err(error) => {
                            status(Tone::Warning, "Warning", error);
                            continue;
                        }
                    };
                    if change_kind == ChangeKind::Style {
                        status(Tone::Accent, "Updated", "styles");
                        continue;
                    }
                    let reload_started = Instant::now();
                    let refresh_imports = change_kind == ChangeKind::Python;

                    generation += 1;
                    let next_imports = if refresh_imports {
                        match discover_imports(&config).await {
                            Ok(imports) => imports,
                            Err(error) => {
                                status(
                                    Tone::Error,
                                    "Failed",
                                    format!(
                                        "import discovery; keeping the last working backend ({error})"
                                    ),
                                );
                                continue;
                            }
                        }
                    } else {
                        hot_reload.imports.clone()
                    };

                    if next_imports == hot_reload.imports {
                        match start_candidate(
                            &config,
                            &payload_dir,
                            &mut hot_reload,
                            generation,
                            vite.origin(),
                            refresh_imports,
                        ).await {
                            Ok((candidate, target)) => {
                                *active_target.write().await = Some(target);
                                hot_reload
                                    .stop(active_worker.take().expect("active worker"))
                                    .await?;
                                active_worker = Some(candidate);
                                if refresh_imports {
                                    vite.reload_backend(generation)?;
                                }
                                let target = if refresh_imports {
                                    "Python backend"
                                } else {
                                    "frontend"
                                };
                                status(
                                    Tone::Accent,
                                    "Updated",
                                    format!("{target} {}", timing(reload_started)),
                                );
                            }
                            Err(error) => {
                                status(
                                    Tone::Error,
                                    "Failed",
                                    format!(
                                        "backend reload; keeping the last working backend ({error})"
                                    ),
                                );
                            }
                        }
                    } else {
                        let mut candidate_strategy =
                            match PythonHotReload::new(&config, next_imports, warm_processes).await {
                                Ok(strategy) => strategy,
                                Err(error) => {
                                    status(
                                        Tone::Error,
                                        "Failed",
                                        format!(
                                            "backend reload; keeping the last working backend ({error})"
                                        ),
                                    );
                                    continue;
                                }
                            };
                        match start_candidate(
                            &config,
                            &payload_dir,
                            &mut candidate_strategy,
                            generation,
                            vite.origin(),
                            true,
                        ).await {
                            Ok((candidate, target)) => {
                                *active_target.write().await = Some(target);
                                let mut retired_strategy =
                                    std::mem::replace(&mut hot_reload, candidate_strategy);
                                let retired_worker =
                                    active_worker.replace(candidate);
                                if let Some(worker) = retired_worker {
                                    if let Err(error) = retired_strategy.stop(worker).await {
                                        status(
                                            Tone::Warning,
                                            "Warning",
                                            format!("retiring the previous backend: {error}"),
                                        );
                                    }
                                }
                                if let Err(error) = retired_strategy.shutdown().await {
                                    status(
                                        Tone::Warning,
                                        "Warning",
                                        format!("retiring the previous reload parent: {error}"),
                                    );
                                }
                                vite.reload_backend(generation)?;
                                status(
                                    Tone::Accent,
                                    "Updated",
                                    format!(
                                        "Python backend with refreshed imports {}",
                                        timing(reload_started)
                                    ),
                                );
                            }
                            Err(error) => {
                                if let Err(shutdown_error) = candidate_strategy.shutdown().await {
                                    status(
                                        Tone::Warning,
                                        "Warning",
                                        format!(
                                            "stopping the failed reload candidate: {shutdown_error}"
                                        ),
                                    );
                                }
                                status(
                                    Tone::Error,
                                    "Failed",
                                    format!(
                                        "backend reload; keeping the last working backend ({error})"
                                    ),
                                );
                            }
                        }
                    }
                }
            }
        }
    }
    .await;

    let stop_worker = match active_worker.take() {
        Some(worker) => hot_reload.stop(worker).await,
        None => Ok(()),
    };
    let stop_hot_reload = hot_reload.shutdown().await;
    let stop_vite = vite.shutdown().await;
    proxy_task.abort();
    let _ = proxy_task.await;
    run_result?;
    stop_worker?;
    stop_hot_reload?;
    stop_vite?;
    status(Tone::Muted, "Stopped", "Mountaineer");
    Ok(())
}

async fn start_candidate(
    config: &LaunchConfig,
    payload_dir: &TempDir,
    hot_reload: &mut PythonHotReload,
    generation: u64,
    vite_origin: &str,
    rebuild_generated: bool,
) -> Result<(ActiveWorker, SocketAddr)> {
    let internal_port = reserve_loopback_port()?;
    let target = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), internal_port);
    let payload = config.payload(
        RuntimeMode::Development,
        generation,
        ServerConfig {
            host: Ipv4Addr::LOCALHOST.to_string(),
            port: internal_port,
        },
        Some(vite_origin.to_string()),
        rebuild_generated,
    );
    let payload_path = write_payload(payload_dir, &payload)?;
    let mut worker = hot_reload.start(generation, payload_path).await?;
    tokio::select! {
        result = wait_until_ready(target, Duration::from_secs(15)) => {
            if let Err(error) = result {
                hot_reload.stop(worker).await?;
                return Err(error);
            }
        }
        status = hot_reload.wait() => {
            return Err(unexpected_exit("Python reload parent", status));
        }
        status = worker.wait() => {
            return Err(unexpected_exit("Python backend", status));
        }
    }
    Ok((worker, target))
}

fn unexpected_exit<E>(name: &str, result: std::result::Result<ExitStatus, E>) -> Error
where
    E: Into<Error>,
{
    match result {
        Ok(status) => invalid(format!("{name} exited unexpectedly with {status}")),
        Err(error) => error.into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::error::ErrorKind;

    #[test]
    fn help_is_generated_from_arguments() {
        let error = parse(&["--help".to_string()]).unwrap_err();

        assert_eq!(error.kind(), ErrorKind::DisplayHelp);
        assert_eq!(error.exit_code(), 0);
        let help = error.to_string();
        assert!(help.contains("--debounce-ms <MILLIS>"));
        assert!(help.contains("--warm-processes <COUNT>"));
    }

    #[test]
    fn parser_rejects_unknown_and_duplicate_arguments() {
        for (arguments, expected_kind) in [
            (vec!["--porrt", "5006"], ErrorKind::UnknownArgument),
            (
                vec!["--port", "5006", "--port", "5007"],
                ErrorKind::ArgumentConflict,
            ),
        ] {
            let arguments = arguments
                .into_iter()
                .map(str::to_string)
                .collect::<Vec<_>>();
            let error = parse(&arguments).unwrap_err();

            assert_eq!(error.kind(), expected_kind);
        }
    }
}
