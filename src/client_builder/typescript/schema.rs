use super::super::manifest::{Action, Field, Schema, SchemaKind};
use std::collections::HashSet;

pub(super) fn interface_definition(name: &str, schema: &Schema) -> String {
    let parents = schema
        .all_of
        .iter()
        .map(|parent| {
            parent
                .reference
                .as_deref()
                .expect("validated allOf reference")
        })
        .map(reference_name)
        .collect::<Vec<_>>();
    let extends = if parents.is_empty() {
        String::new()
    } else {
        format!(" extends {}", parents.join(", "))
    };
    format!("export interface {name}{extends} {}", object_fields(schema))
}

pub(super) fn action_input_type(action: &Action) -> String {
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

pub(super) fn action_has_required_input(action: &Action) -> bool {
    action.request_body.is_some()
        || action
            .params
            .iter()
            .chain(&action.headers)
            .any(|field| field.required)
}

pub(super) fn response_type(action: &Action, controller: Option<&str>) -> String {
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

pub(super) fn field_object<'a>(fields: impl Iterator<Item = &'a Field>) -> String {
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
    match schema.kind {
        Some(SchemaKind::String) if schema.format.as_deref() == Some("binary") => "Blob".into(),
        Some(SchemaKind::String) => "string".into(),
        Some(SchemaKind::Number | SchemaKind::Integer) => "number".into(),
        Some(SchemaKind::Boolean) => "boolean".into(),
        Some(SchemaKind::Null) => "null".into(),
        Some(SchemaKind::Array) if !schema.prefix_items.is_empty() => format!(
            "[{}]",
            schema
                .prefix_items
                .iter()
                .map(schema_type)
                .collect::<Vec<_>>()
                .join(",")
        ),
        Some(SchemaKind::Array) if schema.unique_items => format!(
            "Set<{}>",
            schema
                .items
                .as_deref()
                .map(schema_type)
                .unwrap_or_else(|| "any".into())
        ),
        Some(SchemaKind::Array) => format!(
            "Array<{}>",
            schema
                .items
                .as_deref()
                .map(schema_type)
                .unwrap_or_else(|| "any".into())
        ),
        Some(SchemaKind::Object) => {
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
        None => "any".into(),
    }
}

pub(super) fn collect_references<'a>(schema: &'a Schema, output: &mut HashSet<&'a str>) {
    if let Some(reference) = schema.reference.as_deref() {
        output.insert(reference_name(reference));
    }
    for child in schema
        .any_of
        .iter()
        .chain(&schema.all_of)
        .chain(&schema.prefix_items)
        .chain(schema.properties.values())
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

fn reference_name(reference: &str) -> &str {
    reference.rsplit('/').next().unwrap_or(reference)
}
