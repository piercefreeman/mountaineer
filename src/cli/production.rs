use super::{
    config::{write_payload, LaunchConfig, RuntimeMode, ServerConfig},
    invalid,
    output::{link, status, Tone},
    CommonArgs, Result,
};
use clap::Parser;
use std::{ffi::OsString, process::Stdio};
use tokio::{process::Command, signal};

#[derive(Parser, Debug)]
#[command(
    name = "mountaineer-prod",
    version,
    about = "Mountaineer production server"
)]
struct ProdArgs {
    #[command(flatten)]
    common: CommonArgs,
}

fn parse(args: &[String]) -> std::result::Result<ProdArgs, clap::Error> {
    let args =
        std::iter::once(OsString::from("mountaineer-prod")).chain(args.iter().map(OsString::from));
    ProdArgs::try_parse_from(args)
}

pub(super) async fn run(args: &[String], python: String) -> Result<()> {
    let config = LaunchConfig::resolve(parse(args)?.common, python)?;
    let payload_dir = tempfile::tempdir()?;
    let payload = config.payload(
        RuntimeMode::Production,
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
        .args(["-m", "mountaineer.runtime_cli", "serve"])
        .arg(payload_path)
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

#[cfg(test)]
mod tests {
    use super::*;
    use clap::error::ErrorKind;

    #[test]
    fn development_arguments_are_rejected() {
        let error = parse(&["--debounce-ms".to_string(), "10".to_string()]).unwrap_err();

        assert_eq!(error.kind(), ErrorKind::UnknownArgument);
        assert_eq!(error.exit_code(), 2);
    }
}
