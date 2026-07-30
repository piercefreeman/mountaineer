//! Typed ownership of Mountaineer's Vite toolchain and process boundary.

#![warn(missing_docs)]

use serde::Serialize;
use std::{
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
    "vite": "8.1.5"
  }
}
"#;
const VITE_CONFIG: &str = include_str!("../assets/vite.config.mjs");

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

/// A named stylesheet entry for a Vite build.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct Stylesheet {
    /// Stable output stem for the generated stylesheet.
    pub name: String,

    /// Absolute path to the source stylesheet.
    pub path: PathBuf,
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
        let directory = tempfile::tempdir()?;
        let port = reserve_loopback_port()?;
        let public_host = match config.host.as_str() {
            "0.0.0.0" | "::" => "127.0.0.1",
            host => host,
        };
        let origin = format!("http://{public_host}:{port}");
        let backend_signal = directory.path().join("backend-generation");
        fs::write(&backend_signal, b"1")?;

        let mut child = command(
            &frontend_root,
            &directory,
            Mode::Development {
                host: &config.host,
                public_host,
                port,
                backend_signal: &backend_signal,
            },
        )
        .await?
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

/// Builds stylesheet entrypoints through Vite.
pub async fn build_styles(config: StyleBuildConfig) -> Result<()> {
    if config.styles.is_empty() {
        return Ok(());
    }

    let frontend_root = config.frontend_root.canonicalize()?;
    fs::create_dir_all(&config.output_dir)?;
    let output_dir = config.output_dir.canonicalize()?;
    let directory = tempfile::tempdir()?;
    let output = command(
        &frontend_root,
        &directory,
        Mode::BuildStyles {
            styles: &config.styles,
            output_dir: &output_dir,
            minify: config.minify,
        },
    )
    .await?
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
    BuildStyles {
        styles: &'a [Stylesheet],
        output_dir: &'a Path,
        minify: bool,
    },
}

async fn command(frontend_root: &Path, directory: &TempDir, mode: Mode<'_>) -> Result<Command> {
    let build = matches!(mode, Mode::BuildStyles { .. });
    let toolchain_root = ensure_frontend_toolchain(frontend_root).await?;
    let config = Config {
        frontend_root,
        toolchain_package_json: toolchain_root.join("package.json"),
        mode,
    };
    let config_path = directory.path().join("mountaineer-vite.config.mjs");
    fs::write(
        &config_path,
        format!(
            "const mountaineer = {};\n{VITE_CONFIG}",
            serde_json::to_string(&config)?
        ),
    )?;

    let mut command = Command::new(javascript_runtime().await?);
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
        .args(["--config", config_path.to_string_lossy().as_ref()])
        .args(["--logLevel", "warn"])
        .current_dir(frontend_root)
        .stdin(Stdio::null());
    Ok(command)
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
    path.join("package.json").is_file()
        && path
            .join("node_modules")
            .join("vite")
            .join("bin")
            .join("vite.js")
            .is_file()
        && path
            .join("node_modules")
            .join("@vitejs")
            .join("plugin-react")
            .join("package.json")
            .is_file()
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
        "frontend refresh requires Node.js or Bun".to_string(),
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
            "{manager} completed without installing Vite and its React plugin"
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
    fn vite_config_consumes_typed_rust_settings() {
        assert!(!VITE_CONFIG.contains("process.env"));
    }
}
