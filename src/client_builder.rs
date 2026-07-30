use serde::Deserialize;
use serde_json::Value;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::error::Error;
use std::fs;
use std::path::{Component, Path, PathBuf};

type Result<T> = std::result::Result<T, Box<dyn Error + Send + Sync>>;

#[derive(Deserialize)]
struct Envelope {
    schema_version: u8,
    mountaineer_version: String,
    global_root: PathBuf,
    components: Vec<SchemaComponent>,
    controllers: Vec<Controller>,
    views: Vec<View>,
}

#[derive(Deserialize)]
struct SchemaComponent {
    kind: String,
    global_name: String,
    local_name: String,
    schema: Schema,
    status_code: Option<u16>,
    #[serde(default)]
    enum_members: Vec<EnumMember>,
}

#[derive(Deserialize)]
struct EnumMember {
    name: String,
    value: Value,
}

#[derive(Default, Deserialize)]
struct Schema {
    #[serde(rename = "$ref")]
    reference: Option<String>,
    #[serde(rename = "type")]
    kind: Option<String>,
    format: Option<String>,
    #[serde(rename = "anyOf", default)]
    any_of: Vec<Schema>,
    #[serde(rename = "allOf", default)]
    all_of: Vec<Schema>,
    items: Option<Box<Schema>>,
    #[serde(rename = "prefixItems", default)]
    prefix_items: Vec<Schema>,
    #[serde(rename = "enum", default)]
    enum_values: Vec<Value>,
    #[serde(default)]
    properties: BTreeMap<String, Schema>,
    #[serde(default)]
    required: Vec<String>,
    #[serde(rename = "additionalProperties")]
    additional_properties: Option<Box<Schema>>,
    #[serde(rename = "uniqueItems", default)]
    unique_items: bool,
    #[serde(rename = "x-mountaineer-key")]
    mountaineer_key: Option<Box<Schema>>,
}

#[derive(Deserialize)]
struct Field {
    name: String,
    schema: Schema,
    required: bool,
}

#[derive(Deserialize)]
struct Action {
    name: String,
    action_type: String,
    params: Vec<Field>,
    headers: Vec<Field>,
    request_body: Option<String>,
    request_media_type: Option<String>,
    responses: BTreeMap<String, Option<String>>,
    exceptions: Vec<String>,
    urls: BTreeMap<String, String>,
    is_raw_response: bool,
    is_streaming_response: bool,
}

#[derive(Deserialize)]
struct Controller {
    global_name: String,
    local_name: String,
    parents: Vec<String>,
    actions: Vec<Action>,
}

#[derive(Deserialize)]
struct View {
    controller: String,
    server_key: String,
    link_name: String,
    managed_dir: PathBuf,
    entrypoint_url: Option<String>,
    is_layout: bool,
    render: Option<String>,
    queries: Vec<Field>,
    paths: Vec<Field>,
    actions: Vec<Action>,
    controllers: Vec<String>,
    components: Vec<String>,
}

/// Generate all managed client files from a serialized Mountaineer envelope.
pub fn build(payload: &str) -> Result<()> {
    let envelope: Envelope = serde_json::from_str(payload)?;
    if envelope.schema_version != 1 {
        return Err(format!(
            "Unsupported Mountaineer envelope version {}",
            envelope.schema_version
        )
        .into());
    }

    fs::create_dir_all(&envelope.global_root)?;
    fs::write(
        envelope.global_root.join("api.ts"),
        include_str!("../mountaineer/static/api.ts"),
    )?;
    fs::write(
        envelope.global_root.join("live_reload.ts"),
        include_str!("../mountaineer/static/live_reload.ts"),
    )?;

    let components: HashMap<_, _> = envelope
        .components
        .iter()
        .map(|component| (component.global_name.as_str(), component))
        .collect();
    let controllers: HashMap<_, _> = envelope
        .controllers
        .iter()
        .map(|controller| (controller.global_name.as_str(), controller))
        .collect();

    write_generated(
        envelope.global_root.join("controllers.ts"),
        &envelope.mountaineer_version,
        global_controllers(&envelope),
    )?;
    write_generated(
        envelope.global_root.join("links.ts"),
        &envelope.mountaineer_version,
        global_links(&envelope)?,
    )?;
    write_generated(
        envelope.global_root.join("index.ts"),
        &envelope.mountaineer_version,
        vec![
            "export * from './api';\nexport * from './controllers';\nexport * from './links';"
                .into(),
        ],
    )?;

    for view in &envelope.views {
        fs::create_dir_all(&view.managed_dir)?;
        let actions = view.managed_dir.join("actions.ts");
        let models = view.managed_dir.join("models.ts");
        let use_server = view.managed_dir.join("useServer.ts");

        write_generated(
            &actions,
            &envelope.mountaineer_version,
            local_actions(view, &envelope.global_root, &components)?,
        )?;
        write_generated(
            &models,
            &envelope.mountaineer_version,
            local_models(view, &envelope.global_root, &components, &controllers)?,
        )?;
        write_generated(
            &use_server,
            &envelope.mountaineer_version,
            local_use_server(view, &envelope.global_root)?,
        )?;

        let mut modules = vec!["actions", "models", "useServer"];
        let links = view.managed_dir.join("links.ts");
        if view.is_layout {
            if links.exists() {
                fs::remove_file(links)?;
            }
        } else {
            write_generated(
                &links,
                &envelope.mountaineer_version,
                local_links(view, &envelope.global_root)?,
            )?;
            modules.insert(1, "links");
        }
        write_generated(
            view.managed_dir.join("index.ts"),
            &envelope.mountaineer_version,
            vec![modules
                .into_iter()
                .map(|module| format!("export * from './{module}';"))
                .collect::<Vec<_>>()
                .join("\n")],
        )?;
    }

    Ok(())
}

fn write_generated(path: impl AsRef<Path>, version: &str, blocks: Vec<String>) -> Result<()> {
    let body = blocks
        .into_iter()
        .filter(|block| !block.trim().is_empty())
        .collect::<Vec<_>>()
        .join("\n\n");
    fs::write(
        path,
        format!(
            "/*\n * This file was generated by Mountaineer v{version}. Do not edit it manually.\n */\n\n{body}"
        ),
    )?;
    Ok(())
}

fn global_controllers(envelope: &Envelope) -> Vec<String> {
    let mut blocks = vec!["/*\n * Models + Enums\n */".into()];
    blocks.extend(envelope.components.iter().filter_map(
        |component| match component.kind.as_str() {
            "enum" => Some(enum_definition(component)),
            "model" => Some(interface_definition(
                &component.global_name,
                &component.schema,
            )),
            _ => None,
        },
    ));
    blocks.push("/*\n * Exceptions\n */".into());
    blocks.extend(
        envelope
            .components
            .iter()
            .filter(|component| component.kind == "exception")
            .map(|component| interface_definition(&component.global_name, &component.schema)),
    );
    blocks.push("/*\n * View Controllers\n */".into());
    blocks.extend(envelope.controllers.iter().map(controller_definition));
    blocks
}

fn enum_definition(component: &SchemaComponent) -> String {
    let members = component
        .enum_members
        .iter()
        .map(|member| {
            format!(
                "  {} = {}",
                member.name,
                serde_json::to_string(&member.value).expect("JSON enum value")
            )
        })
        .collect::<Vec<_>>()
        .join(",\n");
    format!("export enum {} {{\n{members}\n}}", component.global_name)
}

fn interface_definition(name: &str, schema: &Schema) -> String {
    let parents = schema
        .all_of
        .iter()
        .filter_map(|parent| parent.reference.as_deref())
        .map(reference_name)
        .collect::<Vec<_>>();
    let extends = if parents.is_empty() {
        String::new()
    } else {
        format!(" extends {}", parents.join(", "))
    };
    format!("export interface {name}{extends} {}", object_fields(schema))
}

fn controller_definition(controller: &Controller) -> String {
    let extends = if controller.parents.is_empty() {
        String::new()
    } else {
        format!(" extends {}", controller.parents.join(", "))
    };
    let fields = controller
        .actions
        .iter()
        .map(|action| {
            let optional = if action_has_required_input(action) {
                ""
            } else {
                "?"
            };
            format!(
                "  {}: (params{optional}: {}) => {}",
                action.name,
                action_input_type(action),
                response_type(action, None)
            )
        })
        .collect::<Vec<_>>()
        .join(",\n");
    format!(
        "export interface {}{extends} {{\n{fields}\n}}",
        controller.global_name
    )
}

fn global_links(envelope: &Envelope) -> Result<Vec<String>> {
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

fn local_models(
    view: &View,
    global_root: &Path,
    components: &HashMap<&str, &SchemaComponent>,
    controllers: &HashMap<&str, &Controller>,
) -> Result<Vec<String>> {
    let current = view.managed_dir.join("models.ts");
    let source = import_path(&current, &global_root.join("controllers.ts"))?;
    let mut lines = Vec::new();
    for name in &view.controllers {
        if let Some(controller) = controllers.get(name.as_str()) {
            lines.push(format!(
                "export type {{ {} as {} }} from '{source}';",
                controller.global_name, controller.local_name
            ));
        }
    }
    for name in &view.components {
        if let Some(component) = components.get(name.as_str()) {
            match component.kind.as_str() {
                "model" => lines.push(format!(
                    "export type {{ {} as {} }} from '{source}';",
                    component.global_name, component.local_name
                )),
                "enum" => lines.push(format!(
                    "export {{ {} as {} }} from '{source}';",
                    component.global_name, component.local_name
                )),
                _ => {}
            }
        }
    }
    Ok(vec![lines.join("\n")])
}

fn local_links(view: &View, global_root: &Path) -> Result<Vec<String>> {
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

fn local_actions(
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

fn local_use_server(view: &View, global_root: &Path) -> Result<Vec<String>> {
    let Some(render) = &view.render else {
        return Ok(Vec::new());
    };
    let current = view.managed_dir.join("useServer.ts");
    let api = import_path(&current, &global_root.join("api.ts"))?;
    let links = import_path(&current, &global_root.join("links.ts"))?;
    let controllers = import_path(&current, &global_root.join("controllers.ts"))?;
    let action_names = view
        .actions
        .iter()
        .map(|action| action.name.as_str())
        .collect::<Vec<_>>();

    let mut imports = vec![
        "import React, { useCallback, useMemo, useState } from 'react';".into(),
        format!("import {{ applySideEffect }} from '{api}';"),
        format!("import LinkGenerator from '{links}';"),
        format!(
            "import {{ {render}, {} }} from '{controllers}';",
            view.controller
        ),
    ];
    if !action_names.is_empty() {
        imports.push(format!(
            "import {{ {} }} from './actions';",
            action_names.join(", ")
        ));
    }

    let mut wrappers = Vec::new();
    let mut response = vec![
        "    ...serverState".into(),
        "    linkGenerator: LinkGenerator".into(),
    ];
    let mut dependencies = vec!["serverState".to_string()];
    for action in &view.actions {
        if action.action_type == "sideeffect" {
            let wrapper = format!("{}WithSideEffect", action.name);
            wrappers.push(format!(
                "  const {wrapper} = useMemo(\n    () => applySideEffect({}, setControllerState),\n    [setControllerState],\n  );",
                action.name
            ));
            response.push(format!("    {}: {wrapper}", action.name));
            dependencies.push(wrapper);
        } else {
            response.push(format!("    {}: {}", action.name, action.name));
        }
    }
    let optional = format!("{render}Optional");
    Ok(vec![
        imports.join("\n"),
        format!(
            "declare global {{\n  interface SERVER_DATA_INTERFACE {{\n    {}: {render};\n  }}\n  var SERVER_DATA: SERVER_DATA_INTERFACE;\n}}",
            view.server_key
        ),
        format!(
            "export interface ServerState extends {render}, {} {{\n  linkGenerator: typeof LinkGenerator;\n}}",
            view.controller
        ),
        format!("export type {optional} = Partial<{render}>;"),
        format!(
            "export const useServer = (): ServerState => {{\n  const [serverState, setServerState] = useState(SERVER_DATA.{} as {render});\n\n  const setControllerState = useCallback((payload: {optional}) => {{\n    setServerState((state) => ({{\n      ...state,\n      ...payload,\n    }}));\n  }}, []);\n\n{}\n\n  return useMemo((): ServerState => ({{\n{}\n  }}), [{}]);\n}};",
            view.server_key,
            wrappers.join("\n\n"),
            response.join(",\n"),
            dependencies.join(", ")
        ),
    ])
}

fn action_input_type(action: &Action) -> String {
    let mut lines = action
        .params
        .iter()
        .chain(&action.headers)
        .map(|field| {
            format!(
                "  {}{}: {}",
                field.name,
                if field.required { "" } else { "?" },
                schema_type(&field.schema)
            )
        })
        .collect::<Vec<_>>();
    if let Some(body) = &action.request_body {
        lines.push(format!("  requestBody: {body}"));
    }
    lines.push("  signal?: AbortSignal".into());
    format!("{{\n{}\n}}", lines.join(",\n"))
}

fn action_has_required_input(action: &Action) -> bool {
    action.request_body.is_some()
        || action
            .params
            .iter()
            .chain(&action.headers)
            .any(|field| field.required)
}

fn response_type(action: &Action, controller: Option<&str>) -> String {
    if action.is_raw_response {
        return "Promise<Response>".into();
    }
    let responses: Vec<&Option<String>> = match controller {
        Some(controller) => action.responses.get(controller).into_iter().collect(),
        None => action.responses.values().collect(),
    };
    if responses.is_empty() {
        return "Promise<any>".into();
    }
    let mut output = Vec::new();
    for response in responses {
        let value = match response {
            Some(model) if action.is_streaming_response => {
                format!("Promise<AsyncGenerator<{model}, void, unknown>>")
            }
            Some(model) => format!("Promise<{model}>"),
            None => "Promise<void>".into(),
        };
        if !output.contains(&value) {
            output.push(value);
        }
    }
    output.join(" | ")
}

fn object_fields(schema: &Schema) -> String {
    let required: HashSet<_> = schema.required.iter().map(String::as_str).collect();
    let mut fields = schema.properties.iter().collect::<Vec<_>>();
    fields.sort_by_key(|(name, _)| *name);
    let body = fields
        .into_iter()
        .map(|(name, value)| {
            format!(
                "  {name}{}: {}",
                if required.contains(name.as_str()) {
                    ""
                } else {
                    "?"
                },
                schema_type(value)
            )
        })
        .collect::<Vec<_>>()
        .join(",\n");
    format!("{{\n{body}\n}}")
}

fn field_object<'a>(fields: impl Iterator<Item = &'a Field>) -> String {
    let body = fields
        .map(|field| {
            format!(
                "  {}{}: {}",
                field.name,
                if field.required { "" } else { "?" },
                schema_type(&field.schema)
            )
        })
        .collect::<Vec<_>>()
        .join(",\n");
    format!("{{\n{body}\n}}")
}

fn schema_type(schema: &Schema) -> String {
    if let Some(reference) = &schema.reference {
        return reference_name(reference).to_string();
    }
    if !schema.any_of.is_empty() {
        return schema
            .any_of
            .iter()
            .map(schema_type)
            .collect::<Vec<_>>()
            .join(" | ");
    }
    if !schema.enum_values.is_empty() {
        return schema
            .enum_values
            .iter()
            .map(|value| serde_json::to_string(value).expect("JSON schema enum value"))
            .collect::<Vec<_>>()
            .join(" | ");
    }
    match schema.kind.as_deref() {
        Some("string") if schema.format.as_deref() == Some("binary") => "Blob".into(),
        Some("string") => "string".into(),
        Some("number") | Some("integer") => "number".into(),
        Some("boolean") => "boolean".into(),
        Some("null") => "null".into(),
        Some("array") if !schema.prefix_items.is_empty() => format!(
            "[{}]",
            schema
                .prefix_items
                .iter()
                .map(schema_type)
                .collect::<Vec<_>>()
                .join(",")
        ),
        Some("array") if schema.unique_items => format!(
            "Set<{}>",
            schema
                .items
                .as_deref()
                .map(schema_type)
                .unwrap_or_else(|| "any".into())
        ),
        Some("array") => format!(
            "Array<{}>",
            schema
                .items
                .as_deref()
                .map(schema_type)
                .unwrap_or_else(|| "any".into())
        ),
        Some("object") => {
            if let Some(value) = schema.additional_properties.as_deref() {
                let key = schema
                    .mountaineer_key
                    .as_deref()
                    .map(schema_type)
                    .unwrap_or_else(|| "string".into());
                format!("Record<{key}, {}>", schema_type(value))
            } else {
                object_fields(schema)
            }
        }
        _ => "any".into(),
    }
}

fn collect_references<'a>(schema: &'a Schema, output: &mut HashSet<&'a str>) {
    if let Some(reference) = schema.reference.as_deref() {
        output.insert(reference_name(reference));
    }
    for child in schema
        .any_of
        .iter()
        .chain(&schema.all_of)
        .chain(&schema.prefix_items)
    {
        collect_references(child, output);
    }
    if let Some(child) = schema.items.as_deref() {
        collect_references(child, output);
    }
    if let Some(child) = schema.additional_properties.as_deref() {
        collect_references(child, output);
    }
    if let Some(child) = schema.mountaineer_key.as_deref() {
        collect_references(child, output);
    }
}

fn reference_name(reference: &str) -> &str {
    reference.rsplit('/').next().unwrap_or(reference)
}

fn destructured<'a>(names: impl Iterator<Item = &'a str>) -> String {
    let body = names
        .map(|name| format!("  {name}"))
        .collect::<Vec<_>>()
        .join(",\n");
    format!("{{\n{body}\n}}")
}

fn shorthand_object<'a>(names: impl Iterator<Item = &'a str>) -> String {
    let body = names
        .map(|name| format!("  {name}"))
        .collect::<Vec<_>>()
        .join(",\n");
    format!("{{\n{body}\n}}")
}

fn sorted<'a>(values: impl IntoIterator<Item = &'a str>) -> Vec<&'a str> {
    let mut values = values.into_iter().collect::<Vec<_>>();
    values.sort_unstable();
    values
}

fn import_path(from_file: &Path, to_file: &Path) -> Result<String> {
    let from = from_file
        .parent()
        .ok_or_else(|| format!("Import source has no parent: {}", from_file.display()))?;
    let from = from.components().collect::<Vec<_>>();
    let to = to_file.components().collect::<Vec<_>>();
    let shared = from
        .iter()
        .zip(&to)
        .take_while(|(left, right)| left == right)
        .count();
    if shared == 0
        || matches!(from.first(), Some(Component::Prefix(_))) && from.first() != to.first()
    {
        return Err(format!(
            "Cannot create a relative import from {} to {}",
            from_file.display(),
            to_file.display()
        )
        .into());
    }
    let mut path = PathBuf::new();
    for _ in shared..from.len() {
        path.push("..");
    }
    for component in &to[shared..] {
        path.push(component.as_os_str());
    }
    path.set_extension("");
    let mut path = path.to_string_lossy().replace('\\', "/");
    if !path.starts_with('.') {
        path.insert_str(0, "./");
    }
    Ok(path)
}
