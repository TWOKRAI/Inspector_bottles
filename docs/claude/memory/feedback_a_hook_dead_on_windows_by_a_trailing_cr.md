---
name: feedback_a_hook_dead_on_windows_by_a_trailing_cr
description: Git Bash strips \r in $(...) but NOT in `read < <(...)` — four Edit hooks silently exited for months; prove a hook alive by feeding it a real payload, not by reading it
mechanism: "hooks"
metadata:
  type: feedback
---

A shell hook that parses its JSON input with Windows Python and `read -r A B < <(python -c "...print(...)")`
gets `B` with a trailing `\r`. Every later test (`[[ "$B" == *.py ]]`, `[ -f "$B" ]`) fails and the hook
`exit 0`s — no error, no log. Git Bash (MSYS) strips `\r` in `$(...)` command substitution, but
not in `read` from process substitution. Probe: `read x < <(python -c 'print("a.py")'); printf %q "$x"` →
`$'a.py\r'`.

Measured 2026-10-03/04 (plans/2026-10-03_commit-mechanism, Tasks 1.2 and 1.4): `autoformat-python.sh`
was dead from `3dbb2985a` (2026-05-15) — all 68 pre-commit ruff rejections in a month happened under
the dead hook; `check-imports.sh`, `typecheck-changed.sh`, `semgrep-scan.sh` had the same line.
`typecheck-changed.sh` never ran on any platform: its gate `CLAUDE_TYPECHECK_ON_EDIT` was set nowhere.
Behind the gate a second defect waited: `OUT=$(pyright ...) || exit 0` exits exactly when pyright found
errors (rc=1).

**Why:** the hook looked registered and reviewed for months; nothing surfaces a PostToolUse hook that
does nothing. A plain-text stdout or a stderr line at exit 0 is also invisible to the agent — only the
JSON `hookSpecificOutput.additionalContext` reaches it.

**How to apply:**
- To claim a hook works, feed it a real payload (`{"tool_name":"Write","tool_input":{"file_path":"D:/..."}}`)
  and compare against a copy with the suspected fix — not by reading the script.
- Parse hook input inside Python and print with `sys.stdout.write` (no newline), then `| tr -d '\r'`;
  never `read < <(...)` from Windows Python.
- Agent-facing output goes through `additionalContext` JSON; anything else is for the debug log.
- Related: [[feedback_zero_observations_looks_like_a_result]], [[feedback_zero_observations_looks_like_a_result]].
