use super::{NodeMetadata, LanguageChunker};
use crate::chunk::ChunkType;

pub struct MarkdownChunker;

impl LanguageChunker for MarkdownChunker {
    fn tree_sitter_language(&self) -> tree_sitter::Language {
        tree_sitter_md::LANGUAGE.into()
    }

    fn language_name(&self) -> &str {
        "markdown"
    }

    fn file_extensions(&self) -> &[&str] {
        &["md", "mdx"]
    }

    fn is_splittable(&self, node_type: &str) -> bool {
        matches!(node_type, "section" | "document")
    }

    fn has_nested_chunks(&self, node_type: &str) -> bool {
        matches!(node_type, "document" | "section")
    }

    fn classify_node(&self, node_type: &str, _parent_name: Option<&str>) -> ChunkType {
        match node_type {
            "section" => ChunkType::Section,
            "document" => ChunkType::Document,
            _ => ChunkType::ModuleLevel,
        }
    }

    fn extract_metadata(&self, node: tree_sitter::Node, source: &str) -> NodeMetadata {
        let mut meta = NodeMetadata::default();

        if node.kind() == "section" {
            // Extract heading text as the name
            let mut cursor = node.walk();
            for child in node.children(&mut cursor) {
                if child.kind() == "atx_heading" || child.kind() == "setext_heading" {
                    let text = &source[child.start_byte()..child.end_byte()];
                    let name = text.trim_start_matches('#').trim();
                    meta.name = Some(name.to_string());
                    break;
                }
            }
        } else if node.kind() == "document" {
            meta.name = Some("document".to_string());
        }

        meta
    }
}
