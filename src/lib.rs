use errors::AppError;
use pyo3::exceptions::{PyConnectionAbortedError, PyValueError};
use pyo3::prelude::*;
use std::ffi::c_int;
use std::fs;
use std::path::Path;
use std::time::Duration;

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
    #[pyo3(name = "build_javascript")]
    // PyRef to support borrow checking: https://github.com/PyO3/pyo3/issues/1177
    fn build_javascript(_py: Python, params: Vec<PyRef<BuildContextParams>>) -> PyResult<bool> {
        #[allow(clippy::print_stdout)]
        if cfg!(debug_assertions) {
            println!("Running in debug mode");
        }

        let mut context_ids = Vec::<c_int>::new();

        for param in &params {
            let context_result = src_go::get_build_context(
                &param.path,
                &param.node_modules_path,
                &param.environment,
                param.live_reload_port,
                param.is_server,
            );
            match context_result {
                Ok(context_id) => {
                    context_ids.push(context_id);
                }
                Err(err) => {
                    println!("Error getting build context: {:?}", err);
                    return Err(PyErr::new::<PyValueError, _>(err));
                }
            }
        }

        let rebuild_result = src_go::rebuild_contexts(context_ids);
        if let Err(err) = rebuild_result {
            println!("Error rebuilding contexts: {:?}", err);
            return Err(PyErr::new::<PyValueError, _>(err.join("\n")));
        }

        // We expect that each input path will have an `.js.out.map` file
        // Make the paths referenced in this file absolute to make it clearer for
        // downstream clients
        for param in &params {
            let original_script_path = Path::new(&param.path);
            let original_extension = original_script_path.extension().unwrap();
            let script_file_path = original_script_path
                .with_extension(format!("{}.out", original_extension.to_string_lossy()));
            let map_file_path = original_script_path
                .with_extension(format!("{}.out.map", original_extension.to_string_lossy()));

            // We can also copy these directly in-memory from the golang layer, but this requires
            // keeping all file contents in memory until we reach this point. For larger projects
            // this is a safer approach.
            let mut map_contents = fs::read_to_string(&map_file_path).expect("Failed to read map");
            map_contents = make_source_map_paths_absolute(&map_contents, original_script_path)
                .expect("Error processing source map");

            let mut script_contents =
                fs::read_to_string(&script_file_path).expect("Failed to read script");

            let script_name: String;
            let map_name: String;

            if !param.is_server {
                // Only client files need the hash
                let content_hash = format!(
                    "{:x}",
                    md5::compute(lexers::strip_js_comments(&script_contents, true).as_bytes())
                );
                script_name = format!("{}-{}.js", param.controller_name, content_hash);
                map_name = format!("{}.map", script_name);
            } else {
                script_name = format!("{}.js", param.controller_name);
                map_name = format!("{}.map", script_name);
            }

            // Point the contents to the new map location
            // This should still be relatively positioned to the original script, so we just need
            // to replace the name
            script_contents = update_source_map_path(&script_contents, &map_name);

            let output_dir = Path::new(&param.output_dir);
            fs::write(output_dir.join(script_name), &script_contents)
                .expect("Failed to write script");
            fs::write(output_dir.join(map_name), &map_contents).expect("Failed to write map");
        }

        Ok(true)
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
