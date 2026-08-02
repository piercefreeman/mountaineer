mod manifest;
mod output;
mod typescript;

use std::error::Error;

pub type Result<T> = std::result::Result<T, Box<dyn Error + Send + Sync>>;

/// Validate and generate all managed client files from a Mountaineer envelope.
pub fn build(payload: &str) -> Result<()> {
    let envelope = manifest::Envelope::parse(payload)?;
    typescript::render(&envelope)?.commit()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Value};
    use std::{fs, thread, time::Duration};

    fn controller(name: &str) -> Value {
        json!({
            "global_name": name,
            "local_name": name,
            "parents": [],
            "actions": [],
        })
    }

    fn view(controller: &str, managed_dir: &str) -> Value {
        json!({
            "controller": controller,
            "server_key": controller,
            "link_name": controller,
            "managed_dir": managed_dir,
            "entrypoint_url": null,
            "is_layout": true,
            "render": null,
            "queries": [],
            "paths": [],
            "actions": [],
            "controllers": [],
            "components": [],
        })
    }

    #[test]
    fn invalid_manifest_does_not_touch_existing_output() {
        let directory = tempfile::tempdir().unwrap();
        let global_root = directory.path().join("global");
        fs::create_dir(&global_root).unwrap();
        fs::write(global_root.join("api.ts"), "existing").unwrap();
        let payload = json!({
            "schema_version": 1,
            "mountaineer_version": "test",
            "global_root": global_root,
            "components": [{
                "kind": "unknown",
                "global_name": "Broken",
                "local_name": "Broken",
                "schema": {},
                "status_code": null,
            }],
            "controllers": [],
            "views": [],
        });

        build(&payload.to_string()).unwrap_err();

        assert_eq!(
            fs::read_to_string(global_root.join("api.ts")).unwrap(),
            "existing"
        );
    }

    #[test]
    fn identical_build_does_not_rewrite_generated_files() {
        let directory = tempfile::tempdir().unwrap();
        let global_root = directory.path().join(".mountaineer");
        let payload = json!({
            "schema_version": 1,
            "mountaineer_version": "test",
            "global_root": global_root,
            "components": [],
            "controllers": [],
            "views": [],
        });

        build(&payload.to_string()).unwrap();
        let generated = global_root.join("api.ts");
        let first_modified = fs::metadata(&generated).unwrap().modified().unwrap();
        thread::sleep(Duration::from_millis(20));

        build(&payload.to_string()).unwrap();

        assert_eq!(
            fs::metadata(generated).unwrap().modified().unwrap(),
            first_modified
        );
    }

    #[test]
    fn missing_manifest_reference_does_not_touch_existing_output() {
        let directory = tempfile::tempdir().unwrap();
        let global_root = directory.path().join("global");
        fs::create_dir(&global_root).unwrap();
        fs::write(global_root.join("api.ts"), "existing").unwrap();
        let mut invalid_view = view("Home", directory.path().join("managed").to_str().unwrap());
        invalid_view["components"] = json!(["Missing"]);
        let payload = json!({
            "schema_version": 1,
            "mountaineer_version": "test",
            "global_root": global_root,
            "components": [],
            "controllers": [controller("Home")],
            "views": [invalid_view],
        });

        build(&payload.to_string()).unwrap_err();

        assert_eq!(
            fs::read_to_string(global_root.join("api.ts")).unwrap(),
            "existing"
        );
    }

    #[test]
    fn generated_type_collision_does_not_touch_existing_output() {
        let directory = tempfile::tempdir().unwrap();
        let global_root = directory.path().join("global");
        fs::create_dir(&global_root).unwrap();
        fs::write(global_root.join("api.ts"), "existing").unwrap();
        let payload = json!({
            "schema_version": 1,
            "mountaineer_version": "test",
            "global_root": global_root,
            "components": [{
                "kind": "model",
                "global_name": "Home",
                "local_name": "Home",
                "schema": {"type": "object"},
                "status_code": null,
            }],
            "controllers": [controller("Home")],
            "views": [],
        });

        build(&payload.to_string()).unwrap_err();

        assert_eq!(
            fs::read_to_string(global_root.join("api.ts")).unwrap(),
            "existing"
        );
    }

    #[test]
    fn render_failure_does_not_touch_existing_output() {
        let directory = tempfile::tempdir().unwrap();
        let global_root = directory.path().join("global");
        let managed_dir = directory.path().join("managed");
        fs::create_dir(&global_root).unwrap();
        fs::write(global_root.join("api.ts"), "existing").unwrap();
        let payload = json!({
            "schema_version": 1,
            "mountaineer_version": "test",
            "global_root": global_root,
            "components": [],
            "controllers": [controller("First"), controller("Second")],
            "views": [
                view("First", managed_dir.to_str().unwrap()),
                view("Second", managed_dir.to_str().unwrap()),
            ],
        });

        build(&payload.to_string()).unwrap_err();

        assert_eq!(
            fs::read_to_string(global_root.join("api.ts")).unwrap(),
            "existing"
        );
        assert!(!managed_dir.exists());
    }

    #[test]
    fn action_schema_references_are_imported() {
        let directory = tempfile::tempdir().unwrap();
        let global_root = directory.path().join("global");
        let managed_dir = directory.path().join("managed");
        let mut action_view = view("Home", managed_dir.to_str().unwrap());
        action_view["actions"] = json!([{
            "name": "search",
            "action_type": "render",
            "params": [{
                "name": "filter",
                "schema": {"$ref": "#/components/schemas/Filter"},
                "required": true,
            }],
            "headers": [],
            "request_body": null,
            "request_media_type": null,
            "responses": {"Home": null},
            "exceptions": [],
            "urls": {"Home": "/search"},
            "is_raw_response": false,
            "is_streaming_response": false,
        }]);
        let payload = json!({
            "schema_version": 1,
            "mountaineer_version": "test",
            "global_root": global_root,
            "components": [{
                "kind": "model",
                "global_name": "Filter",
                "local_name": "Filter",
                "schema": {"type": "object"},
                "status_code": null,
            }],
            "controllers": [controller("Home")],
            "views": [action_view],
        });

        build(&payload.to_string()).unwrap();

        let actions = fs::read_to_string(managed_dir.join("actions.ts")).unwrap();
        assert!(actions.contains("import type { Filter }"));
    }
}
