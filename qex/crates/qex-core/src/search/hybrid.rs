//! Hybrid search combining BM25 and dense vector results via Reciprocal Rank Fusion.
//!
//! Only compiled when the `dense` feature is enabled.

use crate::search::SearchResult;
use std::collections::HashMap;

/// RRF constant (controls how much top ranks are favored)
const RRF_K: f32 = 60.0;

/// Merge BM25 and dense search results using Reciprocal Rank Fusion.
///
/// RRF score for each document = Σ 1/(k + rank_i) across all result lists.
/// Documents appearing in both lists get higher scores.
pub fn reciprocal_rank_fusion(
    bm25_results: &[SearchResult],
    dense_matches: &[(String, f32)], // (chunk_id, similarity)
    bm25_results_map: &HashMap<String, SearchResult>, // chunk_id -> full result
) -> Vec<SearchResult> {
    let mut rrf_scores: HashMap<String, f32> = HashMap::new();

    // Score BM25 results by rank
    for (rank, result) in bm25_results.iter().enumerate() {
        let score = 1.0 / (RRF_K + rank as f32 + 1.0);
        *rrf_scores.entry(result.chunk_id.clone()).or_insert(0.0) += score;
    }

    // Score dense results by rank
    for (rank, (chunk_id, _similarity)) in dense_matches.iter().enumerate() {
        let score = 1.0 / (RRF_K + rank as f32 + 1.0);
        *rrf_scores.entry(chunk_id.clone()).or_insert(0.0) += score;
    }

    // Build final result list
    let mut fused: Vec<(String, f32)> = rrf_scores.into_iter().collect();
    fused.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    let mut results = Vec::new();
    for (chunk_id, rrf_score) in fused {
        // Try to find the full SearchResult from BM25 results first
        if let Some(result) = bm25_results.iter().find(|r| r.chunk_id == chunk_id) {
            let mut r = result.clone();
            r.score = rrf_score * 1000.0; // Scale for readability
            results.push(r);
        } else if let Some(result) = bm25_results_map.get(&chunk_id) {
            // Dense-only result — use the full result from the map
            let mut r = result.clone();
            r.score = rrf_score * 1000.0;
            results.push(r);
        }
        // If chunk_id not found in either, skip it (orphaned dense result)
    }

    results
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::chunk::ChunkType;

    fn make_result(id: &str, score: f32) -> SearchResult {
        SearchResult {
            chunk_id: id.to_string(),
            score,
            content: format!("content of {}", id),
            file_path: format!("/test/{}.py", id),
            relative_path: format!("{}.py", id),
            folder_structure: Vec::new(),
            chunk_type: ChunkType::Function,
            name: Some(id.to_string()),
            parent_name: None,
            start_line: 1,
            end_line: 10,
            language: "python".to_string(),
            docstring: None,
            tags: Vec::new(),
        }
    }

    #[test]
    fn test_rrf_both_lists() {
        // BM25 ranks: A=1, B=2, C=3
        let bm25 = vec![
            make_result("A", 100.0),
            make_result("B", 90.0),
            make_result("C", 80.0),
        ];

        // Dense ranks: B=1, D=2, A=3
        let dense = vec![
            ("B".to_string(), 0.95),
            ("D".to_string(), 0.90),
            ("A".to_string(), 0.85),
        ];

        let map: HashMap<String, SearchResult> = vec![
            ("A".to_string(), make_result("A", 0.0)),
            ("B".to_string(), make_result("B", 0.0)),
            ("C".to_string(), make_result("C", 0.0)),
            ("D".to_string(), make_result("D", 0.0)),
        ]
        .into_iter()
        .collect();

        let fused = reciprocal_rank_fusion(&bm25, &dense, &map);

        // B should be first (rank 2 in BM25 + rank 1 in dense = highest combined)
        assert_eq!(fused[0].chunk_id, "B", "B should be top (in both lists, high ranks)");
        // A should be second (rank 1 in BM25 + rank 3 in dense)
        assert_eq!(fused[1].chunk_id, "A", "A should be second");
    }

    #[test]
    fn test_rrf_empty_dense() {
        let bm25 = vec![make_result("A", 100.0), make_result("B", 90.0)];
        let dense: Vec<(String, f32)> = Vec::new();
        let map = HashMap::new();

        let fused = reciprocal_rank_fusion(&bm25, &dense, &map);
        assert_eq!(fused.len(), 2);
        assert_eq!(fused[0].chunk_id, "A");
    }
}
