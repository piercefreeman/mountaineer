#![deny(clippy::print_stdout)]

use pyo3::prelude::*;

use ssr_rs::Ssr;

#[pymodule]
fn filzl_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    #[pyfn(m)]
    #[pyo3(name = "render_ssr")]
    fn render_ssr(py: Python, html_str: String) -> PyResult<PyObject> {
        // init only if we haven't done so already
        let _ = env_logger::try_init();

        // We assume that es-build has created an iife (immediately invoked function expression)
        // that is bound to an SSR variable in the global scope.
        let html = Ssr::render_to_string(&html_str, "SSR", None);

        let html_py: PyObject = html.to_object(py);

        Ok(html_py.into())
    }

    Ok(())
}
