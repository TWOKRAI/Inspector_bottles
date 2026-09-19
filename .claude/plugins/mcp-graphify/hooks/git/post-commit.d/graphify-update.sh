#!/usr/bin/env bash
# ============================================================================
# graphify incremental update — post-commit PART, run by the core dispatcher.
#   1. Own bash process; cwd = repo toplevel (set by the dispatcher).
#   2. stdout/stderr captured into .claude/logs/post-commit.log; exit ignored.
#   3. Linked worktrees are already skipped upstream — no guard needed here.
#   4. Must not background itself (no `&` / disown) and must not `set -e`.
#   5. Prints exactly one line: `ok: ...` / `skip: ...` / `fail: rc=N`.
#
# What this part does NOT do:
#   1. Clean stale nodes — `update` adds, never removes vanished files or
#      newly-.graphifyignore'd ones; full reset: `graphify update . --force`.
#   2. Name new communities — fresh clusters get "Community N" placeholders;
#      catch up with `graphify label . --missing-only` (mind per-batch cost).
# ============================================================================

if ! command -v graphify >/dev/null 2>&1; then
  echo "skip: graphify not found"
  exit 0
fi

ROOT="$(git rev-parse --show-toplevel)"
if [ ! -f "$ROOT/.mcp.json" ]; then
  echo "skip: no .mcp.json in project (MCP servers composed elsewhere)"
  exit 0
fi
if ! grep -q '"graphify"' "$ROOT/.mcp.json" 2>/dev/null; then
  echo "skip: mcp-graphify not enabled"
  exit 0
fi

_run_with_timeout() {
  # $1 = timeout seconds; rest = command. Sets UPDATE_RC.
  local _timeout="$1"; shift
  "$@" >/dev/null 2>&1 &
  local pid=$!
  local waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$waited" -ge "$_timeout" ]; then
      kill "$pid" 2>/dev/null
      sleep 1
      kill -9 "$pid" 2>/dev/null
      echo "fail: timeout after ${_timeout}s"
      exit 1
    fi
    sleep 1
    waited=$((waited + 1))
  done
  wait "$pid"
  UPDATE_RC=$?
}

# A real shell function backgrounded directly (not `bash -c "..."`) avoids
# nested-quote fragility while preserving the original's subshell isolation
# (the `cd` here must not affect this script's own cwd).
_graphify_update() { (cd "$ROOT" && graphify update .); }
_run_with_timeout "${GRAPHIFY_UPDATE_TIMEOUT:-600}" _graphify_update

if [ "$UPDATE_RC" -ne 0 ]; then
  echo "fail: rc=$UPDATE_RC"
  exit 1
fi

mkdir -p "$ROOT/.claude/logs/post-commit.d"
git rev-parse HEAD > "$ROOT/.claude/logs/post-commit.d/graphify-update.sha"
echo "ok: updated"
