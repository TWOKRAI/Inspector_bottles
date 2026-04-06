//! Text embedding for dense vector search.
//!
//! Provides a trait-based abstraction over embedding backends:
//! - `dense` feature: ONNX Runtime with snowflake-arctic-embed-s (384-dim)
//! - `openai` feature: OpenAI API (text-embedding-3-small, 1536-dim)
//!
//! Configure via env vars:
//! - `QEX_EMBEDDING_PROVIDER`: "onnx" (default) or "openai"
//! - `QEX_ONNX_MODEL_DIR`: override ONNX model directory
//! - `QEX_OPENAI_API_KEY` / `OPENAI_API_KEY`: API key for OpenAI
//! - `QEX_OPENAI_MODEL`: model name (default: text-embedding-3-small)

use anyhow::Result;
use serde::{Deserialize, Serialize};

/// L2 normalize a vector in-place
pub(crate) fn l2_normalize(mut vec: Vec<f32>) -> Vec<f32> {
    let norm: f32 = vec.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm.is_finite() && norm > 0.0 {
        for v in &mut vec {
            *v /= norm;
        }
    }
    vec
}

/// Metadata about an embedding provider
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmbedderInfo {
    /// Provider name (e.g. "onnx", "openai")
    pub provider: String,
    /// Output embedding dimensions
    pub dimensions: usize,
    /// Model identifier
    pub model_name: String,
}

/// Trait for embedding text into dense vectors
pub trait Embedder {
    /// Get metadata about this embedder
    fn info(&self) -> EmbedderInfo;

    /// Encode a batch of texts into embedding vectors
    fn encode_batch(&mut self, texts: &[&str]) -> Result<Vec<Vec<f32>>>;

    /// Encode a single query (may add provider-specific prefixes)
    fn encode_query(&mut self, query: &str) -> Result<Vec<f32>>;
}

/// Load the configured embedder based on env vars.
///
/// Reads `QEX_EMBEDDING_PROVIDER` (default: "onnx"):
/// - "onnx": loads ONNX model (requires `dense` feature)
/// - "openai": uses OpenAI API (requires `openai` feature)
pub fn load_embedder() -> Result<Box<dyn Embedder>> {
    let provider = std::env::var("QEX_EMBEDDING_PROVIDER")
        .unwrap_or_else(|_| "onnx".to_string());
    load_embedder_for_provider(&provider)
}

/// Load an embedder for the given provider name.
///
/// Testable without env var manipulation.
pub fn load_embedder_for_provider(provider: &str) -> Result<Box<dyn Embedder>> {
    match provider {
        "onnx" => load_onnx_embedder(),
        #[cfg(feature = "openai")]
        "openai" => {
            let embedder = super::openai_embedder::OpenAiEmbedder::from_env()?;
            Ok(Box::new(embedder))
        }
        #[cfg(not(feature = "openai"))]
        "openai" => anyhow::bail!(
            "OpenAI embedding provider requested but 'openai' feature is not enabled. \
             Build with --features openai"
        ),
        other => anyhow::bail!(
            "Unknown embedding provider '{}'. Supported: onnx, openai",
            other
        ),
    }
}

#[cfg(feature = "dense")]
fn expand_tilde(path: &str) -> Result<std::path::PathBuf> {
    if path == "~" {
        dirs::home_dir().ok_or_else(|| anyhow::anyhow!("Cannot determine home directory"))
    } else if let Some(rest) = path.strip_prefix("~/") {
        let home =
            dirs::home_dir().ok_or_else(|| anyhow::anyhow!("Cannot determine home directory"))?;
        Ok(home.join(rest))
    } else {
        Ok(std::path::PathBuf::from(path))
    }
}

#[cfg(feature = "dense")]
fn load_onnx_embedder() -> Result<Box<dyn Embedder>> {
    let model_dir = match std::env::var("QEX_ONNX_MODEL_DIR") {
        Ok(dir) => expand_tilde(&dir)?,
        Err(_) => EmbeddingModel::default_model_dir()?,
    };

    if !model_dir.join("model.onnx").exists() {
        anyhow::bail!(
            "ONNX embedding model not found at {}. Run scripts/download-model.sh",
            model_dir.display()
        );
    }

    let model = EmbeddingModel::load(&model_dir)?;
    Ok(Box::new(model))
}

#[cfg(not(feature = "dense"))]
fn load_onnx_embedder() -> Result<Box<dyn Embedder>> {
    anyhow::bail!(
        "ONNX embedding provider requested but 'dense' feature is not enabled. \
         Build with --features dense"
    )
}

// ---------------------------------------------------------------------------
// ONNX embedding model (behind "dense" feature)
// ---------------------------------------------------------------------------

#[cfg(feature = "dense")]
use anyhow::Context;
#[cfg(feature = "dense")]
use ndarray::Array2;
#[cfg(feature = "dense")]
use ort::session::Session;
#[cfg(feature = "dense")]
use ort::value::Tensor;
#[cfg(feature = "dense")]
use std::path::Path;
#[cfg(feature = "dense")]
use tokenizers::Tokenizer;
#[cfg(feature = "dense")]
use tracing::info;

/// Query prefix for arctic-embed models (asymmetric retrieval)
#[cfg(feature = "dense")]
const QUERY_PREFIX: &str = "Represent this sentence for searching relevant passages: ";

/// Maximum sequence length for the model
#[cfg(feature = "dense")]
const MAX_SEQ_LEN: usize = 512;

/// snowflake-arctic-embed-s output dimensions
#[cfg(feature = "dense")]
const ARCTIC_EMBED_S_DIMENSIONS: usize = 384;

/// Embedding model backed by ONNX Runtime
#[cfg(feature = "dense")]
pub struct EmbeddingModel {
    session: Session,
    tokenizer: Tokenizer,
    dimensions: usize,
}

#[cfg(feature = "dense")]
impl EmbeddingModel {
    /// Load model from a directory containing model.onnx and tokenizer.json
    pub fn load(model_dir: &Path) -> Result<Self> {
        let model_path = model_dir.join("model.onnx");
        let tokenizer_path = model_dir.join("tokenizer.json");

        anyhow::ensure!(model_path.exists(), "model.onnx not found in {}", model_dir.display());
        anyhow::ensure!(tokenizer_path.exists(), "tokenizer.json not found in {}", model_dir.display());

        // Use available CPU cores for ONNX parallelism
        let num_threads = std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(4);

        let session = Session::builder()
            .context("Failed to create ONNX session builder")?
            .with_intra_threads(num_threads)
            .context("Failed to set thread count")?
            .commit_from_file(&model_path)
            .context("Failed to load ONNX model")?;

        let tokenizer = Tokenizer::from_file(&tokenizer_path)
            .map_err(|e| anyhow::anyhow!("Failed to load tokenizer: {}", e))?;

        info!("Loaded embedding model from {}", model_dir.display());

        Ok(Self {
            session,
            tokenizer,
            dimensions: ARCTIC_EMBED_S_DIMENSIONS,
        })
    }

    /// Get the default model directory
    pub fn default_model_dir() -> Result<std::path::PathBuf> {
        let home = dirs::home_dir().context("Cannot determine home directory")?;
        Ok(home.join(".qex/models/arctic-embed-s"))
    }

    /// Check if the model is downloaded
    pub fn is_available() -> bool {
        Self::default_model_dir()
            .map(|d| d.join("model.onnx").exists() && d.join("tokenizer.json").exists())
            .unwrap_or(false)
    }

    /// Embedding dimensions
    pub fn dimensions(&self) -> usize {
        self.dimensions
    }

    /// Encode a single text into an embedding vector
    pub fn encode(&mut self, text: &str) -> Result<Vec<f32>> {
        let results = self.encode_batch_impl(&[text])?;
        results
            .into_iter()
            .next()
            .context("ONNX model returned empty results for single text")
    }

    /// Internal batch encoding implementation
    fn encode_batch_impl(&mut self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }

        // Tokenize all texts
        let encodings: Vec<_> = texts
            .iter()
            .map(|t| {
                self.tokenizer
                    .encode(*t, true)
                    .map_err(|e| anyhow::anyhow!("Tokenization failed: {}", e))
            })
            .collect::<Result<Vec<_>>>()?;

        // Find max length (capped at MAX_SEQ_LEN)
        let max_len = encodings
            .iter()
            .map(|e| e.get_ids().len().min(MAX_SEQ_LEN))
            .max()
            .unwrap_or(0);

        if max_len == 0 {
            // All texts tokenized to zero length — return zero vectors
            return Ok(vec![vec![0.0f32; self.dimensions]; texts.len()]);
        }

        let batch_size = texts.len();

        // Build padded tensors
        let mut input_ids = Array2::<i64>::zeros((batch_size, max_len));
        let mut attention_mask = Array2::<i64>::zeros((batch_size, max_len));
        let mut token_type_ids = Array2::<i64>::zeros((batch_size, max_len));

        for (i, encoding) in encodings.iter().enumerate() {
            let ids = encoding.get_ids();
            let mask = encoding.get_attention_mask();
            let types = encoding.get_type_ids();
            let len = ids.len().min(max_len);

            for j in 0..len {
                input_ids[[i, j]] = ids[j] as i64;
                attention_mask[[i, j]] = mask[j] as i64;
                token_type_ids[[i, j]] = types[j] as i64;
            }
        }

        // Run inference
        let input_ids_tensor = Tensor::from_array(input_ids)?;
        let attention_mask_tensor = Tensor::from_array(attention_mask.clone())?;
        let token_type_ids_tensor = Tensor::from_array(token_type_ids)?;

        let outputs = self.session.run(ort::inputs![
            "input_ids" => input_ids_tensor,
            "attention_mask" => attention_mask_tensor,
            "token_type_ids" => token_type_ids_tensor,
        ])?;

        // Extract output: [batch_size, seq_len, hidden_dim]
        let (shape, raw_data) = outputs[0]
            .try_extract_tensor::<f32>()
            .context("Failed to extract output tensor")?;

        let hidden_dim = *shape.last().unwrap_or(&(ARCTIC_EMBED_S_DIMENSIONS as i64)) as usize;
        let seq_len_out = if shape.len() >= 2 { shape[1] as usize } else { max_len };

        // Mean pooling with attention mask over raw tensor data
        // raw_data layout: [batch_size * seq_len_out * hidden_dim]
        let mut embeddings = Vec::with_capacity(batch_size);
        for i in 0..batch_size {
            let mut pooled = vec![0.0f32; hidden_dim];
            let mut count = 0.0f32;

            for j in 0..seq_len_out {
                let mask_val = attention_mask[[i, j.min(max_len - 1)]] as f32;
                if mask_val > 0.0 {
                    let offset = (i * seq_len_out + j) * hidden_dim;
                    for k in 0..hidden_dim {
                        pooled[k] += raw_data[offset + k] * mask_val;
                    }
                    count += mask_val;
                }
            }

            // Divide by count
            if count > 0.0 {
                for v in &mut pooled {
                    *v /= count;
                }
            }

            // L2 normalize
            let pooled = l2_normalize(pooled);

            embeddings.push(pooled);
        }

        Ok(embeddings)
    }
}

#[cfg(feature = "dense")]
impl Embedder for EmbeddingModel {
    fn info(&self) -> EmbedderInfo {
        EmbedderInfo {
            provider: "onnx".to_string(),
            dimensions: self.dimensions,
            model_name: "snowflake-arctic-embed-s".to_string(),
        }
    }

    fn encode_batch(&mut self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        self.encode_batch_impl(texts)
    }

    fn encode_query(&mut self, query: &str) -> Result<Vec<f32>> {
        let prefixed = format!("{}{}", QUERY_PREFIX, query);
        self.encode(&prefixed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[cfg(feature = "dense")]
    fn test_embedding_model_load_and_encode() {
        let model_dir = EmbeddingModel::default_model_dir().unwrap();
        if !model_dir.join("model.onnx").exists() {
            eprintln!("Skipping test: model not downloaded. Run scripts/download-model.sh");
            return;
        }

        let mut model = EmbeddingModel::load(&model_dir).unwrap();
        assert_eq!(model.dimensions(), 384);

        // Test single encode
        let embedding = model.encode("authentication middleware").unwrap();
        assert_eq!(embedding.len(), 384);

        // Verify L2 normalized (norm ≈ 1.0)
        let norm: f32 = embedding.iter().map(|x| x * x).sum::<f32>().sqrt();
        assert!((norm - 1.0).abs() < 0.01, "norm={}", norm);

        // Test via Embedder trait
        let query_emb = model.encode_query("authentication").unwrap();
        assert_eq!(query_emb.len(), 384);

        let batch = model
            .encode_batch(&["hello world", "code search", "database connection"])
            .unwrap();
        assert_eq!(batch.len(), 3);
        assert_eq!(batch[0].len(), 384);

        // Verify different texts produce different embeddings
        assert_ne!(batch[0], batch[1]);
        assert_ne!(batch[1], batch[2]);
    }

    #[test]
    fn test_load_embedder_unknown_provider() {
        let result = load_embedder_for_provider("unknown_provider");
        assert!(result.is_err());
        let err = result.err().unwrap();
        assert!(err.to_string().contains("Unknown embedding provider"));
    }

    #[test]
    fn test_load_embedder_for_provider_onnx_without_feature() {
        // "onnx" provider should either work (dense feature) or fail gracefully (no dense)
        let result = load_embedder_for_provider("onnx");
        // We don't assert success/failure because it depends on feature flags and model availability
        // Just ensure it doesn't panic
        let _ = result;
    }
}
