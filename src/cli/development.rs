use super::{CommonArgs, CoordinatorArgs};
use clap::{Args, Parser};
use std::ffi::OsString;

#[derive(Args, Clone, Debug)]
struct DevelopmentArgs {
    #[command(flatten)]
    common: CommonArgs,

    /// Filesystem debounce
    #[arg(long, default_value_t = 100, value_name = "MILLIS")]
    debounce_ms: u64,

    /// Windows warm pool size
    #[arg(long, default_value_t = 2, value_name = "COUNT")]
    warm_processes: usize,
}

#[derive(Parser, Debug)]
#[command(
    name = "mountaineer-dev",
    version,
    about = "Mountaineer development server"
)]
struct DevelopmentCli {
    #[command(flatten)]
    args: DevelopmentArgs,
}

pub(super) fn parse(args: &[String]) -> Result<CoordinatorArgs, clap::Error> {
    let args =
        std::iter::once(OsString::from("mountaineer-dev")).chain(args.iter().map(OsString::from));
    let parsed = DevelopmentCli::try_parse_from(args)?;
    Ok(CoordinatorArgs::from_common(
        parsed.args.common,
        parsed.args.debounce_ms,
        parsed.args.warm_processes,
    ))
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
