use super::{extract_preceding_comments, find_name, NodeMetadata, LanguageChunker};
use crate::chunk::ChunkType;

pub struct JavaChunker;

impl LanguageChunker for JavaChunker {
    fn tree_sitter_language(&self) -> tree_sitter::Language {
        tree_sitter_java::LANGUAGE.into()
    }

    fn language_name(&self) -> &str {
        "java"
    }

    fn file_extensions(&self) -> &[&str] {
        &["java"]
    }

    fn is_splittable(&self, node_type: &str) -> bool {
        matches!(
            node_type,
            "method_declaration"
                | "class_declaration"
                | "interface_declaration"
                | "enum_declaration"
                | "constructor_declaration"
        )
    }

    fn has_nested_chunks(&self, node_type: &str) -> bool {
        matches!(
            node_type,
            "class_declaration" | "interface_declaration" | "enum_declaration"
        )
    }

    fn classify_node(&self, node_type: &str, parent_name: Option<&str>) -> ChunkType {
        match node_type {
            "class_declaration" => ChunkType::Class,
            "interface_declaration" => ChunkType::Interface,
            "enum_declaration" => ChunkType::Enum,
            "method_declaration" | "constructor_declaration" => {
                if parent_name.is_some() {
                    ChunkType::Method
                } else {
                    ChunkType::Function
                }
            }
            _ => ChunkType::ModuleLevel,
        }
    }

    fn extract_metadata(&self, node: tree_sitter::Node, source: &str) -> NodeMetadata {
        let mut meta = NodeMetadata::default();

        match node.kind() {
            "method_declaration" | "constructor_declaration" => {
                meta.name = find_name(node, source);
                meta.docstring = extract_preceding_comments(node, source);
                // Check for annotations
                if let Some(prev) = node.prev_sibling() {
                    if prev.kind() == "marker_annotation" || prev.kind() == "annotation" {
                        let text = &source[prev.start_byte()..prev.end_byte()];
                        meta.decorators.push(text.to_string());
                    }
                }
            }
            "class_declaration" | "interface_declaration" | "enum_declaration" => {
                meta.name = find_name(node, source);
                meta.docstring = extract_preceding_comments(node, source);
            }
            _ => {
                meta.name = find_name(node, source);
                meta.docstring = extract_preceding_comments(node, source);
            }
        }

        meta
    }
}
