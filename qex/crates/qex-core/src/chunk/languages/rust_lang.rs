use super::{extract_preceding_comments, find_child_text, find_name, NodeMetadata, LanguageChunker};
use crate::chunk::ChunkType;

pub struct RustChunker;

impl LanguageChunker for RustChunker {
    fn tree_sitter_language(&self) -> tree_sitter::Language {
        tree_sitter_rust::LANGUAGE.into()
    }

    fn language_name(&self) -> &str {
        "rust"
    }

    fn file_extensions(&self) -> &[&str] {
        &["rs"]
    }

    fn is_splittable(&self, node_type: &str) -> bool {
        matches!(
            node_type,
            "function_item"
                | "impl_item"
                | "struct_item"
                | "enum_item"
                | "trait_item"
                | "mod_item"
                | "macro_definition"
        )
    }

    fn has_nested_chunks(&self, node_type: &str) -> bool {
        matches!(node_type, "impl_item" | "trait_item" | "mod_item")
    }

    fn classify_node(&self, node_type: &str, parent_name: Option<&str>) -> ChunkType {
        match node_type {
            "function_item" if parent_name.is_some() => ChunkType::Method,
            "function_item" => ChunkType::Function,
            "impl_item" => ChunkType::Impl,
            "struct_item" => ChunkType::Struct,
            "enum_item" => ChunkType::Enum,
            "trait_item" => ChunkType::Trait,
            "mod_item" => ChunkType::Module,
            "macro_definition" => ChunkType::Macro,
            _ => ChunkType::ModuleLevel,
        }
    }

    fn extract_metadata(&self, node: tree_sitter::Node, source: &str) -> NodeMetadata {
        let mut meta = NodeMetadata::default();

        match node.kind() {
            "function_item" => {
                meta.name = find_name(node, source);
                let text = &source[node.start_byte()..node.end_byte()];
                meta.is_async = text.starts_with("async ") || text.starts_with("pub async ");
                meta.docstring = extract_preceding_comments(node, source);
            }
            "impl_item" => {
                // impl Type or impl Trait for Type
                meta.name = find_child_text(node, source, "type_identifier");
                meta.docstring = extract_preceding_comments(node, source);
            }
            "struct_item" | "enum_item" => {
                meta.name = find_child_text(node, source, "type_identifier");
                meta.docstring = extract_preceding_comments(node, source);
            }
            "trait_item" => {
                meta.name = find_child_text(node, source, "type_identifier");
                meta.docstring = extract_preceding_comments(node, source);
            }
            "mod_item" => {
                meta.name = find_name(node, source);
                meta.docstring = extract_preceding_comments(node, source);
            }
            "macro_definition" => {
                meta.name = find_name(node, source);
                meta.docstring = extract_preceding_comments(node, source);
            }
            _ => {
                meta.name = find_name(node, source);
                meta.docstring = extract_preceding_comments(node, source);
            }
        }

        // Extract attributes as decorators
        if let Some(prev) = node.prev_sibling() {
            if prev.kind() == "attribute_item" || prev.kind() == "inner_attribute_item" {
                let text = &source[prev.start_byte()..prev.end_byte()];
                meta.decorators.push(text.to_string());
            }
        }

        meta
    }
}
