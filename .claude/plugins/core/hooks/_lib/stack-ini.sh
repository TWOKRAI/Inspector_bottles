#!/usr/bin/env bash
# stack-ini.sh — read a key from the fenced ```ini block of `.claude/modes/_stack.md`.
#
# Usage (source from a hook):
#   source "$(dirname "$0")/../_lib/stack-ini.sh"
#   memory_max_bytes="$(stack_ini_get memory_max_bytes 4096)"
#
# Why this exists: the tests-discipline commit gate (`validate_commit.py`'s
# `gate_config_block()`) and the memory linter (`memory_lint.py`'s
# `read_thresholds()`) both need "the first fenced ```ini block of
# `.claude/modes/_stack.md`" — a config format any project-local hook may
# want a key from without spawning Python. One scanner, reused by every
# consumer, is what Task 6.2 already learned the hard way: two parsers of the
# same config eventually disagree (see `.claude/CLAUDE.md` and
# `memory_lint.py`'s own module docstring for that lesson). `memory_lint.py`
# carries the Python analogue (`parse_first_ini_block`) — same behaviour, two
# runtimes.
#
# Behaviour (mirrors `memory_lint.py`'s `parse_first_ini_block` /
# `read_thresholds` exactly — Task 2.4 review R3 found the two had drifted:
# this scanner used to require the fence at column 0 with no `~~~`
# alternative, and picked the literal FIRST ```ini block regardless of its
# keys):
# - The opening fence may be indented and may use ``` or ~~~ (3+ of either).
# - Of the ```ini blocks found, the first one carrying at least one
#   RECOGNISED key (`tests_gate*` / `memory_*` / `session_lock*` /
#   `pre_report_gate*` / `agent_context_*` / `brief_*` / `doc_size*` /
#   `doc_section*` / `web_search*` / `report_*` — the same
#   gate `validate_commit.py`'s `gate_config_block()` applies for its own
#   `tests_gate*` key) is "the" block; an earlier ```ini block with no
#   recognised key is decorative/example content and is skipped.
#   (`report_*` is recognised here only — Task 4.1 scoped the change to this
#   file; `memory_lint.py`'s `parse_first_ini_block` does not need it since no
#   consumer reads `report_status` through the python parser.)
# - `key = value` lines only; a trailing `# comment` on the same line is
#   stripped; blank lines and full-line `#` comments inside the block are
#   skipped.
# - The returned value has a leading/trailing backtick then leading/trailing
#   quote characters (`'`/`"`) stripped, same as `read_thresholds`'s
#   ``int(raw.strip('`').strip("'\""))`` normalisation — so
#   `memory_max_bytes = "666"` and `` memory_max_bytes = `666` `` both yield
#   `666`, not the quoted/backticked literal.
# - Missing file, missing block, or missing key -> prints the given default.

stack_ini_get() {
  local key="$1"
  local default_value="$2"
  local stack_md="${3:-}"
  [ -n "$stack_md" ] || stack_md=".claude/modes/_stack.md"

  if [ ! -f "$stack_md" ]; then
    printf '%s\n' "$default_value"
    return 0
  fi

  local value
  value=$(awk -v key="$key" '
    function is_fence(line,    t) {
      t = line
      sub(/^[[:space:]]+/, "", t)
      return (t ~ /^```+/) || (t ~ /^~~~+/)
    }
    function fence_info(line,    t) {
      t = line
      sub(/^[[:space:]]+/, "", t)
      sub(/^(```+|~~~+)/, "", t)
      gsub(/[[:space:]]/, "", t)
      return t
    }
    {
      if (is_fence($0)) {
        if (in_block) {
          if (have_known) {
            if (found != "") { print found }
            # `exit` also runs the END block below -- clear in_block first
            # so the END guard below does not print a second, corrupting copy.
            in_block = 0
            exit
          }
          in_block = 0; have_known = 0; found = ""
          next
        } else {
          if (tolower(fence_info($0)) == "ini") {
            in_block = 1; have_known = 0; found = ""
          }
          next
        }
      }
      if (!in_block) { next }
      line = $0
      sub(/^[[:space:]]+/, "", line)
      if (line == "" || line ~ /^#/) { next }
      if (line !~ /=/) { next }
      split(line, kv, "=")
      k = kv[1]
      gsub(/[[:space:]]+$/, "", k)
      gsub(/^[[:space:]]+/, "", k)
      kl = tolower(k)
      if (kl ~ /^tests_gate/ || kl ~ /^memory_/ || kl ~ /^session_lock/ || kl ~ /^pre_report_gate/ || kl ~ /^agent_context_/ || kl ~ /^brief_/ || kl ~ /^doc_size/ || kl ~ /^doc_section/ || kl ~ /^web_search/ || kl ~ /^report_/) {
        have_known = 1
      }
      if (kl == tolower(key)) {
        v = substr(line, index(line, "=") + 1)
        sub(/#.*/, "", v)
        gsub(/^[[:space:]]+/, "", v)
        gsub(/[[:space:]]+$/, "", v)
        found = v
      }
    }
    END {
      if (in_block && have_known && found != "") { print found }
    }
  ' "$stack_md")

  # Strip a leading/trailing backtick, then leading/trailing quote chars --
  # mirrors read_thresholds()'s `int(raw.strip('`').strip("'\""))`.
  value="${value#\`}"; value="${value%\`}"
  while [ "${value#\'}" != "$value" ] || [ "${value#\"}" != "$value" ]; do
    value="${value#?}"
  done
  while [ "${value%\'}" != "$value" ] || [ "${value%\"}" != "$value" ]; do
    value="${value%?}"
  done

  if [ -z "$value" ]; then
    printf '%s\n' "$default_value"
  else
    printf '%s\n' "$value"
  fi
}
