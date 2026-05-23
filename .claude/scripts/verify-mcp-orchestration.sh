#!/usr/bin/env bash
# verify-mcp-orchestration.sh — consistency check for MCP orchestration setup.
#
# Run from project root (where .claude/ lives). Checks:
#   1. All `mcp:server:tool` references in agents/*.md exist in mcp/ROUTING.md.
#   2. No orphan tools in ROUTING.md (mentioned but not used by any agent).
#   3. All routing-blocks in agents are self-contained (no "См. ROUTING.md" runtime ref).
#   4. Settings.json syntactically valid + critical hooks registered.
#   5. ROUTING.md has explicit "not for runtime" disclaimer.
#
# Cross-platform: bash, no GNU-only flags. Designed for Git Bash on Windows too.
#
# Exit codes:
#   0 — all checks pass
#   1 — at least one check failed
#
# Used by /doctor (slash-command) as one of its layers.

set -u

# ANSI colors with fallback
if [ -t 1 ] && [ "${TERM:-dumb}" != "dumb" ]; then
    C_OK=$'\033[32m'
    C_FAIL=$'\033[31m'
    C_RESET=$'\033[0m'
    C_BOLD=$'\033[1m'
else
    C_OK=""
    C_FAIL=""
    C_RESET=""
    C_BOLD=""
fi

PASS_COUNT=0
FAIL_COUNT=0

pass() { echo "${C_OK}✓${C_RESET} $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo "${C_FAIL}✗${C_RESET} $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

# Find project root — script can be run from template/ (seed) or from .claude/scripts/ (installed)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT="$(dirname "$SCRIPT_DIR")"

# If we're in template/scripts → project root is template/. If in .claude/scripts → root is one up.
if [ -d "$PARENT/agents" ] && [ -d "$PARENT/mcp" ]; then
    # template/ layout (seed): everything sits next to script
    ROOT="$PARENT"
    AGENTS_DIR="$ROOT/agents"
    MCP_DIR="$ROOT/mcp"
    SETTINGS_FILE="$ROOT/settings.json"
elif [ -d "$PARENT/../.claude/agents" ]; then
    # Installed: project_root/.claude/scripts → project_root/.claude/{agents,mcp}
    ROOT="$(dirname "$PARENT")"
    AGENTS_DIR="$ROOT/.claude/agents"
    MCP_DIR="$ROOT/.claude/mcp"
    SETTINGS_FILE="$ROOT/.claude/settings.json"
else
    echo "Cannot locate agents/ and mcp/ directories from $SCRIPT_DIR"
    echo "Expected: <root>/{agents,mcp,settings.json} or <root>/.claude/{agents,mcp,settings.json}"
    exit 1
fi

echo "${C_BOLD}=== MCP orchestration verification ===${C_RESET}"
echo "Root: $ROOT"
echo "Agents: $AGENTS_DIR"
echo "MCP docs: $MCP_DIR"
echo

# ---------------------------------------------------------------------------
# Check 1: All mcp:server:tool in agents are in ROUTING.md
# ---------------------------------------------------------------------------

ROUTING="$MCP_DIR/ROUTING.md"
if [ ! -f "$ROUTING" ]; then
    fail "ROUTING.md not found at $ROUTING"
else
    # Extract mcp:server:tool from agent .md files
    AGENT_TOOLS=$(grep -rhoE "mcp:[a-z_-]+:[a-zA-Z_-]+" "$AGENTS_DIR" 2>/dev/null | sort -u)

    # Extract from ROUTING.md (both formats: mcp__server__tool and mcp:server:tool)
    ROUTING_TOOLS=$(grep -oE "mcp__[a-z_-]+__[a-zA-Z_-]+|mcp:[a-z_-]+:[a-zA-Z_-]+|\`[a-z_-]+:[a-zA-Z_-]+\`" "$ROUTING" 2>/dev/null \
                    | sed 's/^`//;s/`$//;s/^mcp__/mcp:/;s/__/:/g' \
                    | sort -u)

    MISSING=""
    while IFS= read -r tool; do
        [ -z "$tool" ] && continue
        # Try both forms: mcp:server:tool and server:tool (ROUTING.md sometimes uses bare server:tool)
        bare="${tool#mcp:}"
        if ! echo "$ROUTING_TOOLS" | grep -qFx "$tool" && ! echo "$ROUTING_TOOLS" | grep -qFx "$bare"; then
            MISSING="$MISSING $tool"
        fi
    done <<< "$AGENT_TOOLS"

    if [ -z "$MISSING" ]; then
        TOOL_COUNT=$(echo "$AGENT_TOOLS" | grep -c .)
        pass "All $TOOL_COUNT mcp:server:tool references in agents exist in ROUTING.md"
    else
        fail "Agents reference MCP tools not documented in ROUTING.md:$MISSING"
    fi
fi

# ---------------------------------------------------------------------------
# Check 2: ROUTING.md explicitly NOT for runtime
# ---------------------------------------------------------------------------

if [ -f "$ROUTING" ]; then
    if grep -qE "Агенты[^.]*НЕ читают|not.*runtime|не runtime" "$ROUTING"; then
        pass "ROUTING.md has explicit 'not for runtime' disclaimer"
    else
        fail "ROUTING.md missing 'not for runtime' disclaimer — agents may try to read it"
    fi
fi

# ---------------------------------------------------------------------------
# Check 3: Agents' routing-blocks self-contained (no See ROUTING.md ref)
# ---------------------------------------------------------------------------

# Look for phrases that suggest agents should read ROUTING.md
RUNTIME_LEAKS=$(grep -rEl "См\. .*ROUTING\.md|See .*ROUTING\.md|читай .*ROUTING\.md|прочитай .*ROUTING\.md" "$AGENTS_DIR" 2>/dev/null)

if [ -z "$RUNTIME_LEAKS" ]; then
    pass "No agent .md instructs to read ROUTING.md at runtime (avoids token amplification)"
else
    fail "Found runtime ROUTING.md references in: $RUNTIME_LEAKS"
fi

# ---------------------------------------------------------------------------
# Check 4: settings.json is valid + new hooks registered
# ---------------------------------------------------------------------------

if [ -f "$SETTINGS_FILE" ]; then
    # Pipe via stdin to avoid Windows path issues in Git Bash (MSYS /c/ vs C:\)
    if cat "$SETTINGS_FILE" | python -c "import json,sys; json.load(sys.stdin)" 2>/dev/null \
       || cat "$SETTINGS_FILE" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
        pass "settings.json is valid JSON"

        # Check that new hooks are registered (Phase 1 additions)
        MISSING_HOOKS=""
        for hook in "quality/mcp-health-check.sh" "quality/sentrux-precheck.sh"; do
            if ! grep -q "$hook" "$SETTINGS_FILE"; then
                MISSING_HOOKS="$MISSING_HOOKS $hook"
            fi
        done

        if [ -z "$MISSING_HOOKS" ]; then
            pass "MCP orchestration hooks registered in settings.json"
        else
            fail "Hooks missing from settings.json:$MISSING_HOOKS"
        fi
    else
        fail "settings.json is not valid JSON"
    fi
else
    fail "settings.json not found at $SETTINGS_FILE"
fi

# ---------------------------------------------------------------------------
# Check 5: Required new files exist
# ---------------------------------------------------------------------------

REQUIRED_FILES=(
    "$MCP_DIR/ROUTING.md"
    "$ROOT/hooks/quality/mcp-health-check.sh"
    "$ROOT/hooks/quality/sentrux-precheck.sh"
    "$ROOT/scripts/doctor.sh"
    "$ROOT/commands/quality/doctor.md"
)

# Adjust paths if in installed (.claude/) layout
if [ ! -d "$ROOT/hooks" ] && [ -d "$ROOT/.claude/hooks" ]; then
    REQUIRED_FILES=(
        "$MCP_DIR/ROUTING.md"
        "$ROOT/.claude/hooks/quality/mcp-health-check.sh"
        "$ROOT/.claude/hooks/quality/sentrux-precheck.sh"
        "$ROOT/.claude/scripts/doctor.sh"
        "$ROOT/.claude/commands/quality/doctor.md"
    )
fi

MISSING_FILES=""
for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$f" ]; then
        MISSING_FILES="$MISSING_FILES $f"
    fi
done

if [ -z "$MISSING_FILES" ]; then
    pass "All required orchestration files exist"
else
    fail "Missing files:$MISSING_FILES"
fi

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

echo
echo "${C_BOLD}Verdict:${C_RESET} $PASS_COUNT passed, $FAIL_COUNT failed"

if [ $FAIL_COUNT -eq 0 ]; then
    echo "${C_OK}✅ MCP orchestration consistent${C_RESET}"
    exit 0
else
    echo "${C_FAIL}❌ MCP orchestration has issues${C_RESET}"
    exit 1
fi
