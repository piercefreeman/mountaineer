use pyo3::prelude::*;
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tempfile::TempDir;

use crate::code_gen;

#[pyfunction]
pub fn compile_independent_bundles(
    py: Python,
    paths: Vec<Vec<String>>,
    node_modules_path: String,
    environment: String,
    live_reload_port: i32,
    live_reload_import: String,
    is_server: bool,
) -> PyResult<Vec<String>> {
    let mut output_files = Vec::new();

    for path_group in paths.iter() {
        let temp_dir = create_temp_dir()?;
        let temp_file_path =
            create_entrypoint(&temp_dir, path_group, is_server, &live_reload_import)?;
        let context_id = create_build_context(
            &temp_file_path,
            &node_modules_path,
            &environment,
            live_reload_port,
            is_server,
        )?;
        rebuild_context(py, context_id)?;
        let compiled_content = read_compiled_file(&temp_file_path)?;
        output_files.push(compiled_content);
    }

    Ok(output_files)
}

fn create_temp_dir() -> PyResult<TempDir> {
    TempDir::new().map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))
}

fn create_entrypoint(
    temp_dir: &TempDir,
    path_group: &[String],
    is_server: bool,
    live_reload_import: &str,
) -> PyResult<PathBuf> {
    let temp_file_path = temp_dir.path().join("entrypoint.jsx");
    let mut temp_file = File::create(&temp_file_path)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;
    let entrypoint_content = code_gen::build_entrypoint(path_group, is_server, live_reload_import);
    temp_file
        .write_all(entrypoint_content.as_bytes())
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;
    Ok(temp_file_path)
}

fn create_build_context(
    temp_path: &Path,
    node_modules_path: &str,
    environment: &str,
    live_reload_port: i32,
    is_server: bool,
) -> PyResult<i32> {
    let temp_path_str = temp_path.to_str().unwrap().to_string();
    src_go::get_build_context(
        &temp_path_str,
        node_modules_path,
        environment,
        live_reload_port,
        is_server,
    )
    .map_err(|err| {
        println!("Error getting build context: {:?}", err);
        PyErr::new::<pyo3::exceptions::PyValueError, _>(err)
    })
}

fn rebuild_context(py: Python, context_id: i32) -> PyResult<()> {
    let callback = Arc::new(Box::new(move |_id: i32| {
        // We don't need to do anything in the callback for a single file compilation
    }) as Box<dyn Fn(i32) + Send + Sync>);

    py.allow_threads(move || src_go::rebuild_contexts(vec![context_id], callback))
        .map_err(|err| {
            println!("Error rebuilding context: {:?}", err);
            PyErr::new::<pyo3::exceptions::PyValueError, _>(err.join("\n"))
        })
}

fn read_compiled_file(temp_file_path: &Path) -> PyResult<String> {
    fs::read_to_string(temp_file_path.with_extension("jsx.out")).map_err(|err| {
        println!("Error reading compiled file: {:?}", err);
        PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
            "Failed to read compiled file: {}",
            err
        ))
    })
}
