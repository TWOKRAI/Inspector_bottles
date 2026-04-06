use serde::Deserialize;

/// Parameters for the index_codebase tool
#[derive(Debug, Deserialize, rmcp::schemars::JsonSchema)]
pub struct IndexCodebaseParams {
    /// Absolute path to the project directory to index
    pub path: String,

    /// Force a full re-index even if an index exists
    pub force: Option<bool>,

    /// Only index files with these extensions (e.g., ["py", "rs", "ts"])
    pub extensions: Option<Vec<String>>,
}

/// Parameters for the search_code tool
#[derive(Debug, Deserialize, rmcp::schemars::JsonSchema)]
pub struct SearchCodeParams {
    /// Absolute path to the project directory
    pub path: String,

    /// Natural language or keyword search query
    pub query: String,

    /// Maximum number of results to return (default: 10)
    pub limit: Option<usize>,

    /// Filter results to a specific file extension (e.g., "py")
    pub extension_filter: Option<String>,
}

/// Parameters for the get_indexing_status tool
#[derive(Debug, Deserialize, rmcp::schemars::JsonSchema)]
pub struct GetStatusParams {
    /// Absolute path to the project directory
    pub path: String,
}

/// Parameters for the clear_index tool
#[derive(Debug, Deserialize, rmcp::schemars::JsonSchema)]
pub struct ClearIndexParams {
    /// Absolute path to the project directory
    pub path: String,
}

/// Parameters for the download_model tool
#[derive(Debug, Deserialize, rmcp::schemars::JsonSchema)]
#[allow(dead_code)]
pub struct DownloadModelParams {
    /// Force re-download even if model already exists
    pub force: Option<bool>,
}
