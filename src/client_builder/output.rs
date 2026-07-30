use super::Result;
use std::{
    collections::HashSet,
    fs,
    io::{ErrorKind, Write},
    path::{Path, PathBuf},
};
use tempfile::NamedTempFile;

#[derive(Default)]
pub(super) struct OutputPlan {
    paths: HashSet<PathBuf>,
    writes: Vec<GeneratedFile>,
    removals: Vec<PathBuf>,
}

struct GeneratedFile {
    path: PathBuf,
    contents: String,
}

impl OutputPlan {
    pub(super) fn write(
        &mut self,
        path: impl Into<PathBuf>,
        contents: impl Into<String>,
    ) -> Result<()> {
        let path = path.into();
        self.reserve(&path)?;
        self.writes.push(GeneratedFile {
            path,
            contents: contents.into(),
        });
        Ok(())
    }

    pub(super) fn remove(&mut self, path: impl Into<PathBuf>) -> Result<()> {
        let path = path.into();
        self.reserve(&path)?;
        self.removals.push(path);
        Ok(())
    }

    pub(super) fn commit(self) -> Result<()> {
        let mut staged = Vec::with_capacity(self.writes.len());
        for generated in self.writes {
            let parent = generated.path.parent().ok_or_else(|| {
                format!("Generated path has no parent: {}", generated.path.display())
            })?;
            fs::create_dir_all(parent)?;
            let mut temporary = NamedTempFile::new_in(parent)?;
            temporary.write_all(generated.contents.as_bytes())?;
            temporary.flush()?;
            match fs::metadata(&generated.path) {
                Ok(metadata) => temporary
                    .as_file()
                    .set_permissions(metadata.permissions())?,
                Err(error) if error.kind() == ErrorKind::NotFound => {}
                Err(error) => return Err(error.into()),
            }
            staged.push((temporary, generated.path));
        }

        // ponytail: replacements are atomic per file; add a journal only if a
        // real cross-directory filesystem failure proves whole-tree rollback necessary.
        for (temporary, path) in staged {
            temporary.persist(path).map_err(|error| error.error)?;
        }
        for path in self.removals {
            if let Err(error) = fs::remove_file(path) {
                if error.kind() != ErrorKind::NotFound {
                    return Err(error.into());
                }
            }
        }
        Ok(())
    }

    fn reserve(&mut self, path: &Path) -> Result<()> {
        if self.paths.insert(path.to_path_buf()) {
            Ok(())
        } else {
            Err(format!("Multiple generated outputs target {}", path.display()).into())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn staging_failure_keeps_existing_outputs_unchanged() {
        let directory = tempfile::tempdir().unwrap();
        let existing = directory.path().join("existing.ts");
        let invalid_parent = directory.path().join("not-a-directory");
        fs::write(&existing, "existing").unwrap();
        fs::write(&invalid_parent, "file").unwrap();
        let mut output = OutputPlan::default();
        output.write(&existing, "replacement").unwrap();
        output
            .write(invalid_parent.join("generated.ts"), "generated")
            .unwrap();

        output.commit().unwrap_err();

        assert_eq!(fs::read_to_string(existing).unwrap(), "existing");
    }
}
