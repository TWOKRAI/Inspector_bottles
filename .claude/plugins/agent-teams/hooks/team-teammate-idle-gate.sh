#!/usr/bin/env bash
# TeammateIdle hook — a teammate must not go idle leaving its own work uncommitted.
#
# Exit 2 = "not yet": the teammate keeps working and reads this script's stderr.
# The rule fires only inside a *linked worktree* (git-dir != git-common-dir): there
# every uncommitted change is the teammate's own. In the shared main tree the dirty
# files may belong to another writer, so the hook never blocks there — it prints a
# systemMessage reminding the lead to stage explicit paths, never `git add -A`
# (`git add -A` in a shared tree sweeps another writer's in-flight work into your
# commit — the failure mode this whole hook exists to make visible).
#
# Fail-open: two blocks for the same teammate -> the third idle passes with a warning;
# unparsable stdin passes too (an unidentified teammate cannot be counted).
# Harness timeout is fail-open as well: the manifest registers this hook with
# `timeout: 15` (s), and a hook killed at the deadline emits no exit 2, so the
# teammate goes idle. Everything here is two git calls plus one json.dumps.
# TEAM_GATES=off disables the hook.
# stdin (CC 2.1.222 TeammateIdle zod schema, read out of the binary): the event carries
# {"session_id","transcript_path","cwd","teammate_name","team_name"} — there is NO
# agent_id and NO agent_type here (those belong to SubagentStart/Stop). An Inspector-era
# hook reading agent_id keyed every teammate's strikes into one shared "idle--.strikes".
# agent_id/agent_type stay only as a legacy fallback for other Claude Code versions.
set +e
INPUT=$(cat)
[ "${TEAM_GATES:-on}" = "off" ] && exit 0

PYLIB="$(dirname "$0")/../../core/hooks/_lib/python-bin.sh"
# shellcheck source=/dev/null
[ -f "$PYLIB" ] && source "$PYLIB"
PY="${PY:-python}"

# Line 1 is a parse status, so unparsable stdin is distinguishable from a payload
# whose fields are genuinely absent (both would otherwise read as "-").
# bash 3.2 (macOS /bin/bash) has no `mapfile`; a read loop is portable to Git Bash too.
FIELDS=()
while IFS= read -r _field; do FIELDS+=("$_field"); done < <(HOOK_INPUT="$INPUT" "$PY" - <<'PYEOF'
import json, os
try:
    d = json.loads(os.environ.get("HOOK_INPUT") or "{}")
    if not isinstance(d, dict):
        raise ValueError("hook payload is not a JSON object")
    print("ok")
except Exception:
    print("unparsable")
    d = {}
for keys in (("teammate_name", "agent_id", "agent_type"), ("cwd",)):
    value = next((d.get(k) for k in keys if d.get(k)), None)
    print(str(value or "-").replace("\n", " "))
PYEOF
)
# Windows Python prints CRLF; a trailing CR would make every path test fail silently.
STATUS="${FIELDS[0]:-unparsable}"; TEAMMATE="${FIELDS[1]:--}"; CWD="${FIELDS[2]:--}"
STATUS="${STATUS%$'\r'}"; TEAMMATE="${TEAMMATE%$'\r'}"; CWD="${CWD%$'\r'}"
# Also covers "no working Python at all": FIELDS is empty -> STATUS unparsable -> pass.
[ "$STATUS" = "ok" ] || exit 0

[ -d "$CWD" ] || CWD="$(pwd)"
TOP="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null)" || exit 0

# Guard: `rev-parse --show-toplevel` walks up to ANY ancestor git repo, not just
# this project's -- if $HOME (or another ancestor dir) is itself a repo, a $CWD
# outside the project still resolves to a real toplevel, and the strike counter
# below (mkdir -p "$STRIKE_DIR") lands in that unrelated tree's data/team-gates.
# CLAUDE_PROJECT_DIR is the harness's own notion of "this project"; when it is
# set, the MAIN repository root must fall INSIDE it (paths normalised for
# Windows: case + backslash-vs-slash). The main root comes from
# `git-common-dir`, not from the worktree's own toplevel: a live-team writer's
# worktree lives BESIDE the repo (`../<repo>--team-<task>`, Д45 -- a worktree
# under `.claude/worktrees/` pays a +20-28k nested-CLAUDE.md tax on its first
# read), so its toplevel is outside CLAUDE_PROJECT_DIR while its common dir is
# `<project>/.git`. Prefix, not exact equality, keeps the older in-tree layout
# working too. Empty CLAUDE_PROJECT_DIR (older harness) keeps the prior,
# unchecked behaviour.
MAIN_COMMON="$(git -C "$CWD" rev-parse --git-common-dir 2>/dev/null)"
case "$MAIN_COMMON" in /*|[A-Za-z]:*) ;; *) MAIN_COMMON="$CWD/$MAIN_COMMON" ;; esac
MAIN_ROOT="$(git -C "$(dirname "$MAIN_COMMON")" rev-parse --show-toplevel 2>/dev/null)" || MAIN_ROOT="$TOP"
[ -n "$MAIN_ROOT" ] || MAIN_ROOT="$TOP"
if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
  NORM_ROOT="$(printf '%s' "$MAIN_ROOT" | tr 'A-Z\\' 'a-z/' | sed 's:/*$::')"
  NORM_PROJECT="$(printf '%s' "$CLAUDE_PROJECT_DIR" | tr 'A-Z\\' 'a-z/' | sed 's:/*$::')"
  case "$NORM_ROOT" in
    "$NORM_PROJECT"|"$NORM_PROJECT"/*) ;;
    *) exit 0 ;;
  esac
fi

# -uall, not the default -unormal: git collapses a wholly-untracked directory to a
# single "?? docs/" entry, which the docs/sessions/ filter below would then miss.
DIRTY="$(git -C "$CWD" status --porcelain -uall 2>/dev/null | grep -v 'docs/sessions/' | head -n 20)"
[ -z "$DIRTY" ] && exit 0

# A linked worktree carries a `.git` *file* (gitdir pointer); the main tree has a `.git` directory.
if [ ! -f "$TOP/.git" ]; then
  # json.dumps, not printf: a quote inside teammate_name must not break the JSON the harness parses.
  HOOK_TEAMMATE="$TEAMMATE" "$PY" -c "import json, os; print(json.dumps({'systemMessage': 'team-gate: %s went idle with uncommitted changes in the shared tree. Lead: stage explicit paths, never git add -A.' % os.environ['HOOK_TEAMMATE']}))"
  exit 0
fi

COMMON="$(git -C "$CWD" rev-parse --git-common-dir 2>/dev/null)"
case "$COMMON" in /*|[A-Za-z]:*) ;; *) COMMON="$CWD/$COMMON" ;; esac
ROOT="$(dirname "$COMMON")"
STRIKE_DIR="$ROOT/data/team-gates"
mkdir -p "$STRIKE_DIR" 2>/dev/null
SAFE_ID="$(printf '%s' "$TEAMMATE" | tr -c 'A-Za-z0-9_.-' '_' | cut -c1-80)"
STRIKE_FILE="$STRIKE_DIR/idle-${SAFE_ID}.strikes"
STRIKES="$(cat "$STRIKE_FILE" 2>/dev/null || echo 0)"
case "$STRIKES" in ''|*[!0-9]*) STRIKES=0 ;; esac

if [ "$STRIKES" -ge 2 ]; then
  echo "team-gate: $TEAMMATE still has uncommitted work in $CWD after two reminders - letting it idle. Lead: collect or discard that work explicitly." >&2
  rm -f "$STRIKE_FILE"
  exit 0
fi
echo $((STRIKES + 1)) > "$STRIKE_FILE"
{
  echo "team-gate BLOCK ($((STRIKES + 1))/2): you are idle with uncommitted work in your own worktree ($CWD):"
  echo "$DIRTY"
  echo "Commit it on your branch (a WIP commit is fine; Why:/Layer: trailers are mandatory, see .claude/COMMIT_GUIDE.md), or tell the lead why it must stay uncommitted, then finish."
} >&2
exit 2
