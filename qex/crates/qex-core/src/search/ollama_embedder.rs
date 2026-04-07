//! Ollama API embedding backend.
//!
//! Uses ureq for synchronous HTTP calls to the Ollama /api/embed endpoint.
//! Configured via environment variables:
//! - `QEX_OLLAMA_BASE_URL` or `OLLAMA_BASE_URL` (default: "http://localhost:11434")
//! - `QEX_OLLAMA_MODEL` or `EMBEDDING_MODEL` (default: "nomic-embed-text")
//! - `QEX_OLLAMA_DIMENSIONS` — override dimension detection (optional)

use crate::search::embedding::{l2_normalize, Embedder, EmbedderInfo};
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tracing::{debug, warn};

/// Maximum texts per Ollama /api/embed request
const MAX_BATCH_SIZE: usize = 16;

/// Default Ollama base URL
const DEFAULT_BASE_URL: &str = "http://localhost:11434";

/// Default embedding model
const DEFAULT_MODEL: &str = "nomic-embed-text";

/// Maximum retry attempts for transient errors
const MAX_RETRIES: u32 = 3;

pub struct OllamaEmbedder {
    agent: ureq::Agent,
    base_url: String,
    model: String,
    dimensions: usize,
}

impl OllamaEmbedder {
    /// Create from environment variables, detecting dimensions automatically.
    pub fn from_env() -> Result<Self> {
        let base_url = std::env::var("QEX_OLLAMA_BASE_URL")
            .or_else(|_| std::env::var("OLLAMA_BASE_URL"))
            .unwrap_or_else(|_| DEFAULT_BASE_URL.to_string());

        let model = std::env::var("QEX_OLLAMA_MODEL")
            .or_else(|_| std::env::var("EMBEDDING_MODEL"))
            .unwrap_or_else(|_| DEFAULT_MODEL.to_string());

        let agent: ureq::Agent = ureq::Agent::config_builder()
            .timeout_connect(Some(Duration::from_secs(10)))
            .timeout_send_request(Some(Duration::from_secs(15)))
            .timeout_recv_response(Some(Duration::from_secs(120)))
            .timeout_recv_body(Some(Duration::from_secs(120)))
            .build()
            .into();

        // Determine dimensions: env override or auto-detect via test embedding
        let dimensions = if let Ok(dim_str) = std::env::var("QEX_OLLAMA_DIMENSIONS") {
            dim_str
                .parse::<usize>()
                .context("QEX_OLLAMA_DIMENSIONS must be a positive integer")?
        } else {
            Self::detect_dimensions(&agent, &base_url, &model)?
        };

        Ok(Self {
            agent,
            base_url,
            model,
            dimensions,
        })
    }

    /// Auto-detect embedding dimensions by running a test inference.
    fn detect_dimensions(agent: &ureq::Agent, base_url: &str, model: &str) -> Result<usize> {
        let url = format!("{}/api/embed", base_url);
        let request = EmbedRequest {
            model: model.to_string(),
            input: vec!["test".to_string()],
        };

        let mut resp = agent
            .post(&url)
            .header("Content-Type", "application/json")
            .send_json(&request)
            .map_err(|e| anyhow::anyhow!("Failed to connect to Ollama at {}: {}", base_url, e))?;

        let response: EmbedResponse = resp
            .body_mut()
            .read_json()
            .context("Failed to parse Ollama /api/embed response")?;

        let dim = response
            .embeddings
            .first()
            .map(|v| v.len())
            .filter(|&d| d > 0)
            .context("Ollama returned an empty embedding — is the model loaded?")?;

        debug!("Detected {} dimensions for model '{}'", dim, model);
        Ok(dim)
    }

    /// Call Ollama /api/embed for a batch of texts with retry.
    fn call_api(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        let url = format!("{}/api/embed", self.base_url);
        let request = EmbedRequest {
            model: self.model.clone(),
            input: texts.iter().map(|s| s.to_string()).collect(),
        };

        for attempt in 0..MAX_RETRIES {
            let result = self
                .agent
                .post(&url)
                .header("Content-Type", "application/json")
                .send_json(&request);

            match result {
                Ok(resp) => return self.process_response(resp, texts.len()),
                Err(e) => {
                    let retryable = Self::is_retryable(&e);
                    let msg = Self::format_error(&e);

                    if retryable && attempt + 1 < MAX_RETRIES {
                        let wait = Duration::from_secs(1 << attempt);
                        warn!(
                            "Ollama API error (attempt {}/{}), retrying in {:?}: {}",
                            attempt + 1,
                            MAX_RETRIES,
                            wait,
                            msg
                        );
                        std::thread::sleep(wait);
                    } else {
                        return Err(anyhow::anyhow!("Ollama API request failed: {}", msg));
                    }
                }
            }
        }

        unreachable!("retry loop always returns")
    }

    fn is_retryable(e: &ureq::Error) -> bool {
        match e {
            ureq::Error::StatusCode(code) => matches!(code, 429 | 500 | 502 | 503),
            ureq::Error::Timeout(_) => true,
            ureq::Error::ConnectionFailed => true,
            ureq::Error::Io(_) => true,
            _ => false,
        }
    }

    fn format_error(e: &ureq::Error) -> String {
        match e {
            ureq::Error::StatusCode(code) => format!("HTTP {}", code),
            ureq::Error::Timeout(kind) => format!("timeout ({:?})", kind),
            ureq::Error::ConnectionFailed => "connection failed".to_string(),
            ureq::Error::Io(io_err) => format!("I/O error: {}", io_err),
            other => other.to_string(),
        }
    }

    fn process_response(
        &self,
        mut resp: ureq::http::Response<ureq::Body>,
        expected: usize,
    ) -> Result<Vec<Vec<f32>>> {
        let response: EmbedResponse = resp
            .body_mut()
            .read_json()
            .context("Failed to parse Ollama /api/embed response")?;

        if response.embeddings.len() != expected {
            anyhow::bail!(
                "Ollama response count mismatch: sent {} texts, received {} embeddings",
                expected,
                response.embeddings.len()
            );
        }

        for (i, emb) in response.embeddings.iter().enumerate() {
            if emb.len() != self.dimensions {
                anyhow::bail!(
                    "Embedding dimension mismatch at index {}: expected {}, got {}",
                    i,
                    self.dimensions,
                    emb.len()
                );
            }
        }

        let embeddings = response
            .embeddings
            .into_iter()
            .map(l2_normalize)
            .collect();

        Ok(embeddings)
    }
}

impl Embedder for OllamaEmbedder {
    fn info(&self) -> EmbedderInfo {
        EmbedderInfo {
            provider: "ollama".to_string(),
            dimensions: self.dimensions,
            model_name: self.model.clone(),
        }
    }

    fn encode_batch(&mut self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }

        let mut all = Vec::with_capacity(texts.len());
        let total_batches = (texts.len() + MAX_BATCH_SIZE - 1) / MAX_BATCH_SIZE;

        for (idx, batch) in texts.chunks(MAX_BATCH_SIZE).enumerate() {
            debug!(
                "Ollama embedding batch {}/{} ({} texts)",
                idx + 1,
                total_batches,
                batch.len()
            );
            let embeddings = self.call_api(batch)?;
            all.extend(embeddings);
        }

        Ok(all)
    }

    fn encode_query(&mut self, query: &str) -> Result<Vec<f32>> {
        let results = self.call_api(&[query])?;
        results
            .into_iter()
            .next()
            .context("Empty response from Ollama API")
    }
}

// ---------------------------------------------------------------------------
// API types
// ---------------------------------------------------------------------------

#[derive(Serialize)]
struct EmbedRequest {
    model: String,
    input: Vec<String>,
}

#[derive(Deserialize)]
struct EmbedResponse {
    embeddings: Vec<Vec<f32>>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ollama_embedder_from_env() {
        // Only runs if Ollama is available
        if std::env::var("OLLAMA_BASE_URL").is_err()
            && std::net::TcpStream::connect("localhost:11434").is_err()
        {
            eprintln!("Skipping test: Ollama not reachable");
            return;
        }

        let embedder = OllamaEmbedder::from_env();
        match embedder {
            Ok(e) => {
                assert!(e.dimensions > 0);
                println!("Detected dimensions: {}", e.dimensions);
            }
            Err(e) => eprintln!("Ollama not available: {}", e),
        }
    }
}
