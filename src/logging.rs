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
