use super::super::{
    manifest::{Envelope, View},
    Result,
};
use super::schema::{collect_references, field_object};
use super::support::{destructured, import_path, shorthand_object, sorted};
use std::collections::HashSet;
use std::path::Path;

pub(super) fn global_links(envelope: &Envelope) -> Result<Vec<String>> {
    let links_path = envelope.global_root.join("links.ts");
    let views = envelope.views.iter().filter(|view| !view.is_layout);
    let mut imports = Vec::new();
    let mut fields = Vec::new();
    for view in views {
        let alias = format!("{}GetLinks", view.controller);
        imports.push(format!(
            "import {{ getLink as {alias} }} from '{}';",
            import_path(&links_path, &view.managed_dir.join("links.ts"))?
        ));
        fields.push(format!("  {}: {alias}", view.link_name));
    }
    Ok(vec![
        imports.join("\n"),
        format!(
            "export const linkGenerator = {{\n{}\n}};",
            fields.join(",\n")
        ),
        "export default linkGenerator;".into(),
    ])
}

pub(super) fn local_links(view: &View, global_root: &Path) -> Result<Vec<String>> {
    let Some(url) = &view.entrypoint_url else {
        return Ok(Vec::new());
    };
    if view.render.is_none() {
        return Ok(Vec::new());
    }

    let current = view.managed_dir.join("links.ts");
    let api = import_path(&current, &global_root.join("api.ts"))?;
    let controllers = import_path(&current, &global_root.join("controllers.ts"))?;
    let mut refs = HashSet::new();
    for field in view.queries.iter().chain(&view.paths) {
        collect_references(&field.schema, &mut refs);
    }
    let type_import = if refs.is_empty() {
        String::new()
    } else {
        format!(
            "\nimport type {{ {} }} from '{controllers}';",
            sorted(refs).join(", ")
        )
    };

    let fields = view.queries.iter().chain(&view.paths).collect::<Vec<_>>();
    let signature = if fields.is_empty() {
        String::new()
    } else {
        format!(
            "{} : {}",
            destructured(fields.iter().map(|field| field.name.as_str())),
            field_object(fields.iter().copied())
        )
    };
    let query = shorthand_object(view.queries.iter().map(|field| field.name.as_str()));
    let paths = shorthand_object(view.paths.iter().map(|field| field.name.as_str()));
    let query_type = if view.queries.is_empty() {
        "Record<string, never>"
    } else {
        "Record<string, string | number | boolean | null | undefined | Array<string | number | boolean>>"
    };
    let path_type = if view.paths.is_empty() {
        "Record<string, never>"
    } else {
        "Record<string, string | number | boolean | null | undefined>"
    };
    let url_value = if url.contains("${") {
        format!("`{url}`")
    } else {
        serde_json::to_string(url)?
    };
    let implementation = format!(
        "export const getLink = ({signature}) => {{\n  const url = {url_value};\n\n  const queryParameters: {query_type} = {query};\n  const pathParameters: {path_type} = {paths};\n\n  return __getLink({{\n    rawUrl: url,\n    queryParameters,\n    pathParameters\n  }});\n}};"
    );
    Ok(vec![
        format!("import {{ __getLink }} from '{api}';{type_import}"),
        implementation,
    ])
}
