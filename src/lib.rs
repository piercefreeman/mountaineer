use errors::AppError;
use pyo3::exceptions::{PyConnectionAbortedError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use tempfile;

mod code_gen;
mod errors;
mod lexers;
mod logging;
mod source_map;
mod ssr;
mod timeout;

#[macro_use]
extern crate lazy_static;

// Export mainly for use in benchmarks
pub use lexers::strip_js_comments;
pub use source_map::{
    make_source_map_paths_absolute, update_source_map_path, MapMetadata, SourceMapParser,
    VLQDecoder,
};
pub use ssr::Ssr;

fn run_ssr(js_string: String, hard_timeout: u64) -> Result<String, AppError> {
    if hard_timeout > 0 {
        timeout::run_thread_with_timeout(
            || {
                let js = ssr::Ssr::new(js_string, "SSR");
                js.render_to_string(None)
            },
            Duration::from_millis(hard_timeout),
        )
    } else {
        // Call inline, no timeout
        let js = ssr::Ssr::new(js_string, "SSR");
        js.render_to_string(None)
    }
}

#[derive(Debug, PartialEq, Clone)]
#[pyclass(get_all, set_all)]
struct BuildContextParams {
    // Build watch settings
    path: String,
    node_modules_path: String,
    environment: String,
    live_reload_port: i32,
    is_server: bool,

    // Output settings
    controller_name: String,
    output_dir: String,
}

#[pymethods]
impl BuildContextParams {
    #[new]
    fn new(
        path: String,
        node_modules_path: String,
        environment: String,
        live_reload_port: i32,
        is_server: bool,
        controller_name: String,
        output_dir: String,
    ) -> Self {
        Self {
            path,
            node_modules_path,
            environment,
            live_reload_port,
            is_server,
            controller_name,
            output_dir,
        }
    }
}

#[pymodule]
fn mountaineer(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<MapMetadata>()?;
    m.add_class::<BuildContextParams>()?;

    #[pyfn(m)]
    #[pyo3(name = "render_ssr")]
    fn render_ssr(py: Python, js_string: String, hard_timeout: u64) -> PyResult<PyObject> {
        /*
         * :param js_string: the full ssr compiled .js script to execute in V8
         * :param hard_timeout: after this many milliseconds, the V8 engine will be forcibly
         *   terminated. Use 0 for no timeout.
         *
         * :raises ConnectionAbortedError: if the hard_timeout is reached
         * :raises ValueError: if the V8 engine throws an exception, since there's probably
         *   something wrong with the script
         */
        if cfg!(debug_assertions) {
            println!("Running in debug mode");
        }

        // init only if we haven't done so already
        let _ = env_logger::try_init();

        let result_value = run_ssr(js_string, hard_timeout);

        match result_value {
            Ok(result) => {
                let result_py: PyObject = result.to_object(py);
                Ok(result_py)
            }
            Err(err) => match err {
                AppError::HardTimeoutError(msg) => Err(PyConnectionAbortedError::new_err(msg)),
                AppError::V8ExceptionError(msg) => Err(PyValueError::new_err(msg)),
            },
        }
    }

    #[pyfn(m)]
    #[pyo3(name = "parse_source_map_mappings")]
    fn parse_source_map_mappings(py: Python, mapping: String) -> PyResult<PyObject> {
        #[allow(clippy::print_stdout)]
        if cfg!(debug_assertions) {
            println!("Running in debug mode");
        }

        let mut parser = SourceMapParser::new(VLQDecoder::new());

        let result = parser.parse_mapping(&mapping);

        match result {
            Ok(result) => {
                let result_py: PyObject = result.to_object(py);
                Ok(result_py)
            }
            Err(_err) => Err(PyValueError::new_err("Unable to parse source map mappings")),
        }
    }

    #[pyfn(m)]
    #[pyo3(name = "compile_multiple_javascript")]
    fn compile_multiple_javascript(
        py: Python,
        paths: Vec<Vec<String>>,
        node_modules_path: String,
        environment: String,
        live_reload_port: i32,
        live_reload_import: String,
        is_server: bool,
    ) -> PyResult<Vec<String>> {
        #[allow(clippy::print_stdout)]
        if cfg!(debug_assertions) {
            println!("Running in debug mode");
        }

        let mut output_files = Vec::new();

        // Each entrypoint definition is a single page
        for path_group in paths.iter() {
            // Create a temporary file for the synthetic entrypoint
            let temp_dir = tempfile::TempDir::new()?;
            let temp_file_path = temp_dir.path().join("entrypoint.jsx");
            let mut temp_file = fs::File::create(&temp_file_path)?;

            let entrypoint_content =
                code_gen::build_entrypoint(&path_group, is_server, &live_reload_import);
            println!("entrypoint_content: {}", entrypoint_content);

            // Write the entrypoint content to the temporary file
            temp_file.write_all(entrypoint_content.as_bytes())?;

            // Use the temporary file as the entrypoint for esbuild
            // TODO: Refactor out so we can pass multiple files
            let temp_path_str = temp_file_path.to_str().unwrap().to_string();
            let context_result = src_go::get_build_context(
                &temp_path_str,
                &node_modules_path,
                &environment,
                live_reload_port,
                is_server,
            );

            let context_id = match context_result {
                Ok(id) => id,
                Err(err) => {
                    println!("Error getting build context: {:?}", err);
                    return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(err));
                }
            };

            let callback = Arc::new(Box::new(move |_id: i32| {
                // We don't need to do anything in the callback for a single file compilation
            }) as Box<dyn Fn(i32) + Send + Sync>);

            let rebuild_result =
                py.allow_threads(move || src_go::rebuild_contexts(vec![context_id], callback));

            if let Err(err) = rebuild_result {
                println!("Error rebuilding context: {:?}", err);
                return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                    err.join("\n"),
                ));
            }

            // Read all the contents in temp_dir
            println!("Contents of temporary directory:");
            let mut file_paths = Vec::new();
            for entry in fs::read_dir(temp_dir.path())? {
                let entry = entry?;
                let path: PathBuf = entry.path();
                println!("  {:?}", path);
                file_paths.push(path);
            }

            // Read the compiled file
            match fs::read_to_string(temp_file_path.with_extension("jsx.out")) {
                Ok(content) => {
                    output_files.push(content);
                }
                Err(err) => {
                    println!("Error reading compiled file: {:?}", err);
                    return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                        "Failed to read compiled file: {}",
                        err
                    )));
                }
            }
        }

        Ok(output_files)
    }

    #[pyfn(m)]
    #[pyo3(name = "build_production_bundle")]
    fn build_production_bundle(
        py: Python,
        paths: Vec<Vec<String>>,
        node_modules_path: String,
        environment: String,
        live_reload_import: String,
        is_server: bool,
    ) -> PyResult<Py<PyDict>> {
        /*
         * Builds a full production bundle from multiple JavaScript files. Uses
         * file splitting and tree-shaking to optimize the bundle size for
         * client users.
         */
        // We expect to have a 1:1 mapping of input files to output files
        // with the same name (entrypoint.js)
        // We return these with a mapping of {original_path: contents}
        // alongside a list of {supporting_path: content} for the bundle
        // files that are shared between multiple entrypoints
        if cfg!(debug_assertions) {
            println!("Running in debug mode");
        }

        // Create a temporary folder for synthetic entrypoints
        let temp_dir = tempfile::TempDir::new()?;
        let temp_dir_path = temp_dir.path();
        let mut entrypoint_paths = Vec::new();
        let mut original_to_temp_map = HashMap::new();

        // Create synthetic entrypoints
        for (index, path_group) in paths.iter().enumerate() {
            let temp_file_path = temp_dir_path.join(format!("entrypoint{}.jsx", index));
            let mut temp_file = fs::File::create(&temp_file_path)?;
            let entrypoint_content =
                code_gen::build_entrypoint(&path_group, is_server, &live_reload_import);
            println!("entrypoint_content: {}", entrypoint_content);
            temp_file.write_all(entrypoint_content.as_bytes())?;
            let temp_path_str = temp_file_path.to_str().unwrap().to_string();
            entrypoint_paths.push(temp_path_str.clone());
            //original_to_temp_map.insert(format!("entrypoint{}.js", index), path_group[0].clone());
            // TODO: Just store these in a set alongside the map files
            original_to_temp_map.insert(
                format!("entrypoint{}.js", index),
                format!("entrypoint{}.js", index),
            );
        }

        // Create output directory
        let output_dir = temp_dir.path().join("bundled");
        fs::create_dir_all(&output_dir)?;

        // Call bundle_all function
        match src_go::bundle_all(
            entrypoint_paths,
            node_modules_path,
            environment,
            output_dir.to_str().unwrap().to_string(),
        ) {
            Ok(()) => {
                let result = PyDict::new(py);
                let entrypoints = PyDict::new(py);
                let supporting = PyDict::new(py);

                for entry in fs::read_dir(&output_dir)? {
                    let entry = entry?;
                    let path = entry.path();
                    if path.is_file() {
                        let content = fs::read_to_string(&path)?;
                        let filename = path.file_name().unwrap().to_str().unwrap();

                        // Check if this is an entrypoint file
                        if let Some(original_path) = original_to_temp_map.get(filename) {
                            entrypoints.set_item(original_path, content)?;
                            println!("ENTRYPOINT {}", filename);
                        } else {
                            // This is a supporting file
                            supporting.set_item(filename, content)?;
                            println!("SUPPORTING {}", filename);
                        }
                    }
                }

                result.set_item("entrypoints", entrypoints)?;
                result.set_item("supporting", supporting)?;

                Ok(result.into())
            }
            Err(error) => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(error)),
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn render_no_timeout() {
        let js_string = r##"var SSR = { renderToString: () => "<html></html>" };"##.to_string();
        let hard_timeout = 0;

        let result = run_ssr(js_string, hard_timeout).unwrap();
        assert_eq!(result, "<html></html>");
    }

    #[test]
    fn render_with_timeout() {
        let js_string = r##"var SSR = { renderToString: () => "<html></html>" };"##.to_string();
        let hard_timeout = 2000;

        let result = run_ssr(js_string, hard_timeout).unwrap();
        assert_eq!(result, "<html></html>");
    }
}
