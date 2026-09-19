---
description: Check Markdown links (relative paths, anchors, optionally HTTP)
---

Run a check of Markdown links in the project:

```bash
uv run --no-project python scripts/link_check/link_check.py
```

What it catches: broken relative paths (`[x](../foo.md)`), missing anchors (`[x](#section)`), non-standard schemes. HTTP checking is optional (OFF by default, so it doesn't depend on the network).

Config: [scripts/link_check/link_check.toml](../../scripts/link_check/link_check.toml). Details and exit codes — [README.md](../../scripts/link_check/README.md).

Useful options:
- `uv run --no-project python scripts/link_check/link_check.py --external` — enable a HEAD check of HTTP links (slower).
- `uv run --no-project python scripts/link_check/link_check.py --format json --no-strict` — for CI without failing.
- `uv run --no-project python scripts/link_check/link_check.py --no-anchor` — skip anchors (useful if the site generator uses its own slugs).

**Inline suppression:** `<!-- link-check: ignore -->` on the same line disables all checks.

**When to use:**
- In `pre-commit` (with `--no-external`) — a fast gate on the correctness of relative paths.
- In CI as a gate on the correctness of the docs.
- After refactoring/renaming files — catch links that came detached from their targets.

**Notes:**
- The parser catches `[text](url)` and `<https://...>`, it doesn't parse reference-style `[text][ref]`.
- Heading slugs are GitHub-style (`# My Heading` → `my-heading`). For mkdocs-material with custom slugs, turn anchor checks off with `--no-anchor`.

$ARGUMENTS
