use super::MerkleDAG;
use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;

/// Snapshot metadata
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SnapshotMetadata {
    pub version: String,
    pub timestamp: DateTime<Utc>,
    pub file_count: usize,
    pub total_size: u64,
    pub root_hash: Option<String>,
}

/// Manages Merkle DAG snapshots on disk
pub struct SnapshotManager {
    storage_dir: PathBuf,
}

impl SnapshotManager {
    pub fn new(storage_dir: PathBuf) -> Self {
        Self { storage_dir }
    }

    /// Save a snapshot to disk
    pub fn save(&self, dag: &MerkleDAG) -> Result<()> {
        fs::create_dir_all(&self.storage_dir)
            .context("Failed to create snapshot directory")?;

        let snapshot_path = self.storage_dir.join("snapshot.json");
        let metadata_path = self.storage_dir.join("snapshot_metadata.json");

        // Save DAG
        let dag_json = serde_json::to_string_pretty(dag)
            .context("Failed to serialize DAG")?;
        fs::write(&snapshot_path, dag_json)
            .context("Failed to write snapshot")?;

        // Save metadata
        let metadata = SnapshotMetadata {
            version: "1.0".to_string(),
            timestamp: Utc::now(),
            file_count: dag.file_count,
            total_size: dag.total_size,
            root_hash: dag.get_root_hash().map(String::from),
        };
        let meta_json = serde_json::to_string_pretty(&metadata)
            .context("Failed to serialize metadata")?;
        fs::write(&metadata_path, meta_json)
            .context("Failed to write metadata")?;

        Ok(())
    }

    /// Load a snapshot from disk
    pub fn load(&self) -> Result<Option<MerkleDAG>> {
        let snapshot_path = self.storage_dir.join("snapshot.json");

        if !snapshot_path.exists() {
            return Ok(None);
        }

        let json = fs::read_to_string(&snapshot_path)
            .context("Failed to read snapshot")?;
        let mut dag: MerkleDAG = serde_json::from_str(&json)
            .context("Failed to deserialize snapshot")?;

        // Rebuild file_hashes cache (it's skipped in serde)
        dag.rebuild_cache();

        Ok(Some(dag))
    }

    /// Load snapshot metadata
    pub fn load_metadata(&self) -> Result<Option<SnapshotMetadata>> {
        let metadata_path = self.storage_dir.join("snapshot_metadata.json");

        if !metadata_path.exists() {
            return Ok(None);
        }

        let json = fs::read_to_string(&metadata_path)
            .context("Failed to read metadata")?;
        let metadata: SnapshotMetadata = serde_json::from_str(&json)
            .context("Failed to deserialize metadata")?;

        Ok(Some(metadata))
    }

    /// Check if a snapshot exists
    pub fn has_snapshot(&self) -> bool {
        self.storage_dir.join("snapshot.json").exists()
    }

    /// Delete snapshot files
    pub fn clear(&self) -> Result<()> {
        let snapshot_path = self.storage_dir.join("snapshot.json");
        let metadata_path = self.storage_dir.join("snapshot_metadata.json");

        if snapshot_path.exists() {
            fs::remove_file(&snapshot_path)?;
        }
        if metadata_path.exists() {
            fs::remove_file(&metadata_path)?;
        }

        Ok(())
    }

    /// Get the age of the snapshot in seconds
    pub fn snapshot_age_secs(&self) -> Option<i64> {
        self.load_metadata().ok().flatten().map(|m| {
            let now = Utc::now();
            (now - m.timestamp).num_seconds()
        })
    }
}

impl MerkleDAG {
    /// Rebuild the file_hashes cache after deserialization
    pub fn rebuild_cache(&mut self) {
        self.cache_file_hashes();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn test_snapshot_save_load() {
        let dir = TempDir::new().unwrap();
        let project_dir = TempDir::new().unwrap();

        fs::write(project_dir.path().join("file.txt"), "hello").unwrap();
        let dag = MerkleDAG::build(project_dir.path(), &[]).unwrap();

        let manager = SnapshotManager::new(dir.path().to_path_buf());
        manager.save(&dag).unwrap();

        assert!(manager.has_snapshot());

        let loaded = manager.load().unwrap().unwrap();
        assert_eq!(loaded.file_count, dag.file_count);
        assert_eq!(loaded.get_root_hash(), dag.get_root_hash());
        assert_eq!(loaded.get_all_files().len(), dag.get_all_files().len());
    }

    #[test]
    fn test_snapshot_metadata() {
        let dir = TempDir::new().unwrap();
        let project_dir = TempDir::new().unwrap();

        fs::write(project_dir.path().join("file.txt"), "hello").unwrap();
        let dag = MerkleDAG::build(project_dir.path(), &[]).unwrap();

        let manager = SnapshotManager::new(dir.path().to_path_buf());
        manager.save(&dag).unwrap();

        let metadata = manager.load_metadata().unwrap().unwrap();
        assert_eq!(metadata.version, "1.0");
        assert_eq!(metadata.file_count, 1);
    }

    #[test]
    fn test_snapshot_clear() {
        let dir = TempDir::new().unwrap();
        let project_dir = TempDir::new().unwrap();

        fs::write(project_dir.path().join("file.txt"), "hello").unwrap();
        let dag = MerkleDAG::build(project_dir.path(), &[]).unwrap();

        let manager = SnapshotManager::new(dir.path().to_path_buf());
        manager.save(&dag).unwrap();
        assert!(manager.has_snapshot());

        manager.clear().unwrap();
        assert!(!manager.has_snapshot());
    }
}
