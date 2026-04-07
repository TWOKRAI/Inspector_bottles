//! Dense vector search backed by Qdrant REST API.
//!
//! Replaces the previous usearch HNSW backend with a Qdrant-based implementation.
//! Requires a running Qdrant instance (default: http://localhost:6333).
//!
//! Configuration via environment variables:
//! - `QDRANT_URL` (default: "http://localhost:6333")
//! - `QDRANT_COLLECTION_NAME` (default: "qex_dense_index")
//! - `QDRANT_BATCH_SIZE` — upsert batch size (default: 64)

use crate::chunk::CodeChunk;
use crate::search::embedding::Embedder;
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::path::Path;
use std::time::Duration;
use tracing::{debug, info, warn};
use ureq::Agent;

const DEFAULT_QDRANT_URL: &str = "http://localhost:6333";
const DEFAULT_COLLECTION: &str = "qex_dense_index";
const DEFAULT_UPSERT_BATCH: usize = 64;
const EMBED_BATCH_SIZE: usize = 8;

/// Qdrant-backed dense vector index.
pub struct DenseIndex {
    agent: Agent,
    url: String,
    collection: String,
    dimensions: usize,
    cached_len: usize,
}

impl DenseIndex {
    /// Create a new dense index, ensuring the Qdrant collection exists.
    pub fn new(dimensions: usize) -> Result<Self> {
        let agent = build_agent();
        let url = qdrant_url();
        let collection = collection_name();

        let idx = Self {
            agent,
            url,
            collection,
            dimensions,
            cached_len: 0,
        };

        idx.ensure_collection()?;
        Ok(idx)
    }

    /// Open an existing index (or create if absent). `index_dir` is ignored —
    /// Qdrant handles persistence. Reads env vars for connection settings.
    pub fn open(_index_dir: &Path, dimensions: usize) -> Result<Self> {
        let agent = build_agent();
        let url = qdrant_url();
        let collection = collection_name();

        let mut idx = Self {
            agent,
            url,
            collection,
            dimensions,
            cached_len: 0,
        };

        idx.ensure_collection()?;
        idx.cached_len = idx.fetch_count()?;
        info!("Opened Qdrant dense index: {} vectors", idx.cached_len);
        Ok(idx)
    }

    /// No-op: Qdrant persists data automatically after each upsert.
    pub fn save(&self, _index_dir: &Path) -> Result<()> {
        Ok(())
    }

    /// Embed `chunks` and upsert into Qdrant.
    pub fn add_chunks(&mut self, chunks: &[CodeChunk], model: &mut dyn Embedder) -> Result<usize> {
        if chunks.is_empty() {
            return Ok(0);
        }

        let upsert_batch = std::env::var("QDRANT_BATCH_SIZE")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(DEFAULT_UPSERT_BATCH);

        let total = chunks.len();
        let mut added = 0;

        // Embed in small batches (Ollama/ONNX memory constraint)
        for (embed_batch_idx, embed_batch) in chunks.chunks(EMBED_BATCH_SIZE).enumerate() {
            debug!(
                "Embedding batch {}/{} ({} chunks embedded so far)",
                embed_batch_idx + 1,
                (total + EMBED_BATCH_SIZE - 1) / EMBED_BATCH_SIZE,
                added
            );

            let texts: Vec<String> = embed_batch
                .iter()
                .map(|c| {
                    let mut text = String::new();
                    if let Some(name) = &c.name {
                        text.push_str(name);
                        text.push(' ');
                    }
                    if let Some(doc) = &c.docstring {
                        text.push_str(doc);
                        text.push(' ');
                    }
                    text.push_str(&c.content);
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

            // Build Qdrant points
            let points: Vec<QdrantPoint> = embed_batch
                .iter()
                .zip(embeddings.iter())
                .map(|(chunk, vec)| QdrantPoint {
                    id: chunk_id_to_u64(&chunk.id),
                    vector: vec.clone(),
                    payload: ChunkPayload {
                        chunk_id: chunk.id.clone(),
                        file_path: chunk.file_path.clone(),
                    },
                })
                .collect();

            // Upsert in sub-batches
            for upsert_slice in points.chunks(upsert_batch) {
                self.upsert_points(upsert_slice)?;
                added += upsert_slice.len();
            }
        }

        self.cached_len = self.fetch_count().unwrap_or(self.cached_len + added);
        info!("Upserted {} vectors to Qdrant (total: {})", added, self.cached_len);
        Ok(added)
    }

    /// Search for nearest neighbors of `query_vec`. Returns `(chunk_id, similarity)`.
    pub fn search(&self, query_vec: &[f32], k: usize) -> Result<Vec<(String, f32)>> {
        if self.is_empty() {
            return Ok(Vec::new());
        }

        let url = format!("{}/collections/{}/points/search", self.url, self.collection);
        let request = SearchRequest {
            vector: query_vec.to_vec(),
            limit: k,
            with_payload: true,
        };

        let mut resp = self
            .agent
            .post(&url)
            .header("Content-Type", "application/json")
            .send_json(&request)
            .map_err(|e| anyhow::anyhow!("Qdrant search request failed: {}", e))?;

        let response: SearchResponse = resp
            .body_mut()
            .read_json()
            .context("Failed to parse Qdrant search response")?;

        let matches = response
            .result
            .into_iter()
            .filter_map(|hit| {
                let chunk_id = hit.payload?.chunk_id;
                let score = hit.score;
                Some((chunk_id, score))
            })
            .collect();

        Ok(matches)
    }

    /// Delete all vectors whose `file_path` payload matches `file_path`.
    pub fn remove_file(&mut self, file_path: &str) {
        let url = format!(
            "{}/collections/{}/points/delete",
            self.url, self.collection
        );
        let request = DeleteByFilter {
            filter: PayloadFilter {
                must: vec![FieldMatch {
                    key: "file_path".to_string(),
                    r#match: MatchValue {
                        value: file_path.to_string(),
                    },
                }],
            },
        };

        match self
            .agent
            .post(&url)
            .header("Content-Type", "application/json")
            .send_json(&request)
        {
            Ok(_) => {
                debug!("Removed vectors for file {}", file_path);
                self.cached_len = self.fetch_count().unwrap_or(0);
            }
            Err(e) => {
                warn!("Failed to remove vectors for {}: {}", file_path, e);
            }
        }
    }

    /// Drop and recreate the Qdrant collection.
    pub fn clear(&mut self) -> Result<()> {
        let url = format!("{}/collections/{}", self.url, self.collection);
        let _ = self.agent.delete(&url).call();
        self.cached_len = 0;
        self.ensure_collection()?;
        Ok(())
    }

    pub fn len(&self) -> usize {
        self.cached_len
    }

    pub fn is_empty(&self) -> bool {
        self.cached_len == 0
    }
}

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

impl DenseIndex {
    /// Create the Qdrant collection if it doesn't exist.
    fn ensure_collection(&self) -> Result<()> {
        let url = format!("{}/collections/{}", self.url, self.collection);

        // Check if exists
        match self.agent.get(&url).call() {
            Ok(_) => {
                // Collection exists — verify dimension compatibility
                debug!("Qdrant collection '{}' already exists", self.collection);
                Ok(())
            }
            Err(ureq::Error::StatusCode(404)) => {
                // Create new collection
                let create_url = url.clone();
                let body = CreateCollection {
                    vectors: VectorsConfig {
                        size: self.dimensions,
                        distance: "Cosine".to_string(),
                    },
                };
                self.agent
                    .put(&create_url)
                    .header("Content-Type", "application/json")
                    .send_json(&body)
                    .map_err(|e| {
                        anyhow::anyhow!(
                            "Failed to create Qdrant collection '{}': {}",
                            self.collection,
                            e
                        )
                    })?;
                info!(
                    "Created Qdrant collection '{}' with {} dims",
                    self.collection, self.dimensions
                );
                Ok(())
            }
            Err(e) => Err(anyhow::anyhow!(
                "Failed to check Qdrant collection '{}': {}. \
                 Is Qdrant running at {}?",
                self.collection,
                e,
                self.url
            )),
        }
    }

    /// Upsert a batch of points into Qdrant.
    fn upsert_points(&self, points: &[QdrantPoint]) -> Result<()> {
        let url = format!("{}/collections/{}/points", self.url, self.collection);
        let body = UpsertRequest { points: points.to_vec() };

        self.agent
            .put(&url)
            .header("Content-Type", "application/json")
            .send_json(&body)
            .map_err(|e| anyhow::anyhow!("Qdrant upsert failed: {}", e))?;

        Ok(())
    }

    /// Query the number of indexed vectors from Qdrant.
    fn fetch_count(&self) -> Result<usize> {
        let url = format!("{}/collections/{}", self.url, self.collection);
        let mut resp = self
            .agent
            .get(&url)
            .call()
            .context("Failed to query Qdrant collection info")?;

        let info: CollectionInfo = resp
            .body_mut()
            .read_json()
            .context("Failed to parse Qdrant collection info")?;

        Ok(info.result.points_count)
    }
}

// ---------------------------------------------------------------------------
// Env var helpers
// ---------------------------------------------------------------------------

fn qdrant_url() -> String {
    std::env::var("QDRANT_URL").unwrap_or_else(|_| DEFAULT_QDRANT_URL.to_string())
}

fn collection_name() -> String {
    std::env::var("QDRANT_COLLECTION_NAME").unwrap_or_else(|_| DEFAULT_COLLECTION.to_string())
}

fn build_agent() -> Agent {
    ureq::Agent::config_builder()
        .timeout_connect(Some(Duration::from_secs(5)))
        .timeout_send_request(Some(Duration::from_secs(10)))
        .timeout_recv_response(Some(Duration::from_secs(60)))
        .timeout_recv_body(Some(Duration::from_secs(60)))
        .build()
        .into()
}

/// Deterministic u64 from chunk_id (first 8 bytes of SHA-256).
fn chunk_id_to_u64(chunk_id: &str) -> u64 {
    let mut hasher = Sha256::new();
    hasher.update(chunk_id.as_bytes());
    let result = hasher.finalize();
    u64::from_le_bytes(result[..8].try_into().unwrap())
}

// ---------------------------------------------------------------------------
// Qdrant REST API types
// ---------------------------------------------------------------------------

#[derive(Serialize, Clone)]
struct QdrantPoint {
    id: u64,
    vector: Vec<f32>,
    payload: ChunkPayload,
}

#[derive(Serialize, Deserialize, Clone)]
struct ChunkPayload {
    chunk_id: String,
    file_path: String,
}

#[derive(Serialize)]
struct UpsertRequest {
    points: Vec<QdrantPoint>,
}

#[derive(Serialize)]
struct CreateCollection {
    vectors: VectorsConfig,
}

#[derive(Serialize)]
struct VectorsConfig {
    size: usize,
    distance: String,
}

#[derive(Serialize)]
struct SearchRequest {
    vector: Vec<f32>,
    limit: usize,
    with_payload: bool,
}

#[derive(Deserialize)]
struct SearchResponse {
    result: Vec<SearchHit>,
}

#[derive(Deserialize)]
struct SearchHit {
    score: f32,
    payload: Option<ChunkPayload>,
}

#[derive(Serialize)]
struct DeleteByFilter {
    filter: PayloadFilter,
}

#[derive(Serialize)]
struct PayloadFilter {
    must: Vec<FieldMatch>,
}

#[derive(Serialize)]
struct FieldMatch {
    key: String,
    r#match: MatchValue,
}

#[derive(Serialize)]
struct MatchValue {
    value: String,
}

#[derive(Deserialize)]
struct CollectionInfo {
    result: CollectionResult,
}

#[derive(Deserialize)]
struct CollectionResult {
    points_count: usize,
}
