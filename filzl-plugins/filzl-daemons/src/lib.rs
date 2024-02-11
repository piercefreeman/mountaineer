#![deny(clippy::print_stdout)]

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

mod threading;

#[pymodule]
fn filzl_daemons(_py: Python, m: &PyModule) -> PyResult<()> {
    #[pyfn(m)]
    #[pyo3(name = "get_thread_cpu_time")]
    fn get_thread_cpu_time(py: Python, thread_id: usize) -> PyResult<PyObject> {
        if cfg!(debug_assertions) {
            println!("Running in debug mode");
        }

        let result = unsafe { threading::platform::get_thread_cpu_usage(thread_id) };

        match result {
            Ok(result) => {
                let result_py: PyObject = result.to_object(py);
                Ok(result_py.into())
            }
            Err(_err) => Err(PyValueError::new_err("Unable to get thread CPU time")),
        }
    }

    Ok(())
}
