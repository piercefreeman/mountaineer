#![allow(non_upper_case_globals)]
#![allow(non_camel_case_types)]
#![allow(non_snake_case)]

include!(concat!(env!("OUT_DIR"), "/bindings.rs"));

use std::ffi::{c_int, CString};

pub fn get_build_context(filename: &str, is_server: bool) -> c_int {
    let c_filename = CString::new(filename).unwrap();
    let is_server = if is_server { 1 } else { 0 };
    unsafe { GetBuildContext(c_filename.into_raw(), is_server) }
}

pub fn rebuild_context(context_ptr: c_int) {
    unsafe {
        RebuildContext(context_ptr);
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

        let context_id = get_build_context(&js_file_path.to_str().unwrap(), true);
        assert_ne!(context_id, 0);

        rebuild_context(context_id);
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

        rebuild_context(context_id);

        // Check that <div> is in the updated output
        let updated_output = fs::read_to_string(&output_file_path).unwrap();
        println!("Output 2: {}", output);
        assert!(
            updated_output.contains("<UPDATED>"),
            "Updated output does not contain expected <UPDATED> tag"
        );
    }
}
