use crate::chunk::languages::LanguageChunker;
use crate::chunk::{ChunkType, CodeChunk};
use anyhow::{Context, Result};
use std::path::Path;

/// Raw chunk extracted from tree-sitter before enrichment
#[derive(Debug, Clone)]
pub struct TreeSitterChunk {
    pub content: String,
    pub start_line: usize,
    pub end_line: usize,
    pub node_type: String,
    pub chunk_type: ChunkType,
    pub name: Option<String>,
    pub parent_name: Option<String>,
    pub docstring: Option<String>,
    pub decorators: Vec<String>,
    pub is_async: bool,
}

/// Tree-sitter based code parsing engine
pub struct TreeSitterEngine;

impl TreeSitterEngine {
    /// Parse a source file and extract semantic chunks
    pub fn parse_file(
        source: &str,
        file_path: &str,
        relative_path: &str,
        language: &str,
        chunker: &dyn LanguageChunker,
    ) -> Result<Vec<CodeChunk>> {
        let mut parser = ::tree_sitter::Parser::new();
        let ts_language = chunker.tree_sitter_language();
        parser
            .set_language(&ts_language)
            .context("Failed to set tree-sitter language")?;

        let tree = parser
            .parse(source.as_bytes(), None)
            .context("Failed to parse source")?;

        let root = tree.root_node();
        let mut raw_chunks = Vec::new();

        Self::traverse_node(root, source, chunker, None, &mut raw_chunks);

        // If no chunks found, create a single module-level chunk
        if raw_chunks.is_empty() && !source.trim().is_empty() {
            let line_count = source.lines().count();
            raw_chunks.push(TreeSitterChunk {
                content: source.to_string(),
                start_line: 1,
                end_line: line_count,
                node_type: "module".to_string(),
                chunk_type: ChunkType::ModuleLevel,
                name: Path::new(relative_path)
                    .file_stem()
                    .and_then(|s| s.to_str())
                    .map(String::from),
                parent_name: None,
                docstring: None,
                decorators: Vec::new(),
                is_async: false,
            });
        }

        // Convert raw chunks to enriched CodeChunks
        let folder_structure = CodeChunk::extract_folder_structure(relative_path);
        let chunks = raw_chunks
            .into_iter()
            .map(|raw| {
                let id = CodeChunk::generate_id(file_path, raw.start_line, raw.end_line, raw.name.as_deref());
                let tags = CodeChunk::extract_tags(&raw.content, &raw.chunk_type);
                let complexity_score = CodeChunk::compute_complexity(&raw.content);
                let imports = Self::extract_imports(&raw.content, language);

                CodeChunk {
                    id,
                    content: raw.content,
                    chunk_type: raw.chunk_type,
                    start_line: raw.start_line,
                    end_line: raw.end_line,
                    file_path: file_path.to_string(),
                    relative_path: relative_path.to_string(),
                    folder_structure: folder_structure.clone(),
                    name: raw.name,
                    parent_name: raw.parent_name,
                    language: language.to_string(),
                    docstring: raw.docstring,
                    decorators: raw.decorators,
                    imports,
                    tags,
                    complexity_score,
                }
            })
            .collect();

        Ok(chunks)
    }

    /// Recursively traverse tree-sitter nodes to find splittable chunks
    fn traverse_node(
        node: ::tree_sitter::Node,
        source: &str,
        chunker: &dyn LanguageChunker,
        parent_name: Option<&str>,
        chunks: &mut Vec<TreeSitterChunk>,
    ) {
        let node_type = node.kind();

        if chunker.is_splittable(node_type) {
            // Extract this node as a chunk
            let start_byte = node.start_byte();
            let end_byte = node.end_byte();
            let content = &source[start_byte..end_byte];
            let start_line = node.start_position().row + 1;
            let end_line = node.end_position().row + 1;

            let metadata = chunker.extract_metadata(node, source);
            let chunk_type = chunker.classify_node(node_type, parent_name);

            let chunk = TreeSitterChunk {
                content: content.to_string(),
                start_line,
                end_line,
                node_type: node_type.to_string(),
                chunk_type,
                name: metadata.name.clone(),
                parent_name: parent_name.map(String::from),
                docstring: metadata.docstring,
                decorators: metadata.decorators,
                is_async: metadata.is_async,
            };

            chunks.push(chunk);

            // For classes/impls, also traverse children for nested methods
            let current_name = metadata.name.as_deref().or(parent_name);
            if chunker.has_nested_chunks(node_type) {
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    Self::traverse_node(child, source, chunker, current_name, chunks);
                }
            }
        } else {
            // Not splittable, recurse into children
            let mut cursor = node.walk();
            for child in node.children(&mut cursor) {
                Self::traverse_node(child, source, chunker, parent_name, chunks);
            }
        }
    }

    /// Extract import statements from source
    fn extract_imports(content: &str, language: &str) -> Vec<String> {
        let mut imports = Vec::new();
        for line in content.lines() {
            let trimmed = line.trim();
            let is_import = match language {
                "python" => trimmed.starts_with("import ") || trimmed.starts_with("from "),
                "javascript" | "typescript" | "tsx" | "jsx" => {
                    trimmed.starts_with("import ") || trimmed.starts_with("require(")
                }
                "rust" => trimmed.starts_with("use ") || trimmed.starts_with("extern crate"),
                "go" => trimmed.starts_with("import "),
                "java" | "csharp" => trimmed.starts_with("import ") || trimmed.starts_with("using "),
                "c" | "cpp" => trimmed.starts_with("#include"),
                _ => false,
            };
            if is_import {
                imports.push(trimmed.to_string());
            }
        }
        imports
    }
}
