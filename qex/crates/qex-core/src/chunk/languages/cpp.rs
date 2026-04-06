use super::{extract_preceding_comments, find_child_text, find_name, NodeMetadata, LanguageChunker};
use crate::chunk::ChunkType;

pub struct CppChunker;

impl LanguageChunker for CppChunker {
    fn tree_sitter_language(&self) -> tree_sitter::Language {
        tree_sitter_cpp::LANGUAGE.into()
    }

    fn language_name(&self) -> &str {
        "cpp"
    }

    fn file_extensions(&self) -> &[&str] {
        &["cpp", "cc", "cxx", "hpp", "hh", "hxx"]
    }

    fn is_splittable(&self, node_type: &str) -> bool {
        matches!(
            node_type,
            "function_definition"
                | "class_specifier"
                | "struct_specifier"
                | "enum_specifier"
                | "namespace_definition"
                | "template_declaration"
        )
    }

    fn has_nested_chunks(&self, node_type: &str) -> bool {
        matches!(
            node_type,
            "class_specifier" | "struct_specifier" | "namespace_definition" | "template_declaration"
        )
    }

    fn classify_node(&self, node_type: &str, parent_name: Option<&str>) -> ChunkType {
        match node_type {
            "class_specifier" => ChunkType::Class,
            "struct_specifier" => ChunkType::Struct,
            "enum_specifier" => ChunkType::Enum,
            "namespace_definition" => ChunkType::Namespace,
            "function_definition" if parent_name.is_some() => ChunkType::Method,
            "function_definition" => ChunkType::Function,
            "template_declaration" => ChunkType::Function,
            _ => ChunkType::ModuleLevel,
        }
    }

    fn extract_metadata(&self, node: tree_sitter::Node, source: &str) -> NodeMetadata {
        let mut meta = NodeMetadata::default();

        match node.kind() {
            "function_definition" => {
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    if child.kind() == "function_declarator" {
                        meta.name = find_name(child, source)
                            .or_else(|| find_child_text(child, source, "field_identifier"))
                            .or_else(|| find_child_text(child, source, "destructor_name"));
                    }
                }
                meta.docstring = extract_preceding_comments(node, source);
            }
            "class_specifier" | "struct_specifier" | "enum_specifier" => {
                meta.name = find_child_text(node, source, "type_identifier")
                    .or_else(|| find_name(node, source));
                meta.docstring = extract_preceding_comments(node, source);
            }
            "namespace_definition" => {
                meta.name = find_name(node, source);
                meta.docstring = extract_preceding_comments(node, source);
            }
            "template_declaration" => {
                // Look inside for the actual declaration
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    if child.kind() == "function_definition" || child.kind() == "class_specifier" {
                        let inner = self.extract_metadata(child, source);
                        meta.name = inner.name;
                        meta.docstring = inner.docstring;
                        break;
                    }
                }
                if meta.docstring.is_none() {
                    meta.docstring = extract_preceding_comments(node, source);
                }
            }
            _ => {
                meta.name = find_name(node, source);
                meta.docstring = extract_preceding_comments(node, source);
            }
        }

        meta
    }
}
