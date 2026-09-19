#!/usr/bin/env bash
# SessionStart hook — re-prime the agent on plan-driven workflow status.
#
# Which plan the current branch is working on is NOT decided here. It is
# decided once, in the seed's validate_commit.py, and asked for through
# `--resolve-plan` (Task 1.5). The `Refs:` commit gate, the injections
# pre-push gate and this banner must give the same answer; a second resolver
# written in bash could only agree with them by accident, and it did not —
# the old glob here matched `plans/<slug>` against the branch slug and nothing
# else, so on `feat/harvest-gaps` (plan `2026-09-03_harvest-inspector-bottles`)
# the banner printed nothing while the plan was very much active.
#
# Silent (exit 0) on non-git repos, detached HEAD, branches without plans, a
# project that has no validator yet, a machine without Python, and any error —
# a SessionStart hook may never block a session or shout at the user.

set +e

git rev-parse --git-dir >/dev/null 2>&1 || exit 0
repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -n "$repo_root" ] || exit 0
cd "$repo_root" 2>/dev/null || exit 0

branch=$(git symbolic-ref --short HEAD 2>/dev/null)
[ -z "$branch" ] && exit 0

# Find the shipped resolver. Same candidate order (and reason) as the
# injections-gate block in install_pre_push_hook.sh: the project's own copy,
# which its owner may edit → the seed tree, for a repo that dogfoods its own
# template → the materialized plugin tree, for a project that got `.claude/`
# through `init` and has no scripts/.
#
# The seed tree deliberately outranks `.claude/plugins/`: in this repo the
# latter is a REGENERATED mirror of the former and is stale between an edit to
# `src/…/template/` and the next `plugin upgrade`. Preferring the mirror made
# the banner run yesterday's resolver against today's plans.
resolver=""
for _cand in "$repo_root"/scripts/validate_commit/validate_commit.py \
             "$repo_root"/src/*/template/plugins/lang-python/templates/validate_commit/validate_commit.py \
             "$repo_root"/.claude/plugins/lang-python/templates/validate_commit/validate_commit.py; do
  if [ -f "$_cand" ]; then resolver="$_cand"; break; fi
done
[ -n "$resolver" ] || exit 0

py=""
for _cand in "${CLAUDE_PYTHON_BIN:-}" python3 python py; do
  [ -n "$_cand" ] || continue
  if command -v "$_cand" >/dev/null 2>&1 && "$_cand" -c "import sys" >/dev/null 2>&1; then
    py="$_cand"; break
  fi
done
[ -n "$py" ] || exit 0

plan=$("$py" "$resolver" --resolve-plan "$branch" 2>/dev/null)
[ -n "$plan" ] && [ -f "$plan" ] || exit 0

# Task 2.2 — the Progress line comes from `plans_ledger.py status --branch
# --oneline`: it walks ALL of the plan's files (plan.md + phase-N.md) and
# counts `### Task X.Y` closure the same way the ledger and the `Refs:` gate
# do. The grep-based marker count below only ever saw `$plan` (one file) and
# counted `[PENDING]`/`[DONE]` wherever they occurred, prose included — same
# candidate order (and reason) as the resolver lookup above.
ledger=""
for _cand in "$repo_root"/scripts/plans_ledger.py \
             "$repo_root"/src/*/template/plugins/core/scripts/plans_ledger.py \
             "$repo_root"/.claude/plugins/core/scripts/plans_ledger.py; do
  if [ -f "$_cand" ]; then ledger="$_cand"; break; fi
done

line=""
if [ -n "$ledger" ]; then
  line=$("$py" "$ledger" status --root "$repo_root" --plan "$plan" --oneline 2>/dev/null)
fi

# Status counts — lenient: count occurrences of [PENDING|IN_PROGRESS|DONE]
pending=$(grep -oE '\[PENDING\]' "$plan" 2>/dev/null | wc -l | tr -d ' ')
inprog=$(grep -oE '\[IN_PROGRESS\]' "$plan" 2>/dev/null | wc -l | tr -d ' ')
done_c=$(grep -oE '\[DONE\]' "$plan" 2>/dev/null | wc -l | tr -d ' ')
total=$((pending + inprog + done_c))

last=$(git log -1 --format='%h %s' 2>/dev/null | cut -c1-80)

echo ""
echo "📋 Plan-driven workflow active"
echo "   Branch:   $branch"
echo "   Plan:     $plan"
if [ -n "$line" ]; then
  echo "   Progress: $line"
elif [ "$total" -gt 0 ]; then
  echo "   Progress: $done_c/$total DONE ($inprog in progress, $pending pending)"
else
  echo "   Progress: (no task statuses in plan yet)"
fi
[ -n "$last" ] && echo "   Last:     $last"
echo "   Next:     /dev:plan-status for details · commit needs Refs: $plan"

exit 0
