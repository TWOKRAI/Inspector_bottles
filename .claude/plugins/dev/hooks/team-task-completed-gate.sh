#!/usr/bin/env bash
# TaskCompleted hook — quality gate before a team task is marked complete.
#
# Blocks (exit 2) when the changed Python files fail `ruff check` or when the
# changed *test* files are red. Exit 2 keeps the task open and feeds this script's
# stderr back to the teammate, so every message says what to do next.
#
# Fail-open rules (a gate that loops forever burns tokens, not defects):
#   - two blocks on the same task_id -> the third attempt passes with a warning
#     (mirrors the project's 2-iteration limit -> escalate to the lead);
#   - pytest over 90 s -> not blocking: a hang is not evidence;
#   - TEAM_GATES=off -> skipped entirely;
#   - task title containing [RED], [docs] or [skip-gate] -> skipped: the tester's
#     RED set is red by design, docs tasks touch no Python.
#
# Shared-tree caveat: in-process teammates share one working tree, so "changed
# files" can include another writer's in-flight work. The strike counter bounds
# the damage; the durable fix is one worktree per writer (docs/claude/AGENT_TEAMS_GUIDE.md).
#
# stdin: {"task_id","task_title","cwd",...}. Exits 0 on its own errors.
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
for key in ("task_id", "task_title", "cwd"):
    print(str(d.get(key) or "-").replace("\n", " "))
PYEOF
)
# Windows Python prints CRLF; a trailing CR would make every path test fail silently.
TASK_ID="${FIELDS[0]:--}"; TASK_TITLE="${FIELDS[1]:--}"; CWD="${FIELDS[2]:--}"
TASK_ID="${TASK_ID%$'\r'}"; TASK_TITLE="${TASK_TITLE%$'\r'}"; CWD="${CWD%$'\r'}"

case "$TASK_TITLE" in *"[RED]"*|*"[docs]"*|*"[skip-gate]"*) exit 0 ;; esac

[ -d "$CWD" ] || CWD="$(pwd)"
ROOT="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$ROOT" || exit 0

STRIKE_DIR="$ROOT/data/team-gates"
mkdir -p "$STRIKE_DIR" 2>/dev/null
SAFE_ID="$(printf '%s' "$TASK_ID" | tr -c 'A-Za-z0-9_.-' '_')"
STRIKE_FILE="$STRIKE_DIR/task-${SAFE_ID}.strikes"
STRIKES="$(cat "$STRIKE_FILE" 2>/dev/null || echo 0)"
case "$STRIKES" in ''|*[!0-9]*) STRIKES=0 ;; esac

block() {
  if [ "$STRIKES" -ge 2 ]; then
    echo "team-gate: $1" >&2
    echo "team-gate: third attempt on task '$TASK_TITLE' - passing with a warning. Tell the lead this task closed with a failing gate." >&2
    rm -f "$STRIKE_FILE"
    exit 0
  fi
  echo $((STRIKES + 1)) > "$STRIKE_FILE"
  echo "team-gate BLOCK ($((STRIKES + 1))/2) on task '$TASK_TITLE': $1" >&2
  echo "Fix it; if the failure is not yours, tell the lead which files and why, then complete the task again." >&2
  exit 2
}

CHANGED="$( { git diff --name-only HEAD -- '*.py'; git ls-files --others --exclude-standard -- '*.py'; } 2>/dev/null | grep -v '^\.claude/worktrees/' | sort -u)"
FILES=()
while IFS= read -r f; do [ -n "$f" ] && [ -f "$f" ] && FILES+=("$f"); done <<< "$CHANGED"
if [ "${#FILES[@]}" -eq 0 ]; then rm -f "$STRIKE_FILE"; exit 0; fi

if command -v ruff >/dev/null 2>&1; then
  OUT="$(ruff check "${FILES[@]}" 2>&1)"; RC=$?
  if [ "$RC" -ne 0 ]; then
    block "ruff check failed on changed files:
$(printf '%s\n' "$OUT" | tail -n 25)"
  fi
fi

TESTS=()
for f in "${FILES[@]}"; do
  case "$f" in */tests/*|test_*.py|*/test_*.py) TESTS+=("$f") ;; esac
done
if [ "${#TESTS[@]}" -gt 0 ]; then
  RUN=("$PY" -m pytest -q -x -p no:cacheprovider "${TESTS[@]}")
  command -v timeout >/dev/null 2>&1 && RUN=(timeout 90 "${RUN[@]}")
  OUT="$(QT_QPA_PLATFORM=offscreen "${RUN[@]}" 2>&1)"; RC=$?
  if [ "$RC" -eq 124 ]; then
    echo "team-gate: pytest on changed tests exceeded 90 s - not blocking, but a hanging test is worse than a red one; report it to the lead." >&2
    exit 0
  fi
  # 5 = no tests collected (conftest-only change): nothing to judge
  if [ "$RC" -ne 0 ] && [ "$RC" -ne 5 ]; then
    block "changed tests are red:
$(printf '%s\n' "$OUT" | tail -n 30)"
  fi
fi

rm -f "$STRIKE_FILE"
exit 0
