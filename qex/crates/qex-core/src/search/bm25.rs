use crate::chunk::{ChunkType, CodeChunk};
use crate::search::SearchResult;
use anyhow::{Context, Result};
use std::collections::HashMap;
use std::path::Path;
use tantivy::collector::TopDocs;
use tantivy::query::QueryParser;
use tantivy::schema::*;
use tantivy::{doc, Index, IndexWriter, ReloadPolicy};

/// BM25 full-text search index backed by Tantivy
pub struct BM25Index {
    index: Index,
    // Schema fields
    f_chunk_id: Field,
    f_content: Field,
    f_name: Field,
    f_docstring: Field,
    f_path_tokens: Field,
    f_tags: Field,
    f_file_path: Field,
    f_relative_path: Field,
    f_chunk_type: Field,
    f_start_line: Field,
    f_end_line: Field,
    f_language: Field,
    f_parent_name: Field,
    f_folder_structure: Field,
    f_json_data: Field,
}

impl BM25Index {
    /// Create or open a BM25 index at the given path
    pub fn open(index_path: &Path) -> Result<Self> {
        let schema = Self::build_schema();

        let index = if index_path.exists() && index_path.join("meta.json").exists() {
            Index::open_in_dir(index_path)
                .context("Failed to open existing tantivy index")?
        } else {
            std::fs::create_dir_all(index_path)
                .context("Failed to create index directory")?;
            Index::create_in_dir(index_path, schema.clone())
                .context("Failed to create tantivy index")?
        };

        let f_chunk_id = schema.get_field("chunk_id").unwrap();
        let f_content = schema.get_field("content").unwrap();
        let f_name = schema.get_field("name").unwrap();
        let f_docstring = schema.get_field("docstring").unwrap();
        let f_path_tokens = schema.get_field("path_tokens").unwrap();
        let f_tags = schema.get_field("tags").unwrap();
        let f_file_path = schema.get_field("file_path").unwrap();
        let f_relative_path = schema.get_field("relative_path").unwrap();
        let f_chunk_type = schema.get_field("chunk_type").unwrap();
        let f_start_line = schema.get_field("start_line").unwrap();
        let f_end_line = schema.get_field("end_line").unwrap();
        let f_language = schema.get_field("language").unwrap();
        let f_parent_name = schema.get_field("parent_name").unwrap();
        let f_folder_structure = schema.get_field("folder_structure").unwrap();
        let f_json_data = schema.get_field("json_data").unwrap();

        Ok(Self {
            index,
            f_chunk_id,
            f_content,
            f_name,
            f_docstring,
            f_path_tokens,
            f_tags,
            f_file_path,
            f_relative_path,
            f_chunk_type,
            f_start_line,
            f_end_line,
            f_language,
            f_parent_name,
            f_folder_structure,
            f_json_data,
        })
    }

    fn build_schema() -> Schema {
        let mut builder = Schema::builder();

        // Stored + indexed fields for search
        builder.add_text_field("chunk_id", STRING | STORED);
        builder.add_text_field("content", TEXT | STORED);
        builder.add_text_field("name", TEXT | STORED);
        builder.add_text_field("docstring", TEXT | STORED);
        builder.add_text_field("path_tokens", TEXT | STORED);
        builder.add_text_field("tags", TEXT | STORED);

        // Stored + indexed metadata fields
        builder.add_text_field("file_path", STRING | STORED);
        builder.add_text_field("relative_path", STRING | STORED);
        builder.add_text_field("chunk_type", STRING | STORED);
        builder.add_u64_field("start_line", STORED);
        builder.add_u64_field("end_line", STORED);
        builder.add_text_field("language", STRING | STORED);
        builder.add_text_field("parent_name", STORED);
        builder.add_text_field("folder_structure", STORED);

        // Full chunk data as JSON for reconstruction
        builder.add_text_field("json_data", STORED);

        builder.build()
    }

    /// Add chunks to the index
    pub fn add_chunks(&self, chunks: &[CodeChunk]) -> Result<usize> {
        let mut writer: IndexWriter = self
            .index
            .writer(50_000_000) // 50MB heap
            .context("Failed to create index writer")?;

        let mut count = 0;
        for chunk in chunks {
            let path_tokens = crate::search::query::tokenize(&chunk.relative_path).join(" ");
            let tags_text = chunk.tags.join(" ");
            let folder_text = chunk.folder_structure.join("/");
            let json_data = serde_json::to_string(chunk).unwrap_or_default();

            writer.add_document(doc!(
                self.f_chunk_id => chunk.id.as_str(),
                self.f_content => chunk.content.as_str(),
                self.f_name => chunk.name.as_deref().unwrap_or(""),
                self.f_docstring => chunk.docstring.as_deref().unwrap_or(""),
                self.f_path_tokens => path_tokens.as_str(),
                self.f_tags => tags_text.as_str(),
                self.f_file_path => chunk.file_path.as_str(),
                self.f_relative_path => chunk.relative_path.as_str(),
                self.f_chunk_type => chunk.chunk_type.to_string(),
                self.f_start_line => chunk.start_line as u64,
                self.f_end_line => chunk.end_line as u64,
                self.f_language => chunk.language.as_str(),
                self.f_parent_name => chunk.parent_name.as_deref().unwrap_or(""),
                self.f_folder_structure => folder_text.as_str(),
                self.f_json_data => json_data.as_str(),
            ))?;
            count += 1;
        }

        writer.commit().context("Failed to commit index")?;
        Ok(count)
    }

    /// Sanitize query string by removing/escaping Tantivy query syntax characters
    fn sanitize_query(query: &str) -> String {
        let sanitized: String = query
            .chars()
            .map(|c| match c {
                // Keep alphanumeric, underscore, hyphen, dot, slash, colon (useful for code search)
                c if c.is_alphanumeric() || c == '_' || c == '-' || c == '.' || c == '/' || c == ':' => c,
                // Keep whitespace
                c if c.is_whitespace() => ' ',
                // Everything else becomes space
                _ => ' ',
            })
            .collect();

        // Replace "--" (NOT operator) with space
        let sanitized = sanitized.replace("--", " ");

        // Collapse multiple spaces
        sanitized.split_whitespace().collect::<Vec<_>>().join(" ")
    }

    /// Search the index
    pub fn search(&self, query_str: &str, limit: usize) -> Result<Vec<SearchResult>> {
        // Sanitize query to prevent Tantivy parse errors from special chars
        let query_str = Self::sanitize_query(query_str);
        if query_str.is_empty() {
            return Ok(Vec::new());
        }

        let reader = self
            .index
            .reader_builder()
            .reload_policy(ReloadPolicy::OnCommitWithDelay)
            .try_into()
            .context("Failed to create index reader")?;

        let searcher = reader.searcher();

        // Search across content, name, docstring, path_tokens, tags
        // BM25F-style field boosting: symbol names >> path >> content
        let mut query_parser = QueryParser::for_index(
            &self.index,
            vec![
                self.f_content,
                self.f_name,
                self.f_docstring,
                self.f_path_tokens,
                self.f_tags,
            ],
        );
        query_parser.set_field_boost(self.f_name, 5.0);
        query_parser.set_field_boost(self.f_path_tokens, 2.0);
        query_parser.set_field_boost(self.f_docstring, 1.5);
        query_parser.set_field_boost(self.f_tags, 1.5);

        let query = match query_parser.parse_query(&query_str) {
            Ok(q) => q,
            Err(_) => {
                // Gracefully handle unparseable queries (e.g., only special chars)
                return Ok(Vec::new());
            }
        };

        // Always fetch enough candidates for re-ranking (min 50)
        let fetch_limit = (limit * 5).max(50);
        let top_docs = searcher
            .search(&query, &TopDocs::with_limit(fetch_limit))
            .context("Search failed")?;

        let mut results = Vec::new();
        for (score, doc_address) in top_docs {
            let doc: tantivy::TantivyDocument = searcher.doc(doc_address)?;

            // Try to reconstruct from json_data first
            if let Some(json_val) = doc.get_first(self.f_json_data) {
                if let Some(json_str) = json_val.as_str() {
                    if let Ok(chunk) = serde_json::from_str::<CodeChunk>(json_str) {
                        results.push(SearchResult::from_chunk(&chunk, score));
                        continue;
                    }
                }
            }

            // Fallback: reconstruct from individual fields
            let get_text = |field: Field| -> String {
                doc.get_first(field)
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string()
            };
            let get_u64 = |field: Field| -> u64 {
                doc.get_first(field)
                    .and_then(|v| v.as_u64())
                    .unwrap_or(0)
            };

            let chunk_type_str = get_text(self.f_chunk_type);
            let chunk_type = match chunk_type_str.as_str() {
                "function" => ChunkType::Function,
                "method" => ChunkType::Method,
                "class" => ChunkType::Class,
                "struct" => ChunkType::Struct,
                "enum" => ChunkType::Enum,
                "interface" => ChunkType::Interface,
                "trait" => ChunkType::Trait,
                "impl" => ChunkType::Impl,
                "module" => ChunkType::Module,
                "module_level" => ChunkType::ModuleLevel,
                "import_block" => ChunkType::ImportBlock,
                "namespace" => ChunkType::Namespace,
                "macro" => ChunkType::Macro,
                "section" => ChunkType::Section,
                "document" => ChunkType::Document,
                _ => ChunkType::ModuleLevel,
            };

            let name_str = get_text(self.f_name);
            let parent_str = get_text(self.f_parent_name);
            let docstring_str = get_text(self.f_docstring);
            let tags_str = get_text(self.f_tags);
            let folder_str = get_text(self.f_folder_structure);

            results.push(SearchResult {
                chunk_id: get_text(self.f_chunk_id),
                score,
                content: get_text(self.f_content),
                file_path: get_text(self.f_file_path),
                relative_path: get_text(self.f_relative_path),
                folder_structure: if folder_str.is_empty() {
                    Vec::new()
                } else {
                    folder_str.split('/').map(String::from).collect()
                },
                chunk_type,
                name: if name_str.is_empty() { None } else { Some(name_str) },
                parent_name: if parent_str.is_empty() { None } else { Some(parent_str) },
                start_line: get_u64(self.f_start_line) as usize,
                end_line: get_u64(self.f_end_line) as usize,
                language: get_text(self.f_language),
                docstring: if docstring_str.is_empty() { None } else { Some(docstring_str) },
                tags: if tags_str.is_empty() {
                    Vec::new()
                } else {
                    tags_str.split_whitespace().map(String::from).collect()
                },
            });
        }

        Ok(results)
    }

    /// Remove all documents matching a file path
    pub fn remove_file(&self, file_path: &str) -> Result<()> {
        let mut writer: IndexWriter = self
            .index
            .writer(50_000_000)
            .context("Failed to create index writer")?;

        let term = tantivy::Term::from_field_text(self.f_file_path, file_path);
        writer.delete_term(term);
        writer.commit().context("Failed to commit deletion")?;

        Ok(())
    }

    /// Clear the entire index
    pub fn clear(&self) -> Result<()> {
        let mut writer: IndexWriter = self
            .index
            .writer(50_000_000)
            .context("Failed to create index writer")?;

        writer.delete_all_documents()?;
        writer.commit().context("Failed to commit clear")?;

        Ok(())
    }

    /// Look up specific chunks by their IDs (for dense-only results in hybrid search)
    pub fn get_by_chunk_ids(&self, chunk_ids: &[&str]) -> Result<HashMap<String, SearchResult>> {
        if chunk_ids.is_empty() {
            return Ok(HashMap::new());
        }

        let reader = self
            .index
            .reader_builder()
            .reload_policy(ReloadPolicy::OnCommitWithDelay)
            .try_into()
            .context("Failed to create reader")?;

        let searcher = reader.searcher();
        let mut results_map = HashMap::new();

        for &cid in chunk_ids {
            let term = tantivy::Term::from_field_text(self.f_chunk_id, cid);
            let term_query = tantivy::query::TermQuery::new(term, tantivy::schema::IndexRecordOption::Basic);
            if let Ok(top_docs) = searcher.search(&term_query, &tantivy::collector::TopDocs::with_limit(1)) {
                for (_score, doc_address) in top_docs {
                    if let Ok(doc) = searcher.doc::<tantivy::TantivyDocument>(doc_address) {
                        let get_text = |field: Field| -> String {
                            doc.get_first(field)
                                .and_then(|v| v.as_str())
                                .unwrap_or("")
                                .to_string()
                        };
                        let get_u64 = |field: Field| -> u64 {
                            doc.get_first(field).and_then(|v| v.as_u64()).unwrap_or(0)
                        };

                        let chunk_type_str = get_text(self.f_chunk_type);
                        let chunk_type = match chunk_type_str.as_str() {
                            "function" => ChunkType::Function,
                            "method" => ChunkType::Method,
                            "class" => ChunkType::Class,
                            "struct" => ChunkType::Struct,
                            "enum" => ChunkType::Enum,
                            "interface" => ChunkType::Interface,
                            "trait" => ChunkType::Trait,
                            "impl" => ChunkType::Impl,
                            "module" => ChunkType::Module,
                            "module_level" => ChunkType::ModuleLevel,
                            _ => ChunkType::ModuleLevel,
                        };

                        let name_str = get_text(self.f_name);
                        let parent_str = get_text(self.f_parent_name);
                        let docstring_str = get_text(self.f_docstring);
                        let tags_str = get_text(self.f_tags);
                        let folder_str = get_text(self.f_folder_structure);

                        let result = SearchResult {
                            chunk_id: get_text(self.f_chunk_id),
                            score: 0.0,
                            content: get_text(self.f_content),
                            file_path: get_text(self.f_file_path),
                            relative_path: get_text(self.f_relative_path),
                            folder_structure: if folder_str.is_empty() {
                                Vec::new()
                            } else {
                                folder_str.split('/').map(String::from).collect()
                            },
                            chunk_type,
                            name: if name_str.is_empty() { None } else { Some(name_str) },
                            parent_name: if parent_str.is_empty() { None } else { Some(parent_str) },
                            start_line: get_u64(self.f_start_line) as usize,
                            end_line: get_u64(self.f_end_line) as usize,
                            language: get_text(self.f_language),
                            docstring: if docstring_str.is_empty() { None } else { Some(docstring_str) },
                            tags: if tags_str.is_empty() {
                                Vec::new()
                            } else {
                                tags_str.split_whitespace().map(String::from).collect()
                            },
                        };
                        results_map.insert(cid.to_string(), result);
                    }
                }
            }
        }

        Ok(results_map)
    }

    /// Get the number of documents in the index
    pub fn doc_count(&self) -> Result<u64> {
        let reader = self
            .index
            .reader_builder()
            .reload_policy(ReloadPolicy::OnCommitWithDelay)
            .try_into()
            .context("Failed to create reader")?;

        let searcher = reader.searcher();
        Ok(searcher.num_docs())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn make_chunk(name: &str, content: &str, chunk_type: ChunkType) -> CodeChunk {
        CodeChunk {
            id: CodeChunk::generate_id("/test", 1, 10, Some(name)),
            content: content.to_string(),
            chunk_type: chunk_type.clone(),
            start_line: 1,
            end_line: 10,
            file_path: "/test/file.py".to_string(),
            relative_path: "file.py".to_string(),
            folder_structure: Vec::new(),
            name: Some(name.to_string()),
            parent_name: None,
            language: "python".to_string(),
            docstring: None,
            decorators: Vec::new(),
            imports: Vec::new(),
            tags: CodeChunk::extract_tags(content, &chunk_type),
            complexity_score: 5,
        }
    }

    #[test]
    fn test_bm25_add_and_search() {
        let dir = TempDir::new().unwrap();
        let index = BM25Index::open(dir.path()).unwrap();

        let chunks = vec![
            make_chunk(
                "authenticate_user",
                "def authenticate_user(username, password):\n    # Check credentials\n    return True",
                ChunkType::Function,
            ),
            make_chunk(
                "get_user_profile",
                "def get_user_profile(user_id):\n    # Fetch user data\n    return {}",
                ChunkType::Function,
            ),
            make_chunk(
                "DatabaseConnection",
                "class DatabaseConnection:\n    def connect(self):\n        pass",
                ChunkType::Class,
            ),
        ];

        let count = index.add_chunks(&chunks).unwrap();
        assert_eq!(count, 3);
        assert_eq!(index.doc_count().unwrap(), 3);

        // Search for authentication
        let results = index.search("authenticate", 10).unwrap();
        assert!(!results.is_empty());
        assert_eq!(results[0].name.as_deref(), Some("authenticate_user"));

        // Search for database
        let results = index.search("database connection", 10).unwrap();
        assert!(!results.is_empty());
    }

    #[test]
    fn test_bm25_remove_file() {
        let dir = TempDir::new().unwrap();
        let index = BM25Index::open(dir.path()).unwrap();

        let chunks = vec![make_chunk("test_fn", "def test(): pass", ChunkType::Function)];
        index.add_chunks(&chunks).unwrap();
        assert_eq!(index.doc_count().unwrap(), 1);

        index.remove_file("/test/file.py").unwrap();
        assert_eq!(index.doc_count().unwrap(), 0);
    }

    #[test]
    fn test_bm25_clear() {
        let dir = TempDir::new().unwrap();
        let index = BM25Index::open(dir.path()).unwrap();

        let chunks = vec![
            make_chunk("fn1", "def fn1(): pass", ChunkType::Function),
            make_chunk("fn2", "def fn2(): pass", ChunkType::Function),
        ];
        index.add_chunks(&chunks).unwrap();
        assert_eq!(index.doc_count().unwrap(), 2);

        index.clear().unwrap();
        assert_eq!(index.doc_count().unwrap(), 0);
    }

    #[test]
    fn test_sanitize_query() {
        // Special characters stripped, keep alphanumeric + _-./:
        assert_eq!(BM25Index::sanitize_query("def __init__(self)"), "def __init__ self");
        assert_eq!(BM25Index::sanitize_query("get_by_id"), "get_by_id");
        assert_eq!(BM25Index::sanitize_query("DROP TABLE users --"), "DROP TABLE users");
        assert_eq!(BM25Index::sanitize_query("@#$%^&*()"), "");
        // Empty / control chars
        assert_eq!(BM25Index::sanitize_query(""), "");
        assert_eq!(BM25Index::sanitize_query("\x00\x01"), "");
        // Normal queries unchanged
        assert_eq!(BM25Index::sanitize_query("middleware auth"), "middleware auth");
        // Keep useful code chars
        assert_eq!(BM25Index::sanitize_query("src/main.rs:42"), "src/main.rs:42");
    }

    #[test]
    fn test_search_with_special_chars_no_crash() {
        let dir = TempDir::new().unwrap();
        let index = BM25Index::open(dir.path()).unwrap();
        let chunks = vec![make_chunk("__init__", "def __init__(self): pass", ChunkType::Method)];
        index.add_chunks(&chunks).unwrap();

        // These should not crash
        let r = index.search("def __init__(self)", 5);
        assert!(r.is_ok());
        let r = index.search("'; DROP TABLE --", 5);
        assert!(r.is_ok());
        let r = index.search("", 5);
        assert!(r.is_ok());
        assert!(r.unwrap().is_empty());
    }
}
