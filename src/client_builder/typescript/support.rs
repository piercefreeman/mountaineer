use super::super::Result;
use std::path::{Component, Path, PathBuf};

pub(super) fn destructured<'a>(names: impl Iterator<Item = &'a str>) -> String {
    let body = names
        .map(|name| format!("  {name}"))
        .collect::<Vec<_>>()
        .join(",\n");
    format!("{{\n{body}\n}}")
}

pub(super) fn shorthand_object<'a>(names: impl Iterator<Item = &'a str>) -> String {
    let body = names
        .map(|name| format!("  {name}"))
        .collect::<Vec<_>>()
        .join(",\n");
    format!("{{\n{body}\n}}")
}

pub(super) fn sorted<'a>(values: impl IntoIterator<Item = &'a str>) -> Vec<&'a str> {
    let mut values = values.into_iter().collect::<Vec<_>>();
    values.sort_unstable();
    values
}

pub(super) fn import_path(from_file: &Path, to_file: &Path) -> Result<String> {
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
