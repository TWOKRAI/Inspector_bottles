#!/usr/bin/env bash
# SessionStart / SubagentStart / SubagentStop hook — one JSON line per event in
# data/agent-journal.jsonl ("who started / finished what, and when"), so the lead and the
# owner can replay a session without opening every transcript. data/ is gitignored.
#
# Every record carries session_id, branch (git branch of the event's cwd; empty on a
# detached HEAD or outside a git repo) and source (SessionStart only: startup / resume /
# clear / compact, so a reader can tell a new session from a compaction). SessionStart gives "which session sits where" even
# for a lead that never spawns a subagent. The journal stays per worktree: no shared file.
#
# Lives in `observability` (default-on), not in `agent-teams`: every subagent this
# project spawns fires SubagentStart/Stop, so the journal is the one cheap way to
# observe ORDINARY subagents — with or without the Agent Teams engine enabled.
#
# Never blocks: always exits 0. Override the directory with AGENT_JOURNAL_DIR.
set +e
INPUT=$(cat)

PYLIB="$(dirname "$0")/../../core/hooks/_lib/python-bin.sh"
# shellcheck source=/dev/null
[ -f "$PYLIB" ] && source "$PYLIB"
PY="${PY:-python}"

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
DIR="${AGENT_JOURNAL_DIR:-$ROOT/data}"
mkdir -p "$DIR" 2>/dev/null || exit 0

HOOK_INPUT="$INPUT" "$PY" - "$DIR/agent-journal.jsonl" <<'PYEOF' 2>/dev/null
import datetime, json, os, subprocess, sys
try:
    d = json.loads(os.environ.get("HOOK_INPUT") or "{}")
except Exception:
    d = {}
msg = d.get("last_assistant_message") or ""
cwd = d.get("cwd") or ""
branch = ""
if cwd:
    try:
        branch = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=3,
        ).stdout.strip()
    except Exception:
        branch = ""
rec = {
    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
    "event": d.get("hook_event_name", ""),
    "agent_type": d.get("agent_type", ""),
    "agent_id": d.get("agent_id", ""),
    "session_id": d.get("session_id", ""),
    "source": d.get("source", ""),
    "cwd": cwd,
    "branch": branch,
    "tail": msg[-300:],
}
with open(sys.argv[1], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
PYEOF
exit 0
