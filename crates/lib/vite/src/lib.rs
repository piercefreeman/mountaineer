//! Typed ownership of Mountaineer's Vite toolchain and process boundary.

#![warn(missing_docs)]

use serde::Serialize;
use std::{
    collections::BTreeSet,
    env, fs, io,
    net::{IpAddr, Ipv4Addr, SocketAddr},
    path::{Path, PathBuf},
    process::{ExitStatus, Stdio},
    time::Duration,
};
use tempfile::TempDir;
use tokio::{
    net::TcpStream,
    process::{Child, Command},
    time::{sleep, Instant},
};

const FRONTEND_TOOLCHAIN_PACKAGE_JSON: &str = r#"{
  "name": "mountaineer-frontend-toolchain",
  "private": true,
  "type": "module",
  "dependencies": {
    "@vitejs/plugin-react": "6.0.4",
    "vite": "8.1.5",
    "vite-tsconfig-paths": "6.1.1"
  }
}
"#;
const VITE_CONFIG: &str = include_str!("../assets/vite.config.mjs");
const ENTRYPOINTS: &str = include_str!("../assets/entrypoints.mjs");
const USE_CLIENT: &str = include_str!("../assets/use-client.mjs");

/// Error returned by the Vite component.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// A filesystem, socket, or child-process operation failed.
    #[error(transparent)]
    Io(#[from] io::Error),

    /// Typed configuration could not be serialized for the Vite process.
    #[error(transparent)]
    Serialize(#[from] serde_json::Error),

    /// The requested Vite operation was invalid or failed.
    #[error("{0}")]
    Invalid(String),
}

/// Result returned by the Vite component.
pub type Result<T> = std::result::Result<T, Error>;

/// Typed configuration for a Vite development server.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DevelopmentConfig {
    /// Root directory containing the application's frontend source.
    pub frontend_root: PathBuf,

    /// Host interface Vite should listen on.
    pub host: String,
}

/// One named Mountaineer page and its ordered layout hierarchy.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct Entrypoint {
    /// Stable output filename stem.
    pub name: String,

    /// Component paths ordered from outermost layout to page.
    pub views: Vec<PathBuf>,
}

/// A named stylesheet entry for a Vite build.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct Stylesheet {
    /// Stable output stem for the generated stylesheet.
    pub name: String,

    /// Absolute path to the source stylesheet.
    pub path: PathBuf,
}

/// Typed configuration for a complete production frontend build.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionConfig {
    /// Root directory containing the application's frontend source.
    pub frontend_root: PathBuf,

    /// Directory that receives browser JavaScript, chunks, and stylesheets.
    pub client_output_dir: PathBuf,

    /// Directory that receives standalone scripts for embedded-V8 rendering.
    pub ssr_output_dir: PathBuf,

    /// Controller entrypoints compiled for both browser and server rendering.
    pub entrypoints: Vec<Entrypoint>,

    /// Stylesheets compiled as stable, independently linked assets.
    pub styles: Vec<PathBuf>,

    /// Whether production JavaScript and CSS should be minified.
    pub minify: bool,
}

/// Typed configuration for one standalone development SSR compilation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SsrConfig {
    /// Root directory containing the application's frontend source.
    pub frontend_root: PathBuf,

    /// Component paths ordered from outermost layout to page.
    pub views: Vec<PathBuf>,
}

/// Standalone JavaScript produced for embedded-V8 rendering.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompiledSsr {
    /// Self-contained script exposing Mountaineer's `SSR` entrypoint object.
    pub script: String,

    /// Source map emitted beside the script.
    pub source_map: Option<String>,
}

/// Typed configuration for a stylesheet-only Vite build.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StyleBuildConfig {
    /// Root directory containing the application's frontend source.
    pub frontend_root: PathBuf,

    /// Directory that receives generated stylesheets.
    pub output_dir: PathBuf,

    /// Stylesheet entrypoints to build.
    pub styles: Vec<Stylesheet>,

    /// Whether Vite should minify generated stylesheets.
    pub minify: bool,
}

/// Running Vite development server.
pub struct DevelopmentServer {
    child: Child,
    _directory: TempDir,
    origin: String,
    backend_signal: PathBuf,
}

impl DevelopmentServer {
    /// Starts Vite from typed Rust configuration and waits until it accepts connections.
    pub async fn spawn(config: DevelopmentConfig) -> Result<Self> {
        let frontend_root = config.frontend_root.canonicalize()?;
        let toolchain_root = ensure_frontend_toolchain(&frontend_root).await?;
        let javascript_runtime = javascript_runtime().await?;
        let directory = tempfile::tempdir()?;
        let port = reserve_loopback_port()?;
        let public_host = match config.host.as_str() {
            "0.0.0.0" | "::" => "127.0.0.1",
            host => host,
        };
        let origin = format!("http://{public_host}:{port}");
        let backend_signal = directory.path().join("backend-generation");
        fs::write(&backend_signal, b"1")?;
        write_config(
            &directory,
            Config {
                frontend_root: &frontend_root,
                toolchain_package_json: toolchain_root.join("package.json"),
                mode: Mode::Development {
                    host: &config.host,
                    public_host,
                    port,
                    backend_signal: &backend_signal,
                },
            },
        )?;

        let mut child = vite_command(
            javascript_runtime,
            &frontend_root,
            &toolchain_root,
            &directory,
            false,
        )?
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .kill_on_drop(true)
        .spawn()?;
        let address = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), port);
        let ready = tokio::select! {
            result = wait_until_ready(address, Duration::from_secs(15)) => result,
            status = child.wait() => {
                let status = status?;
                Err(Error::Invalid(format!("Vite development server exited with {status}")))
            }
        };
        if let Err(error) = ready {
            if child.try_wait()?.is_none() {
                child.start_kill()?;
            }
            child.wait().await?;
            return Err(error);
        }

        Ok(Self {
            child,
            _directory: directory,
            origin,
            backend_signal,
        })
    }

    /// Browser-visible origin of the running Vite server.
    pub fn origin(&self) -> &str {
        &self.origin
    }

    /// Invalidates Vite's backend-dependent modules and reloads connected browsers.
    pub fn reload_backend(&self, generation: u64) -> Result<()> {
        fs::write(&self.backend_signal, generation.to_string())?;
        Ok(())
    }

    /// Waits for an unexpected Vite process exit.
    pub async fn wait(&mut self) -> Result<ExitStatus> {
        Ok(self.child.wait().await?)
    }

    /// Stops Vite and waits for its process to exit.
    pub async fn shutdown(&mut self) -> Result<()> {
        if self.child.try_wait()?.is_none() {
            self.child.start_kill()?;
        }
        self.child.wait().await?;
        Ok(())
    }
}

/// Builds browser, stylesheet, and standalone SSR artifacts for production.
pub async fn build_production(config: ProductionConfig) -> Result<()> {
    let frontend_root = config.frontend_root.canonicalize()?;
    let entrypoints = prepare_entrypoints(config.entrypoints)?;
    let styles = prepare_style_paths(&frontend_root, config.styles)?;
    if entrypoints.is_empty() {
        return Ok(());
    }

    let client_output_dir = prepare_output_dir(&frontend_root, config.client_output_dir)?;
    let ssr_output_dir = prepare_output_dir(&frontend_root, config.ssr_output_dir)?;
    if client_output_dir == ssr_output_dir {
        return Err(Error::Invalid(
            "client and SSR output directories must differ".to_string(),
        ));
    }

    let toolchain_root = ensure_frontend_toolchain(&frontend_root).await?;
    let javascript_runtime = javascript_runtime().await?;
    let directory = tempfile::tempdir()?;
    run_build(
        javascript_runtime,
        &frontend_root,
        &toolchain_root,
        &directory,
        Mode::BuildClient {
            entrypoints: &entrypoints,
            output_dir: &client_output_dir,
            minify: config.minify,
        },
    )
    .await?;

    for (index, entrypoint) in entrypoints.iter().enumerate() {
        run_build(
            javascript_runtime,
            &frontend_root,
            &toolchain_root,
            &directory,
            Mode::BuildSsr {
                entrypoint,
                output_dir: &ssr_output_dir,
                environment: "production",
                minify: config.minify,
                empty_output: index == 0,
            },
        )
        .await?;
    }

    if !styles.is_empty() {
        run_build(
            javascript_runtime,
            &frontend_root,
            &toolchain_root,
            &directory,
            Mode::BuildStyles {
                styles: &styles,
                output_dir: &client_output_dir,
                minify: config.minify,
            },
        )
        .await?;
    }
    Ok(())
}

/// Compiles one self-contained development SSR script for embedded V8.
pub async fn compile_ssr(config: SsrConfig) -> Result<CompiledSsr> {
    let frontend_root = config.frontend_root.canonicalize()?;
    let entrypoint = prepare_entrypoint(Entrypoint {
        name: "entrypoint".to_string(),
        views: config.views,
    })?;
    let toolchain_root = ensure_frontend_toolchain(&frontend_root).await?;
    let javascript_runtime = javascript_runtime().await?;
    let directory = tempfile::tempdir()?;
    let output_dir = directory.path().join("ssr");
    fs::create_dir(&output_dir)?;
    run_build(
        javascript_runtime,
        &frontend_root,
        &toolchain_root,
        &directory,
        Mode::BuildSsr {
            entrypoint: &entrypoint,
            output_dir: &output_dir,
            environment: "development",
            minify: false,
            empty_output: true,
        },
    )
    .await?;

    let script_path = output_dir.join("entrypoint.js");
    let source_map_path = output_dir.join("entrypoint.js.map");
    Ok(CompiledSsr {
        script: fs::read_to_string(script_path)?,
        source_map: source_map_path
            .is_file()
            .then(|| fs::read_to_string(source_map_path))
            .transpose()?,
    })
}

/// Builds stylesheet entrypoints through Vite.
pub async fn build_styles(config: StyleBuildConfig) -> Result<()> {
    let frontend_root = config.frontend_root.canonicalize()?;
    let styles = prepare_styles(config.styles)?;
    if styles.is_empty() {
        return Ok(());
    }
    let output_dir = prepare_output_dir(&frontend_root, config.output_dir)?;
    let toolchain_root = ensure_frontend_toolchain(&frontend_root).await?;
    let javascript_runtime = javascript_runtime().await?;
    let directory = tempfile::tempdir()?;
    run_build(
        javascript_runtime,
        &frontend_root,
        &toolchain_root,
        &directory,
        Mode::BuildStyles {
            styles: &styles,
            output_dir: &output_dir,
            minify: config.minify,
        },
    )
    .await
}

#[derive(Serialize)]
struct Config<'a> {
    frontend_root: &'a Path,
    toolchain_package_json: PathBuf,
    #[serde(flatten)]
    mode: Mode<'a>,
}

#[derive(Serialize)]
#[serde(tag = "mode", rename_all = "snake_case")]
enum Mode<'a> {
    Development {
        host: &'a str,
        public_host: &'a str,
        port: u16,
        backend_signal: &'a Path,
    },
    BuildClient {
        entrypoints: &'a [Entrypoint],
        output_dir: &'a Path,
        minify: bool,
    },
    BuildSsr {
        entrypoint: &'a Entrypoint,
        output_dir: &'a Path,
        environment: &'a str,
        minify: bool,
        empty_output: bool,
    },
    BuildStyles {
        styles: &'a [Stylesheet],
        output_dir: &'a Path,
        minify: bool,
    },
}

async fn run_build(
    javascript_runtime: &str,
    frontend_root: &Path,
    toolchain_root: &Path,
    directory: &TempDir,
    mode: Mode<'_>,
) -> Result<()> {
    write_config(
        directory,
        Config {
            frontend_root,
            toolchain_package_json: toolchain_root.join("package.json"),
            mode,
        },
    )?;
    let output = vite_command(
        javascript_runtime,
        frontend_root,
        toolchain_root,
        directory,
        true,
    )?
    .output()
    .await?;
    if output.status.success() {
        return Ok(());
    }
    let stderr = String::from_utf8_lossy(&output.stderr);
    let stdout = String::from_utf8_lossy(&output.stdout);
    Err(Error::Invalid(if stderr.trim().is_empty() {
        stdout.trim().to_string()
    } else {
        stderr.trim().to_string()
    }))
}

fn write_config(directory: &TempDir, config: Config<'_>) -> Result<()> {
    fs::write(
        directory.path().join("mountaineer-entrypoints.mjs"),
        ENTRYPOINTS,
    )?;
    fs::write(
        directory.path().join("mountaineer-use-client.mjs"),
        USE_CLIENT,
    )?;
    fs::write(
        directory.path().join("mountaineer-vite.config.mjs"),
        format!(
            "const mountaineer = {};\n{VITE_CONFIG}",
            serde_json::to_string(&config)?
        ),
    )?;
    Ok(())
}

fn vite_command(
    javascript_runtime: &str,
    frontend_root: &Path,
    toolchain_root: &Path,
    directory: &TempDir,
    build: bool,
) -> Result<Command> {
    let mut command = executable_command(javascript_runtime);
    command.arg(
        toolchain_root
            .join("node_modules")
            .join("vite")
            .join("bin")
            .join("vite.js"),
    );
    if build {
        command.arg("build");
    }
    command
        .args([
            "--config",
            directory
                .path()
                .join("mountaineer-vite.config.mjs")
                .to_string_lossy()
                .as_ref(),
        ])
        .args(["--logLevel", "warn"])
        .current_dir(frontend_root)
        .stdin(Stdio::null());
    Ok(command)
}

fn prepare_entrypoints(entrypoints: Vec<Entrypoint>) -> Result<Vec<Entrypoint>> {
    let mut names = BTreeSet::new();
    entrypoints
        .into_iter()
        .map(|entrypoint| {
            let entrypoint = prepare_entrypoint(entrypoint)?;
            if !names.insert(entrypoint.name.clone()) {
                return Err(Error::Invalid(format!(
                    "duplicate frontend entrypoint name {:?}",
                    entrypoint.name
                )));
            }
            Ok(entrypoint)
        })
        .collect()
}

fn prepare_entrypoint(mut entrypoint: Entrypoint) -> Result<Entrypoint> {
    validate_name("frontend entrypoint", &entrypoint.name)?;
    if entrypoint.views.is_empty() {
        return Err(Error::Invalid(format!(
            "frontend entrypoint {:?} has no views",
            entrypoint.name
        )));
    }
    entrypoint.views = entrypoint
        .views
        .into_iter()
        .map(|view| view.canonicalize().map_err(Error::from))
        .collect::<Result<_>>()?;
    Ok(entrypoint)
}

fn prepare_styles(styles: Vec<Stylesheet>) -> Result<Vec<Stylesheet>> {
    let mut names = BTreeSet::new();
    styles
        .into_iter()
        .map(|mut style| {
            validate_name("stylesheet", &style.name)?;
            if !names.insert(style.name.clone()) {
                return Err(Error::Invalid(format!(
                    "duplicate stylesheet name {:?}",
                    style.name
                )));
            }
            style.path = style.path.canonicalize()?;
            Ok(style)
        })
        .collect()
}

fn prepare_style_paths(frontend_root: &Path, styles: Vec<PathBuf>) -> Result<Vec<Stylesheet>> {
    let styles = styles
        .into_iter()
        .map(|style| {
            let path = style.canonicalize()?;
            let relative = path.strip_prefix(frontend_root).map_err(|_| {
                Error::Invalid(format!(
                    "stylesheet {} is outside frontend root {}",
                    path.display(),
                    frontend_root.display()
                ))
            })?;
            let name = relative
                .with_extension("")
                .components()
                .filter_map(|component| component.as_os_str().to_str())
                .collect::<Vec<_>>()
                .join("_");
            Ok(Stylesheet { name, path })
        })
        .collect::<Result<Vec<_>>>()?;
    prepare_styles(styles)
}

fn validate_name(kind: &str, name: &str) -> Result<()> {
    if name.is_empty()
        || !name
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || matches!(character, '-' | '_'))
    {
        return Err(Error::Invalid(format!(
            "{kind} name {name:?} must contain only ASCII letters, digits, '-' or '_'"
        )));
    }
    Ok(())
}

fn prepare_output_dir(frontend_root: &Path, output_dir: PathBuf) -> Result<PathBuf> {
    fs::create_dir_all(&output_dir)?;
    let output_dir = output_dir.canonicalize()?;
    if frontend_root.starts_with(&output_dir) {
        return Err(Error::Invalid(
            "Vite output directory cannot contain the frontend root".to_string(),
        ));
    }
    Ok(output_dir)
}

fn frontend_toolchain_cache_dir() -> Result<PathBuf> {
    let base = if let Some(path) = env::var_os("MOUNTAINEER_CACHE_DIR") {
        PathBuf::from(path)
    } else if cfg!(windows) {
        env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .ok_or_else(|| Error::Invalid("LOCALAPPDATA is not set".to_string()))?
    } else if cfg!(target_os = "macos") {
        env::var_os("HOME")
            .map(PathBuf::from)
            .ok_or_else(|| Error::Invalid("HOME is not set".to_string()))?
            .join("Library")
            .join("Caches")
    } else {
        env::var_os("XDG_CACHE_HOME")
            .map(PathBuf::from)
            .or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(".cache")))
            .ok_or_else(|| Error::Invalid("XDG_CACHE_HOME and HOME are not set".to_string()))?
    };
    let digest = format!(
        "{:x}",
        md5::compute(FRONTEND_TOOLCHAIN_PACKAGE_JSON.as_bytes())
    );
    Ok(base.join("mountaineer").join(format!(
        "frontend-{}-{}-{digest}",
        env::consts::OS,
        env::consts::ARCH
    )))
}

fn frontend_toolchain_complete(path: &Path) -> bool {
    [
        path.join("package.json"),
        path.join("node_modules")
            .join("vite")
            .join("bin")
            .join("vite.js"),
        path.join("node_modules")
            .join("@vitejs")
            .join("plugin-react")
            .join("package.json"),
        path.join("node_modules")
            .join("vite-tsconfig-paths")
            .join("package.json"),
    ]
    .iter()
    .all(|path| path.is_file())
}

fn package_manager_preferences(frontend_root: &Path) -> Vec<&'static str> {
    let mut preferences = Vec::new();
    let mut add = |manager| {
        if !preferences.contains(&manager) {
            preferences.push(manager);
        }
    };

    if let Ok(package_json) = fs::read_to_string(frontend_root.join("package.json")) {
        if let Ok(package_json) = serde_json::from_str::<serde_json::Value>(&package_json) {
            if let Some(manager) = package_json
                .get("packageManager")
                .and_then(serde_json::Value::as_str)
                .and_then(|manager| manager.split('@').next())
            {
                match manager {
                    "npm" => add("npm"),
                    "pnpm" => add("pnpm"),
                    "yarn" => add("yarn"),
                    "bun" => add("bun"),
                    _ => {}
                }
            }
        }
    }

    for (lockfiles, manager) in [
        (&["bun.lock", "bun.lockb"][..], "bun"),
        (&["pnpm-lock.yaml"][..], "pnpm"),
        (&["yarn.lock"][..], "yarn"),
        (&["package-lock.json", "npm-shrinkwrap.json"][..], "npm"),
    ] {
        if lockfiles
            .iter()
            .any(|lockfile| frontend_root.join(lockfile).is_file())
        {
            add(manager);
        }
    }
    for manager in ["npm", "pnpm", "yarn", "bun"] {
        add(manager);
    }
    preferences
}

fn executable_command(executable: &str) -> Command {
    #[cfg(windows)]
    {
        let mut command = Command::new("cmd");
        command.args(["/C", executable]);
        command
    }
    #[cfg(not(windows))]
    Command::new(executable)
}

async fn executable_available(executable: &str) -> bool {
    executable_command(executable)
        .arg("--version")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .await
        .is_ok_and(|status| status.success())
}

async fn frontend_package_manager(frontend_root: &Path) -> Result<&'static str> {
    for manager in package_manager_preferences(frontend_root) {
        if executable_available(manager).await {
            return Ok(manager);
        }
    }
    Err(Error::Invalid(
        "frontend refresh requires npm, pnpm, Yarn, or Bun".to_string(),
    ))
}

async fn javascript_runtime() -> Result<&'static str> {
    for runtime in ["node", "bun"] {
        if executable_available(runtime).await {
            return Ok(runtime);
        }
    }
    Err(Error::Invalid(
        "frontend tooling requires Node.js or Bun".to_string(),
    ))
}

async fn ensure_frontend_toolchain(frontend_root: &Path) -> Result<PathBuf> {
    let toolchain_root = frontend_toolchain_cache_dir()?;
    if frontend_toolchain_complete(&toolchain_root) {
        return Ok(toolchain_root);
    }

    let cache_root = toolchain_root
        .parent()
        .ok_or_else(|| Error::Invalid("invalid frontend toolchain cache path".to_string()))?;
    fs::create_dir_all(cache_root)?;
    let install_root = tempfile::Builder::new()
        .prefix(".frontend-install-")
        .tempdir_in(cache_root)?;
    fs::write(
        install_root.path().join("package.json"),
        FRONTEND_TOOLCHAIN_PACKAGE_JSON,
    )?;

    let manager = frontend_package_manager(frontend_root).await?;
    if manager == "yarn" {
        fs::write(
            install_root.path().join(".yarnrc.yml"),
            "nodeLinker: node-modules\n",
        )?;
    }
    let mut command = executable_command(manager);
    command.arg("install");
    if manager == "npm" {
        command.args(["--no-audit", "--no-fund"]);
    }
    let output = command
        .current_dir(install_root.path())
        .stdin(Stdio::null())
        .output()
        .await?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let stdout = String::from_utf8_lossy(&output.stdout);
        let details = if stderr.trim().is_empty() {
            stdout.trim()
        } else {
            stderr.trim()
        };
        return Err(Error::Invalid(format!(
            "{manager} could not install frontend tooling: {details}"
        )));
    }
    if !frontend_toolchain_complete(install_root.path()) {
        return Err(Error::Invalid(format!(
            "{manager} completed without installing the complete Vite toolchain"
        )));
    }

    if let Err(error) = fs::rename(install_root.path(), &toolchain_root) {
        if !frontend_toolchain_complete(&toolchain_root) {
            return Err(error.into());
        }
    }
    Ok(toolchain_root)
}

fn reserve_loopback_port() -> Result<u16> {
    Ok(std::net::TcpListener::bind((Ipv4Addr::LOCALHOST, 0))?
        .local_addr()?
        .port())
}

async fn wait_until_ready(address: SocketAddr, wait: Duration) -> Result<()> {
    let deadline = Instant::now() + wait;
    loop {
        if TcpStream::connect(address).await.is_ok() {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err(Error::Invalid(format!(
                "timed out waiting for Vite at {address}"
            )));
        }
        sleep(Duration::from_millis(50)).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frontend_toolchain_prefers_the_projects_package_manager() {
        let frontend = tempfile::tempdir().unwrap();
        fs::write(
            frontend.path().join("package.json"),
            r#"{"packageManager":"yarn@4.9.1"}"#,
        )
        .unwrap();
        fs::write(frontend.path().join("bun.lock"), "").unwrap();

        assert_eq!(
            &package_manager_preferences(frontend.path())[..3],
            &["yarn", "bun", "npm"]
        );
    }

    #[test]
    fn entrypoint_names_cannot_escape_the_output_directory() {
        let error = prepare_entrypoint(Entrypoint {
            name: "../outside".to_string(),
            views: vec![PathBuf::from("page.tsx")],
        })
        .unwrap_err();

        assert!(error.to_string().contains("only ASCII"));
    }

    #[test]
    fn output_directory_cannot_contain_frontend_sources() {
        let workspace = tempfile::tempdir().unwrap();
        let frontend = workspace.path().join("frontend");
        fs::create_dir(&frontend).unwrap();
        let frontend = frontend.canonicalize().unwrap();

        let error = prepare_output_dir(&frontend, workspace.path().to_path_buf()).unwrap_err();

        assert!(error.to_string().contains("cannot contain"));
    }
}
