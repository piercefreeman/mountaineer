use super::{invalid, Result};
use mountaineer_vite::{StyleBuildConfig, Stylesheet};
use std::{
    collections::BTreeSet,
    fs,
    path::{Component, PathBuf},
};

pub async fn build_frontend_styles(
    frontend_root: PathBuf,
    output_dir: PathBuf,
    styles: Vec<PathBuf>,
    minify: bool,
) -> Result<()> {
    if styles.is_empty() {
        return Ok(());
    }

    let frontend_root = frontend_root.canonicalize()?;
    fs::create_dir_all(&output_dir)?;
    let output_dir = output_dir.canonicalize()?;
    let mut names = BTreeSet::new();
    let styles = styles
        .into_iter()
        .map(|style| {
            let style = style.canonicalize()?;
            let relative = style.strip_prefix(&frontend_root).map_err(|_| {
                invalid(format!(
                    "stylesheet {} is outside frontend root {}",
                    style.display(),
                    frontend_root.display()
                ))
            })?;
            let name = relative
                .with_extension("")
                .components()
                .filter_map(|component| match component {
                    Component::Normal(part) => part.to_str(),
                    _ => None,
                })
                .collect::<Vec<_>>()
                .join("_");
            if name.is_empty() || !names.insert(name.clone()) {
                return Err(invalid(format!(
                    "stylesheet {} does not have a unique output name",
                    style.display()
                )));
            }
            Ok(Stylesheet { name, path: style })
        })
        .collect::<Result<Vec<_>>>()?;

    mountaineer_vite::build_styles(StyleBuildConfig {
        frontend_root,
        output_dir,
        styles,
        minify,
    })
    .await?;
    Ok(())
}
