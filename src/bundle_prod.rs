use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::collections::HashSet;
use std::fs::File;
use std::io::Write;
use std::path::Path;
use tempfile::TempDir;

use crate::bundle_common::{self, BundleError, BundleMode};
use crate::code_gen;

#[pyfunction]
#[pyo3(
    signature = (
        paths,
        node_modules_path,
        environment,
        minify,
        live_reload_import,
        is_server,
        tsconfig_path = None,
        entrypoint_names = None
    )
)]
#[allow(clippy::too_many_arguments)]
pub fn compile_production_bundle(
    py: Python<'_>,
    paths: Vec<Vec<String>>,
    node_modules_path: String,
    environment: String,
    minify: bool,
    live_reload_import: String,
    is_server: bool,
    tsconfig_path: Option<String>,
    entrypoint_names: Option<Vec<String>>,
) -> PyResult<Py<PyDict>> {
    let bundle_output = compile_production_bundle_rust(
        &paths,
        ProductionBundleConfig {
            entrypoint_names: entrypoint_names.as_deref(),
            node_modules_path: &node_modules_path,
            environment: &environment,
            minify,
            live_reload_import: &live_reload_import,
            is_server,
            tsconfig_path: tsconfig_path.as_deref(),
        },
    )
    .map_err(|e| match e {
        BundleError::IoError(err) => pyo3::exceptions::PyIOError::new_err(err.to_string()),
        BundleError::BundlingError(msg)
        | BundleError::OutputError(msg)
        | BundleError::InvalidInput(msg) => pyo3::exceptions::PyRuntimeError::new_err(msg),
        BundleError::FileNotFound(path) => {
            pyo3::exceptions::PyFileNotFoundError::new_err(format!("File not found: {path}"))
        }
    })?;

    let result = PyDict::new(py);

    let py_entrypoints = PyList::new(py, &bundle_output.entrypoints)?;
    let py_entrypoint_maps = PyList::new(py, &bundle_output.entrypoint_maps)?;

    let py_supporting = PyDict::new(py);
    let py_supporting_maps = PyDict::new(py);

    for (filename, content) in bundle_output.supporting {
        py_supporting.set_item(filename, content)?;
    }
    for (filename, content) in bundle_output.supporting_maps {
        py_supporting_maps.set_item(filename, content)?;
    }

    result.set_item("entrypoints", &py_entrypoints)?;
    result.set_item("entrypoint_maps", &py_entrypoint_maps)?;
    result.set_item("supporting", &py_supporting)?;
    result.set_item("supporting_maps", &py_supporting_maps)?;

    Ok(result.into())
}

/// Internal representation before we convert to Python.
struct ProductionBundleOutput {
    #[allow(dead_code)]
    entrypoint_paths: Vec<String>,
    entrypoints: Vec<String>,
    entrypoint_maps: Vec<String>,
    supporting: Vec<(String, String)>,
    supporting_maps: Vec<(String, String)>,
    #[allow(dead_code)]
    supporting_paths: Vec<String>,
}

struct ProductionBundleConfig<'a> {
    entrypoint_names: Option<&'a [String]>,
    node_modules_path: &'a str,
    environment: &'a str,
    minify: bool,
    live_reload_import: &'a str,
    is_server: bool,
    tsconfig_path: Option<&'a str>,
}

fn compile_production_bundle_rust(
    paths: &[Vec<String>],
    config: ProductionBundleConfig<'_>,
) -> Result<ProductionBundleOutput, BundleError> {
    let temp_dir = TempDir::new().map_err(BundleError::IoError)?;
    let temp_dir_path = temp_dir.path();

    let entrypoint_paths = create_synthetic_entrypoints_rust(
        temp_dir_path,
        paths,
        config.entrypoint_names,
        config.is_server,
        config.live_reload_import,
    )?;

    let bundle_mode = if config.is_server {
        BundleMode::SingleServer
    } else {
        BundleMode::MultiClient
    };

    let bundle_results = bundle_common::bundle_common(
        entrypoint_paths.clone(),
        bundle_mode,
        config.environment.to_string(),
        config.node_modules_path.to_string(),
        None, // production: no live-reload port
        config.tsconfig_path.map(str::to_owned),
        config.minify,
    )?;

    let mut entrypoints = Vec::new();
    let mut entrypoint_maps = Vec::new();
    let mut entrypoint_paths_raw: Vec<String> = Vec::new();
    let mut supporting = Vec::new();
    let mut supporting_maps = Vec::new();
    let mut supporting_paths_raw: Vec<String> = Vec::new();

    for entrypoint_path in &entrypoint_paths {
        let file_stem = Path::new(entrypoint_path)
            .file_stem()
            .map(|s| s.to_string_lossy().to_string())
            .ok_or_else(|| BundleError::InvalidInput(format!("Invalid path: {entrypoint_path}")))?;

        let bundle_result = bundle_results.entrypoints.get(&file_stem).ok_or_else(|| {
            BundleError::OutputError(format!("No bundle result for entrypoint: {file_stem}"))
        })?;

        entrypoints.push(bundle_result.script.clone());
        entrypoint_maps.push(bundle_result.map.clone().unwrap_or_default());
        entrypoint_paths_raw.push(entrypoint_path.to_string());
    }

    for (filename, bundle_result) in bundle_results.extras {
        supporting.push((filename.clone(), bundle_result.script));
        if let Some(map) = bundle_result.map {
            supporting_maps.push((filename.clone(), map));
        }
        supporting_paths_raw.push(filename.to_string());
    }

    Ok(ProductionBundleOutput {
        entrypoints,
        entrypoint_maps,
        entrypoint_paths: entrypoint_paths_raw,
        supporting,
        supporting_maps,
        supporting_paths: supporting_paths_raw,
    })
}

fn create_synthetic_entrypoints_rust(
    temp_dir_path: &std::path::Path,
    paths: &[Vec<String>],
    entrypoint_names: Option<&[String]>,
    is_server: bool,
    live_reload_import: &str,
) -> Result<Vec<String>, BundleError> {
    if let Some(entrypoint_names) = entrypoint_names {
        if entrypoint_names.len() != paths.len() {
            return Err(BundleError::InvalidInput(format!(
                "Expected {} entrypoint names, but got {}",
                paths.len(),
                entrypoint_names.len()
            )));
        }

        let mut seen_names = HashSet::new();
        for entrypoint_name in entrypoint_names {
            if entrypoint_name.is_empty() {
                return Err(BundleError::InvalidInput(
                    "Entrypoint names must not be empty".to_string(),
                ));
            }

            if !seen_names.insert(entrypoint_name.as_str()) {
                return Err(BundleError::InvalidInput(format!(
                    "Duplicate entrypoint name: {entrypoint_name}"
                )));
            }
        }
    }

    paths
        .iter()
        .enumerate()
        .map(|(index, path_group)| {
            let default_entrypoint_name = format!("entrypoint{index}");
            let entrypoint_name = entrypoint_names
                .and_then(|names| names.get(index).map(String::as_str))
                .unwrap_or(default_entrypoint_name.as_str());
            let temp_file_path = temp_dir_path.join(format!("{entrypoint_name}.jsx"));
            let mut temp_file = File::create(&temp_file_path).map_err(BundleError::IoError)?;
            let entrypoint_content =
                code_gen::build_entrypoint(path_group, is_server, live_reload_import);
            temp_file
                .write_all(entrypoint_content.as_bytes())
                .map_err(BundleError::IoError)?;
            Ok(temp_file_path
                .to_str()
                .expect("Temp path is valid UTF-8")
                .to_owned())
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::tempdir;

    #[test]
    fn test_entrypoint_order_is_preserved() {
        let temp_dir = tempdir().unwrap();
        let temp_path = temp_dir.path();

        // simulate node_modules/
        let node_modules_path = temp_path.join("node_modules");
        std::fs::create_dir_all(&node_modules_path).unwrap();

        // create three dummy jsx files
        let files = [
            ("page1.jsx", "export default () => <div>1</div>;"),
            ("page2.jsx", "export default () => <div>2</div>;"),
            ("page3.jsx", "export default () => <div>3</div>;"),
        ];
        for (file, content) in &files {
            let mut f = File::create(temp_path.join(file)).unwrap();
            f.write_all(content.as_bytes()).unwrap();
        }

        // Create a dummy live reload file
        let live_reload_path = temp_path.join("live_reload.ts");
        File::create(&live_reload_path)
            .unwrap()
            .write_all(b"export default function mountLiveReload() {}")
            .unwrap();

        let input_paths = vec![
            vec!["page1.jsx".into()],
            vec!["page2.jsx".into()],
            vec!["page3.jsx".into()],
        ];

        let out = compile_production_bundle_rust(
            &input_paths,
            ProductionBundleConfig {
                entrypoint_names: None,
                node_modules_path: node_modules_path.to_string_lossy().as_ref(),
                environment: "production",
                minify: false,
                live_reload_import: live_reload_path.to_string_lossy().as_ref(),
                is_server: false,
                tsconfig_path: None,
            },
        )
        .unwrap();

        assert_eq!(out.entrypoints.len(), 3);
        assert_eq!(out.entrypoint_maps.len(), 3);
        assert!(!out.entrypoints.iter().any(String::is_empty));

        // Validate the path ordering is preserved by comparing just the filenames. The synthetic entrypoints
        // are written to a different temp directory than the input.
        let expected_filenames = vec!["entrypoint0.jsx", "entrypoint1.jsx", "entrypoint2.jsx"];

        let actual_filenames: Vec<String> = out
            .entrypoint_paths
            .iter()
            .map(|path| {
                Path::new(path)
                    .file_name()
                    .unwrap()
                    .to_string_lossy()
                    .to_string()
            })
            .collect();

        assert_eq!(actual_filenames, expected_filenames);
    }

    #[test]
    fn test_custom_entrypoint_names_are_preserved() {
        let temp_dir = tempdir().unwrap();
        let temp_path = temp_dir.path();

        let node_modules_path = temp_path.join("node_modules");
        std::fs::create_dir_all(&node_modules_path).unwrap();

        let files = [
            ("page1.jsx", "export default () => <div>1</div>;"),
            ("page2.jsx", "export default () => <div>2</div>;"),
        ];
        for (file, content) in &files {
            let mut f = File::create(temp_path.join(file)).unwrap();
            f.write_all(content.as_bytes()).unwrap();
        }

        let live_reload_path = temp_path.join("live_reload.ts");
        File::create(&live_reload_path)
            .unwrap()
            .write_all(b"export default function mountLiveReload() {}")
            .unwrap();

        let input_paths = vec![vec!["page1.jsx".into()], vec!["page2.jsx".into()]];
        let entrypoint_names = vec![
            "home_controller".to_string(),
            "detail_controller".to_string(),
        ];

        let out = compile_production_bundle_rust(
            &input_paths,
            ProductionBundleConfig {
                entrypoint_names: Some(&entrypoint_names),
                node_modules_path: node_modules_path.to_string_lossy().as_ref(),
                environment: "production",
                minify: false,
                live_reload_import: live_reload_path.to_string_lossy().as_ref(),
                is_server: false,
                tsconfig_path: None,
            },
        )
        .unwrap();

        let actual_filenames: Vec<String> = out
            .entrypoint_paths
            .iter()
            .map(|path| {
                Path::new(path)
                    .file_name()
                    .unwrap()
                    .to_string_lossy()
                    .to_string()
            })
            .collect();

        assert_eq!(
            actual_filenames,
            vec!["home_controller.jsx", "detail_controller.jsx"]
        );
    }
}
