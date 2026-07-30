use super::{
    config::{write_payload, CoordinatorConfig, ServerConfig},
    hot_reload::{discover_imports, ActiveWorker, PythonHotReload},
    invalid,
    output::{finish_startup_spinner, link, start_startup_spinner, status, timing, Tone},
    server::{reserve_loopback_port, serve_proxy, wait_until_ready},
    watcher::{restart_kind, ChangeKind},
    Error, Result,
};
use mountaineer_vite::{DevelopmentConfig as ViteConfig, DevelopmentServer as ViteDevServer};
use notify_debouncer_full::{new_debouncer, notify::RecursiveMode, DebounceEventResult};
use std::{
    net::{IpAddr, Ipv4Addr, SocketAddr},
    process::ExitStatus,
    sync::Arc,
    time::Duration,
};
use tempfile::TempDir;
use tokio::{
    net::TcpListener,
    signal,
    sync::{mpsc, RwLock},
    time::Instant,
};

pub(super) async fn run(config: CoordinatorConfig) -> Result<()> {
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
    let mut hot_reload = PythonHotReload::new(&config, imports).await?;
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

    let (event_tx, mut event_rx) = mpsc::unbounded_channel();
    let mut debouncer = new_debouncer(
        Duration::from_millis(config.debounce_ms),
        None,
        move |result: DebounceEventResult| {
            let _ = event_tx.send(result);
        },
    )?;
    debouncer.watch(&config.python_package_root, RecursiveMode::Recursive)?;
    if !config
        .frontend_root
        .starts_with(&config.python_package_root)
    {
        debouncer.watch(&config.frontend_root, RecursiveMode::Recursive)?;
    }

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
                result = event_rx.recv() => {
                    let Some(result) = result else {
                        break Err(invalid("filesystem watcher stopped unexpectedly"));
                    };
                    let events = match result {
                        Ok(events) => events,
                        Err(errors) => {
                            for error in errors {
                                status(Tone::Warning, "Warning", format!("watch error: {error}"));
                            }
                            continue;
                        }
                    };
                    let Some(change_kind) = restart_kind(&events) else {
                        continue;
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
                            match PythonHotReload::new(&config, next_imports).await {
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
    config: &CoordinatorConfig,
    payload_dir: &TempDir,
    hot_reload: &mut PythonHotReload,
    generation: u64,
    vite_origin: &str,
    rebuild_generated: bool,
) -> Result<(ActiveWorker, SocketAddr)> {
    let internal_port = reserve_loopback_port()?;
    let target = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), internal_port);
    let payload = config.payload(
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
