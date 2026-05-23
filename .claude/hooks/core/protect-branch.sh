#!/usr/bin/env bash
# PreToolUse(Bash) hook — block `git commit` on protected branches.
#
# Reason: `/pipeline`, `/implement`, and ad-hoc agent commits go through
# `Bash(git commit -m *)`, which is in `allow` for autonomy. Without this hook,
# an agent that forgets to create a feature branch will silently commit
# straight to `main` / `develop` / `release/*`.
#
# Behaviour:
#   - Only intercepts commands matching `^git[[:space:]]+commit\b`.
#   - Reads .claude/protected-branches (one pattern per line; regex anchored).
#   - If missing, defaults to: main, master, develop, dev, release/.*, prod, production.
#   - Detached HEAD or non-git repo → no-op (let bash handle).
#
# Exit codes:
#   0 — allow
#   2 — block (PreToolUse contract)
#
# Override: edit .claude/protected-branches, or move git commit to ask in settings.

source "$(dirname "$0")/../_lib/python-bin.sh"

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | $PY -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)

# Only check git commit invocations (catches `git commit -m`, `-am`, `--amend`, etc.)
if ! echo "$COMMAND" | grep -qE '^[[:space:]]*git[[:space:]]+commit\b'; then
    exit 0
fi

# Current branch (no-op on detached HEAD or non-git)
BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null) || exit 0
[ -z "$BRANCH" ] && exit 0

# Load protected list — PWD-first (see protect-readonly.sh rationale for why
# pwd beats git toplevel on Windows / nested-repo setups).
if [ -f "$PWD/.claude/protected-branches" ]; then
    PROTECTED_FILE="$PWD/.claude/protected-branches"
else
    REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    PROTECTED_FILE="$REPO_ROOT/.claude/protected-branches"
fi

if [ -f "$PROTECTED_FILE" ]; then
    PATTERNS=$(grep -vE '^[[:space:]]*(#|$)' "$PROTECTED_FILE" 2>/dev/null || true)
else
    # Secure-by-default — no config file == standard protected set
    PATTERNS=$(printf '%s\n' 'main' 'master' 'develop' 'dev' 'release/.*' 'production' 'prod')
fi

while IFS= read -r pattern; do
    [ -z "$pattern" ] && continue
    # Anchored match: ^pattern$
    if [[ "$BRANCH" =~ ^${pattern}$ ]]; then
        cat >&2 <<EOF
Blocked: refusing 'git commit' on protected branch '$BRANCH' (matches: $pattern).

This is .claude/hooks/core/protect-branch.sh — it stops accidental commits
straight to main/release/develop when /pipeline or /implement is run without
first creating a feature branch.

If intentional:
  - Create a feature branch:  git checkout -b feat/<slug>
  - Or edit .claude/protected-branches to remove the pattern
  - Or override per-machine in ~/.claude/settings.local.json
EOF
        exit 2
    fi
done <<< "$PATTERNS"

exit 0
