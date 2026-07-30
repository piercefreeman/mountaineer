use super::Result;
use serde::Deserialize;
use serde_json::Value;
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    path::PathBuf,
};

#[derive(Deserialize)]
pub(super) struct Envelope {
    schema_version: u8,
    pub(super) mountaineer_version: String,
    pub(super) global_root: PathBuf,
    pub(super) components: Vec<SchemaComponent>,
    pub(super) controllers: Vec<Controller>,
    pub(super) views: Vec<View>,
}

#[derive(Clone, Copy, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "lowercase")]
pub(super) enum ComponentKind {
    Model,
    Enum,
    Exception,
}

#[derive(Deserialize)]
pub(super) struct SchemaComponent {
    pub(super) kind: ComponentKind,
    pub(super) global_name: String,
    pub(super) local_name: String,
    pub(super) schema: Schema,
    pub(super) status_code: Option<u16>,
    #[serde(default)]
    pub(super) enum_members: Vec<EnumMember>,
}

#[derive(Deserialize)]
pub(super) struct EnumMember {
    pub(super) name: String,
    pub(super) value: Value,
}

#[derive(Clone, Copy, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "lowercase")]
pub(super) enum SchemaKind {
    String,
    Number,
    Integer,
    Boolean,
    Null,
    Array,
    Object,
}

#[derive(Default, Deserialize)]
pub(super) struct Schema {
    #[serde(rename = "$ref")]
    pub(super) reference: Option<String>,
    #[serde(rename = "type")]
    pub(super) kind: Option<SchemaKind>,
    pub(super) format: Option<String>,
    #[serde(rename = "anyOf", default)]
    pub(super) any_of: Vec<Schema>,
    #[serde(rename = "allOf", default)]
    pub(super) all_of: Vec<Schema>,
    pub(super) items: Option<Box<Schema>>,
    #[serde(rename = "prefixItems", default)]
    pub(super) prefix_items: Vec<Schema>,
    #[serde(rename = "enum", default)]
    pub(super) enum_values: Vec<Value>,
    #[serde(default)]
    pub(super) properties: BTreeMap<String, Schema>,
    #[serde(default)]
    pub(super) required: Vec<String>,
    #[serde(rename = "additionalProperties")]
    pub(super) additional_properties: Option<Box<Schema>>,
    #[serde(rename = "uniqueItems", default)]
    pub(super) unique_items: bool,
    #[serde(rename = "x-mountaineer-key")]
    pub(super) mountaineer_key: Option<Box<Schema>>,
}

#[derive(Deserialize)]
pub(super) struct Field {
    pub(super) name: String,
    pub(super) schema: Schema,
    pub(super) required: bool,
}

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "lowercase")]
pub(super) enum ActionType {
    #[serde(rename = "sideeffect")]
    SideEffect,
    Passthrough,
    Render,
}

#[derive(Deserialize)]
pub(super) struct Action {
    pub(super) name: String,
    pub(super) action_type: ActionType,
    pub(super) params: Vec<Field>,
    pub(super) headers: Vec<Field>,
    pub(super) request_body: Option<String>,
    pub(super) request_media_type: Option<String>,
    pub(super) responses: BTreeMap<String, Option<String>>,
    pub(super) exceptions: Vec<String>,
    pub(super) urls: BTreeMap<String, String>,
    pub(super) is_raw_response: bool,
    pub(super) is_streaming_response: bool,
}

#[derive(Deserialize)]
pub(super) struct Controller {
    pub(super) global_name: String,
    pub(super) local_name: String,
    pub(super) parents: Vec<String>,
    pub(super) actions: Vec<Action>,
}

#[derive(Deserialize)]
pub(super) struct View {
    pub(super) controller: String,
    pub(super) server_key: String,
    pub(super) link_name: String,
    pub(super) managed_dir: PathBuf,
    pub(super) entrypoint_url: Option<String>,
    pub(super) is_layout: bool,
    pub(super) render: Option<String>,
    pub(super) queries: Vec<Field>,
    pub(super) paths: Vec<Field>,
    pub(super) actions: Vec<Action>,
    pub(super) controllers: Vec<String>,
    pub(super) components: Vec<String>,
}

impl Envelope {
    pub(super) fn parse(payload: &str) -> Result<Self> {
        let envelope: Self = serde_json::from_str(payload)?;
        if envelope.schema_version != 1 {
            return Err(format!(
                "Unsupported Mountaineer envelope version {}",
                envelope.schema_version
            )
            .into());
        }
        envelope.validate()?;
        Ok(envelope)
    }

    fn validate(&self) -> Result<()> {
        let mut components = HashMap::new();
        let mut generated_types = HashSet::new();
        for component in &self.components {
            if components
                .insert(component.global_name.as_str(), component)
                .is_some()
            {
                return Err(format!("Duplicate component {}", component.global_name).into());
            }
            generated_types.insert(component.global_name.as_str());
        }
        let mut controllers = HashMap::new();
        for controller in &self.controllers {
            if controllers
                .insert(controller.global_name.as_str(), controller)
                .is_some()
            {
                return Err(format!("Duplicate controller {}", controller.global_name).into());
            }
            if !generated_types.insert(controller.global_name.as_str()) {
                return Err(format!("Duplicate generated type {}", controller.global_name).into());
            }
        }

        for component in &self.components {
            if matches!(
                component.kind,
                ComponentKind::Model | ComponentKind::Exception
            ) && component.schema.kind != Some(SchemaKind::Object)
            {
                return Err(format!("{} must have an object schema", component.global_name).into());
            }
            validate_schema(&component.schema, &components)?;
            if component.kind == ComponentKind::Exception && component.status_code.is_none() {
                return Err(
                    format!("Exception {} has no status code", component.global_name).into(),
                );
            }
        }
        for controller in &self.controllers {
            for parent in &controller.parents {
                require_map(parent, &controllers, "controller")?;
            }
            validate_actions(&controller.actions, &components, &controllers)?;
        }
        let mut link_names = HashSet::new();
        let mut linked_controllers = HashSet::new();
        for view in &self.views {
            require_map(&view.controller, &controllers, "controller")?;
            if !view.is_layout && (view.entrypoint_url.is_none() || view.render.is_none()) {
                return Err(format!(
                    "Non-layout view {} requires an entrypoint URL and render component",
                    view.controller
                )
                .into());
            }
            if !view.is_layout && !link_names.insert(view.link_name.as_str()) {
                return Err(format!("Duplicate view link name {}", view.link_name).into());
            }
            if !view.is_layout && !linked_controllers.insert(view.controller.as_str()) {
                return Err(format!("Duplicate linked controller {}", view.controller).into());
            }
            let mut local_types = HashSet::new();
            for controller in &view.controllers {
                let controller = controllers
                    .get(controller.as_str())
                    .ok_or_else(|| format!("Unknown controller {controller}"))?;
                if !local_types.insert(controller.local_name.as_str()) {
                    return Err(format!(
                        "Duplicate local type {} in view {}",
                        controller.local_name, view.controller
                    )
                    .into());
                }
            }
            for component in &view.components {
                let component = components
                    .get(component.as_str())
                    .ok_or_else(|| format!("Unknown component {component}"))?;
                match component.kind {
                    ComponentKind::Model | ComponentKind::Enum => {}
                    ComponentKind::Exception => {
                        return Err(format!(
                            "{} is not a view model or enum component",
                            component.global_name
                        )
                        .into())
                    }
                }
                if !local_types.insert(component.local_name.as_str()) {
                    return Err(format!(
                        "Duplicate local type {} in view {}",
                        component.local_name, view.controller
                    )
                    .into());
                }
            }
            if let Some(render) = &view.render {
                match components.get(render.as_str()) {
                    Some(component) if component.kind == ComponentKind::Model => {}
                    Some(_) => {
                        return Err(format!("{render} is not a model component").into());
                    }
                    None => return Err(format!("Unknown render component {render}").into()),
                }
            }
            for field in view.queries.iter().chain(&view.paths) {
                validate_schema(&field.schema, &components)?;
            }
            validate_actions(&view.actions, &components, &controllers)?;
            for action in &view.actions {
                if !action.urls.contains_key(&view.controller) {
                    return Err(format!(
                        "Action {} has no URL for {}",
                        action.name, view.controller
                    )
                    .into());
                }
                if !action.responses.contains_key(&view.controller) {
                    return Err(format!(
                        "Action {} has no response for {}",
                        action.name, view.controller
                    )
                    .into());
                }
            }
        }
        Ok(())
    }
}

fn validate_actions(
    actions: &[Action],
    components: &HashMap<&str, &SchemaComponent>,
    controllers: &HashMap<&str, &Controller>,
) -> Result<()> {
    let mut names = HashSet::new();
    for action in actions {
        if !names.insert(action.name.as_str()) {
            return Err(format!("Duplicate action {}", action.name).into());
        }
        let mut inputs = HashSet::new();
        for field in action.params.iter().chain(&action.headers) {
            if !inputs.insert(field.name.as_str())
                || field.name == "signal"
                || action.request_body.is_some() && field.name == "requestBody"
            {
                return Err(format!(
                    "Duplicate or reserved input {} on action {}",
                    field.name, action.name
                )
                .into());
            }
            validate_schema(&field.schema, components)?;
        }
        if let Some(component) = &action.request_body {
            require_map(component, components, "request body component")?;
        } else if action.request_media_type.is_some() {
            return Err(format!(
                "Action {} has a media type without a request body",
                action.name
            )
            .into());
        }
        for (controller, response) in &action.responses {
            require_map(controller, controllers, "response controller")?;
            if let Some(component) = response {
                require_map(component, components, "response component")?;
            }
        }
        for controller in action.urls.keys() {
            require_map(controller, controllers, "URL controller")?;
        }
        let mut exception_statuses = HashSet::new();
        for exception in &action.exceptions {
            let component = components
                .get(exception.as_str())
                .ok_or_else(|| format!("Unknown exception component {exception}"))?;
            if component.kind != ComponentKind::Exception {
                return Err(format!("{exception} is not an exception component").into());
            }
            let status = component.status_code.expect("validated exception status");
            if !exception_statuses.insert(status) {
                return Err(format!(
                    "Action {} has multiple exceptions with status {status}",
                    action.name
                )
                .into());
            }
        }
    }
    Ok(())
}

fn validate_schema(schema: &Schema, components: &HashMap<&str, &SchemaComponent>) -> Result<()> {
    if let Some(reference) = &schema.reference {
        require_map(reference_name(reference), components, "schema component")?;
    }
    if schema
        .all_of
        .iter()
        .any(|parent| parent.reference.is_none())
    {
        return Err("allOf entries must reference schema components".into());
    }
    let mut required = HashSet::new();
    for property in &schema.required {
        if !required.insert(property) {
            return Err(format!("Duplicate required property {property}").into());
        }
        if !schema.properties.contains_key(property) {
            return Err(format!("Required property {property} is not defined").into());
        }
    }
    for child in schema
        .any_of
        .iter()
        .chain(&schema.all_of)
        .chain(&schema.prefix_items)
        .chain(schema.properties.values())
    {
        validate_schema(child, components)?;
    }
    for child in [
        schema.items.as_deref(),
        schema.additional_properties.as_deref(),
        schema.mountaineer_key.as_deref(),
    ]
    .into_iter()
    .flatten()
    {
        validate_schema(child, components)?;
    }
    Ok(())
}

fn require_map<T>(name: &str, values: &HashMap<&str, T>, label: &str) -> Result<()> {
    if values.contains_key(name) {
        Ok(())
    } else {
        Err(format!("Unknown {label} {name}").into())
    }
}

fn reference_name(reference: &str) -> &str {
    reference.rsplit('/').next().unwrap_or(reference)
}
