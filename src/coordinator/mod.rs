mod config;
mod frontend;
mod hot_reload;
mod output;
mod server;
mod watcher;

use config::{usage, write_payload, CoordinatorConfig, PAYLOAD_PATH_ENV};
use frontend::ViteDevServer;
use hot_reload::{discover_imports, ActiveWorker, PythonHotReload};
use notify_debouncer_full::{new_debouncer, notify::RecursiveMode, DebounceEventResult};
use output::{finish_startup_spinner, link, start_startup_spinner, status, timing, Tone};
use server::{reserve_loopback_port, serve_proxy, wait_until_ready};
use std::{
    error::Error,
    io::{Error as IoError, ErrorKind},
    net::{IpAddr, Ipv4Addr, SocketAddr},
    process::Stdio,
    sync::Arc,
    time::Duration,
};
use tempfile::TempDir;
use tokio::{
    net::TcpListener,
    process::Command,
    signal,
    sync::{mpsc, RwLock},
    time::Instant,
};
use watcher::{restart_kind, ChangeKind};

pub use config::{RuntimeMode, ServerConfig};
pub(crate) use frontend::build_frontend_styles;
pub use output::report_error;

type AnyError = Box<dyn Error + Send + Sync>;
type Result<T> = std::result::Result<T, AnyError>;

pub async fn run(mode: RuntimeMode, args: &[String]) -> Result<()> {
    if args
        .iter()
        .any(|argument| argument == "--help" || argument == "-h")
    {
        println!("{}", usage(mode));
        return Ok(());
    }

    let config = CoordinatorConfig::parse(mode, args)
        .map_err(|error| invalid(format!("{error}\n\n{}", usage(mode))))?;
    match mode {
        RuntimeMode::Development => run_development(config).await,
        RuntimeMode::Production => run_production(config).await,
    }
}

async fn run_development(config: CoordinatorConfig) -> Result<()> {
    start_startup_spinner();
    let listener = TcpListener::bind((config.host.as_str(), config.port)).await?;
    let public_address = listener.local_addr()?;
    let active_target = Arc::new(RwLock::new(None));
    let proxy_task = tokio::spawn(serve_proxy(listener, active_target.clone()));

    let payload_dir = tempfile::tempdir()?;
    let mut vite = ViteDevServer::spawn(&config, &payload_dir).await?;
    let mut generation = 1;
    let imports = discover_imports(&config).await?;
    let backend_started = Instant::now();
    let mut hot_reload = PythonHotReload::new(&config, imports).await?;
    let (mut active_worker, initial_target) = start_candidate(
        &config,
        &payload_dir,
        &mut hot_reload,
        generation,
        &vite.origin,
        true,
    )
    .await?;
    *active_target.write().await = Some(initial_target);
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

    loop {
        tokio::select! {
            _ = signal::ctrl_c() => break,
            result = event_rx.recv() => {
                let Some(result) = result else {
                    return Err(invalid("filesystem watcher stopped unexpectedly"));
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
                        &vite.origin,
                        refresh_imports,
                    ).await {
                        Ok((candidate, target)) => {
                            *active_target.write().await = Some(target);
                            hot_reload.stop(active_worker).await?;
                            active_worker = candidate;
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
                        PythonHotReload::new(&config, next_imports).await?;
                    match start_candidate(
                        &config,
                        &payload_dir,
                        &mut candidate_strategy,
                        generation,
                        &vite.origin,
                        true,
                    ).await {
                        Ok((candidate, target)) => {
                            *active_target.write().await = Some(target);
                            hot_reload.stop(active_worker).await?;
                            hot_reload.shutdown().await?;
                            hot_reload = candidate_strategy;
                            active_worker = candidate;
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
                            candidate_strategy.shutdown().await?;
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

    hot_reload.stop(active_worker).await?;
    hot_reload.shutdown().await?;
    vite.shutdown().await?;
    proxy_task.abort();
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
    let worker = hot_reload.start(generation, payload_path).await?;
    if let Err(error) = wait_until_ready(target, Duration::from_secs(15)).await {
        hot_reload.stop(worker).await?;
        return Err(error);
    }
    Ok((worker, target))
}

async fn run_production(config: CoordinatorConfig) -> Result<()> {
    let payload_dir = tempfile::tempdir()?;
    let payload = config.payload(
        1,
        ServerConfig {
            host: config.host.clone(),
            port: config.port,
        },
        None,
        false,
    );
    let payload_path = write_payload(&payload_dir, &payload)?;
    status(
        Tone::Accent,
        "Starting",
        format!(
            "production server at {}",
            link(format!("http://{}:{}", config.host, config.port))
        ),
    );

    let mut child = Command::new(&config.python)
        .args(["-c", "from mountaineer.runtime import main; main()"])
        .env(PAYLOAD_PATH_ENV, payload_path)
        .current_dir(&config.project_root)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .kill_on_drop(true)
        .spawn()?;

    tokio::select! {
        status = child.wait() => {
            let status = status?;
            if !status.success() {
                return Err(invalid(format!("Python server exited with {status}")));
            }
        }
        _ = signal::ctrl_c() => {
            child.start_kill()?;
            child.wait().await?;
        }
    }
    Ok(())
}

fn invalid(message: impl Into<String>) -> AnyError {
    IoError::new(ErrorKind::InvalidInput, message.into()).into()
}
