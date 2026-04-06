pub mod storage;

use crate::chunk::multi_language::MultiLanguageChunker;
use crate::ignore::walk_files;
use crate::merkle::change_detector::ChangeDetector;
use crate::merkle::snapshot::SnapshotManager;
use crate::merkle::MerkleDAG;
use crate::search::bm25::BM25Index;
use crate::search::query::analyze_query;
use crate::search::ranking::rank_results;
use crate::search::SearchResult;
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::path::Path;
use std::time::Instant;
use storage::ProjectStorage;
use tracing::{debug, info, warn};

#[cfg(feature = "dense")]
use crate::search::dense::DenseIndex;
#[cfg(feature = "dense")]
use crate::search::hybrid::reciprocal_rank_fusion;
#[cfg(feature = "dense")]
use std::collections::HashMap;

/// Default ignored directories for Merkle DAG building
const MERKLE_IGNORE_DIRS: &[&str] = &[
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "target",
    "build",
    "dist",
    ".next",
    ".cache",
    ".qex",
];

/// Maximum snapshot age before triggering re-index (seconds)
const MAX_SNAPSHOT_AGE_SECS: i64 = 300; // 5 minutes

/// Result of an indexing operation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndexResult {
    pub files_indexed: usize,
    pub chunks_created: usize,
    pub time_taken_ms: u64,
    pub languages: Vec<String>,
    pub incremental: bool,
    pub files_added: usize,
    pub files_removed: usize,
    pub files_modified: usize,
}

/// Indexing status for a project
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndexStatus {
    pub indexed: bool,
    pub file_count: usize,
    pub chunk_count: usize,
    pub last_indexed: Option<String>,
    pub languages: Vec<String>,
}

/// Incremental indexer that manages the full indexing pipeline
pub struct IncrementalIndexer {
    chunker: MultiLanguageChunker,
}

impl IncrementalIndexer {
    pub fn new() -> Self {
        Self {
            chunker: MultiLanguageChunker::new(),
        }
    }

    /// Perform a full index of a project directory
    pub fn full_index(
        &self,
        project_path: &Path,
        extensions: Option<&[&str]>,
    ) -> Result<IndexResult> {
        let start = Instant::now();
        let storage = ProjectStorage::for_project(project_path)?;

        info!("Starting full index of {}", project_path.display());

        // Clear existing index
        if let Ok(bm25) = BM25Index::open(&storage.tantivy_dir()) {
            let _ = bm25.clear();
        }
        storage.clear()?;

        // Build Merkle DAG
        let dag = MerkleDAG::build(project_path, MERKLE_IGNORE_DIRS)
            .context("Failed to build Merkle DAG")?;

        // Walk files
        let files = walk_files(project_path, extensions);
        let supported_files: Vec<(String, String)> = files
            .into_iter()
            .filter(|(abs, _)| self.chunker.is_supported(abs))
            .collect();

        info!("Found {} supported files", supported_files.len());

        // Chunk all files in parallel
        let chunk_results = self.chunker.chunk_files(&supported_files);
        let mut all_chunks = Vec::new();
        let mut languages = HashSet::new();
        let mut error_count = 0;

        for (rel_path, result) in chunk_results {
            match result {
                Ok(chunks) => {
                    for chunk in &chunks {
                        languages.insert(chunk.language.clone());
                    }
                    all_chunks.extend(chunks);
                }
                Err(e) => {
                    debug!("Failed to chunk {}: {}", rel_path, e);
                    error_count += 1;
                }
            }
        }

        if error_count > 0 {
            warn!("{} files failed to chunk", error_count);
        }

        // Index chunks in BM25
        let bm25 = BM25Index::open(&storage.tantivy_dir())
            .context("Failed to open BM25 index")?;
        let chunk_count = bm25.add_chunks(&all_chunks)
            .context("Failed to add chunks to BM25 index")?;

        // Dense vector indexing (if embedder available)
        #[cfg(feature = "dense")]
        {
            if let Ok(mut embedder) = Self::load_embedder() {
                info!("Dense search enabled — embedding {} chunks", all_chunks.len());
                let dims = embedder.info().dimensions;
                let mut dense = DenseIndex::new(dims)?;
                dense.add_chunks(&all_chunks, embedder.as_mut())?;
                dense.save(&storage.dense_dir())?;
                Self::save_dense_meta(&storage, &embedder.info())?;
                info!("Dense index saved: {} vectors", dense.len());
            }
        }

        // Save snapshot
        let snapshot_manager = SnapshotManager::new(storage.base_dir().to_path_buf());
        snapshot_manager.save(&dag)?;

        // Save stats
        let mut lang_list: Vec<String> = languages.into_iter().collect();
        lang_list.sort();

        let elapsed = start.elapsed();

        let result = IndexResult {
            files_indexed: supported_files.len(),
            chunks_created: chunk_count,
            time_taken_ms: elapsed.as_millis() as u64,
            languages: lang_list,
            incremental: false,
            files_added: supported_files.len(),
            files_removed: 0,
            files_modified: 0,
        };

        storage.save_stats(&result)?;

        info!(
            "Full index complete: {} files, {} chunks in {}ms",
            result.files_indexed, result.chunks_created, result.time_taken_ms
        );

        Ok(result)
    }

    /// Perform an incremental index update
    pub fn incremental_index(
        &self,
        project_path: &Path,
        extensions: Option<&[&str]>,
    ) -> Result<IndexResult> {
        let start = Instant::now();
        let storage = ProjectStorage::for_project(project_path)?;
        let snapshot_manager = SnapshotManager::new(storage.base_dir().to_path_buf());

        // Load previous snapshot
        let old_dag = match snapshot_manager.load()? {
            Some(dag) => dag,
            None => {
                info!("No previous snapshot found, performing full index");
                return self.full_index(project_path, extensions);
            }
        };

        // Build current DAG
        let new_dag = MerkleDAG::build(project_path, MERKLE_IGNORE_DIRS)?;

        // Quick check
        if !ChangeDetector::has_changes(&old_dag, &new_dag) {
            info!("No changes detected, skipping index update");
            return Ok(IndexResult {
                files_indexed: 0,
                chunks_created: 0,
                time_taken_ms: start.elapsed().as_millis() as u64,
                languages: Vec::new(),
                incremental: true,
                files_added: 0,
                files_removed: 0,
                files_modified: 0,
            });
        }

        // Detect changes
        let changes = ChangeDetector::detect_changes(&old_dag, &new_dag);
        info!(
            "Detected changes: {} added, {} removed, {} modified",
            changes.added.len(),
            changes.removed.len(),
            changes.modified.len()
        );

        let bm25 = BM25Index::open(&storage.tantivy_dir())?;

        // Remove old chunks for removed and modified files
        let files_to_remove: Vec<&String> = changes
            .removed
            .iter()
            .chain(changes.modified.iter())
            .collect();

        for rel_path in &files_to_remove {
            let abs_path = project_path.join(rel_path);
            let _ = bm25.remove_file(&abs_path.to_string_lossy());
        }

        // Chunk and index new/modified files
        let files_to_add: Vec<(String, String)> = changes
            .added
            .iter()
            .chain(changes.modified.iter())
            .map(|rel| {
                let abs = project_path.join(rel).to_string_lossy().to_string();
                (abs, rel.clone())
            })
            .filter(|(abs, _)| self.chunker.is_supported(abs))
            .collect();

        let chunk_results = self.chunker.chunk_files(&files_to_add);
        let mut all_chunks = Vec::new();
        let mut languages = HashSet::new();

        for (_rel_path, result) in chunk_results {
            if let Ok(chunks) = result {
                for chunk in &chunks {
                    languages.insert(chunk.language.clone());
                }
                all_chunks.extend(chunks);
            }
        }

        let chunk_count = bm25.add_chunks(&all_chunks)?;

        // Dense vector indexing (if embedder available)
        #[cfg(feature = "dense")]
        {
            if let Ok(mut embedder) = Self::load_embedder() {
                let info = embedder.info();
                let dims = info.dimensions;

                // Check for dimension mismatch with existing index
                let mut dense = match Self::check_dense_meta(&storage, &info) {
                    Ok(()) => DenseIndex::open(&storage.dense_dir(), dims)
                        .or_else(|_| DenseIndex::new(dims))?,
                    Err(e) => {
                        warn!("Dense index mismatch: {}. Rebuilding.", e);
                        DenseIndex::new(dims)?
                    }
                };

                // Remove vectors for deleted/modified files (preserves unchanged files)
                for rel_path in &files_to_remove {
                    let abs_path = project_path.join(rel_path);
                    dense.remove_file(&abs_path.to_string_lossy());
                }

                if !all_chunks.is_empty() {
                    dense.add_chunks(&all_chunks, embedder.as_mut())?;
                }
                dense.save(&storage.dense_dir())?;
                Self::save_dense_meta(&storage, &info)?;
                debug!("Dense index updated: {} vectors", dense.len());
            }
        }

        // Update snapshot
        snapshot_manager.save(&new_dag)?;

        let mut lang_list: Vec<String> = languages.into_iter().collect();
        lang_list.sort();

        let elapsed = start.elapsed();

        let result = IndexResult {
            files_indexed: files_to_add.len(),
            chunks_created: chunk_count,
            time_taken_ms: elapsed.as_millis() as u64,
            languages: lang_list,
            incremental: true,
            files_added: changes.added.len(),
            files_removed: changes.removed.len(),
            files_modified: changes.modified.len(),
        };

        storage.save_stats(&result)?;

        info!(
            "Incremental index complete: {} chunks in {}ms",
            result.chunks_created, result.time_taken_ms
        );

        Ok(result)
    }

    /// Auto-index: full if no index, incremental if stale
    pub fn auto_index(
        &self,
        project_path: &Path,
        force: bool,
        extensions: Option<&[&str]>,
    ) -> Result<IndexResult> {
        let storage = ProjectStorage::for_project(project_path)?;

        if force || !storage.has_index() {
            return self.full_index(project_path, extensions);
        }

        let snapshot_manager = SnapshotManager::new(storage.base_dir().to_path_buf());

        // Check if snapshot is stale by age
        let age_stale = snapshot_manager
            .snapshot_age_secs()
            .map(|age| age > MAX_SNAPSHOT_AGE_SECS)
            .unwrap_or(true);

        if age_stale {
            return self.incremental_index(project_path, extensions);
        }

        // Even if age is fresh, check root hash for changes
        let hash_changed = snapshot_manager
            .load()
            .ok()
            .flatten()
            .and_then(|old_dag| {
                let new_dag = MerkleDAG::build(project_path, MERKLE_IGNORE_DIRS).ok()?;
                Some(ChangeDetector::has_changes(&old_dag, &new_dag))
            })
            .unwrap_or(true);

        if hash_changed {
            self.incremental_index(project_path, extensions)
        } else {
            Ok(IndexResult {
                files_indexed: 0,
                chunks_created: 0,
                time_taken_ms: 0,
                languages: Vec::new(),
                incremental: true,
                files_added: 0,
                files_removed: 0,
                files_modified: 0,
            })
        }
    }

    /// Search with auto-indexing
    pub fn search(
        &self,
        project_path: &Path,
        query: &str,
        limit: usize,
        extension_filter: Option<&str>,
    ) -> Result<Vec<SearchResult>> {
        let storage = ProjectStorage::for_project(project_path)?;

        // Auto-index if needed
        if !storage.has_index() {
            info!("No index found, auto-indexing before search");
            self.full_index(project_path, None)?;
        }

        let bm25 = BM25Index::open(&storage.tantivy_dir())?;
        let analyzed = analyze_query(query);

        // Perform BM25 search with processed query (stop words removed + synonyms expanded)
        let mut results = bm25.search(&analyzed.search_query, limit)?;

        // Hybrid search: combine BM25 + dense results if available
        #[cfg(feature = "dense")]
        {
            if let Some(fused) = Self::try_hybrid_search(&storage, &bm25, &results, query, limit) {
                results = fused;
            }
        }

        // Filter by extension if specified
        if let Some(ext) = extension_filter {
            results.retain(|r| r.relative_path.ends_with(&format!(".{}", ext)));
        }

        // Apply multi-factor ranking (includes dedup, thresholding, truncation)
        rank_results(&mut results, &analyzed, limit);

        Ok(results)
    }

    /// Get indexing status
    pub fn get_status(&self, project_path: &Path) -> Result<IndexStatus> {
        let storage = ProjectStorage::for_project(project_path)?;

        if !storage.has_index() {
            return Ok(IndexStatus {
                indexed: false,
                file_count: 0,
                chunk_count: 0,
                last_indexed: None,
                languages: Vec::new(),
            });
        }

        let snapshot_manager = SnapshotManager::new(storage.base_dir().to_path_buf());
        let metadata = snapshot_manager.load_metadata()?;

        let bm25 = BM25Index::open(&storage.tantivy_dir())?;
        let chunk_count = bm25.doc_count().unwrap_or(0) as usize;

        let stats = storage.load_stats()?;

        Ok(IndexStatus {
            indexed: true,
            file_count: metadata.as_ref().map(|m| m.file_count).unwrap_or(0),
            chunk_count,
            last_indexed: metadata.map(|m| m.timestamp.to_rfc3339()),
            languages: stats.map(|s| s.languages).unwrap_or_default(),
        })
    }

    /// Clear the index for a project
    pub fn clear_index(&self, project_path: &Path) -> Result<()> {
        let storage = ProjectStorage::for_project(project_path)?;
        storage.clear_all()?;
        info!("Cleared index for {}", project_path.display());
        Ok(())
    }
}

impl IncrementalIndexer {
    /// Attempt hybrid BM25 + dense vector search.
    /// Returns fused results on success, None on any failure (graceful fallback to BM25-only).
    #[cfg(feature = "dense")]
    fn try_hybrid_search(
        storage: &ProjectStorage,
        bm25: &BM25Index,
        bm25_results: &[SearchResult],
        query: &str,
        limit: usize,
    ) -> Option<Vec<SearchResult>> {
        let dense_dir = storage.dense_dir();
        if !dense_dir.join("dense.usearch").exists() {
            return None;
        }

        let mut embedder = match Self::load_embedder() {
            Ok(e) => e,
            Err(e) => {
                warn!("Failed to load embedder for hybrid search: {}", e);
                return None;
            }
        };

        let dims = embedder.info().dimensions;
        let dense = match DenseIndex::open(&dense_dir, dims) {
            Ok(d) => d,
            Err(e) => {
                warn!("Failed to open dense index: {}", e);
                return None;
            }
        };

        if dense.is_empty() {
            return None;
        }

        let query_vec = match embedder.encode_query(query) {
            Ok(v) => v,
            Err(e) => {
                warn!("Failed to encode query for dense search: {}", e);
                return None;
            }
        };

        let dense_k = (limit * 3).max(20);
        let dense_matches = match dense.search(&query_vec, dense_k) {
            Ok(m) => m,
            Err(e) => {
                warn!("Dense search failed: {}", e);
                return None;
            }
        };

        // Build lookup map from BM25 results
        let mut full_map: HashMap<String, SearchResult> = bm25_results
            .iter()
            .map(|r| (r.chunk_id.clone(), r.clone()))
            .collect();

        // Fetch dense-only results from BM25 by chunk_id
        let missing_ids: Vec<&str> = dense_matches
            .iter()
            .filter(|(cid, _)| !full_map.contains_key(cid))
            .map(|(cid, _)| cid.as_str())
            .collect();
        if !missing_ids.is_empty() {
            if let Ok(extra) = bm25.get_by_chunk_ids(&missing_ids) {
                full_map.extend(extra);
            }
        }

        let fused = reciprocal_rank_fusion(bm25_results, &dense_matches, &full_map);
        debug!(
            "Hybrid search: BM25={} dense={} fused={}",
            full_map.len(),
            dense_matches.len(),
            fused.len()
        );

        Some(fused)
    }

    #[cfg(feature = "dense")]
    fn load_embedder() -> Result<Box<dyn crate::search::embedding::Embedder>> {
        crate::search::embedding::load_embedder()
    }

    #[cfg(feature = "dense")]
    fn save_dense_meta(
        storage: &ProjectStorage,
        info: &crate::search::embedding::EmbedderInfo,
    ) -> Result<()> {
        let meta_path = storage.dense_dir().join("dense_meta.json");
        std::fs::create_dir_all(storage.dense_dir())?;
        let json = serde_json::to_string(info)?;
        std::fs::write(&meta_path, json)?;
        Ok(())
    }

    #[cfg(feature = "dense")]
    fn check_dense_meta(
        storage: &ProjectStorage,
        current: &crate::search::embedding::EmbedderInfo,
    ) -> Result<()> {
        let meta_path = storage.dense_dir().join("dense_meta.json");
        if !meta_path.exists() {
            return Ok(());
        }
        let data = std::fs::read_to_string(&meta_path)?;
        let saved: crate::search::embedding::EmbedderInfo = serde_json::from_str(&data)?;
        if saved.dimensions != current.dimensions
            || saved.provider != current.provider
            || saved.model_name != current.model_name
        {
            anyhow::bail!(
                "Embedder mismatch: index built with {} / {} ({}d), current is {} / {} ({}d). Re-index required.",
                saved.provider,
                saved.model_name,
                saved.dimensions,
                current.provider,
                current.model_name,
                current.dimensions,
            );
        }
        Ok(())
    }
}

impl Default for IncrementalIndexer {
    fn default() -> Self {
        Self::new()
    }
}
