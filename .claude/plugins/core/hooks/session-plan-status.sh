#!/usr/bin/env bash
# SessionStart hook — re-prime the agent on plan-driven workflow status.
#
# If current branch matches <type>/<slug> AND a plan exists at
# plans/<slug>.md or plans/<slug>/plan.md — print a 3-line banner so the
# agent doesn't forget which task is in progress.
#
# Silent (exit 0) on non-git repos, detached HEAD, branches without plans,
# and any error — never blocks session start.

set +e

[ -d .git ] || exit 0

branch=$(git symbolic-ref --short HEAD 2>/dev/null)
[ -z "$branch" ] && exit 0

# Match <type>/<slug> where <type> is a Conventional Commits type
if ! [[ "$branch" =~ ^(feat|fix|refactor|docs|test|chore|perf|build|ci|style|revert)/(.+)$ ]]; then
  exit 0
fi
slug="${BASH_REMATCH[2]}"

# Plans are date-prefixed by convention (plans/YYYY-MM-DD_<slug>.md or
# plans/YYYY-MM-DD_<slug>/plan.md); also tolerate the bare-slug form. Newest match wins.
plan=$(ls -t plans/*_"${slug}".md "plans/${slug}.md" 2>/dev/null | head -1)
if [ -z "$plan" ]; then
  dir=$(ls -td plans/*_"${slug}"/ "plans/${slug}/" 2>/dev/null | head -1)
  [ -n "$dir" ] && [ -f "${dir}plan.md" ] && plan="${dir}plan.md"
fi
[ -z "$plan" ] || [ ! -f "$plan" ] && exit 0

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
if [ "$total" -gt 0 ]; then
  echo "   Progress: $done_c/$total DONE ($inprog in progress, $pending pending)"
else
  echo "   Progress: (no task statuses in plan yet)"
fi
[ -n "$last" ] && echo "   Last:     $last"
echo "   Next:     /dev:plan-status for details · commit needs Refs: $plan"

exit 0
