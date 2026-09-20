#!/usr/bin/env bash
# SubagentStart / SubagentStop hook — one JSON line per event in data/team-journal.jsonl
# ("who started / finished what, and when"), so the lead and the owner can replay a
# team session without opening every transcript. data/ is gitignored.
# Never blocks: always exits 0. Override the directory with TEAM_JOURNAL_DIR.
set +e
INPUT=$(cat)

PYLIB="$(dirname "$0")/../../core/hooks/_lib/python-bin.sh"
# shellcheck source=/dev/null
[ -f "$PYLIB" ] && source "$PYLIB"
PY="${PY:-python}"

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
DIR="${TEAM_JOURNAL_DIR:-$ROOT/data}"
mkdir -p "$DIR" 2>/dev/null || exit 0

HOOK_INPUT="$INPUT" "$PY" - "$DIR/team-journal.jsonl" <<'PYEOF' 2>/dev/null
import datetime, json, os, sys
try:
    d = json.loads(os.environ.get("HOOK_INPUT") or "{}")
except Exception:
    d = {}
msg = d.get("last_assistant_message") or ""
rec = {
    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
    "event": d.get("hook_event_name", ""),
    "agent_type": d.get("agent_type", ""),
    "agent_id": d.get("agent_id", ""),
    "cwd": d.get("cwd", ""),
    "tail": msg[-300:],
}
with open(sys.argv[1], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
PYEOF
exit 0
