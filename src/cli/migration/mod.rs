mod frontend_imports;

use self::frontend_imports::FrontendImportMigration;
use super::{
    output::{status, Tone},
    Result,
};
use std::{
    io::{self, IsTerminal, Write},
    path::{Path, PathBuf},
};

trait Migration {
    fn name(&self) -> &'static str;
    fn description(&self) -> &'static str;
    fn scan(&self, root: &Path) -> Result<Vec<PathBuf>>;
    fn apply(&self, files: &[PathBuf]) -> Result<()>;
}

pub(super) fn run(root: &Path) -> Result<()> {
    let migrations: &[&dyn Migration] = &[&FrontendImportMigration];
    for &migration in migrations {
        run_one(migration, root)?;
    }
    Ok(())
}

fn run_one(migration: &dyn Migration, root: &Path) -> Result<()> {
    let files = migration.scan(root)?;
    if files.is_empty() {
        return Ok(());
    }
    let noun = if files.len() == 1 { "file" } else { "files" };

    status(
        Tone::Warning,
        "Migration",
        format!(
            "{}: {} ({} {noun})",
            migration.name(),
            migration.description(),
            files.len()
        ),
    );

    if !io::stdin().is_terminal() {
        status(
            Tone::Warning,
            "Skipped",
            format!("run interactively to apply {}", migration.name()),
        );
        return Ok(());
    }

    eprint!("Apply this migration? [y/N] ");
    io::stderr().flush()?;
    let mut answer = String::new();
    io::stdin().read_line(&mut answer)?;
    if matches!(answer.trim().to_ascii_lowercase().as_str(), "y" | "yes") {
        migration.apply(&files)?;
        status(
            Tone::Accent,
            "Migrated",
            format!("{} in {} {noun}", migration.name(), files.len()),
        );
    } else {
        status(Tone::Warning, "Skipped", migration.name());
    }
    Ok(())
}
