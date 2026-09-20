#!/usr/bin/env bash
# ============================================================================
# qex auto-reindex — post-commit PART, run by the core dispatcher.
#   1. Own bash process; cwd = repo toplevel (set by the dispatcher).
#   2. stdout/stderr captured into .claude/logs/post-commit.log; exit ignored.
#   3. Linked worktrees are already skipped upstream — no guard needed here.
#   4. Must not background itself (no `&` / disown) and must not `set -e`.
#   5. Prints exactly one line: `ok: ...` / `skip: ...` / `fail: rc=N`.
#   6. Wall-clock limit 5 h by default (QEX_REINDEX_TIMEOUT, 0 = none); one run
#      per project at a time (lock below).
# ============================================================================

# No `set -e`: every branch below ends in an explicit exit / final line, and
# a mid-script failure must still reach the one required status line.

# --- Opt-in gate: auto-reindex only when the owner asked for it ------------
# Default OFF (owner's rule, 2026-09-20): a commit must never start a
# tens-of-minutes embedder run on its own; `/mcp-qex:qex-reindex` is the
# command. Precedence: env QEX_AUTO_REINDEX (on|off — tests, one-off runs),
# then key `qex_auto_reindex` in the ```ini block of .claude/modes/_stack.md
# (read via core's _lib/stack-ini.sh), then off. bash 3.2-safe (no ${var,,}).
AUTO="${QEX_AUTO_REINDEX:-}"
if [ -z "$AUTO" ]; then
  ROOT0="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  STACK_LIB="$ROOT0/.claude/plugins/core/hooks/_lib/stack-ini.sh"
  if [ -f "$STACK_LIB" ]; then
    # shellcheck source=/dev/null
    . "$STACK_LIB"
    AUTO="$(stack_ini_get qex_auto_reindex off "$ROOT0/.claude/modes/_stack.md" 2>/dev/null || echo off)"
  fi
fi
# No external tools here (the dispatcher may run with a bare PATH): case-insensitive
# match via nocasematch (bash >= 3.1) instead of `tr`.
shopt -s nocasematch 2>/dev/null
case "$AUTO" in
  on|1|true|yes) ;;
  *) echo "skip: auto-reindex off (qex_auto_reindex=off; run /mcp-qex:qex-reindex)"; exit 0 ;;
esac
shopt -u nocasematch 2>/dev/null

# --- Resolve QEX_BIN: env override, then PATH, then known install dirs -----
QEX_BIN="${QEX_BIN:-}"
if [ -z "$QEX_BIN" ]; then
  QEX_BIN="$(command -v qex 2>/dev/null || true)"
fi
if [ -z "$QEX_BIN" ] && [ -x "$HOME/.cargo/bin/qex" ]; then
  QEX_BIN="$HOME/.cargo/bin/qex"
fi
if [ -z "$QEX_BIN" ] && [ -x "$HOME/.local/bin/qex" ]; then
  QEX_BIN="$HOME/.local/bin/qex"
fi

if [ -z "$QEX_BIN" ] || [ ! -x "$QEX_BIN" ]; then
  echo "skip: qex not found"
  exit 0
fi

# --- Ollama reachability (qex needs it for embeddings) ---------------------
OLLAMA_URL="${QEX_OLLAMA_URL:-http://localhost:11434/}"
if ! command -v curl >/dev/null 2>&1 || ! curl -s --max-time 1 "$OLLAMA_URL" >/dev/null 2>&1; then
  echo "skip: ollama down"
  exit 0
fi

# --- Plugin enabled? ---------------------------------------------------------
ROOT="$(git rev-parse --show-toplevel)"
if [ ! -f "$ROOT/.mcp.json" ]; then
  echo "skip: no .mcp.json in project (MCP servers composed elsewhere)"
  exit 0
fi
if ! grep -q '"qex"' "$ROOT/.mcp.json" 2>/dev/null; then
  echo "skip: mcp-qex not enabled"
  exit 0
fi

# --- Incremental reindex -----------------------------------------------------
# Drive the reindex through the seed's own MCP client (reindex_retry.py does the
# initialize / notifications/initialized handshake and a bounded retry loop). A bare
# JSON-RPC line piped into the qex binary is rejected before the handshake — the old
# hook swallowed exactly that failure with `|| echo "... failed"`.
PY=""
for cand in "${CLAUDE_PYTHON_BIN:-}" python3 python py; do
  [ -n "$cand" ] || continue
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import sys" >/dev/null 2>&1; then
    PY="$cand"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "skip: no python for reindex_retry.py"
  exit 0
fi
DRIVER="${QEX_REINDEX_DRIVER:-$ROOT/.claude/plugins/mcp-qex/reindex_retry.py}"
if [ ! -f "$DRIVER" ]; then
  echo "skip: reindex driver not materialized ($DRIVER)"
  exit 0
fi
# --- One reindex per project at a time --------------------------------------
# Forty commits in a session used to start forty concurrent reindexes, each
# embedding the same tree on the GPU until the old 600 s kill hit it — and a
# large code base legitimately needs hours (owner, 2026-09-18). Lock: a
# second run while one is in flight queues exactly ONE follow-up (a commit made
# during the run is picked up by the Merkle diff of that follow-up); a stale
# lock (holder gone) is taken over.
STATE_DIR="$ROOT/.claude/logs/post-commit.d"
mkdir -p "$STATE_DIR"
LOCK="$STATE_DIR/qex-reindex.lock"
PENDING="$STATE_DIR/qex-reindex.pending"
if ! mkdir "$LOCK" 2>/dev/null; then
  holder="$(cat "$LOCK/pid" 2>/dev/null)"
  if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
    : > "$PENDING"
    echo "skip: reindex already running (pid $holder) — one follow-up queued"
    exit 0
  fi
  rm -rf "$LOCK"
  if ! mkdir "$LOCK" 2>/dev/null; then
    echo "skip: lock race"
    exit 0
  fi
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

_descendants() {
  # Prints every descendant pid of $1, parents before children. No pgrep
  # (bare Git Bash) -> prints nothing and the caller kills the driver alone.
  local _c
  for _c in $(pgrep -P "$1" 2>/dev/null); do
    echo "$_c"
    _descendants "$_c"
  done
}

_run_with_timeout() {
  # $1 = timeout seconds; rest = command. Sets REINDEX_RC.
  local _timeout="$1"; shift
  "$@" >/dev/null 2>&1 &
  local pid=$!
  local waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$waited" -ge "$_timeout" ]; then
      # The whole tree, snapshotted BEFORE the first kill: the driver's
      # qex-launcher.py + qex children survive a kill of the driver alone, get
      # reparented to pid 1 and keep embedding. Two qex on one GPU push every
      # batch past qex's built-in 10 s embedder timeout, so neither run ever
      # completes (live probe 2026-09-18: two days, zero finished indexes).
      # The driver goes first and with -9, no grace: a driver that sees its
      # qex die starts the next attempt at once — a fresh launcher + qex this
      # snapshot has never heard of (seen live: two respawns during cleanup).
      local victims _v
      victims="$(_descendants "$pid")"
      kill -9 "$pid" 2>/dev/null
      for _v in $victims; do kill "$_v" 2>/dev/null; done
      sleep 1
      for _v in $victims; do kill -9 "$_v" 2>/dev/null; done
      echo "fail: timeout after ${_timeout}s"
      exit 1
    fi
    sleep 1
    waited=$((waited + 1))
  done
  wait "$pid"
  REINDEX_RC=$?
}

_run_driver() {
  # Wall-clock limit: 5 h by default (owner, 2026-09-18: "4-5 hours"). A full
  # index of a large code base legitimately takes hours, and qex persists
  # nothing until the run completes, so a short limit only throws the work
  # away — but an unbounded run hid a two-day livelock. QEX_REINDEX_TIMEOUT
  # overrides it in seconds; 0 = no limit; garbage falls back to the default.
  local _limit="${QEX_REINDEX_TIMEOUT:-18000}"
  case "$_limit" in
    ''|*[!0-9]*) _limit=18000 ;;
  esac
  if [ "$_limit" -gt 0 ]; then
    _run_with_timeout "$_limit" "$@"
  else
    "$@" >/dev/null 2>&1
    REINDEX_RC=$?
  fi
}

# Attempts: the driver's own default (12). One attempt used to be forced here,
# and a single attempt dies on the first embedding batch that hits qex's ~10 s
# built-in timeout — the reason every hook run of a loaded machine ended rc=1.
while :; do
  rm -f "$PENDING"
  _run_driver "$PY" "$DRIVER" --project "$ROOT" --attempts "${QEX_REINDEX_ATTEMPTS:-12}"
  [ "$REINDEX_RC" -eq 0 ] || break
  [ -f "$PENDING" ] || break
done

if [ "$REINDEX_RC" -ne 0 ]; then
  echo "fail: rc=$REINDEX_RC"
  exit 1
fi

git rev-parse HEAD > "$STATE_DIR/qex-reindex.sha"
echo "ok: reindexed"
