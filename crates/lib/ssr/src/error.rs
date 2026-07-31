use std::fmt;

/// Error returned while rendering JavaScript in embedded V8.
#[derive(Debug, PartialEq, Eq)]
pub enum Error {
    /// V8 could not compile or execute the supplied JavaScript.
    JavaScript(String),

    /// Rendering exceeded its configured hard timeout.
    Timeout(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match *self {
            Self::JavaScript(ref error) => write!(f, "V8 Exception Error: {error}"),
            Self::Timeout(ref error) => write!(f, "Hard Timeout Error: {error}"),
        }
    }
}

impl std::error::Error for Error {}
