#!/usr/bin/env bash
# TeammateIdle hook — a teammate must not go idle leaving its own work uncommitted.
#
# Exit 2 = "not yet": the teammate keeps working and reads this script's stderr.
# The rule fires only inside a *linked worktree* (git-dir != git-common-dir): there
# every uncommitted change is the teammate's own. In the shared main tree the dirty
# files may belong to another writer, so the hook never blocks there — it prints a
# systemMessage reminding the lead to stage explicit paths, never `git add -A`
# (the commit race measured on 2026-05-26; see project memory).
#
# Fail-open: two blocks for the same agent_id -> the third idle passes with a warning.
# TEAM_GATES=off disables the hook. stdin: {"agent_id","agent_type","cwd",...}.
set +e
INPUT=$(cat)
[ "${TEAM_GATES:-on}" = "off" ] && exit 0

PYLIB="$(dirname "$0")/../../core/hooks/_lib/python-bin.sh"
# shellcheck source=/dev/null
[ -f "$PYLIB" ] && source "$PYLIB"
PY="${PY:-python}"

mapfile -t FIELDS < <(HOOK_INPUT="$INPUT" "$PY" - <<'PYEOF'
import json, os
try:
    d = json.loads(os.environ.get("HOOK_INPUT") or "{}")
except Exception:
    d = {}
for key in ("agent_id", "agent_type", "cwd"):
    print(str(d.get(key) or "-").replace("\n", " "))
PYEOF
)
# Windows Python prints CRLF; a trailing CR would make every path test fail silently.
AGENT_ID="${FIELDS[0]:--}"; AGENT_TYPE="${FIELDS[1]:--}"; CWD="${FIELDS[2]:--}"
AGENT_ID="${AGENT_ID%$'\r'}"; AGENT_TYPE="${AGENT_TYPE%$'\r'}"; CWD="${CWD%$'\r'}"

[ -d "$CWD" ] || CWD="$(pwd)"
git -C "$CWD" rev-parse --show-toplevel >/dev/null 2>&1 || exit 0

DIRTY="$(git -C "$CWD" status --porcelain 2>/dev/null | grep -v 'docs/sessions/' | head -n 20)"
[ -z "$DIRTY" ] && exit 0

# A linked worktree carries a `.git` *file* (gitdir pointer); the main tree has a `.git` directory.
TOP="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null)"
if [ ! -f "$TOP/.git" ]; then
  printf '{"systemMessage":"team-gate: %s (%s) went idle with uncommitted changes in the shared tree. Lead: stage explicit paths, never git add -A."}\n' "$AGENT_TYPE" "$AGENT_ID"
  exit 0
fi

COMMON="$(git -C "$CWD" rev-parse --git-common-dir 2>/dev/null)"
case "$COMMON" in /*|[A-Za-z]:*) ;; *) COMMON="$CWD/$COMMON" ;; esac
ROOT="$(dirname "$COMMON")"
STRIKE_DIR="$ROOT/data/team-gates"
mkdir -p "$STRIKE_DIR" 2>/dev/null
SAFE_ID="$(printf '%s' "$AGENT_ID" | tr -c 'A-Za-z0-9_.-' '_')"
STRIKE_FILE="$STRIKE_DIR/idle-${SAFE_ID}.strikes"
STRIKES="$(cat "$STRIKE_FILE" 2>/dev/null || echo 0)"
case "$STRIKES" in ''|*[!0-9]*) STRIKES=0 ;; esac

if [ "$STRIKES" -ge 2 ]; then
  echo "team-gate: $AGENT_TYPE still has uncommitted work in $CWD after two reminders - letting it idle. Lead: collect or discard that work explicitly." >&2
  rm -f "$STRIKE_FILE"
  exit 0
fi
echo $((STRIKES + 1)) > "$STRIKE_FILE"
{
  echo "team-gate BLOCK ($((STRIKES + 1))/2): you are idle with uncommitted work in your own worktree ($CWD):"
  echo "$DIRTY"
  echo "Commit it on your branch (a WIP commit is fine; Why:/Layer: trailers are mandatory, see docs/claude/COMMIT_GUIDE.md), or tell the lead why it must stay uncommitted, then finish."
} >&2
exit 2
