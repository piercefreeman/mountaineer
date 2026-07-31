use super::super::{
    manifest::{Action, SchemaComponent, View},
    Result,
};
use super::schema::{
    action_has_required_input, action_input_type, collect_references, response_type,
};
use super::support::{destructured, import_path, shorthand_object, sorted};
use std::collections::{HashMap, HashSet};
use std::path::Path;

pub(super) fn local_actions(
    view: &View,
    global_root: &Path,
    components: &HashMap<&str, &SchemaComponent>,
) -> Result<Vec<String>> {
    let current = view.managed_dir.join("actions.ts");
    let api = import_path(&current, &global_root.join("api.ts"))?;
    let controllers = import_path(&current, &global_root.join("controllers.ts"))?;
    let mut dependencies = HashSet::new();
    let mut exception_names = HashSet::new();
    for action in &view.actions {
        for field in action.params.iter().chain(&action.headers) {
            collect_references(&field.schema, &mut dependencies);
        }
        if let Some(body) = &action.request_body {
            dependencies.insert(body.as_str());
        }
        if let Some(Some(response)) = action.responses.get(&view.controller) {
            dependencies.insert(response.as_str());
        }
        exception_names.extend(action.exceptions.iter().map(String::as_str));
    }
    let mut imports = vec![format!(
        "import {{ __request, FetchErrorBase }} from '{api}';"
    )];
    if !dependencies.is_empty() {
        imports.push(format!(
            "import type {{ {} }} from '{controllers}';",
            sorted(dependencies).join(", ")
        ));
    }

    let mut definitions = Vec::new();
    for name in sorted(exception_names) {
        let component = components
            .get(name)
            .ok_or_else(|| format!("Unknown exception component {name}"))?;
        let base = format!("{}Base", component.local_name);
        imports.push(format!(
            "import type {{ {} as {base} }} from '{controllers}';",
            component.global_name
        ));
        definitions.push(format!(
            "export class {} extends FetchErrorBase<{base}> {{}}",
            component.local_name
        ));
    }

    let mut blocks = vec![imports.join("\n")];
    for action in &view.actions {
        blocks.push(action_definition(action, view, components)?);
    }
    blocks.extend(definitions);
    Ok(blocks)
}

fn action_definition(
    action: &Action,
    view: &View,
    components: &HashMap<&str, &SchemaComponent>,
) -> Result<String> {
    let url = action
        .urls
        .get(&view.controller)
        .ok_or_else(|| format!("Action {} has no URL for {}", action.name, view.controller))?;
    let mut names = action
        .params
        .iter()
        .chain(&action.headers)
        .map(|field| field.name.as_str())
        .collect::<Vec<_>>();
    if action.request_body.is_some() {
        names.push("requestBody");
    }
    names.push("signal");

    let mut payload = vec![
        "  method: \"POST\"".into(),
        format!("  url: {}", serde_json::to_string(url)?),
    ];
    if !action.headers.is_empty() {
        payload.push(format!(
            "  headers: {}",
            shorthand_object(action.headers.iter().map(|field| field.name.as_str()))
        ));
    }
    if !action.params.is_empty() {
        payload.push(format!(
            "  query: {}",
            shorthand_object(action.params.iter().map(|field| field.name.as_str()))
        ));
    }
    if let Some(body) = &action.request_body {
        payload.push("  body: requestBody".into());
        if let Some(media_type) = &action.request_media_type {
            payload.push(format!(
                "  mediaType: {}",
                serde_json::to_string(media_type)?
            ));
        }
        if body.is_empty() {
            return Err("Request body component cannot be empty".into());
        }
    }
    let mut errors = Vec::new();
    for name in &action.exceptions {
        let component = components
            .get(name.as_str())
            .ok_or_else(|| format!("Unknown exception component {name}"))?;
        let status = component
            .status_code
            .ok_or_else(|| format!("Exception {name} has no status code"))?;
        errors.push(format!("    {status}: {}", component.local_name));
    }
    if !errors.is_empty() {
        payload.push(format!("  errors: {{\n{}\n  }}", errors.join(",\n")));
    }
    if action.is_raw_response {
        payload.push("  outputFormat: \"raw\"".into());
    }
    if action.is_streaming_response {
        payload.push("  eventStreamResponse: true".into());
    }
    payload.push("  signal".into());

    let default = if action_has_required_input(action) {
        ""
    } else {
        " = {}"
    };
    Ok(format!(
        "export const {} = ({} : {}{default}): {} => {{\n  return __request({{\n{}\n  }});\n}};",
        action.name,
        destructured(names.iter().copied()),
        action_input_type(action),
        response_type(action, Some(&view.controller)),
        payload.join(",\n")
    ))
}
