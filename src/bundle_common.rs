use indexmap::IndexMap;
use log::debug;
use rolldown::{
    Bundler, BundlerOptions, InputItem, OutputFormat, RawMinifyOptions, ResolveOptions,
    SourceMapType,
};
use rustc_hash::FxHasher;
use std::collections::HashMap;
use std::fs;
use std::hash::BuildHasherDefault;
use std::path::Path;
use tempfile::TempDir;
use tokio::runtime::Runtime;

#[derive(Debug)]
pub enum OutputType {
    File(std::path::PathBuf),
    Directory(std::path::PathBuf),
}

#[derive(Debug)]
pub enum BundleMode {
    // 1. Single client-side javascript: wraps all dependencies in one file, intended for development embedding
    SingleClient,
    // 2. Split client-side javascript: tree-shakes dependencies into nested files, allows for better caching between
    MultiClient,
    // 3. Server-side javascript: single bundle in Iife mode
    SingleServer,
}

#[derive(Debug)]
pub struct BundleResult {
    // Since rust owns the tmp build directory, it's better to scope it to
    // clear at the end of this function and read everything into memory. We expect
    // our Python client will need this in memory anyway.
    pub script: String,
    pub map: Option<String>,
}

#[derive(Debug)]
pub struct BundleResults {
    // Map of entrypoint paths to their bundle results
    pub entrypoints: HashMap<String, BundleResult>,
    // Map of extra generated file paths to their bundle results
    pub extras: HashMap<String, BundleResult>,
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

/// Bundles JavaScript/TypeScript files using Rolldown, with support for different bundling modes
/// and environment configurations.
///
/// This function serves as the core bundling logic, supporting three modes:
/// - SingleClient: Creates a single bundle for client-side usage
/// - MultiClient: Creates multiple bundles with tree-shaking for optimized client delivery
/// - SingleServer: Creates a single IIFE bundle for server-side rendering
///
/// # Arguments
///
/// * `entrypoint_paths` - Vector of file paths to use as entrypoints for bundling
/// * `mode` - The [`BundleMode`] determining how files should be bundled
/// * `environment` - String indicating the environment (e.g., "development", "production")
/// * `node_modules_path` - Path to the node_modules directory for dependency resolution
/// * `live_reload_port` - Optional port number for live reload functionality
/// * `tsconfig_path` - Optional path to a tsconfig.json file for TypeScript configuration
/// * `minify` - Boolean indicating whether to use aggressive minification
///
/// # Returns
///
/// Returns a [`Result`] containing [`BundleResults`] with both entrypoint and extra generated files,
/// or a [`BundleError`] if the operation fails.
///
/// # Errors
///
/// This function will return an error if:
/// * No entrypoint paths are provided
/// * SingleClient/SingleServer modes receive multiple entrypoints
/// * Any entrypoint file doesn't exist
/// * The bundling process fails
/// * File I/O operations fail
pub fn bundle_common(
    entrypoint_paths: Vec<String>,
    mode: BundleMode,
    // Common build params
    environment: String,
    node_modules_path: String,
    live_reload_port: Option<u16>,
    tsconfig_path: Option<String>,
    minify: bool,
) -> Result<BundleResults, BundleError> {
    // Validate inputs
    if entrypoint_paths.is_empty() {
        return Err(BundleError::InvalidInput(
            "No entrypoint paths provided".to_string(),
        ));
    }

    // If our mode is either SingleClient or SingleServer, we should only accept
    // one file entrypoint in the file
    if matches!(mode, BundleMode::SingleClient | BundleMode::SingleServer)
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
    let temp_dir = TempDir::new().map_err(BundleError::IoError)?;

    // Get the output directory
    let output_dir = temp_dir.path().join("dist");
    fs::create_dir_all(&output_dir).map_err(BundleError::IoError)?;

    // Determine output type based on mode
    let output_type = match mode {
        BundleMode::SingleClient | BundleMode::SingleServer => {
            // Extract the file stem from the first (and only) entrypoint
            let file_stem = Path::new(&entrypoint_paths[0])
                .file_stem()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_else(|| "bundle".to_string());
            OutputType::File(output_dir.join(format!("{}.js", file_stem)))
        }
        BundleMode::MultiClient => {
            // Iife files have to be in a directory, otherwise rolldown will return
            // a build error
            OutputType::Directory(output_dir.clone())
        }
    };

    // Determine if this is server-side rendering based on mode
    let is_ssr = matches!(mode, BundleMode::SingleServer);

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

    debug!("Output type: {:?}", output_type);
    debug!("Input items: {:?}", input_items);
    debug!("Define: {:?}", define);
    debug!("Resolve: {:?}", resolve);
    debug!("Bundle mode: {:?}", mode);

    // https://github.com/rolldown/rolldown/blob/cb5e05c8d9683fd5c190daaad939e5364d7060b2/crates/rolldown_common/src/inner_bundler_options/mod.rs#L41
    let bundler_options = BundlerOptions {
        input: Some(input_items),
        dir: match &output_type {
            OutputType::Directory(path) => Some(path.to_string_lossy().to_string()),
            OutputType::File(_) => None,
        },
        file: match &output_type {
            OutputType::File(path) => Some(path.to_string_lossy().to_string()),
            OutputType::Directory(_) => None,
        },
        // Required for inlining client-side scripts. Otherwise specifying a single file for ESM modules will
        // crash during bundling.
        inline_dynamic_imports: Some(true),
        sourcemap: Some(SourceMapType::File),
        define: Some(define),
        resolve,
        // Choose the output format based on SSR flag
        format: if is_ssr {
            Some(OutputFormat::Iife)
        } else {
            Some(OutputFormat::Esm)
        },
        minify: Some(RawMinifyOptions::Bool(minify)),
        // Add additional options as needed
        ..Default::default()
    };

    // Create the bundler instance.
    let mut bundler = Bundler::new(bundler_options);

    let rt = Runtime::new().map_err(|e| BundleError::BundlingError(e.to_string()))?;

    rt.block_on(async {
        bundler
            .write()
            .await
            .map_err(|err| BundleError::BundlingError(format!("Error during bundling: {:?}", err)))
    })?;

    // Process the output directory and return the results
    process_output_directory(&output_dir, &entrypoint_paths)
}

/// Processes the output directory after bundling to categorize and read generated files.
///
/// This function scans the output directory and:
/// 1. Identifies JavaScript files and their associated source maps
/// 2. Categorizes files as either entrypoints or extra generated files
/// 3. Reads the contents of all files into memory
///
/// # Arguments
///
/// * `output_dir` - Path to the directory containing the bundled output files
/// * `entrypoint_paths` - Slice of original entrypoint paths used to identify main bundles
///
/// # Returns
///
/// Returns a [`Result`] containing [`BundleResults`] with:
/// * `entrypoints`: HashMap of entrypoint file names to their bundle results
/// * `extras`: HashMap of additional generated file names to their bundle results
///
/// # Errors
///
/// This function will return an error if:
/// * Directory reading fails
/// * File reading fails
/// * A file has an invalid name
/// * Expected output files are missing
///
/// # Notes
///
/// The function automatically handles source map files by:
/// * Skipping them in the initial file scan
/// * Associating them with their corresponding JavaScript files
/// * Including them in the bundle results when present
fn process_output_directory(
    output_dir: &Path,
    entrypoint_paths: &[String],
) -> Result<BundleResults, BundleError> {
    let mut entrypoints = HashMap::new();
    let mut extras = HashMap::new();

    // Print all files in the output directory for debugging
    debug!("Files in output directory {}", output_dir.display());
    for entry in fs::read_dir(output_dir).map_err(BundleError::IoError)? {
        let entry = entry.map_err(BundleError::IoError)?;
        let path = entry.path();
        debug!("  - {}", path.display());

        // Skip if not a file
        if !path.is_file() {
            continue;
        }

        // Get the file stem and extension
        let file_stem = path
            .file_stem()
            .ok_or_else(|| {
                BundleError::OutputError(format!("Invalid filename: {}", path.display()))
            })?
            .to_string_lossy();

        // Check if this is a source map file
        let is_map = path.extension().is_some_and(|ext| ext == "map");
        if is_map {
            continue;
        }

        // Read the JavaScript output file
        let script = fs::read_to_string(&path).map_err(|e| match e.kind() {
            std::io::ErrorKind::NotFound => BundleError::OutputError(format!(
                "Expected output file not found: {}",
                path.display()
            )),
            _ => BundleError::IoError(e),
        })?;

        // Read the source map if it exists
        let map_path = path.with_extension("js.map");
        let map = if map_path.exists() {
            Some(fs::read_to_string(&map_path).map_err(BundleError::IoError)?)
        } else {
            None
        };

        // Create bundle result
        let bundle_result = BundleResult { script, map };

        // Check if this is an entrypoint file
        let is_entrypoint = entrypoint_paths.iter().any(|ep| {
            Path::new(ep)
                .file_stem()
                .map(|s| s.to_string_lossy().to_string())
                .is_some_and(|s| s == file_stem)
        });

        // Add to appropriate map
        if is_entrypoint {
            entrypoints.insert(file_stem.to_string(), bundle_result);
        } else {
            // Get the file extension
            let extension = path
                .extension()
                .map(|ext| format!(".{}", ext.to_string_lossy()))
                .unwrap_or_default();
            extras.insert(format!("{}{}", file_stem, extension), bundle_result);
        }
    }

    Ok(BundleResults {
        entrypoints,
        extras,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::File;
    use std::io::Write;

    fn create_test_js_file(
        dir: &Path,
        filename: &str,
        content: &str,
    ) -> Result<String, std::io::Error> {
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
        fs::create_dir(temp_path.join("node_modules"))
            .expect("Failed to create node_modules directory");

        // Bundle the JavaScript
        let result = bundle_common(
            vec![entry_path],
            BundleMode::SingleClient,
            "development".to_string(),
            node_modules_path,
            None,
            None,
            true,
        );

        // Verify the result
        assert!(
            result.is_ok(),
            "Bundle operation failed: {:?}",
            result.err()
        );
        let bundles = result.unwrap();
        assert_eq!(bundles.entrypoints.len(), 1, "Expected 1 bundle result");

        // Check that the output contains our greet function
        let bundle_result = bundles.entrypoints.iter().next().unwrap().1;
        assert!(
            bundle_result.script.contains("greet"),
            "Bundle should contain the greet function"
        );
        assert!(
            bundle_result.script.contains("Hello"),
            "Bundle should contain the greeting text"
        );
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
            import { formatName } from './utils';
            
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
        fs::create_dir(temp_path.join("node_modules"))
            .expect("Failed to create node_modules directory");

        // Bundle the JavaScript - pass both files as entry points
        let result = bundle_common(
            vec![entry_path, utils_path],
            BundleMode::MultiClient,
            "development".to_string(),
            node_modules_path,
            None,
            None,
            false, // Set minify to false to make it easier to inspect output
        );

        // Verify the result
        assert!(
            result.is_ok(),
            "Bundle operation failed: {:?}",
            result.err()
        );
        let bundles = result.unwrap();

        // Check that we have both entrypoints
        assert!(
            !bundles.entrypoints.is_empty(),
            "Expected at least one bundle result"
        );

        // Check that at least one of the outputs contains our greet function
        let has_greet = bundles
            .entrypoints
            .iter()
            .any(|(_, bundle)| bundle.script.contains("greet"));
        assert!(
            has_greet,
            "At least one bundle should contain the greet function"
        );

        // Check that at least one of the outputs contains our formatName function
        let has_format_name = bundles
            .entrypoints
            .iter()
            .any(|(_, bundle)| bundle.script.contains("formatName"));
        assert!(
            has_format_name,
            "At least one bundle should contain the formatName function"
        );
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
        fs::create_dir(temp_path.join("node_modules"))
            .expect("Failed to create node_modules directory");

        // Bundle the JavaScript
        let result = bundle_common(
            vec![entry_path],
            BundleMode::SingleServer,
            "production".to_string(),
            node_modules_path,
            None,
            None,
            true,
        );

        // Verify the result
        assert!(
            result.is_ok(),
            "Bundle operation failed: {:?}",
            result.err()
        );
        let bundles = result.unwrap();
        assert_eq!(
            bundles.entrypoints.len(),
            1,
            "Expected 1 bundle result for server-side bundle"
        );

        // Check that the output contains our processRequest function
        let bundle_result = bundles.entrypoints.iter().next().unwrap().1;
        assert!(
            bundle_result.script.contains("processRequest"),
            "Bundle should contain the processRequest function"
        );
        assert!(
            bundle_result.script.contains("module.exports"),
            "Bundle should have CommonJS exports"
        );
    }

    #[test]
    fn test_extras_file_extension() {
        // Create a temporary directory for test files
        let temp_dir = TempDir::new().expect("Failed to create temp directory");
        let temp_path = temp_dir.path();

        // Create a utility module that will be imported
        let utils_js = r#"
            export function formatName(firstName, lastName) {
                return `${firstName} ${lastName}`;
            }
        "#;

        let utils_path = create_test_js_file(temp_path, "utils.js", utils_js)
            .expect("Failed to create utils.js file");

        // Create a component module that will be imported
        let component_js = r#"
            import { formatName } from './utils';
            
            export function Greeting({ firstName, lastName }) {
                const fullName = formatName(firstName, lastName);
                return `Hello, ${fullName}!`;
            }
        "#;

        let component_path = create_test_js_file(temp_path, "component.js", component_js)
            .expect("Failed to create component.js file");

        // Create a main entry file that imports both modules
        let entry_js = r#"
            import { Greeting } from './component';
            import { formatName } from './utils';
            
            export function greet(firstName, lastName) {
                const fullName = formatName(firstName, lastName);
                return `Hello, ${fullName}!`;
            }
            
            console.log(greet('John', 'Doe'));
            console.log(Greeting({ firstName: 'Jane', lastName: 'Smith' }));
        "#;

        let entry_path = create_test_js_file(temp_path, "main.js", entry_js)
            .expect("Failed to create main.js file");

        // Create a mock node_modules path
        let node_modules_path = temp_path.join("node_modules").to_string_lossy().to_string();
        fs::create_dir(temp_path.join("node_modules"))
            .expect("Failed to create node_modules directory");

        // Bundle the JavaScript with both files as entry points to force chunking
        let result = bundle_common(
            vec![entry_path, utils_path, component_path],
            BundleMode::MultiClient,
            "development".to_string(),
            node_modules_path,
            None,
            None,
            false, // Set minify to false to make it easier to inspect output
        );

        // Verify the result
        assert!(
            result.is_ok(),
            "Bundle operation failed: {:?}",
            result.err()
        );
        let bundles = result.unwrap();

        // Check that we have at least one extra file
        assert!(
            !bundles.extras.is_empty(),
            "Expected at least one extra file in the bundle"
        );

        // Verify that the extras map contains files with their extensions
        for (filename, _) in bundles.extras {
            assert!(
                filename.contains('.'),
                "Extra file '{}' should have a file extension",
                filename
            );
            assert!(
                filename.ends_with(".js"),
                "Extra file '{}' should end with .js extension",
                filename
            );
        }
    }
}
