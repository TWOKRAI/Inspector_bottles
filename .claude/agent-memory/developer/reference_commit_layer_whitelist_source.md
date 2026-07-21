---
name: reference-commit-layer-whitelist-source
description: The real Layer trailer whitelist for Inspector_bottles lives in scripts/validate_commit/validate_commit.py::ALLOWED_LAYERS, not in the generic .claude/commit-layers.txt template
metadata:
  type: reference
---

`.claude/commit-layers.txt` in this repo is the generic claude-kit scaffold — every
line is a comment (`#`), so by the generic COMMIT_GUIDE.md rule ("file present but
only comments → Layer: is OPTIONAL") it would look like Layer enforcement is off.

**It is not off.** The project's actual commit-msg hook
(`scripts/validate_commit/validate_commit.py`) hardcodes its own
`REQUIRED_TRAILERS = {"Why", "Layer"}` and `ALLOWED_LAYERS = {framework, services,
plugins, prototype, docs, scripts, tests, infra, mixed}` — independent of
`.claude/commit-layers.txt`. This matches what root `CLAUDE.md` documents (§ "Формат
commit-сообщений") but the two files can look inconsistent at a glance.

**How to apply:** don't infer whether `Layer:` is required/what values are valid by
reading `.claude/commit-layers.txt` in this repo — read
`scripts/validate_commit/validate_commit.py`'s `ALLOWED_LAYERS`/`REQUIRED_TRAILERS`
directly, or just trust root `CLAUDE.md`'s documented list. Verified 2026-07-21
(Task 1.4, plan `backend-ctl-proof-discipline`) while picking `Layer: mixed` for a
commit touching both `backend_ctl/conditions.py` and `backend_ctl/driver.py`.

See also [[feedback_commit_trailer_no_wrap]] (same validator file, different gotcha).
