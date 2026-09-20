---
description: Update a pinned plugin <id> — consume (re-pin version/sha) OR git β (re-clone to a new ref + atomic swap + recompose)
allowed-tools: Bash(claude-kit-claude plugin update*)
---

The `plugin update` command distinguishes the plugin's source by its entry in enabled.yaml and routes to the right branch.

**α (consume).** Re-pins an already-pinned plugin: keeps the existing `source`, updates only `version`/`sha`, and rebuilds the artifacts. The plugin must already have a `source` (run `pin` first).

**β (git).** For a git-managed plugin (installed in `.claude/plugins/_external/<id>/`): we re-clone the repository at the given `--ref` (or the currently tracked ref), atomically swap the tree, and update `sha` in the lockfile, then recompose. A backup of `.claude/` is created before the operation; on any failure — rollback of both the tree AND the artifacts (transactional). Local edits in `_external/<id>/` are lost — β-code is throwaway (gitignored, reproduced by re-clone from the lockfile).

Usage:
- consume: `/core:plugin:update <id> [--version X | --sha Y]`
- git β: `/core:plugin:update <id> [--ref <branch|tag|sha>] [--yes]`

```bash
claude-kit-claude plugin update $ARGUMENTS
```
