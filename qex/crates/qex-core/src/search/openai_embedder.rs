//! OpenAI API embedding backend.
//!
//! Uses ureq for synchronous HTTP calls to the OpenAI embeddings endpoint.
//! Configured via environment variables:
//! - `QEX_OPENAI_API_KEY` or `OPENAI_API_KEY`
//! - `QEX_OPENAI_MODEL` (default: "text-embedding-3-small")
//! - `QEX_OPENAI_BASE_URL` (default: "https://api.openai.com/v1")

use crate::search::embedding::{l2_normalize, Embedder, EmbedderInfo};
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tracing::{debug, warn};

/// Maximum number of texts per API call
const MAX_BATCH_SIZE: usize = 100;

/// Default model
const DEFAULT_MODEL: &str = "text-embedding-3-small";

/// Default dimensions for text-embedding-3-small
const DEFAULT_DIMENSIONS: usize = 1536;

/// Default base URL
const DEFAULT_BASE_URL: &str = "https://api.openai.com/v1";

/// Maximum number of retry attempts for transient errors
const MAX_RETRIES: u32 = 3;

pub struct OpenAiEmbedder {
    agent: ureq::Agent,
    api_key: String,
    model: String,
    dimensions: usize,
    base_url: String,
}

impl OpenAiEmbedder {
    /// Create from environment variables.
    pub fn from_env() -> Result<Self> {
        let api_key = std::env::var("QEX_OPENAI_API_KEY")
            .or_else(|_| std::env::var("OPENAI_API_KEY"))
            .context(
                "OpenAI API key not found. Set QEX_OPENAI_API_KEY or OPENAI_API_KEY",
            )?;

        let model = std::env::var("QEX_OPENAI_MODEL")
            .unwrap_or_else(|_| DEFAULT_MODEL.to_string());

        let base_url = std::env::var("QEX_OPENAI_BASE_URL")
            .unwrap_or_else(|_| DEFAULT_BASE_URL.to_string());

        // Validate base URL scheme to prevent SSRF
        Self::validate_base_url(&base_url)?;

        // Determine dimensions based on model (or env override)
        let dimensions = match model.as_str() {
            "text-embedding-3-small" | "text-embedding-ada-002" => DEFAULT_DIMENSIONS,
            "text-embedding-3-large" => 3072,
            _ => {
                let dim = std::env::var("QEX_OPENAI_DIMENSIONS")
                    .ok()
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(DEFAULT_DIMENSIONS);
                warn!(
                    "Unknown OpenAI model '{}', assuming {} dimensions. \
                     Set QEX_OPENAI_DIMENSIONS to override.",
                    model, dim
                );
                dim
            }
        };

        let agent: ureq::Agent = ureq::Agent::config_builder()
            .timeout_connect(Some(Duration::from_secs(10)))
            .timeout_send_request(Some(Duration::from_secs(10)))
            .timeout_recv_response(Some(Duration::from_secs(60)))
            .timeout_recv_body(Some(Duration::from_secs(60)))
            .build()
            .into();

        Ok(Self {
            agent,
            api_key,
            model,
            dimensions,
            base_url,
        })
    }

    /// Validate that the base URL uses an allowed scheme.
    /// Only HTTPS is allowed for remote hosts. HTTP is permitted for localhost only.
    fn validate_base_url(url: &str) -> Result<()> {
        if url.starts_with("https://") {
            return Ok(());
        }
        if url.starts_with("http://") {
            // Allow HTTP only for localhost/loopback (testing, local proxies)
            let host_part = url.strip_prefix("http://").unwrap_or("");
            let host = host_part.split('/').next().unwrap_or("");
            // Strip port: handle IPv6 [::1]:port and regular host:port
            let host_no_port = if host.starts_with('[') {
                host.split(']').next().unwrap_or("").trim_start_matches('[')
            } else {
                host.split(':').next().unwrap_or("")
            };
            if matches!(host_no_port, "localhost" | "127.0.0.1" | "::1") {
                return Ok(());
            }
            anyhow::bail!(
                "QEX_OPENAI_BASE_URL: plain HTTP is only allowed for localhost, got: {}",
                url
            );
        }
        anyhow::bail!(
            "QEX_OPENAI_BASE_URL: only https:// URLs are allowed, got: {}",
            url
        );
    }

    /// Call the OpenAI embeddings API with retry for transient errors.
    ///
    /// Retries on 429 (rate limit), 5xx (server errors), timeouts, and connection failures.
    /// Uses exponential backoff: 1s, 2s, 4s between attempts.
    fn call_api(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        let url = format!("{}/embeddings", self.base_url);
        let request = EmbeddingRequest {
            input: texts.iter().map(|s| s.to_string()).collect(),
            model: self.model.clone(),
        };

        for attempt in 0..MAX_RETRIES {
            let result = self
                .agent
                .post(&url)
                .header("Authorization", &format!("Bearer {}", self.api_key))
                .header("Content-Type", "application/json")
                .send_json(&request);

            match result {
                Ok(resp) => return self.process_response(resp, texts.len()),
                Err(e) => {
                    let is_retryable = Self::is_retryable_error(&e);
                    let safe_msg = Self::sanitize_error(&e);

                    if is_retryable && attempt + 1 < MAX_RETRIES {
                        let wait = Duration::from_secs(1 << attempt);
                        warn!(
                            "OpenAI API error (attempt {}/{}), retrying in {:?}: {}",
                            attempt + 1,
                            MAX_RETRIES,
                            wait,
                            safe_msg
                        );
                        std::thread::sleep(wait);
                    } else {
                        return Err(anyhow::anyhow!("OpenAI API request failed: {}", safe_msg));
                    }
                }
            }
        }

        unreachable!("retry loop always returns")
    }

    /// Check if a ureq error is transient and worth retrying
    fn is_retryable_error(e: &ureq::Error) -> bool {
        match e {
            ureq::Error::StatusCode(code) => matches!(code, 429 | 500 | 502 | 503),
            ureq::Error::Timeout(_) => true,
            ureq::Error::ConnectionFailed => true,
            ureq::Error::Io(_) => true,
            _ => false,
        }
    }

    /// Sanitize ureq error to avoid leaking API key from headers
    fn sanitize_error(e: &ureq::Error) -> String {
        match e {
            ureq::Error::StatusCode(code) => format!("HTTP {}", code),
            ureq::Error::Timeout(kind) => format!("timeout ({:?})", kind),
            ureq::Error::ConnectionFailed => "connection failed".to_string(),
            ureq::Error::Io(io_err) => format!("I/O error: {}", io_err),
            other => {
                // For any other error, redact to avoid leaking sensitive data
                let msg = other.to_string();
                if msg.contains("Authorization") || msg.contains("Bearer") || msg.contains(&"sk-") {
                    "request failed (details redacted for security)".to_string()
                } else {
                    msg
                }
            }
        }
    }

    /// Process a successful HTTP response into embeddings
    fn process_response(
        &self,
        mut resp: ureq::http::Response<ureq::Body>,
        expected_count: usize,
    ) -> Result<Vec<Vec<f32>>> {
        let response: EmbeddingResponse = resp
            .body_mut()
            .read_json()
            .map_err(|e| anyhow::anyhow!("Failed to parse OpenAI embeddings response: {}", e))?;

        // Validate response count
        if response.data.len() != expected_count {
            anyhow::bail!(
                "OpenAI response count mismatch: sent {} texts, received {} embeddings",
                expected_count,
                response.data.len()
            );
        }

        // Log token usage if available
        if let Some(usage) = &response.usage {
            debug!("OpenAI embedding tokens used: {}", usage.total_tokens);
        }

        // Sort by index to ensure correct ordering
        let mut data = response.data;
        data.sort_by_key(|d| d.index);

        // Validate embedding dimensions for all items
        for item in &data {
            if item.embedding.len() != self.dimensions {
                anyhow::bail!(
                    "Embedding dimension mismatch at index {}: expected {}, got {}",
                    item.index,
                    self.dimensions,
                    item.embedding.len()
                );
            }
        }

        let embeddings: Vec<Vec<f32>> = data
            .into_iter()
            .map(|d| l2_normalize(d.embedding))
            .collect();

        Ok(embeddings)
    }
}

impl Embedder for OpenAiEmbedder {
    fn info(&self) -> EmbedderInfo {
        EmbedderInfo {
            provider: "openai".to_string(),
            dimensions: self.dimensions,
            model_name: self.model.clone(),
        }
    }

    fn encode_batch(&mut self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }

        let mut all_embeddings = Vec::with_capacity(texts.len());

        // Split into sub-batches of MAX_BATCH_SIZE
        for (batch_idx, batch) in texts.chunks(MAX_BATCH_SIZE).enumerate() {
            debug!(
                "OpenAI embedding batch {}/{} ({} texts)",
                batch_idx + 1,
                (texts.len() + MAX_BATCH_SIZE - 1) / MAX_BATCH_SIZE,
                batch.len()
            );
            let embeddings = self.call_api(batch)?;
            all_embeddings.extend(embeddings);
        }

        Ok(all_embeddings)
    }

    fn encode_query(&mut self, query: &str) -> Result<Vec<f32>> {
        let results = self.call_api(&[query])?;
        results
            .into_iter()
            .next()
            .context("Empty response from OpenAI API")
    }
}

// ---------------------------------------------------------------------------
// API request/response types
// ---------------------------------------------------------------------------

#[derive(Serialize)]
struct EmbeddingRequest {
    input: Vec<String>,
    model: String,
}

#[derive(Deserialize)]
struct EmbeddingResponse {
    data: Vec<EmbeddingData>,
    usage: Option<EmbeddingUsage>,
}

#[derive(Deserialize)]
struct EmbeddingUsage {
    total_tokens: u64,
}

#[derive(Deserialize)]
struct EmbeddingData {
    embedding: Vec<f32>,
    index: usize,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_l2_normalize() {
        let vec = l2_normalize(vec![3.0, 4.0]);
        let norm: f32 = vec.iter().map(|x| x * x).sum::<f32>().sqrt();
        assert!((norm - 1.0).abs() < 1e-6);
        assert!((vec[0] - 0.6).abs() < 1e-6);
        assert!((vec[1] - 0.8).abs() < 1e-6);
    }

    #[test]
    fn test_l2_normalize_zero() {
        let vec = l2_normalize(vec![0.0, 0.0]);
        assert_eq!(vec, vec![0.0, 0.0]);
    }

    #[test]
    fn test_validate_base_url_https() {
        assert!(OpenAiEmbedder::validate_base_url("https://api.openai.com/v1").is_ok());
        assert!(OpenAiEmbedder::validate_base_url("https://custom-api.example.com").is_ok());
    }

    #[test]
    fn test_validate_base_url_http_localhost() {
        assert!(OpenAiEmbedder::validate_base_url("http://localhost:8080/v1").is_ok());
        assert!(OpenAiEmbedder::validate_base_url("http://127.0.0.1:11434").is_ok());
        assert!(OpenAiEmbedder::validate_base_url("http://[::1]:8080").is_ok());
    }

    #[test]
    fn test_validate_base_url_rejects_http_remote() {
        let result = OpenAiEmbedder::validate_base_url("http://evil.example.com/v1");
        assert!(result.is_err());
        assert!(result.err().unwrap().to_string().contains("only allowed for localhost"));
    }

    #[test]
    fn test_validate_base_url_rejects_other_schemes() {
        let result = OpenAiEmbedder::validate_base_url("file:///etc/passwd");
        assert!(result.is_err());
        assert!(result.err().unwrap().to_string().contains("only https://"));

        let result = OpenAiEmbedder::validate_base_url("ftp://example.com");
        assert!(result.is_err());
    }

    #[test]
    fn test_from_env_missing_key() {
        // Only run this test if no API keys are set in the environment
        if std::env::var("QEX_OPENAI_API_KEY").is_ok()
            || std::env::var("OPENAI_API_KEY").is_ok()
        {
            eprintln!("Skipping test: API key is set in environment");
            return;
        }

        let result = OpenAiEmbedder::from_env();
        assert!(result.is_err());
        let err = result.err().unwrap();
        assert!(err.to_string().contains("API key not found"));
    }
}
