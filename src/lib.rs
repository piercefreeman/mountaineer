#![deny(clippy::print_stdout)]

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::time::Duration;

mod ssr;
mod timeout;

#[macro_use]
extern crate lazy_static;

fn run_ssr(js_string: String, hard_timeout: u64) -> Result<String, &'static str> {
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
        Ok(js.render_to_string(None))
    }
}

#[pymodule]
fn filzl(_py: Python, m: &PyModule) -> PyResult<()> {
    #[pyfn(m)]
    #[pyo3(name = "render_ssr")]
    fn render_ssr(py: Python, js_string: String, hard_timeout: u64) -> PyResult<PyObject> {
        /*
         * :param js_string: the full ssr compiled .js script to execute in V8
         * :param hard_timeout: after this many milliseconds, the V8 engine will be forcibly
         *   terminated. Use 0 for no timeout.
         */
        // init only if we haven't done so already
        let _ = env_logger::try_init();

        let result_value = run_ssr(js_string, hard_timeout);

        match result_value {
            Ok(result) => {
                let result_py: PyObject = result.to_object(py);
                Ok(result_py.into())
            }
            Err(err) => Err(PyValueError::new_err(err)),
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
