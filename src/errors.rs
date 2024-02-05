use std::error::Error;
use std::fmt;

#[derive(Debug, PartialEq, Eq)]
pub enum AppError {
    V8ExceptionError(String),
    HardTimeoutError(String),
}

impl fmt::Display for AppError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match *self {
            AppError::V8ExceptionError(ref err) => write!(f, "V8 Exception Error: {}", err),
            AppError::HardTimeoutError(ref err) => write!(f, "Hard Timeout Error: {}", err),
        }
    }
}

impl Error for AppError {}
