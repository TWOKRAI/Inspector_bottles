pub mod c;
pub mod cpp;
pub mod csharp;
pub mod go;
pub mod java;
pub mod javascript;
pub mod markdown;
pub mod python;
pub mod rust_lang;
pub mod typescript;

use crate::chunk::ChunkType;

/// Metadata extracted from a tree-sitter node
#[derive(Debug, Clone, Default)]
pub struct NodeMetadata {
    pub name: Option<String>,
    pub docstring: Option<String>,
    pub decorators: Vec<String>,
    pub is_async: bool,
    pub is_generator: bool,
    pub receiver_type: Option<String>,
}

/// Trait for language-specific code chunking behavior
pub trait LanguageChunker: Send + Sync {
    /// Return the tree-sitter Language for this chunker
    fn tree_sitter_language(&self) -> tree_sitter::Language;

    /// Language name identifier
    fn language_name(&self) -> &str;

    /// File extensions this chunker handles
    fn file_extensions(&self) -> &[&str];

    /// Whether this node type should be extracted as a chunk
    fn is_splittable(&self, node_type: &str) -> bool;

    /// Whether this node type can contain nested splittable nodes (e.g., class body)
    fn has_nested_chunks(&self, node_type: &str) -> bool;

    /// Classify a node type into a ChunkType
    fn classify_node(&self, node_type: &str, parent_name: Option<&str>) -> ChunkType;

    /// Extract language-specific metadata from a node
    fn extract_metadata(&self, node: tree_sitter::Node, source: &str) -> NodeMetadata;
}

/// Helper to find the first named child of a given type and extract its text
pub fn find_child_text<'a>(
    node: tree_sitter::Node<'a>,
    source: &'a str,
    child_type: &str,
) -> Option<String> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == child_type {
            let text = &source[child.start_byte()..child.end_byte()];
            return Some(text.to_string());
        }
    }
    None
}

/// Helper to find identifier name from a node
pub fn find_name(node: tree_sitter::Node, source: &str) -> Option<String> {
    find_child_text(node, source, "identifier")
        .or_else(|| find_child_text(node, source, "type_identifier"))
        .or_else(|| find_child_text(node, source, "property_identifier"))
}

/// Extract a docstring from the node (looks for preceding comment or first string child)
pub fn extract_docstring_from_body(node: tree_sitter::Node, source: &str) -> Option<String> {
    // Look for a comment or string_content in the first child of the body
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        let kind = child.kind();
        if kind == "block" || kind == "body" || kind == "class_body" || kind == "declaration_list" {
            let first_stmt = child.child(0);
            if let Some(first_stmt) = first_stmt {
                if first_stmt.kind() == "expression_statement" {
                    let expr = first_stmt.child(0);
                    if let Some(expr) = expr {
                        if expr.kind() == "string" || expr.kind() == "string_literal" {
                            let text = &source[expr.start_byte()..expr.end_byte()];
                            return Some(text.trim_matches('"').trim_matches('\'').to_string());
                        }
                    }
                }
            }
        }
        // Check for doc comments preceding the node
        if kind == "comment" || kind == "line_comment" || kind == "block_comment" {
            let text = &source[child.start_byte()..child.end_byte()];
            return Some(text.to_string());
        }
    }
    None
}

/// Extract preceding doc comments for a node
pub fn extract_preceding_comments(node: tree_sitter::Node, source: &str) -> Option<String> {
    let mut comments = Vec::new();
    let mut sibling = node.prev_sibling();

    while let Some(sib) = sibling {
        let kind = sib.kind();
        if kind == "comment" || kind == "line_comment" || kind == "block_comment" {
            let text = &source[sib.start_byte()..sib.end_byte()];
            comments.push(text.to_string());
            sibling = sib.prev_sibling();
        } else {
            break;
        }
    }

    if comments.is_empty() {
        None
    } else {
        comments.reverse();
        Some(comments.join("\n"))
    }
}

/// Get all supported language chunkers
pub fn all_chunkers() -> Vec<Box<dyn LanguageChunker>> {
    vec![
        Box::new(python::PythonChunker),
        Box::new(javascript::JavaScriptChunker),
        Box::new(typescript::TypeScriptChunker),
        Box::new(typescript::TsxChunker),
        Box::new(rust_lang::RustChunker),
        Box::new(go::GoChunker),
        Box::new(java::JavaChunker),
        Box::new(c::CChunker),
        Box::new(cpp::CppChunker),
        Box::new(csharp::CSharpChunker),
        Box::new(markdown::MarkdownChunker),
    ]
}
