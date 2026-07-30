mod config;
mod development;
mod frontend;
mod hot_reload;
mod output;
mod production;
mod server;
mod watcher;

use config::{usage, CoordinatorConfig};
use std::io::{Error as IoError, ErrorKind};

pub use config::RuntimeMode;
pub use frontend::build_frontend_styles;
pub use output::report_error;

pub type Error = Box<dyn std::error::Error + Send + Sync>;
pub type Result<T> = std::result::Result<T, Error>;

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
    let result = match mode {
        RuntimeMode::Development => development::run(config).await,
        RuntimeMode::Production => production::run(config).await,
    };
    output::finish_startup_spinner();
    result
}

pub(super) fn invalid(message: impl Into<String>) -> Error {
    IoError::new(ErrorKind::InvalidInput, message.into()).into()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn public_entrypoint_rejects_unknown_options() {
        let error = run(
            RuntimeMode::Development,
            &["--porrt".to_string(), "5006".to_string()],
        )
        .await
        .unwrap_err();

        assert!(error.to_string().starts_with("unknown option \"--porrt\""));
    }
}
