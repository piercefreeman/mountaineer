//! Discovery of third-party imports referenced by a Python package.

#![warn(missing_docs)]

use std::{collections::BTreeSet, io, path::PathBuf, process::ExitStatus};
use tokio::process::Command;

const DISCOVER_IMPORTS: &str = include_str!("../assets/discover_imports.py");

/// Error returned by import discovery.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// Starting or waiting for Python failed.
    #[error(transparent)]
    Io(#[from] io::Error),

    /// Python returned malformed JSON.
    #[error(transparent)]
    Decode(#[from] serde_json::Error),

    /// Python import discovery exited unsuccessfully.
    #[error("Python import discovery exited with {status}:\n{stderr}")]
    Failed {
        /// Python's exit status.
        status: ExitStatus,

        /// Diagnostic output written by Python.
        stderr: String,
    },
}

/// Result returned by import discovery.
pub type Result<T> = std::result::Result<T, Error>;

/// Typed configuration for Python import discovery.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Config {
    /// Python interpreter used to inspect the package.
    pub python: String,

    /// Working directory inherited by Python.
    pub project_root: PathBuf,

    /// Package directory scanned recursively for Python source files.
    pub package_root: PathBuf,

    /// Dotted package name excluded from the discovered dependencies.
    pub package: String,
}

/// Discovers third-party imports referenced by a Python package.
pub async fn discover(config: Config) -> Result<BTreeSet<String>> {
    let output = Command::new(&config.python)
        .args(["-c", DISCOVER_IMPORTS])
        .arg(&config.package_root)
        .arg(&config.package)
        .current_dir(&config.project_root)
        .output()
        .await?;
    if !output.status.success() {
        return Err(Error::Failed {
            status: output.status,
            stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
        });
    }
    Ok(serde_json::from_slice(&output.stdout)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[tokio::test]
    async fn discovers_only_third_party_imports() {
        let project = tempfile::tempdir().unwrap();
        let package_root = project.path().join("example");
        fs::create_dir(&package_root).unwrap();
        fs::write(
            package_root.join("app.py"),
            "import os\nimport pydantic.fields\nfrom fastapi import FastAPI\n\
             from example.local import value\n",
        )
        .unwrap();

        assert_eq!(
            discover(Config {
                python: "python".to_string(),
                project_root: project.path().to_path_buf(),
                package_root,
                package: "example".to_string(),
            })
            .await
            .unwrap(),
            BTreeSet::from(["fastapi".to_string(), "pydantic.fields".to_string()])
        );
    }
}
