use indexmap::IndexMap;
use rolldown::{Bundler, BundlerOptions, InputItem, SourceMapType, OutputExports, OutputFormat, ResolveOptions};
use rustc_hash::FxHasher;
use std::collections::HashMap;
use std::hash::BuildHasherDefault;
use std::fs;
use std::path::Path;
use tempfile::TempDir;
use tokio::runtime::Runtime;


#[derive(Debug)]
pub enum BundleMode {
    // 1. Single client-side javascript: wraps all dependencies in one file, intended for development embedding
    SINGLE_CLIENT,
    // 2. Split client-side javascript: tree-shakes dependencies into nested files, allows for better caching between
    MULTI_CLIENT,
    // 3. Server-side javascript: single bundle in Iife mode
    SINGLE_SERVER,
}

#[derive(Debug)]
pub struct BundleResult {
    // Since rust owns the tmp build directory, it's better to scope it to
    // clear at the end of this function and read everything into memory. We expect
    // our Python client will need this in memory anyway.
    pub script: String,
    pub map: Option<String>,
}

// Custom error type for bundle operations
#[derive(Debug)]
pub enum BundleError {
    IoError(std::io::Error),
    BundlingError(String),
    OutputError(String),
    FileNotFound(String),
    InvalidInput(String),
}

impl std::fmt::Display for BundleError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            BundleError::IoError(err) => write!(f, "IO error: {}", err),
            BundleError::BundlingError(msg) => write!(f, "Bundling error: {}", msg),
            BundleError::OutputError(msg) => write!(f, "Output error: {}", msg),
            BundleError::FileNotFound(path) => write!(f, "File not found: {}", path),
            BundleError::InvalidInput(msg) => write!(f, "Invalid input: {}", msg),
        }
    }
}

impl std::error::Error for BundleError {}

impl From<std::io::Error> for BundleError {
    fn from(err: std::io::Error) -> Self {
        BundleError::IoError(err)
    }
}

// Our common bundler supports
// pages that share functions in production
pub fn bundle_common(
    entrypoint_paths: Vec<String>,
    mode: BundleMode,
    // Common build params
    environment: String,
    node_modules_path: String,
    live_reload_port: Option<u16>,
) -> Result<std::collections::HashMap<String, BundleResult>, BundleError> {
    // Validate inputs
    if entrypoint_paths.is_empty() {
        return Err(BundleError::InvalidInput(
            "No entrypoint paths provided".to_string(),
        ));
    }

    // Determine if this is server-side rendering based on mode
    let is_ssr = matches!(mode, BundleMode::SINGLE_SERVER);

    // If our mode is either SINGLE_CLIENT or SINGLE_SERVER, we should only accept
    // one file entrypoint in the file
    if matches!(mode, BundleMode::SINGLE_CLIENT | BundleMode::SINGLE_SERVER)
        && entrypoint_paths.len() > 1
    {
        return Err(BundleError::InvalidInput(format!(
            "Mode {:?} only supports a single entrypoint, but {} were provided",
            mode,
            entrypoint_paths.len()
        )));
    }

    // Validate that all entrypoints exist
    for path in &entrypoint_paths {
        if !Path::new(path).exists() {
            return Err(BundleError::FileNotFound(path.clone()));
        }
    }

    // Create a temporary directory for output
    let temp_dir = TempDir::new().map_err(|e| BundleError::IoError(e))?;

    // Define environment variables and other settings
    let mut define: IndexMap<String, String, BuildHasherDefault<FxHasher>> =
        IndexMap::with_hasher(BuildHasherDefault::default());
    define.insert(
        "process.env.NODE_ENV".to_string(),
        format!("\"{}\"", environment),
    );

    if let Some(port) = live_reload_port {
        define.insert(
            "process.env.LIVE_RELOAD_PORT".to_string(),
            format!("{}", port),
        );
    }

    if is_ssr {
        define.insert("process.env.SSR_RENDERING".to_string(), "true".to_string());
        define.insert("global".to_string(), "window".to_string());
    } else {
        define.insert("process.env.SSR_RENDERING".to_string(), "false".to_string());
    }

    // Set up resolve options to let Rolldown know where to find node_modules.
    let resolve = Some(ResolveOptions {
        modules: Some(vec![node_modules_path.clone()]),
        ..Default::default()
    });

    // Configure Rolldown bundler options with multiple inputs
    let input_items: Vec<InputItem> = entrypoint_paths
        .iter()
        .map(|path| {
            // Extract the filename without extension to use as the chunk name
            let file_stem = Path::new(path)
                .file_stem()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_else(|| format!("chunk_{}", path.len()));

            InputItem {
                name: Some(file_stem),
                import: path.clone(),
            }
        })
        .collect();

    let bundler_options = BundlerOptions {
        input: Some(input_items),
        cwd: Some(temp_dir.path().to_path_buf()),
        sourcemap: Some(SourceMapType::File),
        define: Some(define),
        resolve,
        // Choose the output format based on SSR flag
        format: if is_ssr {
            Some(OutputFormat::Iife)
        } else {
            Some(OutputFormat::Esm)
        },
        // Add additional options as needed
        ..Default::default()
    };

    // Create the bundler instance.
    let mut bundler = Bundler::new(bundler_options);

    // Run the bundler asynchronously
    println!("RUNNING BUNDLER FOR {} ENTRYPOINTS", entrypoint_paths.len());

    let rt = Runtime::new().map_err(|e| BundleError::BundlingError(e.to_string()))?;

    rt.block_on(async {
        bundler
            .write()
            .await
            .map_err(|err| BundleError::BundlingError(format!("Error during bundling: {:?}", err)))
    })?;

    // Get the output directory
    let output_dir = temp_dir.path().join("dist");

    // Process each entrypoint and collect results
    let mut results = HashMap::new();

    for entrypoint_path in entrypoint_paths {
        // Extract the base filename from the input path
        let input_path = Path::new(&entrypoint_path);
        let file_stem = input_path
            .file_stem()
            .ok_or_else(|| {
                BundleError::OutputError(format!("Invalid input filename: {}", entrypoint_path))
            })?
            .to_string_lossy();

        // Create expected output file paths based on input filename
        let js_filename = format!("{}.js", file_stem);
        let map_filename = format!("{}.js.map", file_stem);

        let js_path = output_dir.join(js_filename);
        let map_path = output_dir.join(map_filename);

        // Read the JavaScript output file (required)
        let script = fs::read_to_string(&js_path).map_err(|e| match e.kind() {
            std::io::ErrorKind::NotFound => BundleError::OutputError(format!(
                "Expected output file not found: {}",
                js_path.display()
            )),
            _ => BundleError::IoError(e),
        })?;

        // Read the source map (optional)
        let map = if map_path.exists() {
            Some(fs::read_to_string(&map_path).map_err(|e| BundleError::IoError(e))?)
        } else {
            None
        };

        // Add result to the map
        results.insert(entrypoint_path, BundleResult { script, map });
    }

    // Return the map of bundle results
    Ok(results)
}
