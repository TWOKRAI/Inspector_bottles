use super::{extract_preceding_comments, find_child_text, find_name, NodeMetadata, LanguageChunker};
use crate::chunk::ChunkType;

pub struct TypeScriptChunker;

impl LanguageChunker for TypeScriptChunker {
    fn tree_sitter_language(&self) -> tree_sitter::Language {
        tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into()
    }

    fn language_name(&self) -> &str {
        "typescript"
    }

    fn file_extensions(&self) -> &[&str] {
        &["ts"]
    }

    fn is_splittable(&self, node_type: &str) -> bool {
        matches!(
            node_type,
            "function_declaration"
                | "class_declaration"
                | "method_definition"
                | "arrow_function"
                | "generator_function_declaration"
                | "export_statement"
                | "lexical_declaration"
                | "interface_declaration"
                | "type_alias_declaration"
                | "enum_declaration"
        )
    }

    fn has_nested_chunks(&self, node_type: &str) -> bool {
        matches!(
            node_type,
            "class_declaration" | "export_statement" | "interface_declaration"
        )
    }

    fn classify_node(&self, node_type: &str, parent_name: Option<&str>) -> ChunkType {
        match node_type {
            "class_declaration" => ChunkType::Class,
            "interface_declaration" => ChunkType::Interface,
            "type_alias_declaration" => ChunkType::Struct,
            "enum_declaration" => ChunkType::Enum,
            "method_definition" => ChunkType::Method,
            "function_declaration" | "generator_function_declaration" => {
                if parent_name.is_some() {
                    ChunkType::Method
                } else {
                    ChunkType::Function
                }
            }
            "arrow_function" => ChunkType::Function,
            _ => ChunkType::ModuleLevel,
        }
    }

    fn extract_metadata(&self, node: tree_sitter::Node, source: &str) -> NodeMetadata {
        let mut meta = NodeMetadata::default();

        match node.kind() {
            "function_declaration" | "generator_function_declaration" => {
                meta.name = find_name(node, source);
                meta.is_async = source[node.start_byte()..node.end_byte()].starts_with("async ");
                meta.docstring = extract_preceding_comments(node, source);
            }
            "class_declaration" | "interface_declaration" | "type_alias_declaration"
            | "enum_declaration" => {
                meta.name = find_name(node, source)
                    .or_else(|| find_child_text(node, source, "type_identifier"));
                meta.docstring = extract_preceding_comments(node, source);
            }
            "method_definition" => {
                meta.name = find_child_text(node, source, "property_identifier");
                meta.docstring = extract_preceding_comments(node, source);
            }
            "export_statement" => {
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    match child.kind() {
                        "function_declaration" | "class_declaration"
                        | "interface_declaration" | "type_alias_declaration"
                        | "enum_declaration" => {
                            meta.name = find_name(child, source)
                                .or_else(|| find_child_text(child, source, "type_identifier"));
                        }
                        "lexical_declaration" => {
                            let mut inner = child.walk();
                            for decl in child.children(&mut inner) {
                                if decl.kind() == "variable_declarator" {
                                    meta.name = find_name(decl, source);
                                    break;
                                }
                            }
                        }
                        _ => {}
                    }
                }
                meta.docstring = extract_preceding_comments(node, source);
            }
            "lexical_declaration" => {
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    if child.kind() == "variable_declarator" {
                        meta.name = find_name(child, source);
                        break;
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

pub struct TsxChunker;

impl LanguageChunker for TsxChunker {
    fn tree_sitter_language(&self) -> tree_sitter::Language {
        tree_sitter_typescript::LANGUAGE_TSX.into()
    }

    fn language_name(&self) -> &str {
        "tsx"
    }

    fn file_extensions(&self) -> &[&str] {
        &["tsx"]
    }

    fn is_splittable(&self, node_type: &str) -> bool {
        TypeScriptChunker.is_splittable(node_type)
    }

    fn has_nested_chunks(&self, node_type: &str) -> bool {
        TypeScriptChunker.has_nested_chunks(node_type)
    }

    fn classify_node(&self, node_type: &str, parent_name: Option<&str>) -> ChunkType {
        TypeScriptChunker.classify_node(node_type, parent_name)
    }

    fn extract_metadata(&self, node: tree_sitter::Node, source: &str) -> NodeMetadata {
        TypeScriptChunker.extract_metadata(node, source)
    }
}
