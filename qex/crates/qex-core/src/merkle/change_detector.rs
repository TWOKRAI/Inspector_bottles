use super::MerkleDAG;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

/// Represents changes detected between two Merkle DAGs
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FileChanges {
    pub added: Vec<String>,
    pub removed: Vec<String>,
    pub modified: Vec<String>,
    pub unchanged: Vec<String>,
}

impl FileChanges {
    pub fn has_changes(&self) -> bool {
        !self.added.is_empty() || !self.removed.is_empty() || !self.modified.is_empty()
    }

    pub fn total_changed(&self) -> usize {
        self.added.len() + self.removed.len() + self.modified.len()
    }
}

/// Detects changes between two Merkle DAGs
pub struct ChangeDetector;

impl ChangeDetector {
    /// Detect file-level changes between old and new DAGs
    pub fn detect_changes(old_dag: &MerkleDAG, new_dag: &MerkleDAG) -> FileChanges {
        let old_files = old_dag.get_file_hashes();
        let new_files = new_dag.get_file_hashes();

        let old_paths: HashSet<&String> = old_files.keys().collect();
        let new_paths: HashSet<&String> = new_files.keys().collect();

        let added: Vec<String> = new_paths
            .difference(&old_paths)
            .map(|p| (*p).clone())
            .collect();

        let removed: Vec<String> = old_paths
            .difference(&new_paths)
            .map(|p| (*p).clone())
            .collect();

        let mut modified = Vec::new();
        let mut unchanged = Vec::new();

        for path in old_paths.intersection(&new_paths) {
            if old_files[*path] != new_files[*path] {
                modified.push((*path).clone());
            } else {
                unchanged.push((*path).clone());
            }
        }

        FileChanges {
            added,
            removed,
            modified,
            unchanged,
        }
    }

    /// Quick check if anything changed using root hash comparison
    pub fn has_changes(old_dag: &MerkleDAG, new_dag: &MerkleDAG) -> bool {
        old_dag.get_root_hash() != new_dag.get_root_hash()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::Path;
    use tempfile::TempDir;

    fn build_dag(root: &Path) -> MerkleDAG {
        MerkleDAG::build(root, &["node_modules", ".git"]).unwrap()
    }

    #[test]
    fn test_detect_no_changes() {
        let dir = TempDir::new().unwrap();
        fs::write(dir.path().join("file.txt"), "hello").unwrap();

        let dag1 = build_dag(dir.path());
        let dag2 = build_dag(dir.path());

        let changes = ChangeDetector::detect_changes(&dag1, &dag2);
        assert!(!changes.has_changes());
        assert_eq!(changes.unchanged.len(), 1);
    }

    #[test]
    fn test_detect_added_file() {
        let dir = TempDir::new().unwrap();
        fs::write(dir.path().join("file1.txt"), "hello").unwrap();
        let dag1 = build_dag(dir.path());

        fs::write(dir.path().join("file2.txt"), "world").unwrap();
        let dag2 = build_dag(dir.path());

        let changes = ChangeDetector::detect_changes(&dag1, &dag2);
        assert!(changes.has_changes());
        assert_eq!(changes.added.len(), 1);
        assert!(changes.added[0].contains("file2.txt"));
    }

    #[test]
    fn test_detect_removed_file() {
        let dir = TempDir::new().unwrap();
        fs::write(dir.path().join("file1.txt"), "hello").unwrap();
        fs::write(dir.path().join("file2.txt"), "world").unwrap();
        let dag1 = build_dag(dir.path());

        fs::remove_file(dir.path().join("file2.txt")).unwrap();
        let dag2 = build_dag(dir.path());

        let changes = ChangeDetector::detect_changes(&dag1, &dag2);
        assert!(changes.has_changes());
        assert_eq!(changes.removed.len(), 1);
    }

    #[test]
    fn test_detect_modified_file() {
        let dir = TempDir::new().unwrap();
        fs::write(dir.path().join("file.txt"), "original").unwrap();
        let dag1 = build_dag(dir.path());

        fs::write(dir.path().join("file.txt"), "modified").unwrap();
        let dag2 = build_dag(dir.path());

        let changes = ChangeDetector::detect_changes(&dag1, &dag2);
        assert!(changes.has_changes());
        assert_eq!(changes.modified.len(), 1);
    }

    #[test]
    fn test_quick_change_check() {
        let dir = TempDir::new().unwrap();
        fs::write(dir.path().join("file.txt"), "hello").unwrap();

        let dag1 = build_dag(dir.path());
        let dag2 = build_dag(dir.path());
        assert!(!ChangeDetector::has_changes(&dag1, &dag2));

        fs::write(dir.path().join("file.txt"), "changed").unwrap();
        let dag3 = build_dag(dir.path());
        assert!(ChangeDetector::has_changes(&dag1, &dag3));
    }
}
