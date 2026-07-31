mod config;
mod development;
mod output;
mod production;

use clap::Args;
use std::{
    io::{Error as IoError, ErrorKind},
    path::PathBuf,
};

pub(crate) type Error = Box<dyn std::error::Error + Send + Sync>;
pub(crate) type Result<T> = std::result::Result<T, Error>;

#[derive(Args, Debug)]
struct CommonArgs {
    /// Public host
    #[arg(long, default_value = "127.0.0.1", value_name = "HOST")]
    host: String,

    /// Public port
    #[arg(long, default_value_t = 5006, value_name = "PORT")]
    port: u16,

    /// Project root (default: nearest pyproject.toml)
    #[arg(long, value_name = "PATH")]
    project_root: Option<PathBuf>,

    /// Python package (default: project name)
    #[arg(long, value_name = "PACKAGE")]
    package: Option<String>,

    /// Python package root (default: inferred)
    #[arg(long, value_name = "PATH")]
    package_root: Option<PathBuf>,

    /// App controller (default: <package>.app:controller)
    #[arg(long, value_name = "TARGET")]
    webcontroller: Option<String>,

    /// Mountaineer view root (default: <package>/views)
    #[arg(long, value_name = "PATH")]
    view_root: Option<PathBuf>,

    /// Frontend package root (default: view root)
    #[arg(long, value_name = "PATH")]
    frontend_root: Option<PathBuf>,

    /// Python executable (default: active environment)
    #[arg(long, value_name = "PATH")]
    python: Option<String>,
}

pub(crate) async fn run_development(args: &[String]) -> Result<()> {
    finish(development::run(args).await)
}

pub(crate) async fn run_production(args: &[String]) -> Result<()> {
    finish(production::run(args).await)
}

pub(crate) fn report_error(program: &str, error: &dyn std::fmt::Display) {
    output::report_error(program, error);
}

fn finish(result: Result<()>) -> Result<()> {
    output::finish_startup_spinner();
    result
}

fn invalid(message: impl Into<String>) -> Error {
    IoError::new(ErrorKind::InvalidInput, message.into()).into()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn public_entrypoint_rejects_unknown_options() {
        let error = run_development(&["--porrt".to_string(), "5006".to_string()])
            .await
            .unwrap_err();

        let error = error
            .downcast_ref::<clap::Error>()
            .expect("CLI errors should retain clap context");
        assert_eq!(error.kind(), clap::error::ErrorKind::UnknownArgument);
    }
}
