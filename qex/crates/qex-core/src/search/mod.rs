pub mod bm25;
#[cfg(feature = "dense")]
pub mod dense;
#[cfg(any(feature = "dense", feature = "openai"))]
pub mod embedding;
#[cfg(feature = "dense")]
pub mod hybrid;
#[cfg(feature = "openai")]
pub mod openai_embedder;
pub mod query;
pub mod ranking;

use crate::chunk::{ChunkType, CodeChunk};
use serde::{Deserialize, Serialize};

/// A search result with ranking score
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResult {
    pub chunk_id: String,
    pub score: f32,
    pub content: String,
    pub file_path: String,
    pub relative_path: String,
    pub folder_structure: Vec<String>,
    pub chunk_type: ChunkType,
    pub name: Option<String>,
    pub parent_name: Option<String>,
    pub start_line: usize,
    pub end_line: usize,
    pub language: String,
    pub docstring: Option<String>,
    pub tags: Vec<String>,
}

impl SearchResult {
    pub fn from_chunk(chunk: &CodeChunk, score: f32) -> Self {
        Self {
            chunk_id: chunk.id.clone(),
            score,
            content: chunk.content.clone(),
            file_path: chunk.file_path.clone(),
            relative_path: chunk.relative_path.clone(),
            folder_structure: chunk.folder_structure.clone(),
            chunk_type: chunk.chunk_type.clone(),
            name: chunk.name.clone(),
            parent_name: chunk.parent_name.clone(),
            start_line: chunk.start_line,
            end_line: chunk.end_line,
            language: chunk.language.clone(),
            docstring: chunk.docstring.clone(),
            tags: chunk.tags.clone(),
        }
    }
}
