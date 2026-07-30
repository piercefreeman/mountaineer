use super::{
    config::{write_payload, CoordinatorConfig, ServerConfig, PAYLOAD_PATH_ENV},
    invalid,
    output::{link, status, Tone},
    Result,
};
use std::process::Stdio;
use tokio::{process::Command, signal};

pub(super) async fn run(config: CoordinatorConfig) -> Result<()> {
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
