// https://amirmalik.net/2023/02/15/embedding-go-in-rust
extern crate bindgen;

use std::env;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    let out_dir = env::var("OUT_DIR").unwrap();
    let out_path = PathBuf::from(&out_dir);

    // Log the GOARCH env variable, if specified
    if let Ok(goarch) = env::var("GOARCH") {
        eprintln!("GOARCH is set to {}", goarch);
    } else {
        eprintln!("GOARCH is not set");
    }

    // Print the current working directory
    eprintln!(
        "Current working directory: {}",
        env::current_dir().unwrap().display()
    );

    // Print the $PATH
    eprintln!("PATH: {}", env::var("PATH").unwrap());

    // Step 1: Compile the Go code into a static library.
    let status = Command::new("go")
        .args([
            "build",
            "-buildmode=c-archive",
            "-o",
            out_path.join("libgo.a").to_str().unwrap(),
            "-ldflags",
            "-s -w", // Strips debug information, can minimize the payload somewhat
            "./go/js_build.go",
        ])
        .status()
        .expect("Failed to execute go build");

    assert!(status.success(), "Go build failed");

    eprintln!("Successful golang build");

    // Step 2: Generate Rust bindings using bindgen.
    let bindings = bindgen::Builder::default()
        .header(out_path.join("libgo.h").to_str().unwrap())
        .parse_callbacks(Box::new(bindgen::CargoCallbacks::new()))
        .generate()
        .expect("Unable to generate bindings");

    bindings
        .write_to_file(out_path.join("bindings.rs"))
        .expect("Couldn't write bindings!");

    // Inform Cargo about the dependencies and how to link the library.
    println!("cargo:rerun-if-changed=go/list_struct.go");
    println!("cargo:rustc-link-search=native={}", out_dir);
    println!("cargo:rustc-link-lib=static=go");

    if cfg!(target_os = "macos") {
        println!("cargo:rustc-link-lib=framework=CoreFoundation");
    }
}
