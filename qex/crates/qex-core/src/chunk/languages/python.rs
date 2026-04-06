use super::{extract_preceding_comments, find_name, NodeMetadata, LanguageChunker};
use crate::chunk::ChunkType;

pub struct PythonChunker;

impl LanguageChunker for PythonChunker {
    fn tree_sitter_language(&self) -> tree_sitter::Language {
        tree_sitter_python::LANGUAGE.into()
    }

    fn language_name(&self) -> &str {
        "python"
    }

    fn file_extensions(&self) -> &[&str] {
        &["py", "pyi"]
    }

    fn is_splittable(&self, node_type: &str) -> bool {
        matches!(
            node_type,
            "function_definition" | "class_definition" | "decorated_definition"
        )
    }

    fn has_nested_chunks(&self, node_type: &str) -> bool {
        matches!(node_type, "class_definition" | "decorated_definition")
    }

    fn classify_node(&self, node_type: &str, parent_name: Option<&str>) -> ChunkType {
        match node_type {
            "class_definition" => ChunkType::Class,
            "function_definition" if parent_name.is_some() => ChunkType::Method,
            "function_definition" => ChunkType::Function,
            "decorated_definition" => ChunkType::Function,
            _ => ChunkType::ModuleLevel,
        }
    }

    fn extract_metadata(&self, node: tree_sitter::Node, source: &str) -> NodeMetadata {
        let mut meta = NodeMetadata::default();

        match node.kind() {
            "function_definition" => {
                meta.name = find_name(node, source);
                meta.is_async = {
                    // Check if preceded by "async" keyword
                    let text = &source[node.start_byte()..node.end_byte()];
                    text.starts_with("async ")
                };
                // Extract docstring from body
                meta.docstring = extract_python_docstring(node, source);
            }
            "class_definition" => {
                meta.name = find_name(node, source);
                meta.docstring = extract_python_docstring(node, source);
            }
            "decorated_definition" => {
                // Extract decorators
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    if child.kind() == "decorator" {
                        let text = &source[child.start_byte()..child.end_byte()];
                        meta.decorators.push(text.to_string());
                    } else if child.kind() == "function_definition" || child.kind() == "class_definition" {
                        let inner = self.extract_metadata(child, source);
                        meta.name = inner.name;
                        meta.docstring = inner.docstring;
                        meta.is_async = inner.is_async;
                    }
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

fn extract_python_docstring(node: tree_sitter::Node, source: &str) -> Option<String> {
    // Look for block/body child, then first expression_statement with string
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "block" {
            let mut block_cursor = child.walk();
            for stmt in child.children(&mut block_cursor) {
                if stmt.kind() == "expression_statement" {
                    let mut stmt_cursor = stmt.walk();
                    for expr in stmt.children(&mut stmt_cursor) {
                        if expr.kind() == "string" {
                            let text = &source[expr.start_byte()..expr.end_byte()];
                            let cleaned = text
                                .trim_start_matches("\"\"\"")
                                .trim_end_matches("\"\"\"")
                                .trim_start_matches("'''")
                                .trim_end_matches("'''")
                                .trim();
                            return Some(cleaned.to_string());
                        }
                    }
                }
                // Only check the first statement
                break;
            }
        }
    }
    None
}
