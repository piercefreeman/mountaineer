use super::{
    output::{status, Tone},
    Result,
};
use regex::Regex;
use std::{
    fs,
    io::{self, IsTerminal, Write},
    path::{Path, PathBuf},
};

const IGNORED_DIRECTORIES: &[&str] = &[
    ".git",
    ".mountaineer",
    ".mountaineer-vite",
    ".venv",
    "__pycache__",
    "node_modules",
];

pub(super) fn run(frontend_root: &Path) -> Result<()> {
    let files = legacy_imports(frontend_root)?;
    if files.is_empty() {
        return Ok(());
    }

    status(
        Tone::Warning,
        "Migration",
        format!(
            "found {} frontend {} importing from \"./_server\"",
            files.len(),
            if files.len() == 1 { "file" } else { "files" }
        ),
    );

    if !io::stdin().is_terminal() {
        status(
            Tone::Warning,
            "Skipped",
            "run interactively to migrate imports to \"./.mountaineer\"",
        );
        return Ok(());
    }

    eprint!("Automatically update these imports? [y/N] ");
    io::stderr().flush()?;
    let mut answer = String::new();
    io::stdin().read_line(&mut answer)?;
    if matches!(answer.trim().to_ascii_lowercase().as_str(), "y" | "yes") {
        migrate(&files)?;
        status(
            Tone::Accent,
            "Migrated",
            format!(
                "{} frontend {} to \"./.mountaineer\"",
                files.len(),
                if files.len() == 1 { "file" } else { "files" }
            ),
        );
    } else {
        status(Tone::Warning, "Skipped", "frontend import migration");
    }
    Ok(())
}

fn legacy_imports(root: &Path) -> Result<Vec<PathBuf>> {
    let pattern = import_pattern();
    let mut directories = vec![root.to_path_buf()];
    let mut files = Vec::new();

    while let Some(directory) = directories.pop() {
        for entry in fs::read_dir(directory)? {
            let entry = entry?;
            let path = entry.path();
            let file_type = entry.file_type()?;
            if file_type.is_dir() {
                if !path
                    .file_name()
                    .and_then(|name| name.to_str())
                    .is_some_and(|name| IGNORED_DIRECTORIES.contains(&name))
                {
                    directories.push(path);
                }
            } else if file_type.is_file() && is_frontend_file(&path) {
                let source = fs::read_to_string(&path)?;
                if pattern.is_match(&source) {
                    files.push(path);
                }
            }
        }
    }

    Ok(files)
}

fn migrate(files: &[PathBuf]) -> Result<()> {
    let pattern = import_pattern();
    for path in files {
        let source = fs::read_to_string(path)?;
        fs::write(
            path,
            pattern
                .replace_all(&source, "${prefix}${quote}./.mountaineer${suffix}${quote}")
                .as_bytes(),
        )?;
    }
    Ok(())
}

fn import_pattern() -> Regex {
    Regex::new(
        r#"(?P<prefix>\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*)(?P<quote>["'])\./_server(?P<suffix>(?:/[^"'\r\n]*)?)["']"#,
    )
    .expect("valid legacy import regex")
}

fn is_frontend_file(path: &Path) -> bool {
    matches!(
        path.extension().and_then(|extension| extension.to_str()),
        Some("js" | "jsx" | "ts" | "tsx" | "mjs" | "cjs")
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn migrates_frontend_imports_without_touching_dependencies_or_plain_strings() {
        let root = tempfile::tempdir().unwrap();
        let page = root.path().join("page.tsx");
        fs::write(
            &page,
            r#"import { useServer } from "./_server";
export { Model } from './_server/models';
const lazy = import("./_server/lazy");
const plainString = "./_server";
"#,
        )
        .unwrap();
        let dependency = root.path().join("node_modules/example/index.js");
        fs::create_dir_all(dependency.parent().unwrap()).unwrap();
        fs::write(&dependency, r#"export * from "./_server";"#).unwrap();

        let files = legacy_imports(root.path()).unwrap();
        assert_eq!(files.len(), 1);
        migrate(&files).unwrap();

        assert_eq!(
            fs::read_to_string(page).unwrap(),
            r#"import { useServer } from "./.mountaineer";
export { Model } from './.mountaineer/models';
const lazy = import("./.mountaineer/lazy");
const plainString = "./_server";
"#
        );
        assert_eq!(
            fs::read_to_string(dependency).unwrap(),
            r#"export * from "./_server";"#
        );
    }
}
