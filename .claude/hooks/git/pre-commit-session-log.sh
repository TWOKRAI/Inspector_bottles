#!/bin/bash
# pre-commit hook: append a per-commit summary to docs/sessions/YYYY-MM-DD.md
# and stage the daily log so it becomes part of the commit being made.
#
# Pairs with /wrap-up command and replaces the old Claude `Stop` hook
# (.claude/hooks/core/session-end-daily-log.sh) — moved here so the
# journal entry is included in the commit instead of dangling after it.
#
# Registered as a `repo: local` hook in .pre-commit-config.yaml.
#
# Customization (via env vars):
#   SESSIONS_DIR — where to write daily logs (default: docs/sessions)
#   PATH_FILTER  — limit to specific path prefix. Empty = all changes.
#
# Quiet: always exits 0, never blocks the commit.

set -e

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SESSIONS_DIR="${SESSIONS_DIR:-$REPO_ROOT/docs/sessions}"
PATH_FILTER="${PATH_FILTER:-}"

DATE="$(date +%Y-%m-%d)"
TIME="$(date +%H:%M)"
DAILY_FILE="$SESSIONS_DIR/$DATE.md"
DAILY_FILE_REL="${DAILY_FILE#$REPO_ROOT/}"

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

# Snapshot the staged set BEFORE we touch the daily log itself,
# so the entry describes the user's commit (not our own write).
if [ -n "$PATH_FILTER" ]; then
    STAGED_FILES=$(cd "$REPO_ROOT" && git diff --cached --name-status -- "$PATH_FILTER" 2>/dev/null | head -30 || true)
    DIFF_STAT=$(cd "$REPO_ROOT" && git diff --cached --shortstat -- "$PATH_FILTER" 2>/dev/null || true)
else
    STAGED_FILES=$(cd "$REPO_ROOT" && git diff --cached --name-status 2>/dev/null | head -30 || true)
    DIFF_STAT=$(cd "$REPO_ROOT" && git diff --cached --shortstat 2>/dev/null || true)
fi
BRANCH=$(cd "$REPO_ROOT" && git branch --show-current 2>/dev/null || echo "?")

# Nothing staged — nothing to log (shouldn't happen during pre-commit, but be safe).
if [ -z "$STAGED_FILES" ] && [ -z "$DIFF_STAT" ]; then
    exit 0
fi

{
    echo ""
    echo "## [$TIME] pre-commit | branch=$BRANCH"
    echo ""
    if [ -n "$STAGED_FILES" ]; then
        echo "**Staged files:**"
        echo '```'
        echo "$STAGED_FILES"
        echo '```'
    fi
    if [ -n "$DIFF_STAT" ]; then
        echo ""
        echo "**Diff stat:** $DIFF_STAT"
    fi
} >> "$DAILY_FILE"

# Stage the journal so it goes into THIS commit.
(cd "$REPO_ROOT" && git add -- "$DAILY_FILE_REL") 2>/dev/null || true

exit 0
