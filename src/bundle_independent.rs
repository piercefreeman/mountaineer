use log::debug;
use pyo3::prelude::*;
use std::fs::File;
use std::io::Write;
use std::path::{Path, PathBuf};
use tempfile::TempDir;

use crate::bundle_common::{bundle_common, BundleError, BundleMode};
use crate::code_gen;

/// Compile independent bundles using bundle_common.
///
/// For each group of input paths, this function:
/// 1. Creates a temporary directory.
/// 2. Writes an entrypoint file (using your custom code generation logic).
/// 3. Uses bundle_common to compile the entrypoint.
/// 4. Returns two lists (one for output and one for sourcemaps) to Python.
///
/// Parameters:
///   - `paths`: List of list of strings representing groups of module paths.
///   - `node_modules_path`: Path to node_modules directory for resolving dependencies.
///   - `environment`: Environment string (e.g., "development", "production").
///   - `live_reload_port`: Port for live reload server if enabled, or -1 if disabled.
///   - `live_reload_import`: An extra import string (if needed) for live reload.
///   - `is_ssr`: Whether the bundle is for server-side (affects entrypoint generation).
///   - `tsconfig_path`: Path to tsconfig file for bundling.
#[pyfunction]
#[pyo3(signature = (paths, node_modules_path, environment, live_reload_port, live_reload_import, is_ssr, tsconfig_path=None))]
#[allow(clippy::too_many_arguments)]
pub fn compile_independent_bundles(
    _py: Python,
    paths: Vec<Vec<String>>,
    node_modules_path: String,
    environment: String,
    live_reload_port: i32,
    live_reload_import: String,
    is_ssr: bool,
    tsconfig_path: Option<String>,
) -> PyResult<(Vec<String>, Vec<String>)> {
    let mut output_files = Vec::new();
    let mut sourcemap_files = Vec::new();

    for path_group in paths.iter() {
        // Create a temporary directory for the current bundle.
        let temp_dir = TempDir::new()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        // Create the entrypoint file
        let entrypoint_path =
            create_entrypoint(&temp_dir, path_group, is_ssr, &live_reload_import)?;

        // Determine bundle mode based on is_ssr flag
        let bundle_mode = if is_ssr {
            BundleMode::SingleServer
        } else {
            BundleMode::SingleClient
        };

        // Get live_reload_port as Option<u16>
        let live_reload_port_option = if live_reload_port > 0 {
            Some(live_reload_port as u16)
        } else {
            None
        };

        // Use bundle_common to bundle the entrypoint
        let bundle_results = bundle_common(
            vec![entrypoint_path.to_str().unwrap().to_string()],
            bundle_mode,
            environment.clone(),
            node_modules_path.clone(),
            live_reload_port_option,
            tsconfig_path.clone(),
            false,
        )
        .map_err(|e| match e {
            BundleError::IoError(err) => {
                PyErr::new::<pyo3::exceptions::PyIOError, _>(err.to_string())
            }
            BundleError::BundlingError(msg) => {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(msg)
            }
            BundleError::OutputError(msg) => PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(msg),
            BundleError::FileNotFound(path) => {
                PyErr::new::<pyo3::exceptions::PyFileNotFoundError, _>(format!(
                    "File not found: {path}"
                ))
            }
            BundleError::InvalidInput(msg) => PyErr::new::<pyo3::exceptions::PyValueError, _>(msg),
        })?;

        // We should only have one entrypoint result as we're bundling one entrypoint at a time
        if bundle_results.entrypoints.len() != 1 {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "Expected 1 bundle result, got {}",
                bundle_results.entrypoints.len()
            )));
        }

        // Extract the script and sourcemap from the result
        let (_, bundle_result) = bundle_results.entrypoints.into_iter().next().unwrap();
        let mut compiled_file = bundle_result.script;
        let sourcemap_file = bundle_result.map.unwrap_or_default();

        // Special handling for SSR mode
        if is_ssr {
            // We expect the format of the iife file will be (function() { ... })()
            // Unlike esbuild, which supports a global-name (https://esbuild.github.io/api/#global-name) to set
            // the entrypoint, rolldown does not currently support this.

            // First validate the format of the compiled file matches our expectations
            if !compiled_file.starts_with("(function(") {
                // Log the beginning and ending of the compiled file for debugging
                let start_chars: String = compiled_file.chars().take(50).collect();
                let end_chars: String = compiled_file
                    .chars()
                    .rev()
                    .take(50)
                    .collect::<String>()
                    .chars()
                    .rev()
                    .collect();

                return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                    format!(
                        "Compiled file does not match expected IIFE format: (function() {{ ... }})()\n\nBeginning 50 chars: {start_chars}\nEnding 50 chars: {end_chars}"
                    )
                ));
            }

            // Then we add a manual var assignment prefix
            // Replace the opening part with our SSR variable assignment
            // Newlines required to clear out any trailing comments
            compiled_file = format!("var SSR = (() => {{\nreturn {compiled_file}\n}})();")
        }

        output_files.push(compiled_file);
        sourcemap_files.push(sourcemap_file);
    }
    Ok((output_files, sourcemap_files))
}

/// Validate that all paths in the group are absolute paths.
/// Returns an error message if any relative paths are found.
fn validate_absolute_paths(path_group: &[String]) -> Result<(), String> {
    for path in path_group {
        let path_buf = Path::new(path);
        if !path_buf.is_absolute() {
            return Err(format!(
                "All paths must be absolute. Relative path found: {path}. The entrypoint is written to a temporary directory that won't properly resolve relative paths."
            ));
        }
    }
    Ok(())
}

/// Create an entrypoint file in the given temporary directory that wraps a core
/// view in its layouts. See `code_gen::build_entrypoint` for the construction logic.
/// The file is named "entrypoint.jsx".
fn create_entrypoint(
    temp_dir: &TempDir,
    path_group: &[String],
    is_server: bool,
    live_reload_import: &str,
) -> PyResult<PathBuf> {
    // Validate that all paths are absolute since the entrypoint will be written to a temporary directory
    if let Err(error_msg) = validate_absolute_paths(path_group) {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(error_msg));
    }

    let entrypoint_path = temp_dir.path().join("entrypoint.jsx");
    let mut file = File::create(&entrypoint_path)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

    let entrypoint_content = code_gen::build_entrypoint(path_group, is_server, live_reload_import);
    debug!(
        "Writing entrypoint at path {}, contents {}",
        entrypoint_path.display(),
        entrypoint_content
    );

    file.write_all(entrypoint_content.as_bytes())
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;
    Ok(entrypoint_path)
}

#[cfg(test)]
mod tests {
    use super::*;
    

    fn win_paths() -> Vec<String> {
        vec![
            r"C:\absolute\path\to\component1.tsx".into(),
            r"C:\absolute\path\to\component2.tsx".into(),
        ]
    }

    fn unix_paths() -> Vec<String> {
        vec![
            "/absolute/path/to/component1.tsx".into(),
            "/absolute/path/to/component2.tsx".into(),
        ]
    }

    #[test]
    fn test_validate_absolute_paths_with_absolute_paths() {
        let absolute_paths = if cfg!(windows) {
            win_paths()
        } else {
            unix_paths()
        };

        let result = validate_absolute_paths(&absolute_paths);
        assert!(
            result.is_ok(),
            "Should succeed with absolute paths on this platform"
        );
    }

    #[test]
    fn test_validate_absolute_paths_with_relative_paths() {
        let relative_paths = vec![
            "relative/path/to/component1.tsx".to_string(),
            "/absolute/path/to/component2.tsx".to_string(),
        ];

        let result = validate_absolute_paths(&relative_paths);
        assert!(result.is_err(), "Should fail with relative paths");

        let error_msg = result.unwrap_err();
        assert!(
            error_msg.contains("All paths must be absolute"),
            "Error message should mention absolute paths requirement"
        );
        assert!(
            error_msg.contains("relative/path/to/component1.tsx"),
            "Error message should mention the problematic path"
        );
    }

    #[test]
    fn test_validate_absolute_paths_with_all_relative_paths() {
        let relative_paths = vec![
            "relative/path1.tsx".to_string(),
            "another/relative/path2.tsx".to_string(),
        ];

        let result = validate_absolute_paths(&relative_paths);
        assert!(result.is_err(), "Should fail with all relative paths");
    }

    #[test]
    fn test_validate_absolute_paths_with_empty_paths() {
        let empty_paths: Vec<String> = vec![];

        let result = validate_absolute_paths(&empty_paths);
        assert!(result.is_ok(), "Should succeed with empty paths");
    }
}
