#![deny(clippy::print_stdout)]

use pyo3::prelude::*;

mod ssr;

#[macro_use]
extern crate lazy_static;

#[pymodule]
fn filzl(_py: Python, m: &PyModule) -> PyResult<()> {
    #[pyfn(m)]
    #[pyo3(name = "render_ssr")]
    fn render_ssr(py: Python, js_string: String, _hard_timeout: f32) -> PyResult<PyObject> {
        /*
         * :param js_string: the full ssr compiled .js script to execute in V8
         * :param hard_timeout: after this many seconds, the V8 engine will be forcibly
         *   terminated. Use -1 for no timeout.
         */
        // init only if we haven't done so already
        let _ = env_logger::try_init();

        // We assume that es-build has created an iife (immediately invoked function expression)
        // that is bound to an SSR variable in the global scope.
        let js = ssr::Ssr::new(js_string, "SSR");
        let html = js.render_to_string(None);
        //let html = ssr::Ssr::render_to_string(&html_str, "SSR", None);

        let html_py: PyObject = html.to_object(py);

        Ok(html_py.into())
    }

    Ok(())
}

pub use ssr::Ssr;
