//! Dense vector search using usearch HNSW index.
//!
//! Only compiled when the `dense` feature is enabled.

use crate::chunk::CodeChunk;
use crate::search::embedding::Embedder;
use anyhow::{Context, Result};
use std::collections::HashMap;
use std::path::Path;
use tracing::{debug, info};
use usearch::{Index, IndexOptions, MetricKind, ScalarKind};

/// Batch size for embedding chunks. Balances memory vs. throughput.
/// (64 caused ~4.6 GB RAM usage with arctic-embed-s)
const EMBED_BATCH_SIZE: usize = 8;

/// Dense vector search index backed by usearch HNSW
pub struct DenseIndex {
    index: Index,
    /// Mapping from usearch u64 key to chunk_id string
    key_to_chunk_id: HashMap<u64, String>,
    /// Reverse mapping from chunk_id to usearch key
    chunk_id_to_key: HashMap<String, u64>,
    /// Mapping from file_path to chunk_ids (for incremental removal)
    file_to_chunks: HashMap<String, Vec<String>>,
    /// Next available key
    next_key: u64,
    dimensions: usize,
}

impl DenseIndex {
    /// Create a new empty dense index
    pub fn new(dimensions: usize) -> Result<Self> {
        let options = IndexOptions {
            dimensions,
            metric: MetricKind::Cos,
            quantization: ScalarKind::F32,
            ..Default::default()
        };

        let index = Index::new(&options)
            .map_err(|e| anyhow::anyhow!("Failed to create usearch index: {}", e))?;

        Ok(Self {
            index,
            key_to_chunk_id: HashMap::new(),
            chunk_id_to_key: HashMap::new(),
            file_to_chunks: HashMap::new(),
            next_key: 0,
            dimensions,
        })
    }

    /// Open or create a dense index from a directory
    pub fn open(index_dir: &Path, dimensions: usize) -> Result<Self> {
        let index_path = index_dir.join("dense.usearch");
        let mapping_path = index_dir.join("dense_mapping.json");

        let mut dense = Self::new(dimensions)?;

        if index_path.exists() && mapping_path.exists() {
            // Load existing index
            let path_str = index_path
                .to_str()
                .context("Dense index path contains non-UTF-8 characters")?;
            dense
                .index
                .load(path_str)
                .map_err(|e| anyhow::anyhow!("Failed to load usearch index: {}", e))?;

            // Load key mappings: Vec<(key, chunk_id, file_path)>
            let mapping_data = std::fs::read_to_string(&mapping_path)
                .context("Failed to read dense mapping file")?;

            // Try new format first (with file_path), fall back to legacy
            if let Ok(mappings) = serde_json::from_str::<Vec<(u64, String, String)>>(&mapping_data) {
                for (key, chunk_id, file_path) in mappings {
                    dense.key_to_chunk_id.insert(key, chunk_id.clone());
                    dense.chunk_id_to_key.insert(chunk_id.clone(), key);
                    dense.file_to_chunks.entry(file_path).or_default().push(chunk_id);
                    if key >= dense.next_key {
                        dense.next_key = key + 1;
                    }
                }
            } else if let Ok(mappings) = serde_json::from_str::<Vec<(u64, String)>>(&mapping_data) {
                // Legacy format without file_path
                for (key, chunk_id) in mappings {
                    dense.key_to_chunk_id.insert(key, chunk_id.clone());
                    dense.chunk_id_to_key.insert(chunk_id, key);
                    if key >= dense.next_key {
                        dense.next_key = key + 1;
                    }
                }
            } else {
                anyhow::bail!(
                    "Failed to parse dense_mapping.json: file is corrupt or in unknown format"
                );
            }

            info!(
                "Loaded dense index: {} vectors",
                dense.key_to_chunk_id.len()
            );
        }

        Ok(dense)
    }

    /// Save the index to disk
    pub fn save(&self, index_dir: &Path) -> Result<()> {
        std::fs::create_dir_all(index_dir)?;

        let index_path = index_dir.join("dense.usearch");
        let mapping_path = index_dir.join("dense_mapping.json");

        let path_str = index_path
            .to_str()
            .context("Dense index path contains non-UTF-8 characters")?;
        self.index
            .save(path_str)
            .map_err(|e| anyhow::anyhow!("Failed to save usearch index: {}", e))?;

        // Save key mappings with file_path info
        // Build reverse lookup: chunk_id -> file_path
        let chunk_to_file: HashMap<&str, &str> = self.file_to_chunks.iter()
            .flat_map(|(file, chunks)| chunks.iter().map(move |c| (c.as_str(), file.as_str())))
            .collect();

        let mappings: Vec<(&u64, &String, &str)> = self.key_to_chunk_id.iter()
            .map(|(k, c)| (k, c, chunk_to_file.get(c.as_str()).copied().unwrap_or("")))
            .collect();
        let json = serde_json::to_string(&mappings)?;
        // Atomic write: write to temp file then rename to avoid corruption on crash
        let tmp_path = mapping_path.with_extension("json.tmp");
        std::fs::write(&tmp_path, &json)?;
        std::fs::rename(&tmp_path, &mapping_path)?;

        debug!("Saved dense index: {} vectors", self.key_to_chunk_id.len());
        Ok(())
    }

    /// Add chunks to the index by embedding them with the model
    pub fn add_chunks(&mut self, chunks: &[CodeChunk], model: &mut dyn Embedder) -> Result<usize> {
        if chunks.is_empty() {
            return Ok(0);
        }

        // Reserve space
        let current_size = self.key_to_chunk_id.len();
        self.index
            .reserve(current_size + chunks.len())
            .map_err(|e| anyhow::anyhow!("Failed to reserve index space: {}", e))?;

        let batch_size = EMBED_BATCH_SIZE;
        let mut added = 0;
        let total = chunks.len();

        for (batch_idx, batch) in chunks.chunks(batch_size).enumerate() {
            debug!(
                "Embedding batch {}/{} ({} chunks done)",
                batch_idx + 1,
                (total + batch_size - 1) / batch_size,
                added
            );
            // Prepare texts: use name + content for richer embedding
            let texts: Vec<String> = batch
                .iter()
                .map(|chunk| {
                    let mut text = String::new();
                    if let Some(name) = &chunk.name {
                        text.push_str(name);
                        text.push(' ');
                    }
                    if let Some(doc) = &chunk.docstring {
                        text.push_str(doc);
                        text.push(' ');
                    }
                    text.push_str(&chunk.content);
                    // Truncate to ~1000 chars — enough for signatures + initial logic
                    if text.len() > 1000 {
                        let mut end = 1000;
                        while !text.is_char_boundary(end) {
                            end -= 1;
                        }
                        text.truncate(end);
                    }
                    text
                })
                .collect();

            let text_refs: Vec<&str> = texts.iter().map(|s| s.as_str()).collect();
            let embeddings = model.encode_batch(&text_refs)?;

            for (chunk, embedding) in batch.iter().zip(embeddings.iter()) {
                let key = self.next_key;
                self.next_key += 1;

                self.index
                    .add(key, embedding)
                    .map_err(|e| anyhow::anyhow!("Failed to add vector: {}", e))?;

                self.key_to_chunk_id.insert(key, chunk.id.clone());
                self.chunk_id_to_key.insert(chunk.id.clone(), key);
                self.file_to_chunks
                    .entry(chunk.file_path.clone())
                    .or_default()
                    .push(chunk.id.clone());
                added += 1;
            }
        }

        Ok(added)
    }

    /// Search for nearest neighbors of a query vector
    pub fn search(&self, query_vec: &[f32], k: usize) -> Result<Vec<(String, f32)>> {
        if self.key_to_chunk_id.is_empty() {
            return Ok(Vec::new());
        }

        let results = self
            .index
            .search(query_vec, k)
            .map_err(|e| anyhow::anyhow!("Dense search failed: {}", e))?;

        let mut matches = Vec::new();
        for (key, distance) in results.keys.iter().zip(results.distances.iter()) {
            if let Some(chunk_id) = self.key_to_chunk_id.get(key) {
                // Convert cosine distance to similarity score
                let similarity = 1.0 - distance;
                matches.push((chunk_id.clone(), similarity));
            }
        }

        Ok(matches)
    }

    /// Remove all chunks belonging to a file path
    pub fn remove_file(&mut self, file_path: &str) {
        if let Some(chunk_ids) = self.file_to_chunks.remove(file_path) {
            for chunk_id in &chunk_ids {
                if let Some(key) = self.chunk_id_to_key.remove(chunk_id) {
                    let _ = self.index.remove(key);
                    self.key_to_chunk_id.remove(&key);
                }
            }
            debug!("Removed {} vectors for file {}", chunk_ids.len(), file_path);
        }
    }

    /// Clear the entire index
    pub fn clear(&mut self) -> Result<()> {
        // Recreate the index
        *self = Self::new(self.dimensions)?;
        Ok(())
    }

    /// Number of vectors in the index
    pub fn len(&self) -> usize {
        self.key_to_chunk_id.len()
    }

    /// Check if index is empty
    pub fn is_empty(&self) -> bool {
        self.key_to_chunk_id.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::search::embedding::EmbeddingModel;

    #[test]
    fn test_dense_index_basic() {
        let index = DenseIndex::new(384).unwrap();
        assert_eq!(index.len(), 0);
        assert!(index.is_empty());
    }

    #[test]
    fn test_dense_index_add_and_search() {
        let model_dir = EmbeddingModel::default_model_dir().unwrap();
        if !model_dir.join("model.onnx").exists() {
            eprintln!("Skipping test: model not downloaded");
            return;
        }

        let mut model = EmbeddingModel::load(&model_dir).unwrap();
        let mut index = DenseIndex::new(model.info().dimensions).unwrap();

        // Create test chunks
        let chunks = vec![
            CodeChunk {
                id: "auth_1".to_string(),
                content: "def authenticate_user(username, password):\n    return check_credentials(username, password)".to_string(),
                chunk_type: crate::chunk::ChunkType::Function,
                start_line: 1, end_line: 2,
                file_path: "/test/auth.py".to_string(),
                relative_path: "auth.py".to_string(),
                folder_structure: Vec::new(),
                name: Some("authenticate_user".to_string()),
                parent_name: None,
                language: "python".to_string(),
                docstring: Some("Authenticate a user with credentials".to_string()),
                decorators: Vec::new(),
                imports: Vec::new(),
                tags: Vec::new(),
                complexity_score: 3,
            },
            CodeChunk {
                id: "db_1".to_string(),
                content: "class DatabasePool:\n    def get_connection(self):\n        return self.pool.acquire()".to_string(),
                chunk_type: crate::chunk::ChunkType::Class,
                start_line: 1, end_line: 3,
                file_path: "/test/db.py".to_string(),
                relative_path: "db.py".to_string(),
                folder_structure: Vec::new(),
                name: Some("DatabasePool".to_string()),
                parent_name: None,
                language: "python".to_string(),
                docstring: Some("Connection pool for database".to_string()),
                decorators: Vec::new(),
                imports: Vec::new(),
                tags: Vec::new(),
                complexity_score: 5,
            },
        ];

        let added = index.add_chunks(&chunks, &mut model).unwrap();
        assert_eq!(added, 2);
        assert_eq!(index.len(), 2);

        // Search for authentication-related code
        let query_vec = model.encode_query("user login authentication").unwrap();
        let results = index.search(&query_vec, 2).unwrap();
        assert_eq!(results.len(), 2);

        // auth chunk should be more relevant
        assert_eq!(results[0].0, "auth_1", "Auth chunk should be top result");

        // Test file removal
        index.remove_file("/test/auth.py");
        assert_eq!(index.len(), 1);

        // Only db chunk should remain
        let results2 = index.search(&query_vec, 2).unwrap();
        assert_eq!(results2.len(), 1);
        assert_eq!(results2[0].0, "db_1");
    }
}
