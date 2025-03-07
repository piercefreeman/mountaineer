use indexmap::IndexMap;
use rolldown::{Bundler, BundlerOptions, InputItem, OutputFormat, SourceMapType};
use rustc_hash::FxHasher;
use std::hash::BuildHasherDefault;
use tokio::runtime::Runtime;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Get the current directory
    let current_dir = std::env::current_dir()?;
    println!("Current directory: {}", current_dir.display());

    // Path to the input file
    let input_file = current_dir.join("index.ts");
    if !input_file.exists() {
        return Err(format!("Input file not found: {}", input_file.display()).into());
    }
    println!("Input file: {}", input_file.display());

    // Path for output
    let output_dir = current_dir.join("dist");
    std::fs::create_dir_all(&output_dir)?;
    println!("Output directory: {}", output_dir.display());

    // Create Define map
    let mut define: IndexMap<String, String, BuildHasherDefault<FxHasher>> = 
        IndexMap::with_hasher(BuildHasherDefault::default());
    
    // Insert the replacement for process.env.MY_VAR
    define.insert("process.env.MY_VAR".to_string(), "\"production\"".to_string());
    
    println!("Define mappings: {:?}", define);

    // Configure bundler options
    let bundler_options = BundlerOptions {
        input: Some(vec![InputItem {
            name: None,
            import: input_file.to_str().unwrap().to_string(),
        }]),
        cwd: Some(current_dir.clone()),
        sourcemap: Some(SourceMapType::File),
        define: Some(define),
        //format: Some(OutputFormat::Esm),
        format: Some(OutputFormat::Iife),
        //dir: Some(output_dir.to_str().unwrap().to_string()),
        ..Default::default()
    };

    // Create bundler instance
    let mut bundler = Bundler::new(bundler_options);

    // Run the bundler
    println!("Running Rolldown bundler...");
    let rt = Runtime::new()?;
    rt.block_on(async {
        bundler.write().await.map_err(|err| {
            format!("Bundling error: {:?}", err)
        })
    })?;

    println!("Bundling complete!");
    Ok(())
}
