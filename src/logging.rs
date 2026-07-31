use env_logger::Builder;
use log::LevelFilter;
use mountaineer_terminal as terminal;
use std::env;
use std::sync::Mutex;

lazy_static! {
    static ref LOGGER_INITIALIZED: Mutex<bool> = Mutex::new(false);
}

pub fn init_logger() {
    let mut initialized = LOGGER_INITIALIZED.lock().unwrap();
    if *initialized {
        return;
    }

    let mut builder = Builder::from_default_env();

    // Check if MOUNTAINEER_LOG_LEVEL is set
    match env::var("MOUNTAINEER_LOG_LEVEL") {
        Ok(level) => {
            // Parse the level from the environment variable
            let log_level = match level.to_uppercase().as_str() {
                "TRACE" => LevelFilter::Trace,
                "DEBUG" => LevelFilter::Debug,
                "INFO" => LevelFilter::Info,
                "WARN" | "WARNING" => LevelFilter::Warn,
                "ERROR" => LevelFilter::Error,
                _ => {
                    // Default to warn if the level is invalid
                    eprintln!(
                        "  {} {} Invalid log level {level:?}; using warning",
                        terminal::info().for_stderr().apply_to("[Rust]"),
                        terminal::warning().for_stderr().apply_to("[warning]")
                    );
                    LevelFilter::Warn
                }
            };
            // Set filter for just the mountaineer crate
            builder.filter(Some("mountaineer"), log_level);
        }
        Err(_) => {
            // Default to warn level if MOUNTAINEER_LOG_LEVEL is not set
            builder.filter(Some("mountaineer"), LevelFilter::Warn);
        }
    }

    // Keep opt-in native diagnostics in the same envelope as SSR console output.
    builder.format(|buf, record| {
        use std::io::Write;
        let level = match record.level() {
            log::Level::Warn => terminal::warning(),
            log::Level::Error => terminal::error(),
            _ => terminal::muted(),
        };
        writeln!(
            buf,
            "  {} {} {}",
            terminal::info().for_stderr().apply_to("[Rust]"),
            level
                .for_stderr()
                .apply_to(format!("[{}]", record.level().to_string().to_lowercase())),
            record.args()
        )
    });

    // Initialize the logger
    let _ = builder.try_init();
    *initialized = true;
}
