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
    tsconfig_path: Option<String>,
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

    define.insert(
        "process.env.LIVE_RELOAD_PORT".to_string(),
        format!("{}", live_reload_port.unwrap_or(0)),
    );

    if is_ssr {
        define.insert("process.env.SSR_RENDERING".to_string(), "true".to_string());
        define.insert("global".to_string(), "window".to_string());
    } else {
        define.insert("process.env.SSR_RENDERING".to_string(), "false".to_string());
    }

    // Set up resolve options to let Rolldown know where to find node_modules.
    let resolve = Some(ResolveOptions {
        modules: Some(vec![node_modules_path.clone()]),
        tsconfig_filename: tsconfig_path,
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


#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::File;
    use std::io::Write;

    fn create_test_js_file(dir: &Path, filename: &str, content: &str) -> Result<String, std::io::Error> {
        let file_path = dir.join(filename);
        let mut file = File::create(&file_path)?;
        file.write_all(content.as_bytes())?;
        Ok(file_path.to_string_lossy().to_string())
    }

    #[test]
    fn test_single_client_bundle() {
        // Create a temporary directory for test files
        let temp_dir = TempDir::new().expect("Failed to create temp directory");
        let temp_path = temp_dir.path();
        
        // Create a simple JavaScript file
        let js_content = r#"
            export function greet(name) {
                return `Hello, ${name}!`;
            }
            
            console.log(greet('World'));
        "#;
        
        let entry_path = create_test_js_file(temp_path, "entry.js", js_content)
            .expect("Failed to create test JS file");
        
        // Create a mock node_modules path
        let node_modules_path = temp_path.join("node_modules").to_string_lossy().to_string();
        fs::create_dir(temp_path.join("node_modules")).expect("Failed to create node_modules directory");
        
        // Bundle the JavaScript
        let result = bundle_common(
            vec![entry_path],
            BundleMode::SINGLE_CLIENT,
            "development".to_string(),
            node_modules_path,
            None,
        );
        
        // Verify the result
        assert!(result.is_ok(), "Bundle operation failed: {:?}", result.err());
        let bundles = result.unwrap();
        assert_eq!(bundles.len(), 1, "Expected 1 bundle result");
        
        // Check that the output contains our greet function
        let (_, bundle_result) = bundles.iter().next().unwrap();
        assert!(bundle_result.script.contains("greet"), "Bundle should contain the greet function");
        assert!(bundle_result.script.contains("Hello"), "Bundle should contain the greeting text");
    }

    #[test]
    fn test_multi_client_bundle() {
        // Create a temporary directory for test files
        let temp_dir = TempDir::new().expect("Failed to create temp directory");
        let temp_path = temp_dir.path();
        
        // Create a module to import
        let utils_js = r#"
            export function formatName(firstName, lastName) {
                return `${firstName} ${lastName}`;
            }
        "#;
        
        let utils_path = create_test_js_file(temp_path, "utils.js", utils_js)
            .expect("Failed to create utils.js file");
        
        // Create a main entry file that imports the module
        let entry_js = r#"
            import { formatName } from './utils.js';
            
            export function greet(firstName, lastName) {
                const fullName = formatName(firstName, lastName);
                return `Hello, ${fullName}!`;
            }
            
            console.log(greet('John', 'Doe'));
        "#;
        
        let entry_path = create_test_js_file(temp_path, "main.js", entry_js)
            .expect("Failed to create main.js file");
        
        // Create a mock node_modules path
        let node_modules_path = temp_path.join("node_modules").to_string_lossy().to_string();
        fs::create_dir(temp_path.join("node_modules")).expect("Failed to create node_modules directory");
        
        // Bundle the JavaScript
        let result = bundle_common(
            vec![entry_path],
            BundleMode::MULTI_CLIENT,
            "development".to_string(),
            node_modules_path,
            None,
        );
        
        // Verify the result
        assert!(result.is_ok(), "Bundle operation failed: {:?}", result.err());
        let bundles = result.unwrap();
        assert!(!bundles.is_empty(), "Expected at least one bundle result");
        
        // Check that at least one of the outputs contains our greet function
        let has_greet = bundles.iter().any(|(_, bundle)| bundle.script.contains("greet"));
        assert!(has_greet, "At least one bundle should contain the greet function");
        
        // Check that at least one of the outputs contains our formatName function
        let has_format_name = bundles.iter().any(|(_, bundle)| bundle.script.contains("formatName"));
        assert!(has_format_name, "At least one bundle should contain the formatName function");
    }

    #[test]
    fn test_single_server_bundle() {
        // Create a temporary directory for test files
        let temp_dir = TempDir::new().expect("Failed to create temp directory");
        let temp_path = temp_dir.path();
        
        // Create a simple server-side JavaScript file
        let server_js = r#"
            function processRequest(req) {
                return {
                    status: 200,
                    body: `Processed request from ${req.ip}`
                };
            }
            
            module.exports = { processRequest };
        "#;
        
        let entry_path = create_test_js_file(temp_path, "server.js", server_js)
            .expect("Failed to create server.js file");
        
        // Create a mock node_modules path
        let node_modules_path = temp_path.join("node_modules").to_string_lossy().to_string();
        fs::create_dir(temp_path.join("node_modules")).expect("Failed to create node_modules directory");
        
        // Bundle the JavaScript
        let result = bundle_common(
            vec![entry_path],
            BundleMode::SINGLE_SERVER,
            "production".to_string(),
            node_modules_path,
            None,
        );
        
        // Verify the result
        assert!(result.is_ok(), "Bundle operation failed: {:?}", result.err());
        let bundles = result.unwrap();
        assert_eq!(bundles.len(), 1, "Expected 1 bundle result for server-side bundle");
        
        // Check that the output contains our processRequest function
        let (_, bundle_result) = bundles.iter().next().unwrap();
        assert!(bundle_result.script.contains("processRequest"), "Bundle should contain the processRequest function");
        assert!(bundle_result.script.contains("module.exports"), "Bundle should have CommonJS exports");
    }
} 