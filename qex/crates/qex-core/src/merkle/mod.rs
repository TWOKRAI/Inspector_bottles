pub mod change_detector;
pub mod snapshot;

use anyhow::Result;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs;
use std::io::Read;
use std::path::Path;

/// A node in the Merkle DAG
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MerkleNode {
    pub path: String,
    pub hash: String,
    pub is_file: bool,
    pub size: u64,
    #[serde(default)]
    pub children: Vec<MerkleNode>,
}

/// Merkle DAG for directory tree hashing
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MerkleDAG {
    pub root_path: String,
    pub root_node: Option<MerkleNode>,
    pub file_count: usize,
    pub total_size: u64,
    #[serde(skip)]
    file_hashes: HashMap<String, String>,
}

impl MerkleDAG {
    /// Build a MerkleDAG from a directory
    pub fn build(root: &Path, ignored_dirs: &[&str]) -> Result<Self> {
        let root_path = root.to_string_lossy().to_string();
        let mut file_count = 0;
        let mut total_size = 0u64;

        let root_node = Self::build_node(root, root, ignored_dirs, &mut file_count, &mut total_size)?;

        let mut dag = Self {
            root_path,
            root_node: Some(root_node),
            file_count,
            total_size,
            file_hashes: HashMap::new(),
        };

        // Build file_hashes cache
        dag.cache_file_hashes();

        Ok(dag)
    }

    fn build_node(
        path: &Path,
        root: &Path,
        ignored_dirs: &[&str],
        file_count: &mut usize,
        total_size: &mut u64,
    ) -> Result<MerkleNode> {
        let relative = path
            .strip_prefix(root)
            .unwrap_or(path)
            .to_string_lossy()
            .to_string();

        if path.is_file() {
            let hash = hash_file(path)?;
            let size = fs::metadata(path).map(|m| m.len()).unwrap_or(0);
            *file_count += 1;
            *total_size += size;

            Ok(MerkleNode {
                path: relative,
                hash,
                is_file: true,
                size,
                children: Vec::new(),
            })
        } else if path.is_dir() {
            let mut children = Vec::new();

            let mut entries: Vec<_> = fs::read_dir(path)?
                .filter_map(|e| e.ok())
                .collect();
            entries.sort_by_key(|e| e.file_name());

            for entry in entries {
                let entry_path = entry.path();
                let name = entry.file_name().to_string_lossy().to_string();

                // Skip ignored directories
                if entry_path.is_dir() && ignored_dirs.contains(&name.as_str()) {
                    continue;
                }

                // Skip hidden files/dirs (except .gitignore etc.)
                if name.starts_with('.') && !matches!(name.as_str(), ".gitignore" | ".env.example") {
                    continue;
                }

                match Self::build_node(&entry_path, root, ignored_dirs, file_count, total_size) {
                    Ok(child) => children.push(child),
                    Err(_) => {
                        // Skip files we can't read (permissions, symlinks, etc.)
                        continue;
                    }
                }
            }

            // Directory hash = hash of (dir_name + sorted child hashes)
            let mut hasher = Sha256::new();
            hasher.update(relative.as_bytes());
            let mut child_hashes: Vec<&str> = children.iter().map(|c| c.hash.as_str()).collect();
            child_hashes.sort();
            for h in &child_hashes {
                hasher.update(h.as_bytes());
            }
            let hash = format!("{:x}", hasher.finalize());

            let size: u64 = children.iter().map(|c| c.size).sum();

            Ok(MerkleNode {
                path: relative,
                hash,
                is_file: false,
                size,
                children,
            })
        } else {
            // Symlink or special file — hash the path
            let hash = {
                let mut hasher = Sha256::new();
                hasher.update(relative.as_bytes());
                format!("{:x}", hasher.finalize())
            };
            Ok(MerkleNode {
                path: relative,
                hash,
                is_file: false,
                size: 0,
                children: Vec::new(),
            })
        }
    }

    fn cache_file_hashes(&mut self) {
        self.file_hashes.clear();
        if let Some(ref root) = self.root_node {
            Self::collect_file_hashes(root, &mut self.file_hashes);
        }
    }

    fn collect_file_hashes(node: &MerkleNode, map: &mut HashMap<String, String>) {
        if node.is_file {
            map.insert(node.path.clone(), node.hash.clone());
        }
        for child in &node.children {
            Self::collect_file_hashes(child, map);
        }
    }

    /// Get file path → hash mapping
    pub fn get_file_hashes(&self) -> &HashMap<String, String> {
        &self.file_hashes
    }

    /// Get all file paths
    pub fn get_all_files(&self) -> Vec<String> {
        self.file_hashes.keys().cloned().collect()
    }

    /// Get the root hash for quick comparison
    pub fn get_root_hash(&self) -> Option<&str> {
        self.root_node.as_ref().map(|n| n.hash.as_str())
    }
}

/// Hash a file using SHA-256 with 8KB buffered reading
fn hash_file(path: &Path) -> Result<String> {
    let mut file = fs::File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 8192];

    loop {
        let bytes_read = file.read(&mut buffer)?;
        if bytes_read == 0 {
            break;
        }
        hasher.update(&buffer[..bytes_read]);
    }

    Ok(format!("{:x}", hasher.finalize()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn test_build_merkle_dag() {
        let dir = TempDir::new().unwrap();
        let root = dir.path();

        fs::write(root.join("file1.txt"), "hello").unwrap();
        fs::write(root.join("file2.txt"), "world").unwrap();
        fs::create_dir_all(root.join("sub")).unwrap();
        fs::write(root.join("sub/file3.txt"), "nested").unwrap();

        let dag = MerkleDAG::build(root, &["node_modules", ".git"]).unwrap();

        assert_eq!(dag.file_count, 3);
        assert!(dag.get_root_hash().is_some());

        let files = dag.get_all_files();
        assert_eq!(files.len(), 3);
    }

    #[test]
    fn test_merkle_dag_detects_change() {
        let dir = TempDir::new().unwrap();
        let root = dir.path();

        fs::write(root.join("file.txt"), "original").unwrap();
        let dag1 = MerkleDAG::build(root, &[]).unwrap();

        fs::write(root.join("file.txt"), "modified").unwrap();
        let dag2 = MerkleDAG::build(root, &[]).unwrap();

        assert_ne!(dag1.get_root_hash(), dag2.get_root_hash());
    }

    #[test]
    fn test_merkle_dag_same_content() {
        let dir = TempDir::new().unwrap();
        let root = dir.path();

        fs::write(root.join("file.txt"), "same content").unwrap();
        let dag1 = MerkleDAG::build(root, &[]).unwrap();
        let dag2 = MerkleDAG::build(root, &[]).unwrap();

        assert_eq!(dag1.get_root_hash(), dag2.get_root_hash());
    }
}
