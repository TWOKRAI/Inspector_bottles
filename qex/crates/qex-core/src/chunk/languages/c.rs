use super::{extract_preceding_comments, find_child_text, find_name, NodeMetadata, LanguageChunker};
use crate::chunk::ChunkType;

pub struct CChunker;

impl LanguageChunker for CChunker {
    fn tree_sitter_language(&self) -> tree_sitter::Language {
        tree_sitter_c::LANGUAGE.into()
    }

    fn language_name(&self) -> &str {
        "c"
    }

    fn file_extensions(&self) -> &[&str] {
        &["c", "h"]
    }

    fn is_splittable(&self, node_type: &str) -> bool {
        matches!(
            node_type,
            "function_definition"
                | "struct_specifier"
                | "enum_specifier"
                | "type_definition"
        )
    }

    fn has_nested_chunks(&self, _node_type: &str) -> bool {
        false
    }

    fn classify_node(&self, node_type: &str, _parent_name: Option<&str>) -> ChunkType {
        match node_type {
            "function_definition" => ChunkType::Function,
            "struct_specifier" => ChunkType::Struct,
            "enum_specifier" => ChunkType::Enum,
            "type_definition" => ChunkType::Struct,
            _ => ChunkType::ModuleLevel,
        }
    }

    fn extract_metadata(&self, node: tree_sitter::Node, source: &str) -> NodeMetadata {
        let mut meta = NodeMetadata::default();

        match node.kind() {
            "function_definition" => {
                // Function name is in the declarator
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    if child.kind() == "function_declarator" {
                        meta.name = find_name(child, source);
                    }
                }
                meta.docstring = extract_preceding_comments(node, source);
            }
            "struct_specifier" | "enum_specifier" => {
                meta.name = find_child_text(node, source, "type_identifier")
                    .or_else(|| find_name(node, source));
                meta.docstring = extract_preceding_comments(node, source);
            }
            "type_definition" => {
                meta.name = find_child_text(node, source, "type_identifier");
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
