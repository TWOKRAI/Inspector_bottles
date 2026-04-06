use super::{extract_preceding_comments, find_child_text, find_name, LanguageChunker, NodeMetadata};
use crate::chunk::ChunkType;

pub struct JavaScriptChunker;

impl LanguageChunker for JavaScriptChunker {
    fn tree_sitter_language(&self) -> tree_sitter::Language {
        tree_sitter_javascript::LANGUAGE.into()
    }

    fn language_name(&self) -> &str {
        "javascript"
    }

    fn file_extensions(&self) -> &[&str] {
        &["js", "jsx", "mjs", "cjs"]
    }

    fn is_splittable(&self, node_type: &str) -> bool {
        matches!(
            node_type,
            "function_declaration"
                | "class_declaration"
                | "method_definition"
                | "arrow_function"
                | "generator_function"
                | "generator_function_declaration"
                | "export_statement"
                | "lexical_declaration"
        )
    }

    fn has_nested_chunks(&self, node_type: &str) -> bool {
        matches!(node_type, "class_declaration" | "export_statement")
    }

    fn classify_node(&self, node_type: &str, parent_name: Option<&str>) -> ChunkType {
        match node_type {
            "class_declaration" => ChunkType::Class,
            "method_definition" => ChunkType::Method,
            "function_declaration" | "generator_function_declaration" => {
                if parent_name.is_some() {
                    ChunkType::Method
                } else {
                    ChunkType::Function
                }
            }
            "arrow_function" | "generator_function" => ChunkType::Function,
            "export_statement" | "lexical_declaration" => ChunkType::ModuleLevel,
            _ => ChunkType::ModuleLevel,
        }
    }

    fn extract_metadata(&self, node: tree_sitter::Node, source: &str) -> NodeMetadata {
        let mut meta = NodeMetadata::default();

        match node.kind() {
            "function_declaration" | "generator_function_declaration" => {
                meta.name = find_name(node, source);
                meta.is_async = source[node.start_byte()..node.end_byte()].starts_with("async ");
                meta.is_generator = node.kind().contains("generator");
                meta.docstring = extract_preceding_comments(node, source);
            }
            "class_declaration" => {
                meta.name = find_name(node, source);
                meta.docstring = extract_preceding_comments(node, source);
            }
            "method_definition" => {
                meta.name = find_child_text(node, source, "property_identifier");
                meta.docstring = extract_preceding_comments(node, source);
            }
            "arrow_function" => {
                // Arrow functions are often assigned: const foo = () => {}
                // Name comes from parent variable_declarator
                meta.docstring = extract_preceding_comments(node, source);
            }
            "export_statement" => {
                // Look for the declaration inside
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    if child.kind() == "function_declaration" || child.kind() == "class_declaration" {
                        meta.name = find_name(child, source);
                    } else if child.kind() == "lexical_declaration" {
                        // const/let export
                        let mut inner = child.walk();
                        for decl in child.children(&mut inner) {
                            if decl.kind() == "variable_declarator" {
                                meta.name = find_name(decl, source);
                                break;
                            }
                        }
                    }
                }
                meta.docstring = extract_preceding_comments(node, source);
            }
            "lexical_declaration" => {
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    if child.kind() == "variable_declarator" {
                        meta.name = find_name(child, source);
                        // Check if value is arrow function
                        let mut inner = child.walk();
                        for val in child.children(&mut inner) {
                            if val.kind() == "arrow_function" {
                                meta.is_async = source[val.start_byte()..val.end_byte()].starts_with("async ");
                            }
                        }
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
