use crate::tools::{ClearIndexParams, GetStatusParams, IndexCodebaseParams, SearchCodeParams};
use crate::tools::DownloadModelParams;
use qex_core::index::IncrementalIndexer;
use rmcp::{
    ErrorData as McpError, ServerHandler,
    handler::server::tool::ToolRouter,
    handler::server::wrapper::Parameters,
    model::{CallToolResult, Content, Implementation, ServerCapabilities, ServerInfo},
    tool, tool_handler, tool_router,
};
use std::path::Path;
use std::sync::Arc;

#[derive(Clone)]
pub struct QexServer {
    indexer: Arc<IncrementalIndexer>,
    tool_router: ToolRouter<Self>,
}

#[tool_router]
impl QexServer {
    pub fn new() -> Self {
        Self {
            indexer: Arc::new(IncrementalIndexer::new()),
            tool_router: Self::tool_router(),
        }
    }

    #[tool(
        name = "index_codebase",
        description = "Index a codebase directory for semantic code search. Uses tree-sitter to parse code into semantic chunks (functions, classes, methods) and builds a BM25 search index. Supports Python, JavaScript, TypeScript, Rust, Go, Java, C, C++, C#, and Markdown."
    )]
    async fn index_codebase(
        &self,
        params: Parameters<IndexCodebaseParams>,
    ) -> Result<CallToolResult, McpError> {
        let params = params.0;
        let path = Path::new(&params.path);
        if !path.exists() {
            return Err(McpError::invalid_params(
                format!("Directory does not exist: {}", params.path),
                None,
            ));
        }
        if !path.is_dir() {
            return Err(McpError::invalid_params(
                format!("Path is not a directory: {}", params.path),
                None,
            ));
        }

        let force = params.force.unwrap_or(false);
        let extensions: Option<Vec<&str>> = params
            .extensions
            .as_ref()
            .map(|exts| exts.iter().map(|s| s.as_str()).collect());

        let result = self
            .indexer
            .auto_index(path, force, extensions.as_deref())
            .map_err(|e| McpError::internal_error(format!("Indexing failed: {}", e), None))?;

        let response = serde_json::json!({
            "files_indexed": result.files_indexed,
            "chunks_created": result.chunks_created,
            "time_taken_ms": result.time_taken_ms,
            "languages": result.languages,
            "incremental": result.incremental,
        });

        Ok(CallToolResult::success(vec![Content::text(
            serde_json::to_string_pretty(&response).unwrap_or_default(),
        )]))
    }

    #[tool(
        name = "search_code",
        description = "Search indexed codebase using natural language or keywords. Returns ranked code chunks with file paths, line numbers, and relevance scores. Auto-indexes if the project hasn't been indexed yet. Uses hybrid BM25 + dense vector search when the embedding model is available, falls back to BM25-only otherwise. Supports queries like 'authentication logic', 'database connection', 'error handling', function/class names, etc."
    )]
    async fn search_code(
        &self,
        params: Parameters<SearchCodeParams>,
    ) -> Result<CallToolResult, McpError> {
        let params = params.0;
        let path = Path::new(&params.path);
        if !path.exists() || !path.is_dir() {
            return Err(McpError::invalid_params(
                format!("Invalid directory: {}", params.path),
                None,
            ));
        }

        let limit = params.limit.unwrap_or(10);

        let results = self
            .indexer
            .search(
                path,
                &params.query,
                limit,
                params.extension_filter.as_deref(),
            )
            .map_err(|e| McpError::internal_error(format!("Search failed: {}", e), None))?;

        if results.is_empty() {
            return Ok(CallToolResult::success(vec![Content::text(
                "No results found. Try different search terms or index the codebase first with index_codebase.",
            )]));
        }

        let mut output = String::new();
        for (i, result) in results.iter().enumerate() {
            output.push_str(&format!(
                "## Result {} (score: {:.3})\n",
                i + 1,
                result.score
            ));
            output.push_str(&format!(
                "**{}** `{}` in `{}`\n",
                result.chunk_type,
                result.name.as_deref().unwrap_or("<unnamed>"),
                result.relative_path,
            ));
            output.push_str(&format!(
                "Lines {}-{} | Language: {}\n",
                result.start_line, result.end_line, result.language
            ));
            if !result.tags.is_empty() {
                output.push_str(&format!("Tags: {}\n", result.tags.join(", ")));
            }
            output.push_str(&format!(
                "\n```{}\n{}\n```\n\n",
                result.language, result.content
            ));
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    #[tool(
        name = "get_indexing_status",
        description = "Check the indexing status of a project directory. Returns whether it's indexed, file count, chunk count, last indexed time, and supported languages found."
    )]
    async fn get_indexing_status(
        &self,
        params: Parameters<GetStatusParams>,
    ) -> Result<CallToolResult, McpError> {
        let params = params.0;
        let path = Path::new(&params.path);

        let status = self
            .indexer
            .get_status(path)
            .map_err(|e| McpError::internal_error(format!("Status check failed: {}", e), None))?;

        #[allow(unused_mut)]
        let mut response = serde_json::json!({
            "indexed": status.indexed,
            "file_count": status.file_count,
            "chunk_count": status.chunk_count,
            "last_indexed": status.last_indexed,
            "languages": status.languages,
        });

        // Add dense search info
        #[cfg(feature = "dense")]
        {
            use qex_core::search::embedding::EmbeddingModel;
            response["dense_search_available"] = serde_json::json!(EmbeddingModel::is_available());
        }

        Ok(CallToolResult::success(vec![Content::text(
            serde_json::to_string_pretty(&response).unwrap_or_default(),
        )]))
    }

    #[tool(
        name = "clear_index",
        description = "Clear the search index for a project directory. Removes all indexed data including the BM25 index, Merkle snapshots, and metadata."
    )]
    async fn clear_index(
        &self,
        params: Parameters<ClearIndexParams>,
    ) -> Result<CallToolResult, McpError> {
        let params = params.0;
        let path = Path::new(&params.path);

        self.indexer
            .clear_index(path)
            .map_err(|e| McpError::internal_error(format!("Clear failed: {}", e), None))?;

        Ok(CallToolResult::success(vec![Content::text(format!(
            "Index cleared for {}",
            params.path
        ))]))
    }

    #[tool(
        name = "download_model",
        description = "Download the embedding model (snowflake-arctic-embed-s, 33MB) for dense vector search. Once downloaded, search_code will automatically use hybrid BM25 + semantic search for better results."
    )]
    async fn download_model(
        &self,
        params: Parameters<DownloadModelParams>,
    ) -> Result<CallToolResult, McpError> {
        #[cfg(not(feature = "dense"))]
        {
            let _ = params;
            return Err(McpError::invalid_params(
                "Dense search not enabled. Build with --features dense to enable.".to_string(),
                None,
            ));
        }

        #[cfg(feature = "dense")]
        {
            use qex_core::search::embedding::EmbeddingModel;

            let force = params.0.force.unwrap_or(false);

            if !force && EmbeddingModel::is_available() {
                return Ok(CallToolResult::success(vec![Content::text(
                    "Embedding model already downloaded. Use force: true to re-download.",
                )]));
            }

            let model_dir = EmbeddingModel::default_model_dir()
                .map_err(|e| McpError::internal_error(format!("Failed to get model dir: {}", e), None))?;

            let model_url = "https://huggingface.co/Snowflake/snowflake-arctic-embed-s/resolve/main/onnx/model_quantized.onnx";
            let tokenizer_url = "https://huggingface.co/Snowflake/snowflake-arctic-embed-s/resolve/main/tokenizer.json";

            std::fs::create_dir_all(&model_dir)
                .map_err(|e| McpError::internal_error(format!("Failed to create model dir: {}", e), None))?;

            let model_path = model_dir.join("model.onnx");
            let tokenizer_path = model_dir.join("tokenizer.json");

            for (url, dest) in [(model_url, &model_path), (tokenizer_url, &tokenizer_path)] {
                let output = std::process::Command::new("curl")
                    .args(["-fSL", "-o", dest.to_str().unwrap(), url])
                    .output()
                    .map_err(|e| McpError::internal_error(format!("curl failed: {}", e), None))?;

                if !output.status.success() {
                    return Err(McpError::internal_error(
                        format!("Download failed: {}", String::from_utf8_lossy(&output.stderr)),
                        None,
                    ));
                }
            }

            let response = serde_json::json!({
                "status": "downloaded",
                "model_dir": model_dir.to_string_lossy(),
                "model": "snowflake-arctic-embed-s",
                "dimensions": 384,
            });

            Ok(CallToolResult::success(vec![Content::text(
                serde_json::to_string_pretty(&response).unwrap_or_default(),
            )]))
        }
    }
}

#[tool_handler]
impl ServerHandler for QexServer {
    fn get_info(&self) -> ServerInfo {
        ServerInfo {
            instructions: Some(
                "Semantic code search server. Index codebases and search for code using natural language queries. \
                 Supports 10+ programming languages with tree-sitter parsing and BM25 ranking."
                    .to_string(),
            ),
            capabilities: ServerCapabilities::builder().enable_tools().build(),
            server_info: Implementation {
                name: "qex".to_string(),
                version: env!("CARGO_PKG_VERSION").to_string(),
                title: None,
                description: None,
                icons: None,
                website_url: None,
            },
            ..Default::default()
        }
    }
}
