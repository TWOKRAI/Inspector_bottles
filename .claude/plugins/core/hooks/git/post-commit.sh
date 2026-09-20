#!/usr/bin/env bash
# Core post-commit dispatcher — one .git/hooks/post-commit, many plugin parts.
#
# Parts contract: one part = one file
#   .claude/plugins/<id>/hooks/git/post-commit.d/<name>.sh
# Each part runs as its own `bash` process, cwd = repo toplevel. A part may
# `exit` freely; its exit code is logged and otherwise ignored. A part
# prints one human line (`ok: ...` / `skip: ...` / `fail: ...`) — that line
# and any other output goes to the shared log, not to the terminal. A part
# must NOT implement its own worktree guard (the dispatcher already skips
# linked worktrees) and must NOT background itself (the dispatcher backgrounds
# the whole batch).
#
# Part basenames must be unique across plugins; the freshness marker is
# <part-basename>.sha.
#
# The dispatcher itself is fail-open: it never aborts on a failing command,
# one failing part never stops the next, and its own exit code is always 0.
# CLAUDE_KIT_POST_COMMIT_SYNC=1 runs the batch in the foreground (tests).
# CLAUDE_KIT_PLUGINS_DIR overrides the plugins directory (tests).

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[ -n "$ROOT" ] || exit 0
PLUGINS_DIR="${CLAUDE_KIT_PLUGINS_DIR:-$ROOT/.claude/plugins}"
LOG="$ROOT/.claude/logs/post-commit.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null || exit 0

if [ -f "$LOG" ]; then
  size=$(wc -c <"$LOG" | tr -d ' ')
  if [ "$size" -gt 1048576 ]; then
    mv -f "$LOG" "$LOG.1"
  fi
fi

_real() { (cd "$1" 2>/dev/null && pwd -P); }

gd="$(_real "$(git rev-parse --git-dir 2>/dev/null)")"
cd_="$(_real "$(git rev-parse --git-common-dir 2>/dev/null)")"
if [ -n "$gd" ] && [ -n "$cd_" ] && [ "$gd" != "$cd_" ]; then
  echo "skip: linked worktree (main tree only)" >>"$LOG"
  exit 0
fi

run_parts() {
  local part n=0
  for part in "$PLUGINS_DIR"/*/hooks/git/post-commit.d/*.sh; do
    [ -f "$part" ] || continue
    n=$((n + 1))
    local id name
    id="$(basename "$(dirname "$(dirname "$(dirname "$(dirname "$part")")")")")"
    name="$(basename "$part")"
    (cd "$ROOT" && bash "$part") >>"$LOG" 2>&1
    echo "[$id/$name] rc=$?" >>"$LOG"
  done
  [ "$n" -eq 0 ] && echo "no parts" >>"$LOG"
  return 0
}

if [ "${CLAUDE_KIT_POST_COMMIT_SYNC:-0}" = "1" ]; then
  run_parts </dev/null
else
  run_parts </dev/null >/dev/null 2>&1 &
  disown 2>/dev/null
fi

exit 0
