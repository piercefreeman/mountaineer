use super::{CommonArgs, CoordinatorArgs};
use clap::Parser;
use std::ffi::OsString;

#[derive(Parser, Debug)]
#[command(
    name = "mountaineer-prod",
    version,
    about = "Mountaineer production server"
)]
struct ProductionCli {
    #[command(flatten)]
    args: CommonArgs,
}

pub(super) fn parse(args: &[String]) -> Result<CoordinatorArgs, clap::Error> {
    let args =
        std::iter::once(OsString::from("mountaineer-prod")).chain(args.iter().map(OsString::from));
    let parsed = ProductionCli::try_parse_from(args)?;
    Ok(CoordinatorArgs::from_common(parsed.args, 100, 2))
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
