use crate::index::IndexResult;
use anyhow::{Context, Result};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

/// Manages storage layout for a project's index data
///
/// Layout:
/// ```text
/// ~/.qex/projects/{project_name}_{hash8}/
///   ├── project_info.json
///   ├── tantivy/           # BM25 index
///   ├── snapshot.json      # Merkle DAG
///   ├── snapshot_metadata.json
///   └── stats.json
/// ```
pub struct ProjectStorage {
    base_dir: PathBuf,
}

impl ProjectStorage {
    /// Create storage for a project path
    pub fn for_project(project_path: &Path) -> Result<Self> {
        let normalized = project_path
            .canonicalize()
            .unwrap_or_else(|_| project_path.to_path_buf());
        let path_str = normalized.to_string_lossy();

        // Project name from directory
        let project_name = normalized
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("unknown");

        // Hash for uniqueness
        let hash = {
            let mut hasher = Sha256::new();
            hasher.update(path_str.as_bytes());
            format!("{:x}", hasher.finalize())[..8].to_string()
        };

        let dir_name = format!("{}_{}", sanitize_name(project_name), hash);

        let base_dir = qex_home()?.join("projects").join(dir_name);
        fs::create_dir_all(&base_dir)
            .context("Failed to create project storage directory")?;

        // Write project info
        let info_path = base_dir.join("project_info.json");
        if !info_path.exists() {
            let info = serde_json::json!({
                "project_path": path_str.as_ref(),
                "project_name": project_name,
            });
            fs::write(&info_path, serde_json::to_string_pretty(&info)?)?;
        }

        Ok(Self { base_dir })
    }

    pub fn base_dir(&self) -> &Path {
        &self.base_dir
    }

    pub fn tantivy_dir(&self) -> PathBuf {
        self.base_dir.join("tantivy")
    }

    pub fn dense_dir(&self) -> PathBuf {
        self.base_dir.join("dense")
    }

    /// Check if an index exists
    pub fn has_index(&self) -> bool {
        self.tantivy_dir().join("meta.json").exists()
    }

    /// Save index stats
    pub fn save_stats(&self, result: &IndexResult) -> Result<()> {
        let stats_path = self.base_dir.join("stats.json");
        let json = serde_json::to_string_pretty(result)?;
        fs::write(stats_path, json)?;
        Ok(())
    }

    /// Load index stats
    pub fn load_stats(&self) -> Result<Option<IndexResult>> {
        let stats_path = self.base_dir.join("stats.json");
        if !stats_path.exists() {
            return Ok(None);
        }
        let json = fs::read_to_string(stats_path)?;
        let stats: IndexResult = serde_json::from_str(&json)?;
        Ok(Some(stats))
    }

    /// Clear snapshot and stats (keeps tantivy index)
    pub fn clear(&self) -> Result<()> {
        let snapshot = self.base_dir.join("snapshot.json");
        let metadata = self.base_dir.join("snapshot_metadata.json");
        let stats = self.base_dir.join("stats.json");

        for path in [snapshot, metadata, stats] {
            if path.exists() {
                fs::remove_file(path)?;
            }
        }
        Ok(())
    }

    /// Clear everything including tantivy index
    pub fn clear_all(&self) -> Result<()> {
        if self.base_dir.exists() {
            fs::remove_dir_all(&self.base_dir)?;
        }
        Ok(())
    }
}

/// Get the qex home directory
fn qex_home() -> Result<PathBuf> {
    let home = dirs::home_dir().context("Could not determine home directory")?;
    Ok(home.join(".qex"))
}

/// Sanitize a project name for use in filesystem paths
fn sanitize_name(name: &str) -> String {
    name.chars()
        .map(|c| if c.is_alphanumeric() || c == '-' || c == '_' { c } else { '_' })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_project_storage_creation() {
        let dir = TempDir::new().unwrap();
        let storage = ProjectStorage::for_project(dir.path()).unwrap();
        assert!(storage.base_dir().exists());
        assert!(storage.base_dir().join("project_info.json").exists());
    }

    #[test]
    fn test_sanitize_name() {
        assert_eq!(sanitize_name("my-project"), "my-project");
        assert_eq!(sanitize_name("my project!"), "my_project_");
        assert_eq!(sanitize_name("code_context"), "code_context");
    }
}
