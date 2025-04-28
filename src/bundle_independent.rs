use pyo3::prelude::*;
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;
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
                    "File not found: {}",
                    path
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
                        "Compiled file does not match expected IIFE format: (function() {{ ... }})()\n\nBeginning 50 chars: {}\nEnding 50 chars: {}",
                        start_chars, end_chars
                    )
                ));
            }

            // Then we add a manual var assignment prefix
            // Replace the opening part with our SSR variable assignment
            // Newlines required to clear out any trailing comments
            compiled_file = format!("var SSR = (() => {{\nreturn {}\n}})();", compiled_file)
        }

        output_files.push(compiled_file);
        sourcemap_files.push(sourcemap_file);
    }
    Ok((output_files, sourcemap_files))
}

/// Create an entrypoint file in the given temporary directory.
/// The file is named "entrypoint.jsx". It is written using custom code generation logic.
fn create_entrypoint(
    temp_dir: &TempDir,
    path_group: &[String],
    is_server: bool,
    live_reload_import: &str,
) -> PyResult<PathBuf> {
    let entrypoint_path = temp_dir.path().join("entrypoint.jsx");
    let mut file = File::create(&entrypoint_path)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

    let entrypoint_content = code_gen::build_entrypoint(path_group, is_server, live_reload_import);
    file.write_all(entrypoint_content.as_bytes())
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;
    Ok(entrypoint_path)
}
