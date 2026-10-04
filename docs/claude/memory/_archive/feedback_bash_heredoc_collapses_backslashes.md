---
name: feedback-bash-heredoc-collapses-backslashes
description: Bash tool collapses `\\` to `\` even inside a quoted heredoc — generated Python gets real control bytes; write such files with Write/Edit
metadata:
  type: feedback
  last-verified: 2026-09-29
---

Text passed to the Bash tool loses one level of backslashes, even inside `<<'EOF'`. A Python
heredoc that writes `b"\\xff"` or `"\\n"` into a file produces the actual byte / newline, not the
escape: ruff then reports `bytes can only contain ASCII`, or a generated script dies with
`unterminated string literal`.

**Why:** hit three times on 2026-09-29 (code_reader Ф6): a test fixture byte literal, an
injection script with `"\n"` anchors, a second injection script — each cost a retry.

**How to apply:** any file or snippet that must contain a literal backslash goes through the
Write/Edit tools, not a Bash heredoc. Inside a Bash-run Python snippet, build it with `chr(92)`
or `NL = "\n"`-free concatenation (`"a" + chr(10) + "b"`). State this trap in subagent briefs
(TRAPS line) — agents hit it too. Related: [[feedback-bash-tool-unbalanced-quote-breaks-command]].
