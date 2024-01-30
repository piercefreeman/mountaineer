fn main() {
    // Check if the code is being built as a binary for another language bridge
    // NOTE - this isn't currently being used with Maturin, so it isn't used, but we're keeping
    // it here in case we modify the build process in the future
    if std::env::var("PYO3_CROSS").is_ok() {
        // If so, emit cargo config for setting crate-type to "cdylib"
        println!("cargo:rustc-crate-type=cdylib");
    }
}
