use crate::terminal;
use console::{colors_enabled_stderr, Style};
use indicatif::{ProgressBar, ProgressStyle};
use notify_debouncer_full::{
    new_debouncer, notify::RecursiveMode, DebounceEventResult, DebouncedEvent,
};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeSet, HashMap},
    env,
    error::Error,
    fmt::Display,
    fs,
    io::{Error as IoError, ErrorKind},
    net::{IpAddr, Ipv4Addr, SocketAddr},
    path::{Component, Path, PathBuf},
    process::Stdio,
    sync::{Arc, Mutex, OnceLock},
    time::Duration,
};
use tempfile::TempDir;
#[cfg(unix)]
use tokio::time::timeout;
use tokio::{
    io::{copy_bidirectional, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    process::{Child, ChildStdin, Command},
    signal,
    sync::{mpsc, RwLock},
    time::{sleep, Instant},
};

type AnyError = Box<dyn Error + Send + Sync>;
type Result<T> = std::result::Result<T, AnyError>;

const PAYLOAD_SCHEMA_VERSION: u16 = 1;
const PAYLOAD_PATH_ENV: &str = "MOUNTAINEER_RUNTIME_PAYLOAD";
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
const DISCOVER_IMPORTS: &str = include_str!("coordinator_assets/discover_imports.py");
const VITE_CONFIG: &str = include_str!("coordinator_assets/vite.config.mjs");
#[cfg(unix)]
const FORK_PARENT: &str = include_str!("coordinator_assets/fork_parent.py");
#[cfg(unix)]
const IMPORT_SAFETY_PROBE: &str = include_str!("coordinator_assets/import_safety_probe.py");
#[cfg(windows)]
const WARM_WORKER: &str = include_str!("coordinator_assets/warm_worker.py");

#[derive(Clone, Copy)]
enum Tone {
    Accent,
    Warning,
    Error,
    Muted,
}

impl Tone {
    fn style(self) -> Style {
        match self {
            Self::Accent => terminal::accent(),
            Self::Warning => terminal::warning(),
            Self::Error => terminal::error(),
            Self::Muted => terminal::muted(),
        }
    }
}

fn startup_spinner_slot() -> &'static Mutex<Option<ProgressBar>> {
    static SPINNER: OnceLock<Mutex<Option<ProgressBar>>> = OnceLock::new();
    SPINNER.get_or_init(|| Mutex::new(None))
}

fn start_startup_spinner() {
    let spinner = ProgressBar::new_spinner();
    spinner.set_style(
        ProgressStyle::with_template("{spinner:.green.bold} {msg}")
            .expect("valid startup spinner template"),
    );
    spinner.set_message("Starting Mountaineer...");
    spinner.enable_steady_tick(Duration::from_millis(80));
    *startup_spinner_slot().lock().unwrap() = Some(spinner);
}

fn finish_startup_spinner() {
    if let Some(spinner) = startup_spinner_slot().lock().unwrap().take() {
        spinner.finish_and_clear();
    }
}

fn print_status_line(line: String) {
    if let Some(spinner) = startup_spinner_slot().lock().unwrap().as_ref() {
        spinner.suspend(|| eprintln!("{line}"));
    } else {
        eprintln!("{line}");
    }
}

fn render_status(label: &str, message: impl Display, tone: Tone, color: bool) -> String {
    let continuation = "\n  ";
    let message = message
        .to_string()
        .replace("\r\n", "\n")
        .replace('\n', continuation);
    let label = tone
        .style()
        .for_stderr()
        .force_styling(color)
        .apply_to(label);
    format!("{label} {message}")
}

fn status(tone: Tone, label: &str, message: impl Display) {
    print_status_line(render_status(label, message, tone, colors_enabled_stderr()));
}

fn render_status_with_details(
    label: &str,
    message: impl Display,
    tone: Tone,
    details: &[String],
    color: bool,
) -> String {
    let mut output = render_status(label, message, tone, color);
    for detail in details {
        output.push('\n');
        output.push_str("  ");
        output.push_str(
            &terminal::detail()
                .for_stderr()
                .force_styling(color)
                .apply_to(detail)
                .to_string(),
        );
    }
    output
}

fn status_with_details(tone: Tone, label: &str, message: impl Display, details: &[String]) {
    print_status_line(render_status_with_details(
        label,
        message,
        tone,
        details,
        colors_enabled_stderr(),
    ));
}

fn discovered_libraries(imports: &BTreeSet<String>) -> Vec<String> {
    let libraries = imports
        .iter()
        .filter_map(|module| module.split('.').next())
        .collect::<BTreeSet<_>>();
    libraries.into_iter().map(str::to_string).collect()
}

fn link(url: impl Display) -> String {
    terminal::link().for_stderr().apply_to(url).to_string()
}

fn emphasis(value: impl Display) -> String {
    Style::new().bold().for_stderr().apply_to(value).to_string()
}

fn detail(value: impl Display) -> String {
    terminal::detail().for_stderr().apply_to(value).to_string()
}

fn timing(start: Instant) -> String {
    let value = format!("in {}", format_duration(start.elapsed()));
    detail(value)
}

fn format_duration(duration: Duration) -> String {
    if duration < Duration::from_millis(1) {
        "<1ms".to_string()
    } else if duration < Duration::from_secs(1) {
        format!("{}ms", duration.as_millis())
    } else {
        format!("{:.2}s", duration.as_secs_f64())
    }
}

pub fn report_error(program: &str, error: &dyn Display) {
    finish_startup_spinner();
    status(Tone::Error, "Error", format!("{program}: {error}"));
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeMode {
    Development,
    Production,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ServerConfig {
    pub host: String,
    pub port: u16,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RuntimePayload {
    pub schema_version: u16,
    pub mode: RuntimeMode,
    pub generation: u64,
    pub rebuild_generated: bool,
    pub webcontroller: String,
    pub server: ServerConfig,
    pub dev_server_origin: Option<String>,
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
pub struct CoordinatorConfig {
    mode: RuntimeMode,
    package: String,
    webcontroller: String,
    host: String,
    port: u16,
    python: String,
    debounce_ms: u64,
    #[cfg_attr(not(windows), allow(dead_code))]
    warm_processes: usize,
    project_root: PathBuf,
    python_package_root: PathBuf,
    frontend_root: PathBuf,
}

impl CoordinatorConfig {
    fn parse(mode: RuntimeMode, args: &[String]) -> Result<Self> {
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
        let mut options = HashMap::new();
        let mut index = 0;
        while index < args.len() {
            let key = args[index].as_str();
            if !key.starts_with("--") {
                return Err(invalid(format!("unexpected argument {key:?}")));
            }
            let value = args
                .get(index + 1)
                .ok_or_else(|| invalid(format!("missing value for {key}")))?;
            options.insert(key.to_string(), value.clone());
            index += 2;
        }

        let project_root = match options.get("--project-root") {
            Some(path) => canonical_dir(resolve_path(current_dir, path), "project root")?,
            None => find_project_root(current_dir)?,
        };
        let project_name = read_project_name(&project_root)?;
        let requested_package = options
            .get("--package")
            .cloned()
            .unwrap_or_else(|| normalize_package_name(&project_name));
        let (package, python_package_root) = match options.get("--package-root") {
            Some(path) => (
                requested_package,
                canonical_dir(resolve_path(&project_root, path), "Python package root")?,
            ),
            None => discover_package_root(
                &project_root,
                &requested_package,
                !options.contains_key("--package"),
            )?,
        };
        let webcontroller = options
            .get("--webcontroller")
            .cloned()
            .unwrap_or_else(|| format!("{package}.app:controller"));
        if !webcontroller.contains(':') {
            return Err(invalid(
                "--webcontroller must look like package.module:controller",
            ));
        }
        let view_root = canonical_dir(
            options
                .get("--view-root")
                .map(|path| resolve_path(&project_root, path))
                .unwrap_or_else(|| python_package_root.join("views")),
            "view root",
        )?;
        let frontend_root = canonical_dir(
            options
                .get("--frontend-root")
                .map(|path| resolve_path(&project_root, path))
                .unwrap_or_else(|| view_root.clone()),
            "frontend root",
        )?;
        let python = options
            .get("--python")
            .cloned()
            .or_else(|| current_exe.and_then(adjacent_python))
            .or_else(virtualenv_python)
            .or_else(|| env::var("PYTHON").ok())
            .unwrap_or_else(|| "python".to_string());

        Ok(Self {
            mode,
            package,
            webcontroller,
            host: options
                .get("--host")
                .cloned()
                .unwrap_or_else(|| "127.0.0.1".to_string()),
            port: parse_number(&options, "--port", 5006)?,
            python,
            debounce_ms: parse_number(&options, "--debounce-ms", 100)?,
            warm_processes: parse_number(&options, "--warm-processes", 2)?,
            project_root,
            python_package_root,
            frontend_root,
        })
    }

    fn payload(
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

#[derive(Debug, Serialize)]
#[serde(tag = "command", rename_all = "snake_case")]
enum LayerCommand {
    Start {
        generation: u64,
        payload_path: PathBuf,
    },
    #[cfg(unix)]
    Stop { generation: u64 },
    #[cfg(unix)]
    Exit,
}

struct PythonHotReload {
    imports: BTreeSet<String>,
    #[cfg(unix)]
    strategy: ForkStrategy,
    #[cfg(windows)]
    strategy: WarmPoolStrategy,
}

struct ActiveWorker {
    #[cfg(unix)]
    generation: u64,
    #[cfg(windows)]
    child: Child,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ChangeKind {
    Python,
    Frontend,
    Style,
}

#[cfg(unix)]
#[derive(Deserialize)]
struct ImportSafetyProbe {
    safe: BTreeSet<String>,
    excluded: Vec<ExcludedImport>,
}

#[cfg(unix)]
#[derive(Deserialize)]
struct ExcludedImport {
    module: String,
    thread_count: Option<usize>,
    reason: String,
}

struct ViteDevServer {
    child: Child,
    origin: String,
    backend_signal: PathBuf,
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
    async fn spawn(config: &CoordinatorConfig, directory: &TempDir) -> Result<Self> {
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
        if let Err(error) = wait_until_ready(
            SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), port),
            Duration::from_secs(15),
        )
        .await
        {
            child.start_kill()?;
            child.wait().await?;
            return Err(error);
        }
        Ok(Self {
            child,
            origin,
            backend_signal,
        })
    }

    fn reload_backend(&self, generation: u64) -> Result<()> {
        fs::write(&self.backend_signal, generation.to_string())?;
        Ok(())
    }

    async fn shutdown(&mut self) -> Result<()> {
        self.child.start_kill()?;
        self.child.wait().await?;
        Ok(())
    }
}

impl PythonHotReload {
    async fn new(config: &CoordinatorConfig, imports: BTreeSet<String>) -> Result<Self> {
        let libraries = discovered_libraries(&imports);
        if !libraries.is_empty() {
            let noun = if libraries.len() == 1 {
                "library"
            } else {
                "libraries"
            };
            status(
                Tone::Muted,
                "Found",
                format!(
                    "{} Python {noun} for warm reload: {}",
                    emphasis(libraries.len()),
                    detail(libraries.join(", "))
                ),
            );
        }
        #[cfg(unix)]
        let strategy = {
            let safe_imports = fork_safe_imports(config, &imports).await?;
            ForkStrategy::spawn(config, &safe_imports)?
        };
        #[cfg(windows)]
        let strategy = WarmPoolStrategy::spawn(config, &imports)?;

        Ok(Self { imports, strategy })
    }

    async fn start(&mut self, generation: u64, payload_path: PathBuf) -> Result<ActiveWorker> {
        #[cfg(unix)]
        {
            self.strategy
                .send(&LayerCommand::Start {
                    generation,
                    payload_path,
                })
                .await?;
            Ok(ActiveWorker { generation })
        }
        #[cfg(windows)]
        {
            let child = self.strategy.activate(generation, payload_path).await?;
            Ok(ActiveWorker { child })
        }
    }

    async fn stop(&mut self, worker: ActiveWorker) -> Result<()> {
        #[cfg(unix)]
        self.strategy
            .send(&LayerCommand::Stop {
                generation: worker.generation,
            })
            .await?;
        #[cfg(windows)]
        {
            let mut worker = worker;
            worker.child.start_kill()?;
            worker.child.wait().await?;
        }
        Ok(())
    }

    async fn shutdown(&mut self) -> Result<()> {
        self.strategy.shutdown().await
    }
}

#[cfg(unix)]
struct ForkStrategy {
    child: Child,
    stdin: ChildStdin,
}

#[cfg(unix)]
impl ForkStrategy {
    fn spawn(config: &CoordinatorConfig, imports: &BTreeSet<String>) -> Result<Self> {
        let mut child = Command::new(&config.python)
            .args(["-c", FORK_PARENT])
            .arg(serde_json::to_string(imports)?)
            .current_dir(&config.project_root)
            .stdin(Stdio::piped())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .kill_on_drop(true)
            .spawn()?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| invalid("failed to open fork-template stdin"))?;
        Ok(Self { child, stdin })
    }

    async fn send(&mut self, command: &LayerCommand) -> Result<()> {
        send_json_line(&mut self.stdin, command).await
    }

    async fn shutdown(&mut self) -> Result<()> {
        let _ = self.send(&LayerCommand::Exit).await;
        if timeout(Duration::from_secs(5), self.child.wait())
            .await
            .is_err()
        {
            self.child.start_kill()?;
            self.child.wait().await?;
        }
        Ok(())
    }
}

#[cfg(windows)]
struct WarmPoolStrategy {
    python: String,
    project_root: PathBuf,
    imports_json: String,
    target_size: usize,
    idle: Vec<WarmProcess>,
}

#[cfg(windows)]
struct WarmProcess {
    child: Child,
    stdin: ChildStdin,
}

#[cfg(windows)]
impl WarmPoolStrategy {
    fn spawn(config: &CoordinatorConfig, imports: &BTreeSet<String>) -> Result<Self> {
        let mut strategy = Self {
            python: config.python.clone(),
            project_root: config.project_root.clone(),
            imports_json: serde_json::to_string(imports)?,
            target_size: config.warm_processes.max(1),
            idle: Vec::new(),
        };
        strategy.replenish()?;
        Ok(strategy)
    }

    fn replenish(&mut self) -> Result<()> {
        while self.idle.len() < self.target_size {
            let mut child = Command::new(&self.python)
                .args(["-c", WARM_WORKER])
                .arg(&self.imports_json)
                .current_dir(&self.project_root)
                .stdin(Stdio::piped())
                .stdout(Stdio::inherit())
                .stderr(Stdio::inherit())
                .kill_on_drop(true)
                .spawn()?;
            let stdin = child
                .stdin
                .take()
                .ok_or_else(|| invalid("failed to open warm-worker stdin"))?;
            self.idle.push(WarmProcess { child, stdin });
        }
        Ok(())
    }

    async fn activate(&mut self, generation: u64, payload_path: PathBuf) -> Result<Child> {
        let mut process = self
            .idle
            .pop()
            .ok_or_else(|| invalid("warm process pool is empty"))?;
        send_json_line(
            &mut process.stdin,
            &LayerCommand::Start {
                generation,
                payload_path,
            },
        )
        .await?;
        drop(process.stdin);
        self.replenish()?;
        Ok(process.child)
    }

    async fn shutdown(&mut self) -> Result<()> {
        for process in &mut self.idle {
            process.child.start_kill()?;
            process.child.wait().await?;
        }
        self.idle.clear();
        Ok(())
    }
}

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
    match mode {
        RuntimeMode::Development => run_development(config).await,
        RuntimeMode::Production => run_production(config).await,
    }
}

fn usage(mode: RuntimeMode) -> &'static str {
    match mode {
        RuntimeMode::Development => {
            "Mountaineer development server

Usage: mountaineer-dev [OPTIONS]

Options:
      --host <HOST>              Public host [default: 127.0.0.1]
      --port <PORT>              Public port [default: 5006]
      --project-root <PATH>      Project root [default: nearest pyproject.toml]
      --package <PACKAGE>        Python package [default: project name]
      --package-root <PATH>      Python package root [default: inferred]
      --webcontroller <TARGET>   App controller [default: <package>.app:controller]
      --view-root <PATH>         Mountaineer view root [default: <package>/views]
      --frontend-root <PATH>     Frontend package root [default: view root]
      --python <PATH>            Python executable [default: active environment]
      --debounce-ms <MILLIS>     Filesystem debounce [default: 100]
      --warm-processes <COUNT>   Windows warm pool size [default: 2]
  -h, --help                     Print help"
        }
        RuntimeMode::Production => {
            "Mountaineer production server

Usage: mountaineer-prod [OPTIONS]

Options:
      --host <HOST>              Public host [default: 127.0.0.1]
      --port <PORT>              Public port [default: 5006]
      --project-root <PATH>      Project root [default: nearest pyproject.toml]
      --package <PACKAGE>        Python package [default: project name]
      --package-root <PATH>      Python package root [default: inferred]
      --webcontroller <TARGET>   App controller [default: <package>.app:controller]
      --view-root <PATH>         Mountaineer view root [default: <package>/views]
      --frontend-root <PATH>     Frontend package root [default: view root]
      --python <PATH>            Python executable [default: active environment]
  -h, --help                     Print help"
        }
    }
}

async fn run_development(config: CoordinatorConfig) -> Result<()> {
    start_startup_spinner();
    let listener = TcpListener::bind((config.host.as_str(), config.port)).await?;
    let public_address = listener.local_addr()?;
    let active_target = Arc::new(RwLock::new(None));
    let proxy_task = tokio::spawn(serve_proxy(listener, active_target.clone()));

    let payload_dir = tempfile::tempdir()?;
    let mut vite = ViteDevServer::spawn(&config, &payload_dir).await?;
    let mut generation = 1;
    let imports = discover_imports(&config).await?;
    let backend_started = Instant::now();
    let mut hot_reload = PythonHotReload::new(&config, imports).await?;
    let (mut active_worker, initial_target) = start_candidate(
        &config,
        &payload_dir,
        &mut hot_reload,
        generation,
        &vite.origin,
        true,
    )
    .await?;
    *active_target.write().await = Some(initial_target);
    finish_startup_spinner();
    status(
        Tone::Accent,
        "Started",
        format!(
            "app {} @ {}",
            timing(backend_started),
            link(format!("http://{public_address}"))
        ),
    );

    let (event_tx, mut event_rx) = mpsc::unbounded_channel();
    let mut debouncer = new_debouncer(
        Duration::from_millis(config.debounce_ms),
        None,
        move |result: DebounceEventResult| {
            let _ = event_tx.send(result);
        },
    )?;
    debouncer.watch(&config.python_package_root, RecursiveMode::Recursive)?;
    if !config
        .frontend_root
        .starts_with(&config.python_package_root)
    {
        debouncer.watch(&config.frontend_root, RecursiveMode::Recursive)?;
    }

    loop {
        tokio::select! {
            _ = signal::ctrl_c() => break,
            result = event_rx.recv() => {
                let Some(result) = result else {
                    return Err(invalid("filesystem watcher stopped unexpectedly"));
                };
                let events = match result {
                    Ok(events) => events,
                    Err(errors) => {
                        for error in errors {
                            status(Tone::Warning, "Warning", format!("watch error: {error}"));
                        }
                        continue;
                    }
                };
                let Some(change_kind) = restart_kind(&events) else {
                    continue;
                };
                if change_kind == ChangeKind::Style {
                    status(Tone::Accent, "Updated", "styles");
                    continue;
                }
                let reload_started = Instant::now();
                let refresh_imports = change_kind == ChangeKind::Python;

                generation += 1;
                let next_imports = if refresh_imports {
                    match discover_imports(&config).await {
                        Ok(imports) => imports,
                        Err(error) => {
                            status(
                                Tone::Error,
                                "Failed",
                                format!(
                                    "import discovery; keeping the last working backend ({error})"
                                ),
                            );
                            continue;
                        }
                    }
                } else {
                    hot_reload.imports.clone()
                };

                if next_imports == hot_reload.imports {
                    match start_candidate(
                        &config,
                        &payload_dir,
                        &mut hot_reload,
                        generation,
                        &vite.origin,
                        refresh_imports,
                    ).await {
                        Ok((candidate, target)) => {
                            *active_target.write().await = Some(target);
                            hot_reload.stop(active_worker).await?;
                            active_worker = candidate;
                            if refresh_imports {
                                vite.reload_backend(generation)?;
                            }
                            let target = if refresh_imports {
                                "Python backend"
                            } else {
                                "frontend"
                            };
                            status(
                                Tone::Accent,
                                "Updated",
                                format!("{target} {}", timing(reload_started)),
                            );
                        }
                        Err(error) => {
                            status(
                                Tone::Error,
                                "Failed",
                                format!(
                                    "backend reload; keeping the last working backend ({error})"
                                ),
                            );
                        }
                    }
                } else {
                    let mut candidate_strategy =
                        PythonHotReload::new(&config, next_imports).await?;
                    match start_candidate(
                        &config,
                        &payload_dir,
                        &mut candidate_strategy,
                        generation,
                        &vite.origin,
                        true,
                    ).await {
                        Ok((candidate, target)) => {
                            *active_target.write().await = Some(target);
                            hot_reload.stop(active_worker).await?;
                            hot_reload.shutdown().await?;
                            hot_reload = candidate_strategy;
                            active_worker = candidate;
                            vite.reload_backend(generation)?;
                            status(
                                Tone::Accent,
                                "Updated",
                                format!(
                                    "Python backend with refreshed imports {}",
                                    timing(reload_started)
                                ),
                            );
                        }
                        Err(error) => {
                            candidate_strategy.shutdown().await?;
                            status(
                                Tone::Error,
                                "Failed",
                                format!(
                                    "backend reload; keeping the last working backend ({error})"
                                ),
                            );
                        }
                    }
                }
            }
        }
    }

    hot_reload.stop(active_worker).await?;
    hot_reload.shutdown().await?;
    vite.shutdown().await?;
    proxy_task.abort();
    status(Tone::Muted, "Stopped", "Mountaineer");
    Ok(())
}

async fn start_candidate(
    config: &CoordinatorConfig,
    payload_dir: &TempDir,
    hot_reload: &mut PythonHotReload,
    generation: u64,
    vite_origin: &str,
    rebuild_generated: bool,
) -> Result<(ActiveWorker, SocketAddr)> {
    let internal_port = reserve_loopback_port()?;
    let target = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), internal_port);
    let payload = config.payload(
        generation,
        ServerConfig {
            host: Ipv4Addr::LOCALHOST.to_string(),
            port: internal_port,
        },
        Some(vite_origin.to_string()),
        rebuild_generated,
    );
    let payload_path = write_payload(payload_dir, &payload)?;
    let worker = hot_reload.start(generation, payload_path).await?;
    if let Err(error) = wait_until_ready(target, Duration::from_secs(15)).await {
        hot_reload.stop(worker).await?;
        return Err(error);
    }
    Ok((worker, target))
}

async fn run_production(config: CoordinatorConfig) -> Result<()> {
    let payload_dir = tempfile::tempdir()?;
    let payload = config.payload(
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
        .args(["-c", "from mountaineer.runtime import main; main()"])
        .env(PAYLOAD_PATH_ENV, payload_path)
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

async fn discover_imports(config: &CoordinatorConfig) -> Result<BTreeSet<String>> {
    let output = Command::new(&config.python)
        .args(["-c", DISCOVER_IMPORTS])
        .arg(&config.python_package_root)
        .arg(&config.package)
        .current_dir(&config.project_root)
        .output()
        .await?;
    if !output.status.success() {
        return Err(invalid(format!(
            "Python import discovery exited with {}:\n{}",
            output.status,
            String::from_utf8_lossy(&output.stderr)
        )));
    }
    let imports: Vec<String> = serde_json::from_slice(&output.stdout)?;
    Ok(imports.into_iter().collect())
}

#[cfg(unix)]
async fn fork_safe_imports(
    config: &CoordinatorConfig,
    imports: &BTreeSet<String>,
) -> Result<BTreeSet<String>> {
    if imports.is_empty() {
        return Ok(BTreeSet::new());
    }
    let output = Command::new(&config.python)
        .args(["-c", IMPORT_SAFETY_PROBE])
        .arg(serde_json::to_string(imports)?)
        .current_dir(&config.project_root)
        .output()
        .await?;
    if !output.status.success() {
        return Err(invalid(format!(
            "fork-safety probe exited with {}:\n{}",
            output.status,
            String::from_utf8_lossy(&output.stderr)
        )));
    }

    let result: ImportSafetyProbe = serde_json::from_slice(&output.stdout)?;
    if !result.excluded.is_empty() {
        let noun = if result.excluded.len() == 1 {
            "library"
        } else {
            "libraries"
        };
        let details = result
            .excluded
            .iter()
            .map(|excluded| match excluded.thread_count {
                Some(threads) => {
                    format!("- {} ({threads} threads after import)", excluded.module)
                }
                None => format!("- {} ({})", excluded.module, excluded.reason),
            })
            .collect::<Vec<_>>();
        status_with_details(
            Tone::Warning,
            "Ignored",
            format!("{} Python {noun} for warm reload", details.len()),
            &details,
        );
    }
    Ok(result.safe)
}

async fn send_json_line(stdin: &mut ChildStdin, command: &LayerCommand) -> Result<()> {
    let mut payload = serde_json::to_vec(command)?;
    payload.push(b'\n');
    stdin.write_all(&payload).await?;
    stdin.flush().await?;
    Ok(())
}

async fn wait_until_ready(address: SocketAddr, wait: Duration) -> Result<()> {
    let deadline = Instant::now() + wait;
    loop {
        if TcpStream::connect(address).await.is_ok() {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err(invalid(format!(
                "timed out waiting for backend at {address}"
            )));
        }
        sleep(Duration::from_millis(50)).await;
    }
}

async fn serve_proxy(
    listener: TcpListener,
    active_target: Arc<RwLock<Option<SocketAddr>>>,
) -> Result<()> {
    loop {
        let (mut inbound, _) = listener.accept().await?;
        let target = *active_target.read().await;
        tokio::spawn(async move {
            let Some(target) = target else {
                let _ = inbound
                    .write_all(
                        b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 23\r\n\r\nBackend is starting up.",
                    )
                    .await;
                return;
            };
            match TcpStream::connect(target).await {
                Ok(mut outbound) => {
                    let _ = copy_bidirectional(&mut inbound, &mut outbound).await;
                }
                Err(error) => status(
                    Tone::Warning,
                    "Warning",
                    format!("backend proxy connection failed: {error}"),
                ),
            }
        });
    }
}

fn restart_kind(events: &[DebouncedEvent]) -> Option<ChangeKind> {
    let mut change_kind = None;
    for path in events.iter().flat_map(|event| &event.event.paths) {
        if ignored_path(path) {
            continue;
        }
        match path.extension().and_then(|extension| extension.to_str()) {
            Some("py") => return Some(ChangeKind::Python),
            Some("js" | "jsx" | "ts" | "tsx" | "mjs" | "cjs" | "json") => {
                change_kind = Some(ChangeKind::Frontend)
            }
            Some("css" | "scss" | "sass") if change_kind.is_none() => {
                change_kind = Some(ChangeKind::Style)
            }
            _ => {}
        }
    }
    change_kind
}

fn ignored_path(path: &Path) -> bool {
    path.components().any(|component| {
        matches!(
            component,
            Component::Normal(name)
                if matches!(
                    name.to_str(),
                    Some(
                        ".git"
                            | ".venv"
                            | ".mountaineer"
                            | ".mountaineer-vite"
                            | "node_modules"
                            | "__pycache__"
                    )
                )
        )
    })
}

fn reserve_loopback_port() -> Result<u16> {
    // ponytail: a short bind/drop race is acceptable for the POC; pass an open
    // socket to Python if real-world collisions make this observable.
    Ok(std::net::TcpListener::bind((Ipv4Addr::LOCALHOST, 0))?
        .local_addr()?
        .port())
}

fn write_payload(directory: &TempDir, payload: &RuntimePayload) -> Result<PathBuf> {
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

fn resolve_path(base: &Path, path: &str) -> PathBuf {
    let path = PathBuf::from(path);
    if path.is_absolute() {
        path
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

fn parse_number<T>(options: &HashMap<String, String>, name: &str, default: T) -> Result<T>
where
    T: std::str::FromStr,
    T::Err: Error + Send + Sync + 'static,
{
    options
        .get(name)
        .map(|value| value.parse().map_err(Into::into))
        .transpose()
        .map(|value| value.unwrap_or(default))
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

fn invalid(message: impl Into<String>) -> AnyError {
    IoError::new(ErrorKind::InvalidInput, message.into()).into()
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
    fn status_lines_share_one_palette_and_layout() {
        assert_eq!(
            render_status("Started", "backend", Tone::Accent, false),
            "Started backend"
        );
        assert_eq!(
            render_status("Failed", "backend", Tone::Error, true),
            "\u{1b}[38;2;231;90;39m\u{1b}[1mFailed\u{1b}[0m backend"
        );
        assert_eq!(
            render_status("Failed", "first line\nsecond line", Tone::Error, false),
            "Failed first line\n  second line"
        );
        assert_eq!(format_duration(Duration::from_micros(50)), "<1ms");
        assert_eq!(format_duration(Duration::from_millis(42)), "42ms");
        assert_eq!(format_duration(Duration::from_millis(1250)), "1.25s");
        assert_eq!(
            discovered_libraries(&BTreeSet::from([
                "fastapi".to_string(),
                "pydantic.fields".to_string(),
                "pydantic.main".to_string(),
            ])),
            vec!["fastapi".to_string(), "pydantic".to_string()]
        );
        assert_eq!(
            render_status_with_details(
                "Found",
                "2 Python libraries for warm reload",
                Tone::Muted,
                &["- fastapi".to_string(), "- pydantic".to_string()],
                true,
            ),
            "\u{1b}[38;2;176;175;167mFound\u{1b}[0m 2 Python libraries for warm reload\n  \u{1b}[38;2;128;128;123m- fastapi\u{1b}[0m\n  \u{1b}[38;2;128;128;123m- pydantic\u{1b}[0m"
        );
    }

    #[test]
    fn startup_spinner_clears_when_the_server_is_ready() {
        start_startup_spinner();
        assert!(startup_spinner_slot().lock().unwrap().is_some());
        finish_startup_spinner();
        assert!(startup_spinner_slot().lock().unwrap().is_none());
    }

    #[tokio::test]
    async fn import_discovery_returns_only_third_party_modules() {
        let project = tempfile::tempdir().unwrap();
        let package_root = project.path().join("example");
        let view_root = package_root.join("views");
        fs::create_dir_all(&view_root).unwrap();
        fs::write(
            package_root.join("app.py"),
            "import os\nimport pydantic.fields\nfrom fastapi import FastAPI\n\
             from example.local import value\n",
        )
        .unwrap();
        let config = CoordinatorConfig {
            mode: RuntimeMode::Development,
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

        assert_eq!(
            discover_imports(&config).await.unwrap(),
            BTreeSet::from(["fastapi".to_string(), "pydantic.fields".to_string()])
        );
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

    #[test]
    fn watcher_ignores_generated_and_dependency_files() {
        let relevant = DebouncedEvent {
            event: notify_debouncer_full::notify::Event::new(
                notify_debouncer_full::notify::EventKind::Any,
            )
            .add_path(PathBuf::from("example/views/home/page.tsx")),
            time: std::time::Instant::now(),
        };
        let ignored = DebouncedEvent {
            event: notify_debouncer_full::notify::Event::new(
                notify_debouncer_full::notify::EventKind::Any,
            )
            .add_path(PathBuf::from("example/views/node_modules/react/index.js")),
            time: std::time::Instant::now(),
        };
        let style = DebouncedEvent {
            event: notify_debouncer_full::notify::Event::new(
                notify_debouncer_full::notify::EventKind::Any,
            )
            .add_path(PathBuf::from("example/views/app/main.css")),
            time: std::time::Instant::now(),
        };
        let python = DebouncedEvent {
            event: notify_debouncer_full::notify::Event::new(
                notify_debouncer_full::notify::EventKind::Any,
            )
            .add_path(PathBuf::from("example/controllers/home.py")),
            time: std::time::Instant::now(),
        };

        assert_eq!(restart_kind(&[relevant]), Some(ChangeKind::Frontend));
        assert_eq!(
            restart_kind(std::slice::from_ref(&style)),
            Some(ChangeKind::Style)
        );
        assert_eq!(restart_kind(&[style, python]), Some(ChangeKind::Python));
        assert_eq!(restart_kind(&[ignored]), None);
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn fork_probe_excludes_thread_starting_imports() {
        let project = tempfile::tempdir().unwrap();
        fs::write(project.path().join("safe_import.py"), "VALUE = 1\n").unwrap();
        fs::write(
            project.path().join("threaded_import.py"),
            "import threading, time\n\
             threading.Thread(target=lambda: time.sleep(5), daemon=True).start()\n",
        )
        .unwrap();
        let package_root = project.path().join("example");
        let view_root = package_root.join("views");
        fs::create_dir_all(&view_root).unwrap();
        let config = CoordinatorConfig {
            mode: RuntimeMode::Development,
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

        let safe = fork_safe_imports(
            &config,
            &BTreeSet::from(["safe_import".to_string(), "threaded_import".to_string()]),
        )
        .await
        .unwrap();

        assert_eq!(safe, BTreeSet::from(["safe_import".to_string()]));
    }
}
