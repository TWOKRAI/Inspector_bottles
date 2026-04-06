use regex::Regex;
use std::collections::HashSet;
use std::sync::LazyLock;

/// Detected intent from query analysis
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum QueryIntent {
    FunctionSearch,
    ErrorHandling,
    Database,
    Api,
    Authentication,
    Testing,
}

/// Analyzed query with extracted information
#[derive(Debug, Clone)]
pub struct AnalyzedQuery {
    pub original: String,
    /// Query after stop word removal + synonym expansion (sent to BM25)
    pub search_query: String,
    pub tokens: Vec<String>,
    pub normalized_tokens: Vec<String>,
    pub intents: HashSet<QueryIntent>,
    pub is_entity_query: bool,
    pub has_class_keyword: bool,
}

static CAMEL_CASE_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"([a-z])([A-Z])").unwrap());
static WORD_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\w+").unwrap());
static CAMEL_CASE_PATTERN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[A-Z][a-z]+[A-Z]").unwrap());

const ACTION_WORDS: &[&str] = &[
    "find", "search", "get", "show", "list", "display", "how", "what", "where", "which",
    "all", "every", "the", "a", "an", "is", "are", "was", "were", "do", "does",
];

/// Stop words to remove from BM25 queries — these cause noise in code search
const STOP_WORDS: &[&str] = &[
    "how", "does", "the", "where", "is", "what", "which", "do", "a", "an", "are", "was",
    "were", "this", "that", "it", "in", "on", "at", "to", "for", "of", "with", "by",
    "from", "can", "could", "would", "should", "will", "be", "been", "being", "have",
    "has", "had", "did", "done", "about", "into", "through", "its", "my", "your",
    "there", "here", "when", "why", "all", "each", "every", "both", "few", "more",
    "most", "other", "some", "such", "than", "too", "very", "just", "also",
];

/// Intent detection patterns
struct IntentPattern {
    intent: QueryIntent,
    patterns: Vec<&'static str>,
}

static INTENT_PATTERNS: LazyLock<Vec<IntentPattern>> = LazyLock::new(|| {
    vec![
        IntentPattern {
            intent: QueryIntent::FunctionSearch,
            patterns: vec![
                r"\bfunction\b", r"\bdef\b", r"\bmethod\b", r"\bclass\b",
                r"how.*work", r"implement", r"algorithm",
            ],
        },
        IntentPattern {
            intent: QueryIntent::ErrorHandling,
            patterns: vec![
                r"\berror\b", r"\bexception\b", r"\btry\b", r"\bcatch\b",
                r"handle.*error", r"exception.*handling",
            ],
        },
        IntentPattern {
            intent: QueryIntent::Database,
            patterns: vec![
                r"\bdatabase\b", r"\bdb\b", r"\bquery\b", r"\bsql\b",
                r"\bmodel\b", r"\btable\b", r"connection",
            ],
        },
        IntentPattern {
            intent: QueryIntent::Api,
            patterns: vec![
                r"\bapi\b", r"\bendpoint\b", r"\broute\b", r"\brequest\b",
                r"\bresponse\b", r"\bhttp\b", r"rest.*api",
            ],
        },
        IntentPattern {
            intent: QueryIntent::Authentication,
            patterns: vec![
                r"\bauth\b", r"\blogin\b", r"\btoken\b", r"\bpassword\b",
                r"\bsession\b", r"authenticate", r"permission",
            ],
        },
        IntentPattern {
            intent: QueryIntent::Testing,
            patterns: vec![
                r"\btest\b", r"\bmock\b", r"\bassert\b", r"\bfixture\b",
                r"unit.*test", r"integration.*test",
            ],
        },
    ]
});

/// Code-aware synonym pairs for query expansion
const SYNONYMS: &[(&[&str], &[&str])] = &[
    (&["auth"], &["authentication", "authorize", "authorization"]),
    (&["db"], &["database"]),
    (&["config"], &["configuration", "settings"]),
    (&["init"], &["initialize", "initialization"]),
    (&["err"], &["error"]),
    (&["msg"], &["message"]),
    (&["req"], &["request"]),
    (&["res", "resp"], &["response"]),
    (&["middleware"], &["middleware"]),
    (&["handler"], &["handler", "handle"]),
    (&["util"], &["utility", "utils", "helpers"]),
    (&["param"], &["parameter"]),
    (&["ctx"], &["context"]),
    (&["conn"], &["connection"]),
    (&["async"], &["asynchronous"]),
    (&["sync"], &["synchronous"]),
];

/// Analyze a search query
pub fn analyze_query(query: &str) -> AnalyzedQuery {
    let tokens = tokenize(query);
    let normalized = normalize_tokens(&tokens);
    let intents = detect_intents(query);
    let is_entity = is_entity_query(&tokens, query);
    let has_class = query.to_lowercase().contains("class");

    // Remove stop words for BM25 search, then expand with synonyms
    let filtered = remove_stop_words(query);
    let search_query = expand_query(&filtered, &normalize_tokens(&tokenize(&filtered)));

    AnalyzedQuery {
        original: query.to_string(),
        search_query,
        tokens,
        normalized_tokens: normalized,
        intents,
        is_entity_query: is_entity,
        has_class_keyword: has_class,
    }
}

/// Remove stop words from a query, preserving meaningful terms
fn remove_stop_words(query: &str) -> String {
    let words: Vec<&str> = query.split_whitespace().collect();

    let filtered: Vec<&str> = words
        .iter()
        .filter(|w| !STOP_WORDS.contains(&w.to_lowercase().as_str()))
        .copied()
        .collect();

    // If all words were stop words, return original to avoid empty query
    if filtered.is_empty() {
        query.to_string()
    } else {
        filtered.join(" ")
    }
}

/// Expand query with code-aware synonyms
fn expand_query(original: &str, tokens: &[String]) -> String {
    let mut expansions: Vec<String> = Vec::new();

    for token in tokens {
        for (abbreviations, full_forms) in SYNONYMS {
            if abbreviations.contains(&token.as_str()) {
                for form in *full_forms {
                    if *form != token.as_str() {
                        expansions.push((*form).to_string());
                    }
                }
            }
            // Also expand full forms → abbreviations
            if full_forms.contains(&token.as_str()) {
                for abbr in *abbreviations {
                    if *abbr != token.as_str() {
                        expansions.push((*abbr).to_string());
                    }
                }
            }
        }
    }

    if expansions.is_empty() {
        original.to_string()
    } else {
        // Tantivy OR: "original_query term1 term2"
        format!("{} {}", original, expansions.join(" "))
    }
}

/// Tokenize a query string
pub fn tokenize(text: &str) -> Vec<String> {
    // Split CamelCase
    let expanded = CAMEL_CASE_RE.replace_all(text, "$1 $2");
    // Split snake_case and kebab-case
    let expanded = expanded.replace('_', " ").replace('-', " ");
    // Extract word tokens
    WORD_RE
        .find_iter(&expanded)
        .map(|m| m.as_str().to_lowercase())
        .collect()
}

/// Normalize tokens by lowercasing and deduplicating
fn normalize_tokens(tokens: &[String]) -> Vec<String> {
    let mut seen = HashSet::new();
    tokens
        .iter()
        .filter(|t| t.len() > 1) // Skip single characters
        .filter_map(|t| {
            let lower = t.to_lowercase();
            if seen.insert(lower.clone()) {
                Some(lower)
            } else {
                None
            }
        })
        .collect()
}

/// Detect query intents using regex patterns
fn detect_intents(query: &str) -> HashSet<QueryIntent> {
    let lower = query.to_lowercase();
    let mut intents = HashSet::new();

    for ip in INTENT_PATTERNS.iter() {
        for pattern in &ip.patterns {
            if let Ok(re) = Regex::new(pattern) {
                if re.is_match(&lower) {
                    intents.insert(ip.intent.clone());
                    break;
                }
            }
        }
    }

    intents
}

/// Check if query looks like an entity name (class/function lookup)
fn is_entity_query(tokens: &[String], original: &str) -> bool {
    // Short queries
    if tokens.len() > 3 {
        return false;
    }

    // Contains action words → not an entity query
    if tokens.iter().any(|t| ACTION_WORDS.contains(&t.as_str())) {
        return false;
    }

    // CamelCase pattern → entity query
    if CAMEL_CASE_PATTERN.is_match(original) {
        return true;
    }

    // Short noun phrase (1-2 tokens, no action words)
    tokens.len() <= 2
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tokenize() {
        assert_eq!(tokenize("getUserById"), vec!["get", "user", "by", "id"]);
        assert_eq!(tokenize("get_user_by_id"), vec!["get", "user", "by", "id"]);
        assert_eq!(tokenize("HTTPClient"), vec!["httpclient"]); // Special case
    }

    #[test]
    fn test_analyze_query() {
        let q = analyze_query("find the login function");
        assert!(q.intents.contains(&QueryIntent::Authentication));
        assert!(q.intents.contains(&QueryIntent::FunctionSearch));
        assert!(!q.is_entity_query);
    }

    #[test]
    fn test_entity_query_detection() {
        let q = analyze_query("UserService");
        assert!(q.is_entity_query);

        let q = analyze_query("find all tests");
        assert!(!q.is_entity_query);
    }

    #[test]
    fn test_query_expansion() {
        let q = analyze_query("auth middleware");
        assert!(q.search_query.contains("authentication"));
        assert!(q.search_query.contains("auth middleware"));

        let q = analyze_query("db connection");
        assert!(q.search_query.contains("database"));

        // No expansion for unknown terms
        let q = analyze_query("foobar baz");
        assert_eq!(q.search_query, "foobar baz");
    }

    #[test]
    fn test_stop_word_removal() {
        assert_eq!(remove_stop_words("how does routing work"), "routing work");
        assert_eq!(remove_stop_words("where is the main app defined"), "main app defined");
        assert_eq!(remove_stop_words("how to add a new endpoint"), "add new endpoint");
        // All stop words → return original
        assert_eq!(remove_stop_words("the is a"), "the is a");
        // No stop words → unchanged
        assert_eq!(remove_stop_words("middleware auth"), "middleware auth");
    }

    #[test]
    fn test_intent_detection() {
        let q = analyze_query("database connection");
        assert!(q.intents.contains(&QueryIntent::Database));

        let q = analyze_query("error handling middleware");
        assert!(q.intents.contains(&QueryIntent::ErrorHandling));
    }
}
