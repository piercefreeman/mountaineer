use errors::AppError;
use log::debug;
use mountaineer_vite::{
    Entrypoint, ProductionConfig as FrontendProductionConfig, SsrConfig as FrontendSsrConfig,
};
use pyo3::exceptions::{PyConnectionAbortedError, PyRuntimeError, PySystemExit, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString};

mod cli;
pub mod client_builder;
pub mod coordinator;
mod errors;
mod lexers;
mod logging;
mod source_map;
mod ssr;
mod terminal;
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

fn run_coordinator(mode: coordinator::RuntimeMode, args: Vec<String>) -> PyResult<()> {
    let runtime = tokio::runtime::Runtime::new()
        .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
    if let Err(error) = runtime.block_on(coordinator::run(mode, &args)) {
        if let Some(error) = error.downcast_ref::<clap::Error>() {
            error
                .print()
                .map_err(|print_error| PyRuntimeError::new_err(print_error.to_string()))?;
            return Err(PySystemExit::new_err(error.exit_code()));
        }
        let program = match mode {
            coordinator::RuntimeMode::Development => "mountaineer-dev",
            coordinator::RuntimeMode::Production => "mountaineer-prod",
        };
        coordinator::report_error(program, error.as_ref());
        return Err(PySystemExit::new_err(1));
    }
    Ok(())
}

#[pyfunction]
fn run_dev(args: Vec<String>) -> PyResult<()> {
    run_coordinator(coordinator::RuntimeMode::Development, args)
}

#[pyfunction]
fn run_prod(args: Vec<String>) -> PyResult<()> {
    run_coordinator(coordinator::RuntimeMode::Production, args)
}

#[pyfunction]
fn build_frontend(
    frontend_root: String,
    client_output_dir: String,
    ssr_output_dir: String,
    entrypoints: Vec<(String, Vec<String>)>,
    styles: Vec<String>,
    minify: bool,
) -> PyResult<()> {
    let runtime = tokio::runtime::Runtime::new()
        .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
    runtime
        .block_on(mountaineer_vite::build_production(
            FrontendProductionConfig {
                frontend_root: frontend_root.into(),
                client_output_dir: client_output_dir.into(),
                ssr_output_dir: ssr_output_dir.into(),
                entrypoints: entrypoints
                    .into_iter()
                    .map(|(name, views)| Entrypoint {
                        name,
                        views: views.into_iter().map(Into::into).collect(),
                    })
                    .collect(),
                styles: styles.into_iter().map(Into::into).collect(),
                minify,
            },
        ))
        .map_err(|error| PyRuntimeError::new_err(error.to_string()))
}

#[pyfunction]
fn compile_frontend_ssr(
    frontend_root: String,
    views: Vec<String>,
) -> PyResult<(String, Option<String>)> {
    let runtime = tokio::runtime::Runtime::new()
        .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
    let compiled = runtime
        .block_on(mountaineer_vite::compile_ssr(FrontendSsrConfig {
            frontend_root: frontend_root.into(),
            views: views.into_iter().map(Into::into).collect(),
        }))
        .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
    Ok((compiled.script, compiled.source_map))
}

/// Generate managed TypeScript client files from a Mountaineer envelope.
#[pyfunction]
fn build_client(payload: String) -> PyResult<()> {
    client_builder::build(&payload).map_err(|error| PyRuntimeError::new_err(error.to_string()))
}

#[pymodule]
fn mountaineer(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Initialize our logger with environment-based configuration
    logging::init_logger();

    m.add_class::<MapMetadata>()?;
    m.add_function(wrap_pyfunction!(run_dev, m)?)?;
    m.add_function(wrap_pyfunction!(run_prod, m)?)?;
    m.add_function(wrap_pyfunction!(build_frontend, m)?)?;
    m.add_function(wrap_pyfunction!(compile_frontend_ssr, m)?)?;
    m.add_function(wrap_pyfunction!(build_client, m)?)?;

    #[pyfn(m)]
    #[pyo3(name = "render_ssr")]
    fn render_ssr(
        py: Python<'_>,
        js_string: String,
        hard_timeout: u64,
    ) -> PyResult<Bound<'_, PyString>> {
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
            debug!("Running in debug mode");
        }

        let result_value = ssr::run_ssr(js_string, hard_timeout);

        match result_value {
            Ok(result) => {
                let result_py = result.into_pyobject(py)?;
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
    fn parse_source_map_mappings(py: Python<'_>, mapping: String) -> PyResult<Bound<'_, PyDict>> {
        if cfg!(debug_assertions) {
            debug!("Running in debug mode");
        }

        let mut parser = SourceMapParser::new(VLQDecoder::new());

        let result = parser.parse_mapping(&mapping);

        match result {
            Ok(result) => {
                let result_py = result.into_pyobject(py)?;
                Ok(result_py)
            }
            Err(_err) => Err(PyValueError::new_err("Unable to parse source map mappings")),
        }
    }

    Ok(())
}
