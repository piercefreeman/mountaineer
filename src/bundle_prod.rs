use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::fs::{self, File};
use std::io::Write;
use std::path::Path;
use tempfile::TempDir;

use crate::bundle_common::{self, BundleError, BundleMode};
use crate::code_gen;

#[pyfunction]
pub fn compile_production_bundle(
    py: Python,
    paths: Vec<Vec<String>>,
    node_modules_path: String,
    environment: String,
    minify: bool,
    live_reload_import: String,
    is_server: bool,
) -> PyResult<Py<PyDict>> {
    println!("COMPILING PROD BUNDLE");

    let temp_dir =
        TempDir::new().map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;
    let temp_dir_path = temp_dir.path();

    let entrypoint_paths =
        create_synthetic_entrypoints(temp_dir_path, &paths, is_server, &live_reload_import)?;

    // Use bundle_common instead of the commented-out bundling code
    let bundle_mode = if is_server {
        BundleMode::SINGLE_SERVER
    } else {
        BundleMode::MULTI_CLIENT
    };

    // Call bundle_common with the appropriate parameters
    let bundle_results = bundle_common::bundle_common(
        entrypoint_paths.clone(),
        bundle_mode,
        environment,
        node_modules_path,
        None, // No live reload port for production
    )
    .map_err(|e| match e {
        BundleError::IoError(err) => PyErr::new::<pyo3::exceptions::PyIOError, _>(err.to_string()),
        BundleError::BundlingError(msg) => PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(msg),
        BundleError::OutputError(msg) => PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(msg),
        BundleError::FileNotFound(path) => PyErr::new::<pyo3::exceptions::PyFileNotFoundError, _>(
            format!("File not found: {}", path),
        ),
        BundleError::InvalidInput(msg) => PyErr::new::<pyo3::exceptions::PyValueError, _>(msg),
    })?;

    // Directly populate the result dictionary using bundle_results
    let result = PyDict::new(py);
    let entrypoints = PyList::empty(py);
    let entrypoint_maps = PyList::empty(py);
    let supporting = PyDict::new(py);

    // Since we have the bundle results in memory, add them to the respective lists
    for (_, bundle_result) in bundle_results {
        entrypoints.append(&bundle_result.script)?;

        if let Some(map) = bundle_result.map {
            entrypoint_maps.append(&map)?;
        }
    }

    result.set_item("entrypoints", entrypoints)?;
    result.set_item("entrypoint_maps", entrypoint_maps)?;
    result.set_item("supporting", supporting)?; // Empty dict since all content is in the main files

    Ok(result.into())
}

fn create_synthetic_entrypoints(
    temp_dir_path: &std::path::Path,
    paths: &[Vec<String>],
    is_server: bool,
    live_reload_import: &str,
) -> PyResult<Vec<String>> {
    paths
        .iter()
        .enumerate()
        .map(|(index, path_group)| {
            let temp_file_path = temp_dir_path.join(format!("entrypoint{}.jsx", index));
            let mut temp_file = File::create(&temp_file_path)
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;
            let entrypoint_content =
                code_gen::build_entrypoint(path_group, is_server, live_reload_import);
            temp_file
                .write_all(entrypoint_content.as_bytes())
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;
            Ok(temp_file_path.to_str().unwrap().to_string())
        })
        .collect()
}
