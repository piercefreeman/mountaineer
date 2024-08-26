use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::collections::HashSet;
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use tempfile::TempDir;

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
    let temp_dir =
        TempDir::new().map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;
    let temp_dir_path = temp_dir.path();
    let output_dir = temp_dir_path.join("bundled");
    fs::create_dir_all(&output_dir)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

    let entrypoint_paths =
        create_synthetic_entrypoints(temp_dir_path, &paths, is_server, &live_reload_import)?;

    src_go::bundle_all(
        entrypoint_paths.clone(),
        node_modules_path,
        environment,
        minify,
        output_dir.to_str().unwrap().to_string(),
    )
    .map_err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>)?;

    let result = PyDict::new(py);
    let (entrypoints, entrypoint_maps, supporting) =
        process_output_files(py, &output_dir, &entrypoint_paths)?;

    result.set_item("entrypoints", entrypoints)?;
    result.set_item("entrypoint_maps", entrypoint_maps)?;
    result.set_item("supporting", supporting)?;

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

fn process_output_files(
    py: Python,
    output_dir: &PathBuf,
    entrypoint_paths: &[String],
) -> PyResult<(Py<PyList>, Py<PyList>, Py<PyDict>)> {
    let entrypoints = PyList::empty(py);
    let entrypoint_maps = PyList::empty(py);
    let supporting = PyDict::new(py);
    let mut processed_files = HashSet::new();

    for path in entrypoint_paths {
        let file_name = Path::new(path).file_name().unwrap().to_str().unwrap();
        let js_path = output_dir.join(file_name).with_extension("js");
        let map_path = output_dir.join(file_name).with_extension("js.map");

        process_file(&js_path, &mut processed_files, |content| {
            entrypoints.append(content)
        })?;

        process_file(&map_path, &mut processed_files, |content| {
            entrypoint_maps.append(content)
        })?;
    }

    // Everything that's left is a supporting file that is imported from one
    // of the entrypoints
    process_supporting_files(output_dir, &mut processed_files, supporting)?;

    Ok((
        entrypoints.into(),
        entrypoint_maps.into(),
        supporting.into(),
    ))
}

fn process_file<F>(
    path: &PathBuf,
    processed_files: &mut HashSet<String>,
    mut action: F,
) -> PyResult<()>
where
    F: FnMut(&str) -> PyResult<()>,
{
    if let Ok(content) = fs::read_to_string(path) {
        let filename = path.file_name().unwrap().to_str().unwrap().to_string();
        action(&content)?;
        processed_files.insert(filename);
    }
    Ok(())
}

fn process_supporting_files(
    output_dir: &PathBuf,
    processed_files: &mut HashSet<String>,
    supporting: &PyDict,
) -> PyResult<()> {
    for entry in fs::read_dir(output_dir)? {
        let entry =
            entry.map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;
        let path = entry.path();
        if path.is_file() {
            let filename = path.file_name().unwrap().to_str().unwrap().to_string();
            if !processed_files.contains(&filename) {
                let content = fs::read_to_string(&path)
                    .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;
                supporting.set_item(filename, content)?;
            }
        }
    }
    Ok(())
}
