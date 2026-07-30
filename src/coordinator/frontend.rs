use super::{
    config::CoordinatorConfig,
    invalid,
    output::{status, timing, Tone},
    server::{reserve_loopback_port, wait_until_ready},
    Result,
};
use serde::Serialize;
use std::{
    collections::BTreeSet,
    env, fs,
    net::{IpAddr, Ipv4Addr, SocketAddr},
    path::{Component, Path, PathBuf},
    process::{ExitStatus, Stdio},
    time::Duration,
};
use tempfile::TempDir;
use tokio::process::{Child, Command};
use tokio::time::Instant;

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
const VITE_CONFIG: &str = include_str!("../coordinator_assets/vite.config.mjs");

pub(super) struct ViteDevServer {
    child: Child,
    pub(super) origin: String,
    backend_signal: PathBuf,
}

#[derive(Serialize)]
struct ViteStyle {
    name: String,
    path: PathBuf,
}

fn frontend_toolchain_cache_dir() -> Result<PathBuf> {
    let base = if let Some(path) = env::var_os("MOUNTAINEER_CACHE_DIR") {
        PathBuf::from(path)
    } else if cfg!(windows) {
        env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .ok_or_else(|| invalid("LOCALAPPDATA is not set"))?
    } else if cfg!(target_os = "macos") {
        env::var_os("HOME")
            .map(PathBuf::from)
            .ok_or_else(|| invalid("HOME is not set"))?
            .join("Library")
            .join("Caches")
    } else {
        env::var_os("XDG_CACHE_HOME")
            .map(PathBuf::from)
            .or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(".cache")))
            .ok_or_else(|| invalid("XDG_CACHE_HOME and HOME are not set"))?
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
    Err(invalid("frontend refresh requires npm, pnpm, Yarn, or Bun"))
}

async fn javascript_runtime() -> Result<&'static str> {
    for runtime in ["node", "bun"] {
        if executable_available(runtime).await {
            return Ok(runtime);
        }
    }
    Err(invalid("frontend refresh requires Node.js or Bun"))
}

async fn ensure_frontend_toolchain(frontend_root: &Path) -> Result<PathBuf> {
    let toolchain_root = frontend_toolchain_cache_dir()?;
    if frontend_toolchain_complete(&toolchain_root) {
        return Ok(toolchain_root);
    }

    let cache_root = toolchain_root
        .parent()
        .ok_or_else(|| invalid("invalid frontend toolchain cache path"))?;
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
    status(
        Tone::Muted,
        "Installing",
        format!("frontend tooling with {manager}"),
    );
    let started = Instant::now();
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
        return Err(invalid(format!(
            "{manager} could not install frontend tooling: {details}"
        )));
    }
    if !frontend_toolchain_complete(install_root.path()) {
        return Err(invalid(format!(
            "{manager} completed without installing Vite and its React plugin"
        )));
    }

    if let Err(error) = fs::rename(install_root.path(), &toolchain_root) {
        if !frontend_toolchain_complete(&toolchain_root) {
            return Err(error.into());
        }
    }
    status(
        Tone::Accent,
        "Installed",
        format!("frontend tooling {}", timing(started)),
    );
    Ok(toolchain_root)
}

impl ViteDevServer {
    pub(super) async fn spawn(config: &CoordinatorConfig, directory: &TempDir) -> Result<Self> {
        let toolchain_root = ensure_frontend_toolchain(&config.frontend_root).await?;
        let package_json = toolchain_root.join("package.json");
        let vite_entrypoint = toolchain_root
            .join("node_modules")
            .join("vite")
            .join("bin")
            .join("vite.js");
        let javascript_runtime = javascript_runtime().await?;

        let port = reserve_loopback_port()?;
        let public_host = match config.host.as_str() {
            "0.0.0.0" | "::" => "127.0.0.1",
            host => host,
        };
        let origin = format!("http://{public_host}:{port}");
        let config_path = directory.path().join("mountaineer-vite.config.mjs");
        let backend_signal = directory.path().join("backend-generation");
        fs::write(&config_path, VITE_CONFIG)?;
        fs::write(&backend_signal, b"1")?;
        let mut child = Command::new(javascript_runtime)
            .arg(vite_entrypoint)
            .args(["--config", config_path.to_string_lossy().as_ref()])
            .args(["--logLevel", "warn"])
            .current_dir(&config.frontend_root)
            .env("MOUNTAINEER_FRONTEND_ROOT", &config.frontend_root)
            .env("MOUNTAINEER_TOOLCHAIN_PACKAGE_JSON", package_json)
            .env("MOUNTAINEER_VITE_HOST", &config.host)
            .env("MOUNTAINEER_VITE_PUBLIC_HOST", public_host)
            .env("MOUNTAINEER_VITE_PORT", port.to_string())
            .env("MOUNTAINEER_BACKEND_SIGNAL", &backend_signal)
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .kill_on_drop(true)
            .spawn()?;
        let ready = tokio::select! {
            result = wait_until_ready(
                SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), port),
                Duration::from_secs(15),
            ) => result,
            status = child.wait() => {
                let status = status?;
                Err(invalid(format!("Vite development server exited with {status}")))
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
            origin,
            backend_signal,
        })
    }

    pub(super) fn reload_backend(&self, generation: u64) -> Result<()> {
        fs::write(&self.backend_signal, generation.to_string())?;
        Ok(())
    }

    pub(super) async fn wait(&mut self) -> Result<ExitStatus> {
        Ok(self.child.wait().await?)
    }

    pub(super) async fn shutdown(&mut self) -> Result<()> {
        if self.child.try_wait()?.is_none() {
            self.child.start_kill()?;
        }
        self.child.wait().await?;
        Ok(())
    }
}

pub async fn build_frontend_styles(
    frontend_root: PathBuf,
    output_dir: PathBuf,
    styles: Vec<PathBuf>,
    minify: bool,
) -> Result<()> {
    if styles.is_empty() {
        return Ok(());
    }

    let frontend_root = frontend_root.canonicalize()?;
    fs::create_dir_all(&output_dir)?;
    let output_dir = output_dir.canonicalize()?;
    let mut names = BTreeSet::new();
    let styles = styles
        .into_iter()
        .map(|style| {
            let style = style.canonicalize()?;
            let relative = style.strip_prefix(&frontend_root).map_err(|_| {
                invalid(format!(
                    "stylesheet {} is outside frontend root {}",
                    style.display(),
                    frontend_root.display()
                ))
            })?;
            let name = relative
                .with_extension("")
                .components()
                .filter_map(|component| match component {
                    Component::Normal(part) => part.to_str(),
                    _ => None,
                })
                .collect::<Vec<_>>()
                .join("_");
            if name.is_empty() || !names.insert(name.clone()) {
                return Err(invalid(format!(
                    "stylesheet {} does not have a unique output name",
                    style.display()
                )));
            }
            Ok(ViteStyle { name, path: style })
        })
        .collect::<Result<Vec<_>>>()?;

    let toolchain_root = ensure_frontend_toolchain(&frontend_root).await?;
    let package_json = toolchain_root.join("package.json");
    let vite_entrypoint = toolchain_root
        .join("node_modules")
        .join("vite")
        .join("bin")
        .join("vite.js");
    let javascript_runtime = javascript_runtime().await?;
    let directory = tempfile::tempdir()?;
    let config_path = directory.path().join("mountaineer-vite.config.mjs");
    let backend_signal = directory.path().join("backend-generation");
    fs::write(&config_path, VITE_CONFIG)?;
    fs::write(&backend_signal, b"1")?;

    let output = Command::new(javascript_runtime)
        .arg(vite_entrypoint)
        .args(["build", "--config", config_path.to_string_lossy().as_ref()])
        .args(["--logLevel", "warn"])
        .current_dir(&frontend_root)
        .env("MOUNTAINEER_FRONTEND_ROOT", &frontend_root)
        .env("MOUNTAINEER_TOOLCHAIN_PACKAGE_JSON", package_json)
        .env("MOUNTAINEER_VITE_HOST", "127.0.0.1")
        .env("MOUNTAINEER_VITE_PUBLIC_HOST", "127.0.0.1")
        .env("MOUNTAINEER_VITE_PORT", "0")
        .env("MOUNTAINEER_BACKEND_SIGNAL", backend_signal)
        .env("MOUNTAINEER_VITE_STYLES", serde_json::to_string(&styles)?)
        .env("MOUNTAINEER_VITE_OUTPUT", output_dir)
        .env(
            "MOUNTAINEER_VITE_MINIFY",
            if minify { "true" } else { "false" },
        )
        .stdin(Stdio::null())
        .output()
        .await?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let stdout = String::from_utf8_lossy(&output.stdout);
        return Err(invalid(if stderr.trim().is_empty() {
            stdout.trim().to_string()
        } else {
            stderr.trim().to_string()
        }));
    }
    Ok(())
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
}
