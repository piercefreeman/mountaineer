use super::super::{
    manifest::{ComponentKind, Controller, Envelope, SchemaComponent, View},
    Result,
};
use super::schema::{
    action_has_required_input, action_input_type, interface_definition, response_type,
};
use super::support::import_path;
use std::collections::HashMap;
use std::path::Path;

pub(super) fn global_controllers(envelope: &Envelope) -> Vec<String> {
    let mut blocks = vec!["/*\n * Models + Enums\n */".into()];
    blocks.extend(
        envelope
            .components
            .iter()
            .filter_map(|component| match component.kind {
                ComponentKind::Enum => Some(enum_definition(component)),
                ComponentKind::Model => Some(interface_definition(
                    &component.global_name,
                    &component.schema,
                )),
                ComponentKind::Exception => None,
            }),
    );
    blocks.push("/*\n * Exceptions\n */".into());
    blocks.extend(
        envelope
            .components
            .iter()
            .filter_map(|component| match component.kind {
                ComponentKind::Exception => Some(interface_definition(
                    &component.global_name,
                    &component.schema,
                )),
                ComponentKind::Model | ComponentKind::Enum => None,
            }),
    );
    blocks.push("/*\n * View Controllers\n */".into());
    blocks.extend(envelope.controllers.iter().map(controller_definition));
    blocks
}

pub(super) fn local_models(
    view: &View,
    global_root: &Path,
    components: &HashMap<&str, &SchemaComponent>,
    controllers: &HashMap<&str, &Controller>,
) -> Result<Vec<String>> {
    let current = view.managed_dir.join("models.ts");
    let source = import_path(&current, &global_root.join("controllers.ts"))?;
    let mut lines = Vec::new();
    for name in &view.controllers {
        let controller = controllers
            .get(name.as_str())
            .expect("validated controller");
        lines.push(format!(
            "export type {{ {} as {} }} from '{source}';",
            controller.global_name, controller.local_name
        ));
    }
    for name in &view.components {
        let component = components.get(name.as_str()).expect("validated component");
        match component.kind {
            ComponentKind::Model => lines.push(format!(
                "export type {{ {} as {} }} from '{source}';",
                component.global_name, component.local_name
            )),
            ComponentKind::Enum => lines.push(format!(
                "export {{ {} as {} }} from '{source}';",
                component.global_name, component.local_name
            )),
            ComponentKind::Exception => unreachable!("view components exclude exceptions"),
        }
    }
    Ok(vec![lines.join("\n")])
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
