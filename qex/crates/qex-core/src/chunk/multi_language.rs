use crate::chunk::languages::{all_chunkers, LanguageChunker};
use crate::chunk::tree_sitter::TreeSitterEngine;
use crate::chunk::CodeChunk;
use anyhow::{Context, Result};
use rayon::prelude::*;
use std::collections::HashMap;
use std::path::Path;

/// Multi-language chunker that dispatches to the appropriate language chunker
pub struct MultiLanguageChunker {
    /// Map from file extension to language chunker
    extension_map: HashMap<String, usize>,
    /// All chunkers
    chunkers: Vec<Box<dyn LanguageChunker>>,
}

impl MultiLanguageChunker {
    pub fn new() -> Self {
        let chunkers = all_chunkers();
        let mut extension_map = HashMap::new();

        for (idx, chunker) in chunkers.iter().enumerate() {
            for ext in chunker.file_extensions() {
                extension_map.insert(ext.to_string(), idx);
            }
        }

        Self {
            extension_map,
            chunkers,
        }
    }

    /// Check if a file extension is supported
    pub fn is_supported(&self, path: &str) -> bool {
        Path::new(path)
            .extension()
            .and_then(|e| e.to_str())
            .map(|ext| self.extension_map.contains_key(ext))
            .unwrap_or(false)
    }

    /// Get the language name for a file
    pub fn language_for_file(&self, path: &str) -> Option<&str> {
        let ext = Path::new(path).extension()?.to_str()?;
        let idx = self.extension_map.get(ext)?;
        Some(self.chunkers[*idx].language_name())
    }

    /// Get all supported extensions
    pub fn supported_extensions(&self) -> Vec<&str> {
        self.chunkers
            .iter()
            .flat_map(|c| c.file_extensions().iter().copied())
            .collect()
    }

    /// Chunk a single file
    pub fn chunk_file(
        &self,
        file_path: &str,
        relative_path: &str,
        source: &str,
    ) -> Result<Vec<CodeChunk>> {
        let ext = Path::new(file_path)
            .extension()
            .and_then(|e| e.to_str())
            .context("File has no extension")?;

        let idx = self
            .extension_map
            .get(ext)
            .context(format!("Unsupported extension: {}", ext))?;

        let chunker = &self.chunkers[*idx];

        TreeSitterEngine::parse_file(source, file_path, relative_path, chunker.language_name(), chunker.as_ref())
    }

    /// Chunk multiple files in parallel
    pub fn chunk_files(
        &self,
        files: &[(String, String)], // (absolute_path, relative_path)
    ) -> Vec<(String, Result<Vec<CodeChunk>>)> {
        files
            .par_iter()
            .filter_map(|(abs_path, rel_path)| {
                if !self.is_supported(abs_path) {
                    return None;
                }
                let source = match std::fs::read_to_string(abs_path) {
                    Ok(s) => s,
                    Err(e) => {
                        return Some((
                            rel_path.clone(),
                            Err(anyhow::anyhow!("Failed to read {}: {}", abs_path, e)),
                        ));
                    }
                };
                let result = self.chunk_file(abs_path, rel_path, &source);
                Some((rel_path.clone(), result))
            })
            .collect()
    }
}

impl Default for MultiLanguageChunker {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_supported_extensions() {
        let chunker = MultiLanguageChunker::new();
        assert!(chunker.is_supported("test.py"));
        assert!(chunker.is_supported("test.rs"));
        assert!(chunker.is_supported("test.js"));
        assert!(chunker.is_supported("test.ts"));
        assert!(chunker.is_supported("test.tsx"));
        assert!(chunker.is_supported("test.go"));
        assert!(chunker.is_supported("test.java"));
        assert!(chunker.is_supported("test.c"));
        assert!(chunker.is_supported("test.cpp"));
        assert!(chunker.is_supported("test.cs"));
        assert!(chunker.is_supported("test.md"));
        assert!(!chunker.is_supported("test.xyz"));
    }

    #[test]
    fn test_language_detection() {
        let chunker = MultiLanguageChunker::new();
        assert_eq!(chunker.language_for_file("test.py"), Some("python"));
        assert_eq!(chunker.language_for_file("test.rs"), Some("rust"));
        assert_eq!(chunker.language_for_file("test.ts"), Some("typescript"));
        assert_eq!(chunker.language_for_file("test.tsx"), Some("tsx"));
    }

    #[test]
    fn test_chunk_python() {
        let chunker = MultiLanguageChunker::new();
        let source = r#"
def hello(name):
    """Say hello to someone."""
    print(f"Hello, {name}!")

class Greeter:
    """A greeter class."""

    def greet(self, name):
        return f"Hello, {name}!"
"#;
        let chunks = chunker
            .chunk_file("/test/hello.py", "hello.py", source)
            .unwrap();
        assert!(!chunks.is_empty());
        // Should have: hello function, Greeter class, greet method
        let names: Vec<_> = chunks.iter().filter_map(|c| c.name.as_deref()).collect();
        assert!(names.contains(&"hello"));
        assert!(names.contains(&"Greeter"));
        assert!(names.contains(&"greet"));
    }

    #[test]
    fn test_chunk_rust() {
        let chunker = MultiLanguageChunker::new();
        let source = r#"
pub struct Config {
    pub name: String,
    pub value: i32,
}

impl Config {
    pub fn new(name: String) -> Self {
        Self { name, value: 0 }
    }

    pub fn set_value(&mut self, value: i32) {
        self.value = value;
    }
}

pub fn process(config: &Config) -> String {
    format!("{}: {}", config.name, config.value)
}
"#;
        let chunks = chunker
            .chunk_file("/test/config.rs", "config.rs", source)
            .unwrap();
        assert!(!chunks.is_empty());
        let names: Vec<_> = chunks.iter().filter_map(|c| c.name.as_deref()).collect();
        assert!(names.contains(&"Config"));
        assert!(names.contains(&"process"));
    }

    #[test]
    fn test_chunk_javascript() {
        let chunker = MultiLanguageChunker::new();
        let source = r#"
function fetchUser(id) {
    return fetch(`/api/users/${id}`);
}

class UserService {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
    }

    getUser(id) {
        return fetch(`${this.baseUrl}/users/${id}`);
    }
}
"#;
        let chunks = chunker
            .chunk_file("/test/user.js", "user.js", source)
            .unwrap();
        assert!(!chunks.is_empty());
        let names: Vec<_> = chunks.iter().filter_map(|c| c.name.as_deref()).collect();
        assert!(names.contains(&"fetchUser"));
        assert!(names.contains(&"UserService"));
    }
}
