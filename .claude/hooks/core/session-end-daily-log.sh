#!/bin/bash
# Stop hook: append a per-session git summary to docs/sessions/YYYY-MM-DD.md.
#
# Opt-in. Enable by adding to .claude/settings.json:
#   "Stop": [
#     { "hooks": [{ "type": "command",
#                   "command": ".claude/hooks/core/session-end-daily-log.sh",
#                   "timeout": 10 }] }
#   ]
#
# Pairs with /wrap-up command:
#   - this hook writes the mechanical part (git status, diff stat)
#   - /wrap-up writes the semantic part (what was done, what's next)
#
# Customization (via env vars or edits below):
#   SESSIONS_DIR — where to write daily logs (default: docs/sessions)
#   PATH_FILTER  — limit to specific path prefix (e.g. "src/"). Empty = all changes.
#
# Quiet: always exits 0, never blocks the Stop event.

set -e

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SESSIONS_DIR="${SESSIONS_DIR:-$REPO_ROOT/docs/sessions}"
PATH_FILTER="${PATH_FILTER:-}"

DATE="$(date +%Y-%m-%d)"
TIME="$(date +%H:%M)"
DAILY_FILE="$SESSIONS_DIR/$DATE.md"

mkdir -p "$SESSIONS_DIR"

# Frontmatter for new file
if [ ! -f "$DAILY_FILE" ]; then
    cat > "$DAILY_FILE" <<EOF
---
title: "Sessions $DATE"
type: session-log
date: $DATE
---

# Журнал сессий — $DATE

EOF
fi

# Collect git state (best-effort, ignore errors)
if [ -n "$PATH_FILTER" ]; then
    CHANGED_FILES=$(cd "$REPO_ROOT" && git status --short -- "$PATH_FILTER" 2>/dev/null | head -30 || true)
    DIFF_STAT=$(cd "$REPO_ROOT" && git diff --shortstat -- "$PATH_FILTER" 2>/dev/null || true)
else
    CHANGED_FILES=$(cd "$REPO_ROOT" && git status --short 2>/dev/null | head -30 || true)
    DIFF_STAT=$(cd "$REPO_ROOT" && git diff --shortstat 2>/dev/null || true)
fi
BRANCH=$(cd "$REPO_ROOT" && git branch --show-current 2>/dev/null || echo "?")
COMMIT=$(cd "$REPO_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo "?")

# No changes — nothing to log
if [ -z "$CHANGED_FILES" ] && [ -z "$DIFF_STAT" ]; then
    exit 0
fi

{
    echo ""
    echo "## [$TIME] session-end | branch=$BRANCH | commit=$COMMIT"
    echo ""
    if [ -n "$CHANGED_FILES" ]; then
        echo "**Changed files:**"
        echo '```'
        echo "$CHANGED_FILES"
        echo '```'
    fi
    if [ -n "$DIFF_STAT" ]; then
        echo ""
        echo "**Diff stat:** $DIFF_STAT"
    fi
} >> "$DAILY_FILE"

exit 0
