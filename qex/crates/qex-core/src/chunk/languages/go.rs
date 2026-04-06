use super::{extract_preceding_comments, find_child_text, find_name, NodeMetadata, LanguageChunker};
use crate::chunk::ChunkType;

pub struct GoChunker;

impl LanguageChunker for GoChunker {
    fn tree_sitter_language(&self) -> tree_sitter::Language {
        tree_sitter_go::LANGUAGE.into()
    }

    fn language_name(&self) -> &str {
        "go"
    }

    fn file_extensions(&self) -> &[&str] {
        &["go"]
    }

    fn is_splittable(&self, node_type: &str) -> bool {
        matches!(
            node_type,
            "function_declaration"
                | "method_declaration"
                | "type_declaration"
        )
    }

    fn has_nested_chunks(&self, _node_type: &str) -> bool {
        false
    }

    fn classify_node(&self, node_type: &str, _parent_name: Option<&str>) -> ChunkType {
        match node_type {
            "function_declaration" => ChunkType::Function,
            "method_declaration" => ChunkType::Method,
            "type_declaration" => ChunkType::Struct,
            _ => ChunkType::ModuleLevel,
        }
    }

    fn extract_metadata(&self, node: tree_sitter::Node, source: &str) -> NodeMetadata {
        let mut meta = NodeMetadata::default();

        match node.kind() {
            "function_declaration" => {
                meta.name = find_name(node, source);
                meta.docstring = extract_preceding_comments(node, source);
            }
            "method_declaration" => {
                meta.name = find_child_text(node, source, "field_identifier");
                // Extract receiver type
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    if child.kind() == "parameter_list" {
                        let mut param_cursor = child.walk();
                        for param in child.children(&mut param_cursor) {
                            if param.kind() == "parameter_declaration" {
                                meta.receiver_type = find_child_text(param, source, "type_identifier");
                                break;
                            }
                        }
                        break;
                    }
                }
                meta.docstring = extract_preceding_comments(node, source);
            }
            "type_declaration" => {
                // type_declaration contains type_spec children
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    if child.kind() == "type_spec" {
                        meta.name = find_child_text(child, source, "type_identifier");
                        // Check if struct or interface
                        let mut spec_cursor = child.walk();
                        for spec_child in child.children(&mut spec_cursor) {
                            if spec_child.kind() == "interface_type" {
                                // Will be classified as struct but semantically interface
                            }
                        }
                    }
                }
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
