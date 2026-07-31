use super::{invalid, Result};
use crate::cli::CoordinatorArgs;
use serde::{Deserialize, Serialize};
use std::{
    env, fs,
    path::{Path, PathBuf},
};
use tempfile::TempDir;

pub(super) const PAYLOAD_PATH_ENV: &str = "MOUNTAINEER_RUNTIME_PAYLOAD";
const PAYLOAD_SCHEMA_VERSION: u16 = 1;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeMode {
    Development,
    Production,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(super) struct ServerConfig {
    pub(super) host: String,
    pub(super) port: u16,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(super) struct RuntimePayload {
    schema_version: u16,
    mode: RuntimeMode,
    generation: u64,
    rebuild_generated: bool,
    webcontroller: String,
    server: ServerConfig,
    dev_server_origin: Option<String>,
}

#[derive(Deserialize)]
struct PyProject {
    project: PyProjectMetadata,
}

#[derive(Deserialize)]
struct PyProjectMetadata {
    name: String,
}

#[derive(Clone, Debug)]
pub(super) struct CoordinatorConfig {
    pub(super) mode: RuntimeMode,
    pub(super) package: String,
    pub(super) webcontroller: String,
    pub(super) host: String,
    pub(super) port: u16,
    pub(super) python: String,
    pub(super) debounce_ms: u64,
    #[cfg_attr(not(windows), allow(dead_code))]
    pub(super) warm_processes: usize,
    pub(super) project_root: PathBuf,
    pub(super) python_package_root: PathBuf,
    pub(super) frontend_root: PathBuf,
}

impl CoordinatorConfig {
    pub(super) fn parse(mode: RuntimeMode, args: &[String]) -> Result<Self> {
        let current_dir = env::current_dir()?;
        let current_exe = env::current_exe().ok();
        Self::parse_from(mode, args, &current_dir, current_exe.as_deref())
    }

    fn parse_from(
        mode: RuntimeMode,
        args: &[String],
        current_dir: &Path,
        current_exe: Option<&Path>,
    ) -> Result<Self> {
        let options = crate::cli::parse(mode, args)?;
        Self::resolve(mode, options, current_dir, current_exe)
    }

    fn resolve(
        mode: RuntimeMode,
        options: CoordinatorArgs,
        current_dir: &Path,
        current_exe: Option<&Path>,
    ) -> Result<Self> {
        let project_root = match options.project_root.as_deref() {
            Some(path) => canonical_dir(resolve_path(current_dir, path), "project root")?,
            None => find_project_root(current_dir)?,
        };
        let project_name = read_project_name(&project_root)?;
        let package_was_inferred = options.package.is_none();
        let requested_package = options
            .package
            .unwrap_or_else(|| normalize_package_name(&project_name));
        let (package, python_package_root) = match options.package_root.as_deref() {
            Some(path) => (
                requested_package,
                canonical_dir(resolve_path(&project_root, path), "Python package root")?,
            ),
            None => discover_package_root(&project_root, &requested_package, package_was_inferred)?,
        };
        let webcontroller = options
            .webcontroller
            .unwrap_or_else(|| format!("{package}.app:controller"));
        if !webcontroller.contains(':') {
            return Err(invalid(
                "--webcontroller must look like package.module:controller",
            ));
        }
        let view_root = canonical_dir(
            options
                .view_root
                .as_deref()
                .map(|path| resolve_path(&project_root, path))
                .unwrap_or_else(|| python_package_root.join("views")),
            "view root",
        )?;
        let frontend_root = canonical_dir(
            options
                .frontend_root
                .as_deref()
                .map(|path| resolve_path(&project_root, path))
                .unwrap_or_else(|| view_root.clone()),
            "frontend root",
        )?;
        let python = options
            .python
            .or_else(virtualenv_python)
            .or_else(|| current_exe.and_then(adjacent_python))
            .or_else(|| env::var("PYTHON").ok())
            .unwrap_or_else(|| "python".to_string());

        Ok(Self {
            mode,
            package,
            webcontroller,
            host: options.host,
            port: options.port,
            python,
            debounce_ms: options.debounce_ms,
            warm_processes: options.warm_processes,
            project_root,
            python_package_root,
            frontend_root,
        })
    }

    pub(super) fn payload(
        &self,
        generation: u64,
        server: ServerConfig,
        dev_server_origin: Option<String>,
        rebuild_generated: bool,
    ) -> RuntimePayload {
        RuntimePayload {
            schema_version: PAYLOAD_SCHEMA_VERSION,
            mode: self.mode,
            generation,
            rebuild_generated,
            webcontroller: self.webcontroller.clone(),
            server,
            dev_server_origin,
        }
    }
}

pub(super) fn write_payload(directory: &TempDir, payload: &RuntimePayload) -> Result<PathBuf> {
    let path = directory
        .path()
        .join(format!("generation-{}.json", payload.generation));
    fs::write(&path, serde_json::to_vec_pretty(payload)?)?;
    Ok(path)
}

fn find_project_root(start: &Path) -> Result<PathBuf> {
    let mut current = start.canonicalize()?;
    if current.is_file() {
        current.pop();
    }
    loop {
        if current.join("pyproject.toml").is_file() {
            return Ok(current);
        }
        if !current.pop() {
            return Err(invalid(
                "could not find pyproject.toml; run inside a Python project or pass --project-root",
            ));
        }
    }
}

fn read_project_name(project_root: &Path) -> Result<String> {
    let path = project_root.join("pyproject.toml");
    let project: PyProject = toml::from_str(&fs::read_to_string(&path)?).map_err(|error| {
        invalid(format!(
            "could not read [project].name from {}: {error}",
            path.display()
        ))
    })?;
    Ok(project.project.name)
}

fn normalize_package_name(project_name: &str) -> String {
    project_name
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || character == '_' {
                character.to_ascii_lowercase()
            } else {
                '_'
            }
        })
        .collect()
}

fn resolve_path(base: &Path, path: &Path) -> PathBuf {
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        base.join(path)
    }
}

fn discover_package_root(
    project_root: &Path,
    package: &str,
    allow_fallback: bool,
) -> Result<(String, PathBuf)> {
    let package_path = package.split('.').collect::<PathBuf>();
    for parent in [project_root.to_path_buf(), project_root.join("src")] {
        let candidate = parent.join(&package_path);
        if candidate.is_dir() {
            return Ok((package.to_string(), candidate.canonicalize()?));
        }
    }

    if allow_fallback {
        let mut candidates = Vec::new();
        for parent in [project_root.to_path_buf(), project_root.join("src")] {
            if !parent.is_dir() {
                continue;
            }
            for entry in fs::read_dir(parent)? {
                let path = entry?.path();
                if path.join("app.py").is_file() && path.join("views").is_dir() {
                    if let Some(name) = path.file_name().and_then(|name| name.to_str()) {
                        candidates.push((name.to_string(), path.canonicalize()?));
                    }
                }
            }
        }
        if candidates.len() == 1 {
            return Ok(candidates.remove(0));
        }
    }

    Err(invalid(format!(
        "could not infer Python package {package:?}; pass --package and --package-root"
    )))
}

fn adjacent_python(executable: &Path) -> Option<String> {
    let candidate = executable.parent()?.join(if cfg!(windows) {
        "python.exe"
    } else {
        "python"
    });
    candidate
        .is_file()
        .then(|| candidate.to_string_lossy().into_owned())
}

fn virtualenv_python() -> Option<String> {
    let environment = PathBuf::from(env::var_os("VIRTUAL_ENV")?);
    let candidate = if cfg!(windows) {
        environment.join("Scripts").join("python.exe")
    } else {
        environment.join("bin").join("python")
    };
    candidate
        .is_file()
        .then(|| candidate.to_string_lossy().into_owned())
}

fn canonical_dir(path: PathBuf, label: &str) -> Result<PathBuf> {
    if !path.is_dir() {
        return Err(invalid(format!(
            "{label} does not exist: {}",
            path.display()
        )));
    }
    Ok(path.canonicalize()?)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zero_argument_config_discovers_a_uv_project() {
        let project = tempfile::tempdir().unwrap();
        fs::write(
            project.path().join("pyproject.toml"),
            "[project]\nname = \"example-app\"\nversion = \"0.1.0\"\n",
        )
        .unwrap();
        let package_root = project.path().join("example_app");
        let view_root = package_root.join("views");
        let nested_dir = view_root.join("home");
        fs::create_dir_all(&nested_dir).unwrap();
        fs::write(package_root.join("app.py"), "controller = object()\n").unwrap();

        let scripts_dir =
            project
                .path()
                .join(".venv")
                .join(if cfg!(windows) { "Scripts" } else { "bin" });
        fs::create_dir_all(&scripts_dir).unwrap();
        let python = scripts_dir.join(if cfg!(windows) {
            "python.exe"
        } else {
            "python"
        });
        fs::write(&python, "").unwrap();
        let executable = scripts_dir.join(if cfg!(windows) {
            "mountaineer-dev.exe"
        } else {
            "mountaineer-dev"
        });

        let config = CoordinatorConfig::parse_from(
            RuntimeMode::Development,
            &[],
            &nested_dir,
            Some(&executable),
        )
        .unwrap();

        assert_eq!(config.project_root, project.path().canonicalize().unwrap());
        assert_eq!(config.package, "example_app");
        assert_eq!(config.webcontroller, "example_app.app:controller");
        assert_eq!(
            config.python_package_root,
            package_root.canonicalize().unwrap()
        );
        assert_eq!(config.frontend_root, view_root.canonicalize().unwrap());
        assert_eq!(config.python, python.to_string_lossy());
    }

    #[test]
    fn runtime_payload_only_contains_process_bootstrap() {
        let project = tempfile::tempdir().unwrap();
        let package_root = project.path().join("example");
        let view_root = package_root.join("views");
        let config = CoordinatorConfig {
            mode: RuntimeMode::Production,
            package: "example".to_string(),
            webcontroller: "example.app:controller".to_string(),
            host: "127.0.0.1".to_string(),
            port: 5006,
            python: "python".to_string(),
            debounce_ms: 100,
            warm_processes: 2,
            project_root: project.path().to_path_buf(),
            python_package_root: package_root,
            frontend_root: view_root,
        };
        let payload = config.payload(
            7,
            ServerConfig {
                host: "127.0.0.1".to_string(),
                port: 5006,
            },
            None,
            false,
        );

        assert_eq!(payload.schema_version, 1);
        assert_eq!(payload.generation, 7);
        assert_eq!(payload.webcontroller, "example.app:controller");
        assert_eq!(payload.server.port, 5006);
        assert_eq!(
            serde_json::from_str::<RuntimePayload>(&serde_json::to_string(&payload).unwrap())
                .unwrap(),
            payload
        );
    }
}
