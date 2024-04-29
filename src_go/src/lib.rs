#![allow(non_upper_case_globals)]
#![allow(non_camel_case_types)]
#![allow(non_snake_case)]

include!(concat!(env!("OUT_DIR"), "/bindings.rs"));

extern crate libc;

use std::ffi::{c_int, CString};
use std::sync::{mpsc, Arc};
use std::thread;

pub fn get_build_context(
    filename: &str,
    node_modules_path: &str,
    environment: &str,
    live_reload_port: i32,
    is_server: bool,
) -> Result<c_int, String> {
    let c_filename = CString::new(filename).unwrap();
    let c_node_modules_path = CString::new(node_modules_path).unwrap();
    let c_environment = CString::new(environment).unwrap();
    let is_server = if is_server { 1 } else { 0 };

    unsafe {
        let result = GetBuildContext(
            c_filename.into_raw(),
            c_node_modules_path.into_raw(),
            c_environment.into_raw(),
            live_reload_port,
            is_server,
        );
        let id = result.r0;
        let error = result.r1;

        if error.is_null() {
            Ok(id)
        } else {
            let error_str = CString::from_raw(error);
            let error_string = error_str
                .into_string()
                .unwrap_or_else(|_| String::from("Unknown error"));
            Err(error_string)
        }
    }
}

pub fn rebuild_context(context_ptr: c_int) -> Result<(), String> {
    unsafe {
        let error = RebuildContext(context_ptr);
        if error.is_null() {
            Ok(())
        } else {
            let error_str = CString::from_raw(error);
            let error_string = error_str
                .into_string()
                .unwrap_or_else(|_| String::from("Unknown error"));
            Err(error_string)
        }
    }
}

type Callback = dyn Fn(c_int) + Send + Sync;

pub fn rebuild_contexts(ids: Vec<c_int>, callback: Arc<Box<Callback>>) -> Result<(), Vec<String>> {
    let (tx, rx) = mpsc::channel();
    let mut handles = Vec::new();

    for id in ids.clone().into_iter() {
        let tx = tx.clone();

        let handle = thread::spawn(move || {
            unsafe {
                let error_ptr = RebuildContext(id);
                let result = if !error_ptr.is_null() {
                    let error_cstr = CString::from_raw(error_ptr);
                    let error_string = error_cstr
                        .into_string()
                        .unwrap_or_else(|_| String::from("Unknown error"));
                    Some(error_string)
                } else {
                    None
                };

                // Send both the ID and result to the main thread via channel
                tx.send((id, result.clone())).unwrap();
            }
        });
        handles.push(handle);
    }

    // Cleanup handles and collect errors
    let mut errors = Vec::new();

    // Collect results in the order they are completed
    for _ in 0..ids.len() {
        if let Ok((id, err)) = rx.recv() {
            if let Some(error) = err {
                errors.push(error);
            } else {
                // Call the callback with the ID
                callback(id);
            }
        }
    }

    // Close out the workers
    for handle in handles {
        handle.join().unwrap();
    }

    if errors.is_empty() {
        Ok(())
    } else {
        Err(errors)
    }
}

pub fn remove_context(context_ptr: c_int) {
    unsafe {
        RemoveContext(context_ptr);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn test_build_js() {
        let temp_dir = tempdir().unwrap();
        let js_file_path = temp_dir.path().join("ssr.js");
        let output_file_path = temp_dir.path().join("ssr.js.out");

        // Write a simple javascript function to a file in a tmp directory
        let initial_js = r##"export const Index = () => "<INITIAL>";"##;
        fs::write(&js_file_path, initial_js).unwrap();

        let context_id =
            get_build_context(&js_file_path.to_str().unwrap(), "", "development", 0, true).unwrap();
        assert_ne!(context_id, 0);

        rebuild_context(context_id).unwrap();
        assert!(output_file_path.exists());

        // Get the output file contents and check that <html> is in the output
        let output = fs::read_to_string(&output_file_path).unwrap();
        println!("Output 1: {}", output);
        assert!(
            output.contains("<INITIAL>"),
            "Output does not contain expected <INITIAL> tag"
        );

        // Update the file
        let updated_js = r##"export const Index = () => "<UPDATED>";"##;
        fs::write(&js_file_path, updated_js).unwrap();

        rebuild_context(context_id).unwrap();

        // Check that <div> is in the updated output
        let updated_output = fs::read_to_string(&output_file_path).unwrap();
        println!("Output 2: {}", output);
        assert!(
            updated_output.contains("<UPDATED>"),
            "Updated output does not contain expected <UPDATED> tag"
        );
    }

    #[test]
    fn test_rebuild_contexts() {
        let temp_dir = tempdir().unwrap();
        let js_file_path = temp_dir.path().join("ssr.js");
        let output_file_path = temp_dir.path().join("ssr.js.out");

        // Write a simple javascript function to a file in a tmp directory
        let initial_js = r##"export const Index = () => "<INITIAL>";"##;
        fs::write(&js_file_path, initial_js).unwrap();

        let context_id =
            get_build_context(&js_file_path.to_str().unwrap(), "", "development", 0, true).unwrap();
        assert_ne!(context_id, 0);

        rebuild_contexts(vec![context_id]).unwrap();
        assert!(output_file_path.exists());
    }

    #[test]
    fn test_exception_thrown() {
        let temp_dir = tempdir().unwrap();
        let js_file_path = temp_dir.path().join("ssr.js");
        let output_file_path = temp_dir.path().join("ssr.js.out");

        // Write a simple javascript function to a file in a tmp directory
        let initial_js = r##"export const Index INVALID SYNTAX () => "<INITIAL>";"##;
        fs::write(&js_file_path, initial_js).unwrap();

        let context_id =
            get_build_context(&js_file_path.to_str().unwrap(), "", "development", 0, true).unwrap();
        assert_ne!(context_id, 0);

        let result = rebuild_context(context_id);
        assert!(
            result.is_err(),
            "Expected an error during rebuild_context, but none occurred."
        );
        assert!(!output_file_path.exists());
    }
}
