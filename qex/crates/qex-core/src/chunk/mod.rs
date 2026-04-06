pub mod languages;
pub mod multi_language;
pub mod tree_sitter;

use serde::{Deserialize, Serialize};
use std::fmt;

/// Represents the type of a code chunk
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChunkType {
    Function,
    Method,
    Class,
    Struct,
    Enum,
    Interface,
    Trait,
    Impl,
    Module,
    ModuleLevel,
    ImportBlock,
    Namespace,
    Macro,
    Section,
    Document,
}

impl fmt::Display for ChunkType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ChunkType::Function => write!(f, "function"),
            ChunkType::Method => write!(f, "method"),
            ChunkType::Class => write!(f, "class"),
            ChunkType::Struct => write!(f, "struct"),
            ChunkType::Enum => write!(f, "enum"),
            ChunkType::Interface => write!(f, "interface"),
            ChunkType::Trait => write!(f, "trait"),
            ChunkType::Impl => write!(f, "impl"),
            ChunkType::Module => write!(f, "module"),
            ChunkType::ModuleLevel => write!(f, "module_level"),
            ChunkType::ImportBlock => write!(f, "import_block"),
            ChunkType::Namespace => write!(f, "namespace"),
            ChunkType::Macro => write!(f, "macro"),
            ChunkType::Section => write!(f, "section"),
            ChunkType::Document => write!(f, "document"),
        }
    }
}

/// A semantic chunk of code extracted from a source file
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CodeChunk {
    /// Unique identifier for this chunk
    pub id: String,
    /// The actual source code content
    pub content: String,
    /// Type of code construct
    pub chunk_type: ChunkType,
    /// Starting line number (1-based)
    pub start_line: usize,
    /// Ending line number (1-based)
    pub end_line: usize,
    /// Absolute file path
    pub file_path: String,
    /// Relative file path from project root
    pub relative_path: String,
    /// Folder components of the path (e.g., ["src", "utils", "auth"])
    pub folder_structure: Vec<String>,
    /// Name of the construct (function/class/method name)
    pub name: Option<String>,
    /// Parent construct name (e.g., class name for methods)
    pub parent_name: Option<String>,
    /// Programming language
    pub language: String,
    /// Docstring/documentation comment
    pub docstring: Option<String>,
    /// Decorator/attribute annotations
    pub decorators: Vec<String>,
    /// Import statements within this chunk
    pub imports: Vec<String>,
    /// Semantic tags for categorization
    pub tags: Vec<String>,
    /// Complexity indicator (rough metric)
    pub complexity_score: u32,
}

impl CodeChunk {
    /// Generate a unique chunk ID from file path, line range, and name
    pub fn generate_id(file_path: &str, start_line: usize, end_line: usize, name: Option<&str>) -> String {
        use sha2::{Digest, Sha256};
        let input = format!("{}:{}:{}:{}", file_path, start_line, end_line, name.unwrap_or(""));
        let hash = Sha256::digest(input.as_bytes());
        format!("{:x}", hash)[..16].to_string()
    }

    /// Extract folder structure from a relative path
    pub fn extract_folder_structure(relative_path: &str) -> Vec<String> {
        let path = std::path::Path::new(relative_path);
        path.parent()
            .map(|p| {
                p.components()
                    .filter_map(|c| match c {
                        std::path::Component::Normal(s) => s.to_str().map(String::from),
                        _ => None,
                    })
                    .collect()
            })
            .unwrap_or_default()
    }

    /// Compute a rough complexity score based on content
    pub fn compute_complexity(content: &str) -> u32 {
        let lines = content.lines().count();
        let branches = content.matches("if ").count()
            + content.matches("else").count()
            + content.matches("match ").count()
            + content.matches("for ").count()
            + content.matches("while ").count()
            + content.matches("case ").count();
        (lines + branches * 2) as u32
    }

    /// Extract semantic tags from content
    pub fn extract_tags(content: &str, chunk_type: &ChunkType) -> Vec<String> {
        let mut tags = Vec::new();
        let lower = content.to_lowercase();

        // Async indicators
        if lower.contains("async ") || lower.contains("await ") || lower.contains(".then(") {
            tags.push("async".to_string());
        }

        // Database indicators
        if lower.contains("query") || lower.contains("sql") || lower.contains("database")
            || lower.contains("insert") || lower.contains("select ") || lower.contains("table")
        {
            tags.push("database".to_string());
        }

        // Auth indicators
        if lower.contains("auth") || lower.contains("login") || lower.contains("token")
            || lower.contains("password") || lower.contains("session") || lower.contains("permission")
        {
            tags.push("auth".to_string());
        }

        // Error handling
        if lower.contains("error") || lower.contains("exception") || lower.contains("try ")
            || lower.contains("catch") || lower.contains("result<") || lower.contains("anyhow")
        {
            tags.push("error_handling".to_string());
        }

        // API/HTTP
        if lower.contains("endpoint") || lower.contains("route") || lower.contains("request")
            || lower.contains("response") || lower.contains("http") || lower.contains("api")
        {
            tags.push("api".to_string());
        }

        // Testing
        if lower.contains("#[test]") || lower.contains("#[cfg(test)]")
            || lower.contains("assert") || lower.contains("mock") || lower.contains("fixture")
        {
            tags.push("test".to_string());
        }

        // Export (JS/TS)
        if lower.contains("export ") || lower.contains("module.exports") || lower.contains("pub ") {
            tags.push("export".to_string());
        }

        // Chunk type tag
        match chunk_type {
            ChunkType::Class | ChunkType::Struct => tags.push("type_definition".to_string()),
            ChunkType::Interface | ChunkType::Trait => tags.push("interface".to_string()),
            ChunkType::ImportBlock => tags.push("imports".to_string()),
            _ => {}
        }

        tags.sort();
        tags.dedup();
        tags
    }
}
