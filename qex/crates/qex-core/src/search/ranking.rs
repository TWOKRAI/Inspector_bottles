use crate::chunk::ChunkType;
use crate::search::query::{AnalyzedQuery, QueryIntent};
use crate::search::SearchResult;
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

// ── Locale pattern for deduplication ──────────────────────────────────
static LOCALE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?:^|/)(?:i18n|locales?|translations?|lang|docs)/([a-z]{2}(?:[_-][A-Za-z]{2,4})?)(?:/|$)")
        .unwrap()
});

/// Full ranking pipeline: boost → dedup → threshold → truncate
pub fn rank_results(results: &mut Vec<SearchResult>, query: &AnalyzedQuery, limit: usize) {
    // Phase 1: Multi-factor score boosting
    for result in results.iter_mut() {
        let mut score = result.score;

        score *= file_type_boost(&result.relative_path, &result.language);
        score *= type_boost(&result.chunk_type, query);
        score *= name_boost(result.name.as_deref(), query);
        score *= path_boost(&result.relative_path, query);
        score *= tag_boost(&result.tags, &query.intents);
        score *= docstring_boost(
            result.docstring.is_some(),
            query.is_entity_query,
            &result.chunk_type,
        );
        score *= complexity_penalty(&result.content);

        result.score = score;
    }

    // Phase 2: Sort by score descending
    results.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    // Phase 3: Path-based deduplication (translations / i18n)
    deduplicate_translations(results);

    // Phase 4: Score thresholding — drop clearly irrelevant tail
    apply_score_threshold(results);

    // Phase 5: Truncate to limit
    results.truncate(limit);
}

// ── NEW: File type / path boost ──────────────────────────────────────
// Sourcegraph-inspired: source code > config > docs; test/vendor penalized

/// Boost or penalize based on file extension and path location
fn file_type_boost(relative_path: &str, language: &str) -> f32 {
    // Extension-based: source code is baseline, docs are penalized
    let ext_boost = match language {
        "python" | "rust" | "typescript" | "tsx" | "javascript" | "go" | "java" | "c" | "cpp"
        | "csharp" => 1.0,
        "markdown" => 0.35,
        _ => 0.6,
    };

    // Path-based penalties (stackable)
    let mut path_factor: f32 = 1.0;

    let lower = relative_path.to_lowercase();

    // Documentation directories
    if lower.starts_with("docs/")
        || lower.starts_with("doc/")
        || lower.starts_with("documentation/")
        || lower.contains("/docs/")
    {
        path_factor *= 0.4;
    }

    // Test directories / files
    if lower.contains("/test/")
        || lower.contains("/tests/")
        || lower.starts_with("test/")
        || lower.starts_with("tests/")
        || lower.contains("_test.")
        || lower.contains(".test.")
        || lower.starts_with("test_")
    {
        path_factor *= 0.7;
    }

    // Vendor / third-party
    if lower.contains("/vendor/") || lower.contains("/third_party/") {
        path_factor *= 0.3;
    }

    // Example/tutorial source files (docs_src/, examples/, samples/)
    if lower.starts_with("docs_src/")
        || lower.contains("/docs_src/")
        || lower.contains("/example")
        || lower.contains("/sample")
    {
        path_factor *= 0.5;
    }

    // Source root boost: files in recognized source directories get a bonus
    // This helps core framework code rank above tests/docs for the same match
    let source_root_boost = if lower.starts_with("src/")
        || lower.starts_with("lib/")
        // Project-name root dirs (e.g., fastapi/, django/, flask/)
        || (relative_path.matches('/').count() <= 2
            && !lower.starts_with("test")
            && !lower.starts_with("doc")
            && !lower.starts_with("script")
            && !lower.starts_with(".")
            && language != "markdown")
    {
        1.15
    } else {
        1.0
    };

    // Depth penalty: root files more important (Zoekt-style)
    let depth = relative_path.matches('/').count();
    let depth_factor = 1.0 / (1.0 + depth as f32 * 0.03);

    ext_boost * path_factor * depth_factor * source_root_boost
}

// ── NEW: Translation / i18n deduplication ────────────────────────────
// Keep only the best-scored result per canonical path (strip locale segment)

fn deduplicate_translations(results: &mut Vec<SearchResult>) {
    // Map: canonical_path → index of best result
    let mut seen: HashMap<String, usize> = HashMap::new();
    let mut to_remove: Vec<bool> = vec![false; results.len()];

    for (idx, result) in results.iter().enumerate() {
        let canonical = LOCALE_RE
            .replace(&result.relative_path, "{LOCALE}/")
            .to_string();

        // Only dedup if the path actually had a locale segment
        if canonical == result.relative_path {
            continue;
        }

        match seen.get(&canonical) {
            Some(&_prev_idx) => {
                // This is a translation duplicate — mark for removal
                // (results are already sorted by score, so prev_idx has higher score)
                to_remove[idx] = true;
            }
            None => {
                seen.insert(canonical, idx);
            }
        }
    }

    // Remove marked entries in reverse order
    let mut i = to_remove.len();
    while i > 0 {
        i -= 1;
        if to_remove[i] {
            results.remove(i);
        }
    }
}

// ── NEW: Score thresholding ──────────────────────────────────────────
// Hybrid: relative threshold (15% of top) + knee-point detection

fn apply_score_threshold(results: &mut Vec<SearchResult>) {
    if results.len() <= 2 {
        return;
    }

    let top_score = results[0].score;
    if top_score <= 0.0 {
        return;
    }

    // Step 1: Remove anything below 12% of top score (clearly irrelevant)
    let min_score = top_score * 0.12;
    results.retain(|r| r.score >= min_score);

    if results.len() <= 3 {
        return;
    }

    // Step 2: Knee-point detection — find where scores drop sharply
    let gaps: Vec<f32> = results
        .windows(2)
        .map(|w| w[0].score - w[1].score)
        .collect();

    let avg_gap = gaps.iter().sum::<f32>() / gaps.len() as f32;

    // Find first gap that's 3x the average (significant drop)
    if let Some(knee) = gaps.iter().position(|&g| g > avg_gap * 3.0) {
        // Keep at least 3 results, cut after knee
        let cutoff = (knee + 1).max(3);
        results.truncate(cutoff);
    }

    // Hard cap: never return more than 50
    results.truncate(50);
}

// ── Existing boost functions (unchanged logic, cleaned up) ───────────

fn type_boost(chunk_type: &ChunkType, query: &AnalyzedQuery) -> f32 {
    if query.has_class_keyword {
        match chunk_type {
            ChunkType::Class => 1.3,
            ChunkType::Struct => 1.2,
            ChunkType::Interface | ChunkType::Trait => 1.15,
            ChunkType::Function | ChunkType::Method => 1.05,
            ChunkType::ModuleLevel | ChunkType::Section | ChunkType::Document => 0.9,
            _ => 1.0,
        }
    } else if query.is_entity_query {
        match chunk_type {
            ChunkType::Class | ChunkType::Struct => 1.15,
            ChunkType::Interface | ChunkType::Trait => 1.1,
            ChunkType::Function | ChunkType::Method => 1.1,
            ChunkType::ModuleLevel | ChunkType::Section | ChunkType::Document => 0.92,
            _ => 1.0,
        }
    } else {
        match chunk_type {
            ChunkType::Function | ChunkType::Method => 1.1,
            ChunkType::Class | ChunkType::Struct => 1.05,
            ChunkType::ModuleLevel | ChunkType::Section | ChunkType::Document => 0.95,
            _ => 1.0,
        }
    }
}

fn name_boost(name: Option<&str>, query: &AnalyzedQuery) -> f32 {
    let name = match name {
        Some(n) => n,
        None => return 1.0,
    };

    let name_lower = name.to_lowercase();
    let query_lower = query.original.to_lowercase();

    // Exact match
    if name_lower == query_lower {
        return 1.5;
    }

    // Substring containment (name contains query or vice versa)
    if name_lower.contains(&query_lower) || query_lower.contains(&name_lower) {
        return 1.35;
    }

    // Token overlap ratio
    let name_tokens: HashSet<String> = super::query::tokenize(name).into_iter().collect();
    let query_tokens: HashSet<String> = query.normalized_tokens.iter().cloned().collect();

    if query_tokens.is_empty() {
        return 1.0;
    }

    let overlap = name_tokens.intersection(&query_tokens).count();
    let ratio = overlap as f32 / query_tokens.len() as f32;

    if ratio >= 0.8 {
        1.3
    } else if ratio >= 0.5 {
        1.2
    } else if ratio >= 0.3 {
        1.1
    } else if overlap > 0 {
        1.05
    } else {
        1.0
    }
}

fn path_boost(relative_path: &str, query: &AnalyzedQuery) -> f32 {
    let path_tokens: HashSet<String> =
        super::query::tokenize(relative_path).into_iter().collect();
    let query_tokens: HashSet<String> = query.normalized_tokens.iter().cloned().collect();

    let overlap = path_tokens.intersection(&query_tokens).count();
    1.0 + (overlap as f32 * 0.05)
}

fn tag_boost(tags: &[String], intents: &HashSet<QueryIntent>) -> f32 {
    let intent_tags: HashSet<&str> = intents
        .iter()
        .map(|i| match i {
            QueryIntent::FunctionSearch => "function",
            QueryIntent::ErrorHandling => "error_handling",
            QueryIntent::Database => "database",
            QueryIntent::Api => "api",
            QueryIntent::Authentication => "auth",
            QueryIntent::Testing => "test",
        })
        .collect();

    let tag_set: HashSet<&str> = tags.iter().map(|t| t.as_str()).collect();
    let overlap = intent_tags.intersection(&tag_set).count();

    1.0 + (overlap as f32 * 0.1)
}

fn docstring_boost(has_docstring: bool, is_entity_query: bool, chunk_type: &ChunkType) -> f32 {
    if !has_docstring {
        return 1.0;
    }
    if is_entity_query && matches!(chunk_type, ChunkType::ModuleLevel) {
        1.02
    } else {
        1.05
    }
}

fn complexity_penalty(content: &str) -> f32 {
    if content.len() > 1000 {
        0.98
    } else {
        1.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::search::query::analyze_query;

    #[test]
    fn test_file_type_boost_code_vs_markdown() {
        let code = file_type_boost("src/auth.py", "python");
        let docs = file_type_boost("docs/en/tutorial/auth.md", "markdown");
        // Code should score significantly higher than markdown in docs/
        assert!(code > docs * 2.0, "code={code}, docs={docs}");
    }

    #[test]
    fn test_file_type_boost_test_penalty() {
        let src = file_type_boost("src/auth.py", "python");
        let test = file_type_boost("tests/test_auth.py", "python");
        assert!(src > test, "src={src}, test={test}");
    }

    #[test]
    fn test_file_type_boost_depth() {
        let shallow = file_type_boost("main.py", "python");
        let deep = file_type_boost("a/b/c/d/e/f/utils.py", "python");
        assert!(shallow > deep);
    }

    #[test]
    fn test_dedup_translations() {
        let make = |path: &str, score: f32| SearchResult {
            chunk_id: String::new(),
            score,
            content: String::new(),
            file_path: String::new(),
            relative_path: path.to_string(),
            folder_structure: Vec::new(),
            chunk_type: ChunkType::Section,
            name: Some("Middleware".to_string()),
            parent_name: None,
            start_line: 1,
            end_line: 10,
            language: "markdown".to_string(),
            docstring: None,
            tags: Vec::new(),
        };

        let mut results = vec![
            make("docs/en/tutorial/middleware.md", 30.0),
            make("docs/tr/tutorial/middleware.md", 29.0),
            make("docs/ja/tutorial/middleware.md", 28.0),
            make("src/middleware.py", 25.0), // not a translation
        ];

        deduplicate_translations(&mut results);

        assert_eq!(results.len(), 2); // en + src/middleware.py
        assert_eq!(results[0].relative_path, "docs/en/tutorial/middleware.md");
        assert_eq!(results[1].relative_path, "src/middleware.py");
    }

    #[test]
    fn test_score_threshold_removes_tail() {
        let make = |score: f32| SearchResult {
            chunk_id: String::new(),
            score,
            content: String::new(),
            file_path: String::new(),
            relative_path: String::new(),
            folder_structure: Vec::new(),
            chunk_type: ChunkType::Function,
            name: None,
            parent_name: None,
            start_line: 1,
            end_line: 10,
            language: "python".to_string(),
            docstring: None,
            tags: Vec::new(),
        };

        let mut results = vec![
            make(100.0),
            make(90.0),
            make(80.0),
            make(5.0),  // way below 12% of 100 = 12
            make(3.0),  // way below
        ];

        apply_score_threshold(&mut results);

        // 5.0 and 3.0 should be removed (below 12% of 100)
        assert!(results.len() <= 3, "len={}", results.len());
        assert!(results.iter().all(|r| r.score >= 12.0));
    }

    #[test]
    fn test_type_boost_class_keyword() {
        let query = analyze_query("UserService class");
        assert!(query.has_class_keyword);
        assert_eq!(type_boost(&ChunkType::Class, &query), 1.3);
        assert!(type_boost(&ChunkType::Function, &query) < 1.3);
    }

    #[test]
    fn test_name_boost_exact_match() {
        let query = analyze_query("UserService");
        assert_eq!(name_boost(Some("UserService"), &query), 1.5);
    }

    #[test]
    fn test_name_boost_partial_match() {
        let query = analyze_query("get user by id");
        let boost = name_boost(Some("getUserById"), &query);
        assert!(boost > 1.0);
    }

    #[test]
    fn test_path_boost() {
        let query = analyze_query("auth middleware");
        let boost = path_boost("src/auth/middleware.rs", &query);
        assert!(boost > 1.0);
    }

    #[test]
    fn test_complexity_penalty() {
        assert_eq!(complexity_penalty("short"), 1.0);
        assert_eq!(complexity_penalty(&"x".repeat(1500)), 0.98);
    }
}
