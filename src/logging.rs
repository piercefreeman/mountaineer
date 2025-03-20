use env_logger::Builder;
use log::LevelFilter;
use std::env;
use std::io::{self, Write};
use std::sync::{Arc, Mutex};

pub struct StdoutWrapper(Arc<Mutex<dyn Write + Send + 'static>>);

impl StdoutWrapper {
    pub fn new() -> Self {
        StdoutWrapper(Arc::new(Mutex::new(io::stdout())))
    }

    pub fn get_arc(&self) -> Arc<Mutex<dyn Write + Send + 'static>> {
        self.0.clone()
    }
}

impl Write for StdoutWrapper {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        let mut writer = self.0.lock().expect("Failed to lock mutex");
        writer.write(buf)
    }

    fn flush(&mut self) -> io::Result<()> {
        let mut writer = self.0.lock().expect("Failed to lock mutex");
        writer.flush()
    }
}

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
                    eprintln!("Invalid log level: {}. Using warn level instead.", level);
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

    // Format logs with timestamp, level, target, and message
    builder.format(|buf, record| {
        use std::io::Write;
        writeln!(
            buf,
            "{} [{}] {}: {}",
            chrono::Local::now().format("%Y-%m-%d %H:%M:%S%.3f"),
            record.level(),
            record.target(),
            record.args()
        )
    });

    // Initialize the logger
    let _ = builder.try_init();
    *initialized = true;
}
