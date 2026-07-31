use super::{
    config::{write_payload, LaunchConfig, RuntimeMode, ServerConfig},
    invalid,
    output::{finish_startup_spinner, start_startup_spinner, status, timing, Tone},
    CommonArgs, Result,
};
use clap::Parser;
use mountaineer_file_monitor::{ChangeKind, Config as FileMonitorConfig, Monitor as FileMonitor};
use std::{ffi::OsString, process::Stdio, time::Duration};
use tempfile::TempDir;
use tokio::{process::Command, signal, time::Instant};

#[derive(Parser, Debug)]
#[command(
    name = "mountaineer-watch",
    version,
    about = "Regenerate Mountaineer client types when Python sources change"
)]
struct WatchArgs {
    #[command(flatten)]
    common: CommonArgs,

    /// Filesystem debounce
    #[arg(long, default_value_t = 100, value_name = "MILLIS")]
    debounce_ms: u64,
}

fn parse(args: &[String]) -> std::result::Result<WatchArgs, clap::Error> {
    let args =
        std::iter::once(OsString::from("mountaineer-watch")).chain(args.iter().map(OsString::from));
    WatchArgs::try_parse_from(args)
}

pub(super) async fn run(args: &[String]) -> Result<()> {
    let WatchArgs {
        common,
        debounce_ms,
    } = parse(args)?;
    let config = LaunchConfig::resolve(common)?;
    let payload_dir = tempfile::tempdir()?;
    let mut generation = 1;
    let mut file_monitor = FileMonitor::start(FileMonitorConfig {
        python_root: config.python_package_root.clone(),
        frontend_root: config.frontend_root.clone(),
        debounce: Duration::from_millis(debounce_ms),
    })?;

    start_startup_spinner();
    let started = Instant::now();
    regenerate(&config, &payload_dir, generation).await?;
    finish_startup_spinner();
    status(
        Tone::Accent,
        "Watching",
        format!("generated client files {}", timing(started)),
    );

    loop {
        tokio::select! {
            _ = signal::ctrl_c() => break,
            result = file_monitor.next() => {
                let Some(result) = result else {
                    return Err(invalid("file monitor stopped unexpectedly"));
                };
                match result {
                    Ok(ChangeKind::Python) => {
                        generation += 1;
                        let started = Instant::now();
                        match regenerate(&config, &payload_dir, generation).await {
                            Ok(()) => status(
                                Tone::Accent,
                                "Updated",
                                format!("generated client files {}", timing(started)),
                            ),
                            Err(error) => status(
                                Tone::Error,
                                "Failed",
                                format!("generated client files; keeping the last build ({error})"),
                            ),
                        }
                    }
                    Ok(ChangeKind::Frontend | ChangeKind::Style) => {}
                    Err(error) => status(Tone::Warning, "Warning", error),
                }
            }
        }
    }

    status(Tone::Muted, "Stopped", "Mountaineer");
    Ok(())
}

async fn regenerate(config: &LaunchConfig, payload_dir: &TempDir, generation: u64) -> Result<()> {
    let payload = config.payload(
        RuntimeMode::Development,
        generation,
        ServerConfig {
            host: config.host.clone(),
            port: config.port,
        },
        None,
        true,
    );
    let payload_path = write_payload(payload_dir, &payload)?;
    let status = Command::new(&config.python)
        .args(["-m", "mountaineer.runtime_cli", "build-generated"])
        .arg(payload_path)
        .current_dir(&config.project_root)
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .status()
        .await?;
    if !status.success() {
        return Err(invalid(format!(
            "Python client builder exited with {status}"
        )));
    }
    Ok(())
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
        assert!(error.to_string().contains("--debounce-ms <MILLIS>"));
    }
}
