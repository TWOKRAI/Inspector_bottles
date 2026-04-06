use super::{extract_preceding_comments, find_child_text, find_name, NodeMetadata, LanguageChunker};
use crate::chunk::ChunkType;

pub struct CSharpChunker;

impl LanguageChunker for CSharpChunker {
    fn tree_sitter_language(&self) -> tree_sitter::Language {
        tree_sitter_c_sharp::LANGUAGE.into()
    }

    fn language_name(&self) -> &str {
        "csharp"
    }

    fn file_extensions(&self) -> &[&str] {
        &["cs"]
    }

    fn is_splittable(&self, node_type: &str) -> bool {
        matches!(
            node_type,
            "method_declaration"
                | "class_declaration"
                | "interface_declaration"
                | "struct_declaration"
                | "enum_declaration"
                | "namespace_declaration"
                | "constructor_declaration"
                | "property_declaration"
        )
    }

    fn has_nested_chunks(&self, node_type: &str) -> bool {
        matches!(
            node_type,
            "class_declaration"
                | "interface_declaration"
                | "struct_declaration"
                | "namespace_declaration"
        )
    }

    fn classify_node(&self, node_type: &str, parent_name: Option<&str>) -> ChunkType {
        match node_type {
            "class_declaration" => ChunkType::Class,
            "interface_declaration" => ChunkType::Interface,
            "struct_declaration" => ChunkType::Struct,
            "enum_declaration" => ChunkType::Enum,
            "namespace_declaration" => ChunkType::Namespace,
            "method_declaration" | "constructor_declaration" | "property_declaration" => {
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
            "method_declaration" | "constructor_declaration" | "property_declaration" => {
                meta.name = find_name(node, source);
                meta.docstring = extract_preceding_comments(node, source);
                // Check for attributes
                if let Some(prev) = node.prev_sibling() {
                    if prev.kind() == "attribute_list" {
                        let text = &source[prev.start_byte()..prev.end_byte()];
                        meta.decorators.push(text.to_string());
                    }
                }
                let text = &source[node.start_byte()..node.end_byte()];
                meta.is_async = text.contains("async ");
            }
            "class_declaration" | "interface_declaration" | "struct_declaration"
            | "enum_declaration" => {
                meta.name = find_name(node, source);
                meta.docstring = extract_preceding_comments(node, source);
            }
            "namespace_declaration" => {
                meta.name = find_name(node, source)
                    .or_else(|| find_child_text(node, source, "qualified_name"));
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
