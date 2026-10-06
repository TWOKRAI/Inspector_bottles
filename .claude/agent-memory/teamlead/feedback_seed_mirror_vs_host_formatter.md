---
name: seed-mirror-vs-host-formatter
description: A claude-kit seed file mirrored under scripts/ gets rewritten by the host pre-commit ruff-format (120 cols vs seed 88) — mirror silently drifts from its .claude/plugins source
metadata:
  type: feedback
---

A seed file copied byte-for-byte from `.claude/plugins/<id>/…` into `scripts/` (e.g. `scripts/plans_ledger.py`) is NOT excluded from the host's ruff-format (only `.claude/` is). The seed is formatted at 88 columns, the project at 120, so the pre-commit hook rewrites the mirror on the first commit that touches it (measured 2026-10-02: 77+/267−) and `diff -q source mirror` stops being empty.

**Why:** the mirror rule (`diff -q` before and after, manifest sha256) exists because `plugin upgrade --apply` overwrites the mirror from the source; a formatter-induced drift breaks that silently.

**How to apply:** before editing any mirrored seed file, run `ruff format --check <mirror>` with the project config. Fix used in Task 1.0: a `# fmt: off` comment line placed right before `from __future__ import annotations` in BOTH copies (placed on line 2 after the shebang it did not suppress formatting; ruff then reports "already formatted" at both 88 and 120). The lead accepted it as a 3-line deviation from the upstream seed; the alternative (exclude the mirror in `.pre-commit-config.yaml`) is the lead's call. Also: the manifest stores the LF-blob hash; with `core.autocrlf=true` a fresh Windows checkout gives a different working-file sha256.
