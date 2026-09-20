---
description: Generate a changelog from Conventional Commits between two refs
---

Generate a changelog from the git history (Conventional Commits):

```bash
# Markdown from the last tag to HEAD
uv run --no-project python scripts/changelog_gen/changelog_gen.py

# A specific range + release name
uv run --no-project python scripts/changelog_gen/changelog_gen.py --from v1.0.0 --to v1.1.0 --release-name v1.1.0

# Plain text without hashes (for email / issue)
uv run --no-project python scripts/changelog_gen/changelog_gen.py --no-hashes --style plain

# JSON for automated processing
uv run --no-project python scripts/changelog_gen/changelog_gen.py --style json
```

What it does: parses `git log <from>..<to>` → looks for commits in the format `type(scope)?!?: subject` → groups them by `type` into sections (Features, Bug Fixes, Documentation, ...) → aggregates breaking changes (by `!` or `BREAKING CHANGE:`) into a separate section.

Config: [scripts/changelog_gen/changelog_gen.toml](../../scripts/changelog_gen/changelog_gen.toml). Details — [README.md](../../scripts/changelog_gen/README.md).

**Works well together with** [`/validate_commit`](../../scripts/validate_commit/) — that one validates the format, this one assembles the report.

Useful options:
- `--from v1.0.0 --to HEAD` — release notes
- `--include-unknown` — capture commits not in the conventional format (legacy)
- `--authors` — attach `by <author>` to each commit
- `--no-breaking` — disable the BREAKING CHANGES section (if it scares readers)

**When to use:**
- Before a release — a CHANGELOG draft for review.
- In CI after a merge into `main` — update `CHANGELOG.md`.
- For a large PR — see what was actually done in it.

**Notes:**
- Without tags, `--from` takes the whole git log — set it explicitly on fresh repos.
- Doesn't modify `CHANGELOG.md` — prints the text to stdout. Merging/CI flow is on you.
- Merge commits are skipped (`--no-merges`).

$ARGUMENTS
