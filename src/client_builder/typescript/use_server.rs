use super::super::{
    manifest::{ActionType, View},
    Result,
};
use super::support::import_path;
use std::path::Path;

pub(super) fn local_use_server(view: &View, global_root: &Path) -> Result<Vec<String>> {
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
        match action.action_type {
            ActionType::SideEffect => {
                let wrapper = format!("{}WithSideEffect", action.name);
                wrappers.push(format!(
                    "  const {wrapper} = useMemo(\n    () => applySideEffect({}, setControllerState),\n    [setControllerState],\n  );",
                    action.name
                ));
                response.push(format!("    {}: {wrapper}", action.name));
                dependencies.push(wrapper);
            }
            ActionType::Passthrough | ActionType::Render => {
                response.push(format!("    {}: {}", action.name, action.name));
            }
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
