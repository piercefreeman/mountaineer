mod development;
mod production;

use clap::Args;
use std::path::PathBuf;

#[derive(Clone, Debug)]
pub(crate) struct CoordinatorArgs {
    pub(crate) host: String,
    pub(crate) port: u16,
    pub(crate) project_root: Option<PathBuf>,
    pub(crate) package: Option<String>,
    pub(crate) package_root: Option<PathBuf>,
    pub(crate) webcontroller: Option<String>,
    pub(crate) view_root: Option<PathBuf>,
    pub(crate) frontend_root: Option<PathBuf>,
    pub(crate) python: Option<String>,
    pub(crate) debounce_ms: u64,
    pub(crate) warm_processes: usize,
}

#[derive(Args, Clone, Debug)]
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

impl CoordinatorArgs {
    fn from_common(common: CommonArgs, debounce_ms: u64, warm_processes: usize) -> Self {
        Self {
            host: common.host,
            port: common.port,
            project_root: common.project_root,
            package: common.package,
            package_root: common.package_root,
            webcontroller: common.webcontroller,
            view_root: common.view_root,
            frontend_root: common.frontend_root,
            python: common.python,
            debounce_ms,
            warm_processes,
        }
    }
}

pub(crate) fn parse(
    mode: crate::coordinator::RuntimeMode,
    args: &[String],
) -> Result<CoordinatorArgs, clap::Error> {
    match mode {
        crate::coordinator::RuntimeMode::Development => development::parse(args),
        crate::coordinator::RuntimeMode::Production => production::parse(args),
    }
}
