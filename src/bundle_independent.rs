use pyo3::prelude::*;
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use tempfile::TempDir;
use rolldown::{Bundler, BundlerOptions, InputItem, SourceMapType, OutputExports, OutputFormat, ResolveOptions};
use tokio::runtime::Runtime;
use walkdir::WalkDir;
use indexmap::IndexMap;
use rustc_hash::FxHasher;
use std::hash::BuildHasherDefault;
use pyo3::exceptions::PyValueError;
use std::fmt::format;

use crate::code_gen;

/// Compile independent bundles using Rolldown.
///
/// For each group of input paths, this function:
/// 1. Creates a temporary directory.
/// 2. Writes an entrypoint file (using your custom code generation logic).
/// 3. Configures and runs a Rolldown bundler to compile the entrypoint.
/// 4. Reads the resulting compiled file and sourcemap.
/// 5. Returns two lists (one for output and one for sourcemaps) to Python.
///
/// Parameters:
///   - `paths`: List of list of strings representing groups of module paths.
///   - `live_reload_import`: An extra import string (if needed) for live reload.
///   - `is_server`: Whether the bundle is for server-side (affects entrypoint generation).
#[pyfunction]
pub fn compile_independent_bundles(
    // Full implementation kept for now for reverse compatibility
    py: Python,
    paths: Vec<Vec<String>>,
    node_modules_path: String,
    environment: String,
    live_reload_port: i32,
    live_reload_import: String,
    is_ssr: bool,
) -> PyResult<(Vec<String>, Vec<String>)> {
    let mut output_files = Vec::new();
    let mut sourcemap_files = Vec::new();

    for path_group in paths.iter() {
        println!("COMPILING INDEPENDENT BUNDLE {:?}", path_group);

        // Create a temporary directory for the current bundle.
        let temp_dir = TempDir::new()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        // Create the entrypoint file using your custom logic.
        let entrypoint_path =
            create_entrypoint(&temp_dir, path_group, is_ssr, &live_reload_import)?;

            bundle_common()

        println!("BUNDLER DONE WITH BLOCK");

        // Log the contents of the temp_dir
        let walker = WalkDir::new(temp_dir.path())
            .min_depth(1)
            .into_iter()
            .filter_map(|e| e.ok());

        println!("Contents of temporary directory:");
        for entry in walker {
            println!("  - {}", entry.path().display());
        }

        // Extract the filename from the entrypoint path
        let filename = entrypoint_path.file_stem().unwrap_or_default()
            .to_str().unwrap_or("entrypoint");
        
        // Construct paths to the compiled files in the dist directory
        let dist_dir = temp_dir.path().join("dist");
        let compiled_file_path = dist_dir.join(format!("{}.js", filename));
        let sourcemap_file_path = dist_dir.join(format!("{}.js.map", filename));
        
        println!("Looking for compiled file at: {}", compiled_file_path.display());
        println!("Looking for sourcemap at: {}", sourcemap_file_path.display());
        
        // Read the compiled files from the dist directory
        let mut compiled_file = read_file(&compiled_file_path)?;
        let sourcemap_file = read_file(&sourcemap_file_path)?;
        println!("READ FILES");

        //println!("COMPILED FILE: {}", compiled_file);
        //println!("SOURCEMAP FILE: {}", sourcemap_file);

        // Tmp: Write the compiled file to a local file
        if is_ssr {
            // We expect the format of the iife file will be (function() { ... })()
            // Unlike esbuild, which supports a global-name (https://esbuild.github.io/api/#global-name) to set
            // the entrypoint, rolldown does not currently support this.

            // First validate the format of the compiled file matches our expectations
            if !compiled_file.starts_with("(function(") {
                // Log the beginning and ending of the compiled file for debugging
                let start_chars: String = compiled_file.chars().take(50).collect();
                let end_chars: String = compiled_file.chars().rev().take(50).collect::<String>().chars().rev().collect();
                
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
            compiled_file = format!(
                "var SSR = (() => {{\nreturn {}\n}})();",
                compiled_file
            )
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

    // Replace this with your actual code generation logic.
    let entrypoint_content = code_gen::build_entrypoint(path_group, is_server, live_reload_import);
    file.write_all(entrypoint_content.as_bytes())
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;
    Ok(entrypoint_path)
}

/// Utility function to read a file into a String.
fn read_file(path: &Path) -> PyResult<String> {
    fs::read_to_string(path)
        .map_err(|err| PyErr::new::<pyo3::exceptions::PyIOError, _>(err.to_string()))
}
