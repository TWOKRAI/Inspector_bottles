#!/usr/bin/env bash
# lint-result.sh (Task 1.9a) - PostToolUse, matcher "Edit|Write": checks a task result
# `plans/**/tasks/<id>.result.md` the agent just wrote against form 0.7
# (.claude/plugins/dev/templates/task-result.md) with `atlas lint-result`. The writer of
# `**Не проверено:**` and the reader of `_section` once disagreed on one character and
# nothing gated it (CTO_PLAN_REVISION 2026-10-08, par. 0); this hook is that gate.
#
# Same idiom as autofix-text.sh: read stdin once, a cheap `case` pre-filter before Python
# starts, python-bin.sh in a subshell (its `exit 1` must not surface as a hook error),
# fail open on any error. The repo root comes from the hook's own path
# (.claude/plugins/dev/hooks -> four levels up), not from the payload cwd.
#
# A violation is exit 1 AND a last stdout line `lint-result: нарушений N`, N >= 1. Exit 1
# alone is NOT one: `python -m scripts.atlas` outside a repo with Atlas also exits 1
# ("No module named scripts.atlas") and must stay silent. Race: PostToolUse hooks run in
# parallel and autofix-text.sh rewrites the file with open(path, "wb"), so the lint can
# read a truncated file. On a violation the hook sleeps 0.3 s, lints again and reports
# only if both outputs are equal.
#
# The report goes to stderr with exit 2 (Claude Code shows it to the agent); stdout stays
# empty. Every other path is exit 0, silent. No ini knob: to switch it off remove the
# group from .claude/settings.json. Wired only there, not in plugin.json: the hook needs
# `scripts.atlas`, useless in a project without Atlas.

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT="$(cat)"

# Cheap pre-filter: every other tool call exits before Python starts.
case "$INPUT" in
  *.result.md*) ;;
  *) exit 0 ;;
esac

# python-bin.sh `exit 1`s when no interpreter is found - run it in a subshell.
# $PY unquoted on purpose: python-bin.sh may export "py -3".
PY="$(source "$HOOK_DIR/../../core/hooks/_lib/python-bin.sh" 2>/dev/null && printf '%s' "$PY")" || exit 0
[ -n "${PY:-}" ] || exit 0

# file_path through $(...), not `read < <(...)`: Python on Windows ends a line with \r\n.
FILE="$(printf '%s' "$INPUT" | PYTHONUTF8=1 $PY -c '
import json, sys
path = json.load(sys.stdin)["tool_input"]["file_path"]
sys.stdout.write(path if isinstance(path, str) else "")
' 2>/dev/null)" || exit 0
FILE="${FILE%$'\r'}"
FILE="${FILE//\\//}"

result_re='(^|/)plans/(.+/)?tasks/[^/]+\.result\.md$'
[[ "$FILE" =~ $result_re ]] || exit 0
# a relative path is relative to the caller's cwd, and the lint runs from the repo root
case "$FILE" in
  /*|[A-Za-z]:/*) ;;
  *) FILE="$PWD/$FILE" ;;
esac

ROOT="$(cd "$HOOK_DIR/../../../.." && pwd)" || exit 0

OUT=""
RC=0
run_lint() {
  OUT="$(cd "$ROOT" && PYTHONUTF8=1 PYTHONIOENCODING=utf-8 $PY -m scripts.atlas lint-result "$FILE" 2>/dev/null)"
  RC=$?
  OUT="${OUT//$'\r'/}"
}

violation_re='^lint-result: нарушений [1-9][0-9]*$'
is_violation() {
  [ "$RC" -eq 1 ] && [[ "${OUT##*$'\n'}" =~ $violation_re ]]
}

run_lint
is_violation || exit 0
FIRST="$OUT"
sleep 0.3
run_lint
is_violation || exit 0
[ "$OUT" = "$FIRST" ] || exit 0

printf 'lint-result: %s не по форме 0.7 (.claude/plugins/dev/templates/task-result.md):\n%s\n' "$FILE" "$OUT" >&2
exit 2
