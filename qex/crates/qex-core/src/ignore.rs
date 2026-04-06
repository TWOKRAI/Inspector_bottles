use ignore::WalkBuilder;
use std::collections::HashSet;
use std::path::Path;

/// Default directory patterns to ignore (beyond .gitignore)
const DEFAULT_IGNORE_DIRS: &[&str] = &[
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    ".env",
    ".direnv",
    "node_modules",
    ".pnpm-store",
    ".yarn",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".pytype",
    ".ipynb_checkpoints",
    "build",
    "dist",
    "out",
    "public",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".angular",
    ".astro",
    ".vite",
    ".cache",
    ".parcel-cache",
    ".turbo",
    "coverage",
    ".coverage",
    ".nyc_output",
    ".gradle",
    ".idea",
    ".vscode",
    ".docusaurus",
    ".vercel",
    ".serverless",
    ".terraform",
    ".mvn",
    ".tox",
    "target",
    "bin",
    "obj",
    ".qex",
];

/// Default file patterns to ignore
const DEFAULT_IGNORE_FILES: &[&str] = &[
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "Thumbs.db",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "go.sum",
];

/// Walk a directory respecting .gitignore + default ignore patterns
pub fn walk_files(
    root: &Path,
    extensions: Option<&[&str]>,
) -> Vec<(String, String)> {
    let ignore_dirs: HashSet<&str> = DEFAULT_IGNORE_DIRS.iter().copied().collect();

    let mut builder = WalkBuilder::new(root);
    builder
        .hidden(false) // Don't skip hidden by default (let .gitignore handle it)
        .git_ignore(true)
        .git_global(true)
        .git_exclude(true)
        .parents(true);

    // Add default ignores as custom override rules
    if let Some(overrides) = build_overrides(root) {
        builder.overrides(overrides);
    }

    let walker = builder.build();

    walker
        .filter_map(|entry| entry.ok())
        .filter(|entry| entry.file_type().map(|ft| ft.is_file()).unwrap_or(false))
        .filter(|entry| {
            // Skip files in ignored directories
            let path = entry.path();
            !path.components().any(|c| {
                c.as_os_str()
                    .to_str()
                    .map(|s| ignore_dirs.contains(s))
                    .unwrap_or(false)
            })
        })
        .filter(|entry| {
            // Filter by extension if specified
            if let Some(exts) = extensions {
                entry
                    .path()
                    .extension()
                    .and_then(|e| e.to_str())
                    .map(|ext| exts.contains(&ext))
                    .unwrap_or(false)
            } else {
                true
            }
        })
        .filter(|entry| {
            // Skip files matching default ignore patterns
            let name = entry.file_name().to_str().unwrap_or("");
            !DEFAULT_IGNORE_FILES.iter().any(|pattern| {
                if let Some(ext_pattern) = pattern.strip_prefix("*.") {
                    name.ends_with(&format!(".{}", ext_pattern))
                } else {
                    name == *pattern
                }
            })
        })
        .map(|entry| {
            let abs_path = entry.path().to_string_lossy().to_string();
            let rel_path = entry
                .path()
                .strip_prefix(root)
                .unwrap_or(entry.path())
                .to_string_lossy()
                .to_string();
            (abs_path, rel_path)
        })
        .collect()
}

fn build_overrides(root: &Path) -> Option<ignore::overrides::Override> {
    let mut builder = ignore::overrides::OverrideBuilder::new(root);
    // The ignore crate uses "!" prefix for negation (allow), no prefix for ignore
    // But overrides work differently — globs without "!" mean "only include these"
    // We want to exclude patterns, so we use "!" prefix
    for dir in DEFAULT_IGNORE_DIRS {
        let _ = builder.add(&format!("!{}/**", dir));
    }
    builder.build().ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn test_walk_files_basic() {
        let dir = TempDir::new().unwrap();
        let root = dir.path();

        // Create some files
        fs::write(root.join("main.py"), "print('hello')").unwrap();
        fs::write(root.join("lib.rs"), "fn main() {}").unwrap();
        fs::create_dir_all(root.join("src")).unwrap();
        fs::write(root.join("src/utils.py"), "def util(): pass").unwrap();

        // Create an ignored directory
        fs::create_dir_all(root.join("node_modules")).unwrap();
        fs::write(root.join("node_modules/pkg.js"), "module.exports = {}").unwrap();

        let files = walk_files(root, None);
        let rel_paths: Vec<&str> = files.iter().map(|(_, r)| r.as_str()).collect();

        assert!(rel_paths.contains(&"main.py"));
        assert!(rel_paths.contains(&"lib.rs"));
        assert!(rel_paths.contains(&"src/utils.py"));
        assert!(!rel_paths.iter().any(|p| p.contains("node_modules")));
    }

    #[test]
    fn test_walk_files_with_extensions() {
        let dir = TempDir::new().unwrap();
        let root = dir.path();

        fs::write(root.join("main.py"), "print('hello')").unwrap();
        fs::write(root.join("lib.rs"), "fn main() {}").unwrap();
        fs::write(root.join("readme.md"), "# Hello").unwrap();

        let files = walk_files(root, Some(&["py", "rs"]));
        let rel_paths: Vec<&str> = files.iter().map(|(_, r)| r.as_str()).collect();

        assert!(rel_paths.contains(&"main.py"));
        assert!(rel_paths.contains(&"lib.rs"));
        assert!(!rel_paths.contains(&"readme.md"));
    }
}
