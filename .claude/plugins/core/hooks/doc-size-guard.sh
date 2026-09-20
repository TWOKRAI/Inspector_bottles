#!/usr/bin/env bash
# doc-size-guard.sh (Task 2.2) — PostToolUse, matcher "Edit|Write": tells the
# agent AT WRITE TIME that a markdown file it just wrote (or its biggest
# heading-delimited section) is over the document-size budget, so it splits
# the file instead of growing it. A lint (Task 2.1, `scripts/lint_doc_size.py`
# + doctor's "Document size" section) finds the problem later; this hook
# makes the agent see it at the moment of the write.
#
# Cheap pre-filter on the RAW JSON payload before spawning Python at all: no
# literal `.md"` substring -> exit 0 immediately, no Python process started
# (this keeps the standing price of every OTHER Write/Edit — .py, .json, ...
# — a single `case` match, no fork). The Python step below re-checks the
# actual `tool_input.file_path` properly (a `.md"` substring can appear
# elsewhere in the payload, e.g. in `tool_response`).
#
# The size/section thresholds and the WARN math itself are never re-derived
# here — imported BY PATH from the bundled `scripts/lint_doc_size.py` (Task
# 2.1: `read_doc_size_config_for_root`, `section_sizes`), same as the doctor's
# "Document size" check does in-process. One parser for the ```ini block
# (`.claude/modes/_stack.md`'s `doc_size*` keys), not a second dialect grown
# in bash+python.
#
# Exit code ALWAYS 0 — this hook never blocks. ANY error (malformed JSON, a
# missing/unreadable file, an import failure, no Python interpreter on PATH,
# a path outside the project) degrades to exit 0 with NO stdout at all: the
# harness parses a PostToolUse hook's stdout as JSON, so printing anything
# other than the one well-formed object below would corrupt every OTHER
# Write/Edit, not just markdown ones.

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT="$(cat)"
case "$INPUT" in *'.md"'*) ;; *) exit 0 ;; esac

PY="$(source "$HOOK_DIR/_lib/python-bin.sh" 2>/dev/null && printf '%s' "$PY")" || exit 0
[ -n "${PY:-}" ] || exit 0

# The JSON payload must reach the Python step on stdin (it calls
# json.load(sys.stdin)) — `"$PY" - <<EOF` would instead make the heredoc
# ITSELF python's stdin (as the program source, since `-` means "read the
# program from stdin"), leaving nothing for json.load to read. So the
# program text is written to a throwaway temp file and passed as an
# argument, keeping stdin free for the piped payload.
TMP_PY="$(mktemp 2>/dev/null)" || exit 0
trap 'rm -f "$TMP_PY"' EXIT

cat >"$TMP_PY" <<'PYEOF'
import fnmatch
import importlib.util
import json
import os
import sys
from pathlib import Path


def _silent_exit() -> None:
    sys.exit(0)


try:
    payload = json.load(sys.stdin)
except Exception:
    _silent_exit()

file_path = payload.get("tool_input", {}).get("file_path")
if not file_path or not str(file_path).endswith(".md"):
    _silent_exit()

target = Path(file_path)
if not target.is_file():
    _silent_exit()

project_dir = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or "."
project = Path(project_dir).resolve()
try:
    resolved = target.resolve()
    rel = resolved.relative_to(project)
except (OSError, ValueError):
    _silent_exit()

plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
candidates = []
if plugin_root:
    candidates.append(Path(plugin_root) / "scripts" / "lint_doc_size.py")
candidates.append(project / ".claude" / "plugins" / "core" / "scripts" / "lint_doc_size.py")

lds = None
for candidate in candidates:
    try:
        if not candidate.is_file():
            continue
        spec = importlib.util.spec_from_file_location(
            "_doc_size_guard_lint_doc_size", candidate
        )
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        lds = module
        break
    except Exception:
        continue

if lds is None:
    _silent_exit()

try:
    config = lds.read_doc_size_config_for_root(project)
except Exception:
    _silent_exit()

if not config.get("enabled", True):
    _silent_exit()

rel_posix = rel.as_posix()
exempt = config.get("exempt", ())
try:
    is_exempt = any(fnmatch.fnmatchcase(rel_posix, pattern) for pattern in exempt)
except Exception:
    is_exempt = False
if is_exempt:
    _silent_exit()

try:
    raw = resolved.read_bytes()
    size = len(raw)
    text = raw.decode("utf-8")
except Exception:
    _silent_exit()

file_kb_limit = config.get("file_kb", 32)
section_kb_limit = config.get("section_kb", 8)
size_kb = size / 1024
messages = []

if size_kb > file_kb_limit:
    messages.append(
        f"doc-size-guard: {rel_posix} is {size_kb:.1f} KB (budget "
        f"{file_kb_limit} KB). Split it by level-2 headings into separate "
        "files - qex and graphify do not index the tail of oversized "
        "documents."
    )

try:
    sections = lds.section_sizes(text)
except Exception:
    sections = []

if sections:
    heading, biggest = max(sections, key=lambda item: item[1])
    biggest_kb = biggest / 1024
    if biggest_kb > section_kb_limit:
        messages.append(
            f"doc-size-guard: section '{heading}' is {biggest_kb:.1f} KB "
            f"(budget {section_kb_limit} KB): add sub-headings or split it."
        )

if not messages:
    _silent_exit()

output = {
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": " ".join(messages),
    }
}
sys.stdout.write(json.dumps(output, ensure_ascii=True))
PYEOF

printf '%s' "$INPUT" |
  CLAUDE_PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}" \
  CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-}" \
  "$PY" "$TMP_PY" 2>/dev/null
exit 0
