use regex::Regex;
use rolldown::plugin::{
    HookLoadArgs, HookLoadOutput, HookLoadReturn, HookResolveIdArgs, HookResolveIdOutput,
    HookResolveIdReturn, HookUsage, Plugin, PluginContext, PluginHookMeta, PluginOrder,
};
use rolldown::ModuleType;
use std::borrow::Cow;
use std::collections::{BTreeSet, HashMap};
use std::fs;
use std::io::{Error as IoError, ErrorKind};
use std::path::Path;
use std::sync::Mutex;

use crate::lexers::strip_js_comments;

const CLIENT_WRAPPER_PREFIX: &str = "\0mountaineer-client-wrapper:";
const CLIENT_ACTUAL_PREFIX: &str = "\0mountaineer-client-actual:";

lazy_static! {
    static ref EXPORT_DEFAULT_RE: Regex = Regex::new(r"(?m)^\s*export\s+default\b").unwrap();
    static ref EXPORT_FUNCTION_RE: Regex =
        Regex::new(r"(?m)^\s*export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\b").unwrap();
    static ref EXPORT_CLASS_RE: Regex =
        Regex::new(r"(?m)^\s*export\s+class\s+([A-Za-z_$][\w$]*)\b").unwrap();
    static ref EXPORT_VAR_RE: Regex =
        Regex::new(r"(?m)^\s*export\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*)\b").unwrap();
    static ref EXPORT_NAMESPACE_RE: Regex =
        Regex::new(r"(?m)^\s*export\s+\*\s+as\s+([A-Za-z_$][\w$]*)\s+from\b").unwrap();
    static ref EXPORT_BLOCK_RE: Regex =
        Regex::new(r#"(?m)^\s*export\s*\{([^}]*)\}\s*(?:from\s*['"][^'"]+['"])?\s*;?"#).unwrap();
    static ref EXPORT_ALL_RE: Regex = Regex::new(r"(?m)^\s*export\s+\*\s+from\b").unwrap();
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
struct ExportSurface {
    has_default: bool,
    named: Vec<String>,
}

impl ExportSurface {
    fn has_exports(&self) -> bool {
        self.has_default || !self.named.is_empty()
    }
}

#[derive(Debug)]
pub struct UseClientPlugin {
    is_ssr: bool,
    client_module_cache: Mutex<HashMap<String, bool>>,
    export_surface_cache: Mutex<HashMap<String, ExportSurface>>,
}

impl UseClientPlugin {
    pub fn new(is_ssr: bool) -> Self {
        Self {
            is_ssr,
            client_module_cache: Mutex::new(HashMap::new()),
            export_surface_cache: Mutex::new(HashMap::new()),
        }
    }

    fn wrapper_virtual_id(path: &str) -> String {
        format!("{CLIENT_WRAPPER_PREFIX}{path}")
    }

    fn actual_virtual_id(path: &str) -> String {
        format!("{CLIENT_ACTUAL_PREFIX}{path}")
    }

    fn parse_wrapper_virtual_id<'a>(id: &'a str) -> Option<&'a str> {
        id.strip_prefix(CLIENT_WRAPPER_PREFIX)
    }

    fn parse_actual_virtual_id<'a>(id: &'a str) -> Option<&'a str> {
        id.strip_prefix(CLIENT_ACTUAL_PREFIX)
    }

    fn is_local_source_file(path: &str) -> bool {
        let path = Path::new(path);
        if !path.is_absolute()
            || path
                .components()
                .any(|component| component.as_os_str().to_string_lossy() == "node_modules")
        {
            return false;
        }

        matches!(
            path.extension().and_then(|ext| ext.to_str()),
            Some("js" | "jsx" | "ts" | "tsx")
        )
    }

    fn is_client_boundary_path(&self, path: &str) -> Result<bool, IoError> {
        if !Self::is_local_source_file(path) {
            return Ok(false);
        }

        if let Some(cached) = self
            .client_module_cache
            .lock()
            .expect("client module cache lock poisoned")
            .get(path)
            .copied()
        {
            return Ok(cached);
        }

        let source = fs::read_to_string(path)?;
        let is_client = has_use_client_directive(&source);
        self.client_module_cache
            .lock()
            .expect("client module cache lock poisoned")
            .insert(path.to_string(), is_client);
        Ok(is_client)
    }

    fn get_export_surface(&self, path: &str) -> Result<ExportSurface, IoError> {
        if let Some(cached) = self
            .export_surface_cache
            .lock()
            .expect("export surface cache lock poisoned")
            .get(path)
            .cloned()
        {
            return Ok(cached);
        }

        let source = fs::read_to_string(path)?;
        let surface = parse_export_surface(&source)?;
        self.export_surface_cache
            .lock()
            .expect("export surface cache lock poisoned")
            .insert(path.to_string(), surface.clone());
        Ok(surface)
    }

    fn module_type_from_path(path: &str) -> Option<ModuleType> {
        match Path::new(path).extension().and_then(|ext| ext.to_str()) {
            Some("js") => Some(ModuleType::Js),
            Some("jsx") => Some(ModuleType::Jsx),
            Some("ts") => Some(ModuleType::Ts),
            Some("tsx") => Some(ModuleType::Tsx),
            _ => None,
        }
    }

    fn generate_boundary_module(&self, path: &str) -> Result<String, IoError> {
        let surface = self.get_export_surface(path)?;
        if self.is_ssr {
            Ok(generate_ssr_boundary_module(&surface))
        } else {
            generate_client_boundary_module(path, &surface)
        }
    }
}

impl Plugin for UseClientPlugin {
    fn name(&self) -> Cow<'static, str> {
        "mountaineer:use-client".into()
    }

    fn register_hook_usage(&self) -> HookUsage {
        HookUsage::ResolveId | HookUsage::Load
    }

    fn resolve_id_meta(&self) -> Option<PluginHookMeta> {
        Some(PluginHookMeta {
            order: Some(PluginOrder::Pre),
        })
    }

    fn load_meta(&self) -> Option<PluginHookMeta> {
        Some(PluginHookMeta {
            order: Some(PluginOrder::Pre),
        })
    }

    async fn resolve_id(
        &self,
        ctx: &PluginContext,
        args: &HookResolveIdArgs<'_>,
    ) -> HookResolveIdReturn {
        if Self::parse_wrapper_virtual_id(args.specifier).is_some()
            || Self::parse_actual_virtual_id(args.specifier).is_some()
        {
            return Ok(Some(HookResolveIdOutput::from_id(args.specifier)));
        }

        if let Some(importer) = args.importer {
            if let Some(actual_importer_path) = Self::parse_actual_virtual_id(importer) {
                let resolved = ctx
                    .resolve(args.specifier, Some(actual_importer_path), None)
                    .await
                    .map_err(|err| IoError::other(err.to_string()))?
                    .map_err(|err| IoError::other(err.to_string()))?;

                if self.is_client_boundary_path(resolved.id.as_str())? {
                    return Ok(Some(HookResolveIdOutput::from_id(Self::actual_virtual_id(
                        resolved.id.as_str(),
                    ))));
                }

                return Ok(Some(HookResolveIdOutput::from_resolved_id(resolved)));
            }
        }

        let resolved = match ctx.resolve(args.specifier, args.importer, None).await {
            Ok(Ok(resolved)) => resolved,
            Ok(Err(_)) | Err(_) => return Ok(None),
        };

        if self.is_client_boundary_path(resolved.id.as_str())? {
            return Ok(Some(HookResolveIdOutput::from_id(
                Self::wrapper_virtual_id(resolved.id.as_str()),
            )));
        }

        Ok(None)
    }

    async fn load(&self, _ctx: &PluginContext, args: &HookLoadArgs<'_>) -> HookLoadReturn {
        if let Some(path) = Self::parse_wrapper_virtual_id(args.id) {
            let code = self.generate_boundary_module(path)?;
            return Ok(Some(HookLoadOutput {
                code: code.into(),
                module_type: Some(ModuleType::Js),
                ..Default::default()
            }));
        }

        if let Some(path) = Self::parse_actual_virtual_id(args.id) {
            let code = fs::read_to_string(path)?;
            return Ok(Some(HookLoadOutput {
                code: code.into(),
                module_type: Self::module_type_from_path(path),
                ..Default::default()
            }));
        }

        Ok(None)
    }
}

fn has_use_client_directive(source: &str) -> bool {
    let stripped = strip_js_comments(source, false);
    let trimmed = stripped.trim_start_matches('\u{feff}').trim_start();

    directive_matches(trimmed, "'use client'") || directive_matches(trimmed, "\"use client\"")
}

fn directive_matches(source: &str, directive: &str) -> bool {
    let Some(remainder) = source.strip_prefix(directive) else {
        return false;
    };

    remainder.is_empty() || matches!(remainder.chars().next(), Some(';' | '\n' | '\r'))
}

fn parse_export_surface(source: &str) -> Result<ExportSurface, IoError> {
    let stripped = strip_js_comments(source, false);
    if EXPORT_ALL_RE.is_match(&stripped) {
        return Err(IoError::new(
            ErrorKind::InvalidInput,
            "Modules marked 'use client' cannot use `export * from ...`. Re-export explicit component names instead.",
        ));
    }

    let mut named = BTreeSet::new();
    let mut has_default = EXPORT_DEFAULT_RE.is_match(&stripped);

    for regex in [
        &*EXPORT_FUNCTION_RE,
        &*EXPORT_CLASS_RE,
        &*EXPORT_VAR_RE,
        &*EXPORT_NAMESPACE_RE,
    ] {
        for captures in regex.captures_iter(&stripped) {
            if let Some(name) = captures.get(1) {
                named.insert(name.as_str().to_string());
            }
        }
    }

    for captures in EXPORT_BLOCK_RE.captures_iter(&stripped) {
        let Some(block) = captures.get(1) else {
            continue;
        };

        for segment in block.as_str().split(',') {
            let segment = segment.trim();
            if segment.is_empty() || segment.starts_with("type ") {
                continue;
            }

            let export_name = segment
                .split_once(" as ")
                .map(|(_, alias)| alias.trim())
                .unwrap_or(segment);

            if export_name == "default" {
                has_default = true;
                continue;
            }

            if !is_valid_identifier(export_name) {
                return Err(IoError::new(
                    ErrorKind::InvalidInput,
                    format!(
                        "Unsupported export `{export_name}` in a module marked 'use client'. Re-export explicit identifier names only."
                    ),
                ));
            }

            named.insert(export_name.to_string());
        }
    }

    Ok(ExportSurface {
        has_default,
        named: named.into_iter().collect(),
    })
}

fn is_valid_identifier(value: &str) -> bool {
    let mut chars = value.chars();
    match chars.next() {
        Some(ch) if ch == '_' || ch == '$' || ch.is_ascii_alphabetic() => {}
        _ => return false,
    }

    chars.all(|ch| ch == '_' || ch == '$' || ch.is_ascii_alphanumeric())
}

fn generate_ssr_boundary_module(surface: &ExportSurface) -> String {
    if !surface.has_exports() {
        return String::new();
    }

    let mut output = String::from(
        "const createClientBoundary = (exportName) => {\n  const Boundary = (props) => props.children ?? null;\n  Boundary.displayName = `ClientBoundary(${exportName})`;\n  return Boundary;\n};\n",
    );

    if surface.has_default {
        output.push_str("export default createClientBoundary('default');\n");
    }

    for export_name in &surface.named {
        output.push_str(&format!(
            "export const {export_name} = createClientBoundary({});\n",
            js_string_literal(export_name).expect("export names are valid string literals"),
        ));
    }

    output
}

fn generate_client_boundary_module(path: &str, surface: &ExportSurface) -> Result<String, IoError> {
    let actual_id = js_string_literal(&UseClientPlugin::actual_virtual_id(path))?;

    if !surface.has_exports() {
        return Ok(format!("import {};\n", actual_id));
    }

    let mut output = format!(
        "import React, {{ useEffect, useState }} from 'react';\nimport * as actual from {};\nconst createClientBoundary = (Actual, exportName) => {{\n  const Boundary = (props) => {{\n    const [isMounted, setIsMounted] = useState(false);\n    useEffect(() => {{\n      setIsMounted(true);\n    }}, []);\n    if (!isMounted) {{\n      return props.children ?? null;\n    }}\n    return React.createElement(Actual, props);\n  }};\n  Boundary.displayName = `ClientBoundary(${{exportName}})`;\n  return Boundary;\n}};\n",
        actual_id
    );

    if surface.has_default {
        output.push_str("export default createClientBoundary(actual.default, 'default');\n");
    }

    for export_name in &surface.named {
        output.push_str(&format!(
            "export const {export_name} = createClientBoundary(actual.{export_name}, {});\n",
            js_string_literal(export_name)?,
        ));
    }

    Ok(output)
}

fn js_string_literal(value: &str) -> Result<String, IoError> {
    serde_json::to_string(value).map_err(|err| IoError::new(ErrorKind::InvalidInput, err))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_has_use_client_directive_after_comments() {
        let source = "/* comment */\n'use client';\nexport default function Page() {}";
        assert!(has_use_client_directive(source));
    }

    #[test]
    fn test_parse_export_surface_collects_default_and_named_exports() {
        let source = r#"
        'use client';

        export default function Page() {}
        export const Graph = () => null;
        export async function Loader() {}
        const Local = () => null;
        export { Local as Alias };
        export * as Namespace from './namespace';
        "#;

        let surface = parse_export_surface(source).unwrap();
        assert!(surface.has_default);
        assert_eq!(
            surface.named,
            vec![
                "Alias".to_string(),
                "Graph".to_string(),
                "Loader".to_string(),
                "Namespace".to_string(),
            ]
        );
    }

    #[test]
    fn test_parse_export_surface_rejects_export_star() {
        let source = "'use client';\nexport * from './client';";
        let error = parse_export_surface(source).unwrap_err();
        assert!(error.to_string().contains("export * from"));
    }

    #[test]
    fn test_generate_boundary_modules_passthrough_children() {
        let surface = ExportSurface {
            has_default: true,
            named: vec!["Graph".to_string()],
        };

        let ssr_output = generate_ssr_boundary_module(&surface);
        assert!(ssr_output.contains("props.children ?? null"));

        let client_output = generate_client_boundary_module("/tmp/client.tsx", &surface).unwrap();
        assert!(client_output.contains("if (!isMounted)"));
        assert!(client_output.contains("return props.children ?? null;"));
        assert!(client_output.contains("actual.default"));
        assert!(client_output.contains("actual.Graph"));
    }
}
