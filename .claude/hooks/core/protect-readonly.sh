#!/bin/bash
# PreToolUse hook: block Write/Edit to paths listed in .claude/readonly-paths.
#
# Use case: protect immutable data zones (raw datasets, applied DB migrations,
# generated artifacts) from accidental Claude edits.
#
# Config file: .claude/readonly-paths
#   - One pattern per line
#   - Empty lines and # comments ignored
#   - Match is literal substring against the absolute file path
#   - If file doesn't exist or is empty → hook is a no-op
#
# Examples of patterns:
#   data/raw/
#   data/corpus.db
#   migrations/applied/
#
# Exit codes:
#   0 — allow
#   2 — block (PreToolUse contract)

set -e

# Resolve Python interpreter (python3 on Linux/macOS, python on Windows).
source "$(dirname "$0")/../_lib/python-bin.sh"

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | $PY -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('file_path', ''))
except Exception:
    print('')
" 2>/dev/null)

# Nothing to check
[ -z "$FILE_PATH" ] && exit 0

# Find readonly-paths: prefer PWD/.claude/ over git toplevel.
#
# Why PWD-first: on Windows (and any setup where ~/.claude/ is itself a git
# repo, or a parent of pwd is git-tracked), `git rev-parse --show-toplevel`
# returns the OUTER repo instead of the project — the hook would read the
# wrong .claude/readonly-paths (or none). Claude Code always launches hooks
# with cwd = project root, so PWD is the authoritative anchor.
if [ -f "$PWD/.claude/readonly-paths" ]; then
    PATTERNS_FILE="$PWD/.claude/readonly-paths"
else
    REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    PATTERNS_FILE="$REPO_ROOT/.claude/readonly-paths"
fi

# No config → no-op (this is the common case)
[ ! -f "$PATTERNS_FILE" ] && exit 0

# Read patterns: strip comments + empty lines
PATTERNS=$(grep -vE '^[[:space:]]*(#|$)' "$PATTERNS_FILE" 2>/dev/null || true)
[ -z "$PATTERNS" ] && exit 0

# Match: any pattern as a literal substring of the file path
while IFS= read -r pattern; do
    [ -z "$pattern" ] && continue
    if [[ "$FILE_PATH" == *"$pattern"* ]]; then
        echo "Blocked: $FILE_PATH matches readonly pattern '$pattern' (.claude/readonly-paths)." >&2
        echo "Reason: this path is protected from Edit/Write to prevent accidental data corruption." >&2
        echo "If you really need to modify it, edit .claude/readonly-paths or use a different tool." >&2
        exit 2
    fi
done <<< "$PATTERNS"

exit 0
