---
description: Search project memory (.claude/memory/ + docs/sessions/) — grep + optional qex
---

Search the project's long-term memory and session logs.

## Arguments

`$ARGUMENTS` — the search query (a phrase or keywords).
If empty — ask the user what to search for.

## Steps

1. **Lexical layer (primary).** This is the main mechanism — always works, needs no index:
   ```bash
   grep -rinl --include='*.md' "$ARGUMENTS" .claude/memory/ docs/sessions/ 2>/dev/null
   ```
   For each hit file, pull 2-3 lines of context around the match.

2. **Semantic layer (optional, when it helps).** Call the `mcp__qex__search_code` tool with:
   - `query` = `$ARGUMENTS`
   - `limit` = 10
   - **don't** pass `extension_filter` — markdown has no tree-sitter AST chunking,
     the extension filter here only cuts valid hits, giving nothing back in return.

   Then filter the results: keep only paths under `.claude/memory/` or `docs/sessions/`.

   **Caveat:** qex is tuned for code (tree-sitter chunking) and may not index Markdown under `.claude/`. **Empty is normal**, not an error — grep (step 1) already covers the corpus. Don't suggest `/mcp-qex:qex-reindex` for this command.

3. **Merge and re-rank.** Dedup by path (grep ∪ qex), then sort by decreasing usefulness:
   1. **by entry type** (`metadata.type` from the memory file's frontmatter):
      `feedback` → `project` → `user` → `reference` (actionable rules rank above
      reference context); hits from `docs/sessions/` (logs, no type) — after memory entries;
   2. within the same type — **newer ranks higher** (by file mtime).

   Print the top 5:
   ```
   [memory:<type>|session] <relative-path>:<line>
   <2-3 lines of context>
   ```

4. If nothing was found — honestly say "nothing found in memory or sessions for query '<...>'". Don't make things up.

## When to use

- Before starting a task: "what do I already know about X?"
- On a repeated user question: "we discussed this — what did we decide?"
- At the start of a session, to re-prime context.
