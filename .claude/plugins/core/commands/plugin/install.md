---
description: Install a plugin — consume form <plugin>@<marketplace> (α, delegated to Claude Code) OR git source <git-url> (β, our git-clone + wire)
allowed-tools: Bash(claude-kit-claude plugin install*)
---

The `plugin install` command distinguishes the source by argument and routes to the right branch (`classify_source`). Two forms:

**α (consume) — `<plugin>@<marketplace>`.** Delegated install: Claude Code itself downloads the files from the marketplace cache. The command only writes the pin to enabled.yaml and prints the step `/plugin install <ref>`, which you must run inside Claude Code to actually install the plugin.

**β (git) — `<git-url>` (any `https://…`, `git@…`, `.git`, `file://…`).** We `git clone` the repository ourselves into `.claude/plugins/_external/<id>/`, remove its `.git/`, and **our** composer wires the plugin — its mcpServers / hooks / permissions land in `.mcp.json` / `settings.json`. Installing a third-party plugin = running third-party code: before merging, a diff is shown (what will be added to the artifacts) and confirmation is requested. Confirm is unavailable in a non-interactive environment → pass `--yes`.

Usage:
- consume: `/core:plugin:install <plugin>@<marketplace> [--id <id>] [--version X]`
- git β: `/core:plugin:install <git-url> [--ref <branch|tag|sha>] [--subdir <relpath>] [--id <id>] [--yes]`

β options: `--ref` — branch/tag/sha to clone; `--subdir` — path to `.claude-plugin/plugin.json` if it's NOT at the repo root (without `--subdir`, and if the manifest is missing at the root, the command suggests the exact path); `--id` — name in the managed namespace (default — from repo-name); `--yes` — skip confirm (CI / non-interactive).

```bash
claude-kit-claude plugin install $ARGUMENTS
```
