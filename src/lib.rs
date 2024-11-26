use errors::AppError;
use pyo3::exceptions::{PyConnectionAbortedError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;

mod bundle_independent;
mod bundle_prod;
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

        let result_value = ssr::run_ssr(js_string, hard_timeout);

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
    #[pyo3(name = "compile_independent_bundles")]
    fn compile_independent_bundles(
        py: Python,
        paths: Vec<Vec<String>>,
        node_modules_path: String,
        environment: String,
        live_reload_port: i32,
        live_reload_import: String,
        is_server: bool,
    ) -> PyResult<(Vec<String>, Vec<String>)> {
        /*
         * Accepts a list of page definitions and creates fully isolated bundles
         * that can be executed in a JS runtime with zero dependencies / external imports. For
         * production ready packages that use chunking to decrease the filesize
         * overhead, see `compile_production_bundle`.
         */
        if cfg!(debug_assertions) {
            println!("Running in debug mode");
        }

        bundle_independent::compile_independent_bundles(
            py,
            paths,
            node_modules_path,
            environment,
            live_reload_port,
            live_reload_import,
            is_server,
        )
    }

    #[pyfn(m)]
    #[pyo3(name = "compile_production_bundle")]
    fn compile_production_bundle(
        py: Python,
        paths: Vec<Vec<String>>,
        node_modules_path: String,
        environment: String,
        minify: bool,
        live_reload_import: String,
        is_server: bool,
    ) -> PyResult<Py<PyDict>> {
        /*
         * Builds a full production bundle from multiple JavaScript files. Uses
         * file splitting and tree-shaking to optimize the bundle size for
         * client users.
         */
        if cfg!(debug_assertions) {
            println!("Running in debug mode");
        }

        bundle_prod::compile_production_bundle(
            py,
            paths,
            node_modules_path,
            environment,
            minify,
            live_reload_import,
            is_server,
        )
    }

    Ok(())
}
