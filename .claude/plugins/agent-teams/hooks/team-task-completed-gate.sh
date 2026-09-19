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
#     RED set is red by design, docs tasks touch no Python;
#   - unparsable stdin -> skipped: a gate that cannot identify the task cannot
#     judge it, and guessing from the ambient working tree blocks the wrong agent.
#
# Harness timeout is fail-open too. The manifest registers this hook with
# `timeout: 150` (s); when Claude Code kills it at the deadline the task is NOT
# blocked — a killed hook produces no exit 2, so the task completes. Budget:
# ruff on the changed files + pytest capped at 90 s stays well inside 150 s.
#
# Shared-tree caveat: in-process teammates share one working tree, so "changed
# files" can include another writer's in-flight work. The strike counter bounds
# the damage; the durable fix is one worktree per writer
# (.claude/plugins/agent-teams/README.md).
#
# stdin (CC 2.1.222 TaskCompleted zod schema, read out of the binary — the field is
# `task_subject`, NOT `task_title`; an Inspector-era hook reading `task_title` saw "-"
# for every task and so never honoured a [RED] prefix):
#   {"session_id","transcript_path","cwd","task_id","task_subject",
#    "task_description"?,"teammate_name"?}. Exits 0 on its own errors.
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
# task_title is a legacy alias kept as a fallback: the seed ships to projects on other
# Claude Code versions, and one `or` is cheaper than a silently disarmed gate.
for keys in (("task_id",), ("task_subject", "task_title"), ("cwd",)):
    value = next((d.get(k) for k in keys if d.get(k)), None)
    print(str(value or "-").replace("\n", " "))
PYEOF
)
# Windows Python prints CRLF; a trailing CR would make every path test fail silently.
STATUS="${FIELDS[0]:-unparsable}"; TASK_ID="${FIELDS[1]:--}"; TASK_SUBJECT="${FIELDS[2]:--}"; CWD="${FIELDS[3]:--}"
STATUS="${STATUS%$'\r'}"; TASK_ID="${TASK_ID%$'\r'}"; TASK_SUBJECT="${TASK_SUBJECT%$'\r'}"; CWD="${CWD%$'\r'}"
# Also covers "no working Python at all": FIELDS is empty -> STATUS unparsable -> pass.
[ "$STATUS" = "ok" ] || exit 0

# Only a *prefix* disarms the gate: "[RED] ..." is the tester's set, "fix the [RED] path" is not.
case "$TASK_SUBJECT" in "[RED]"*|"[docs]"*|"[skip-gate]"*) exit 0 ;; esac

[ -d "$CWD" ] || CWD="$(pwd)"
ROOT="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null)" || exit 0

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
MAIN_ROOT="$(git -C "$(dirname "$MAIN_COMMON")" rev-parse --show-toplevel 2>/dev/null)" || MAIN_ROOT="$ROOT"
[ -n "$MAIN_ROOT" ] || MAIN_ROOT="$ROOT"
if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
  NORM_ROOT="$(printf '%s' "$MAIN_ROOT" | tr 'A-Z\\' 'a-z/' | sed 's:/*$::')"
  NORM_PROJECT="$(printf '%s' "$CLAUDE_PROJECT_DIR" | tr 'A-Z\\' 'a-z/' | sed 's:/*$::')"
  case "$NORM_ROOT" in
    "$NORM_PROJECT"|"$NORM_PROJECT"/*) ;;
    *) exit 0 ;;
  esac
fi

cd "$ROOT" || exit 0

# Strike counters live in the MAIN repository root (same as the idle gate), so a task judged
# from a worktree and later from the main tree shares one counter.
COMMON="$(git -C "$CWD" rev-parse --git-common-dir 2>/dev/null)"
case "$COMMON" in /*|[A-Za-z]:*) ;; *) COMMON="$CWD/$COMMON" ;; esac
STRIKE_DIR="$(dirname "$COMMON")/data/team-gates"
mkdir -p "$STRIKE_DIR" 2>/dev/null
# No task_id in the payload -> key the counter by the title instead, so two untitled
# tasks still get separate counters. (A title that equals some other task's id would
# collide; the cost is a shared 2-strike budget, which the ladder bounds anyway.)
[ "$TASK_ID" = "-" ] && TASK_ID="$TASK_SUBJECT"
SAFE_ID="$(printf '%s' "$TASK_ID" | tr -c 'A-Za-z0-9_.-' '_' | cut -c1-80)"
STRIKE_FILE="$STRIKE_DIR/task-${SAFE_ID}.strikes"
STRIKES="$(cat "$STRIKE_FILE" 2>/dev/null || echo 0)"
case "$STRIKES" in ''|*[!0-9]*) STRIKES=0 ;; esac

block() {
  if [ "$STRIKES" -ge 2 ]; then
    echo "team-gate: $1" >&2
    echo "team-gate: third attempt on task '$TASK_SUBJECT' - passing with a warning. Tell the lead this task closed with a failing gate." >&2
    rm -f "$STRIKE_FILE"
    exit 0
  fi
  echo $((STRIKES + 1)) > "$STRIKE_FILE"
  echo "team-gate BLOCK ($((STRIKES + 1))/2) on task '$TASK_SUBJECT': $1" >&2
  echo "Fix it; if the failure is not yours, tell the lead which files and why, then complete the task again." >&2
  exit 2
}

# The worktrees filter is belt-and-braces: .gitignore already hides .claude/worktrees/ from --exclude-standard.
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
  OUT="$("${RUN[@]}" 2>&1)"; RC=$?
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
