#!/usr/bin/env bash
# doctor.sh — test-drive Claude-Kit system health.
#
# Read-only diagnostic. Checks MCP layer, configs, routing consistency,
# indexes, hooks executable, plans integrity. Reports OK/WARN/FAIL per
# section + final verdict + exit code.
#
# Usage:
#   bash .claude/scripts/doctor.sh           # quiet
#   bash .claude/scripts/doctor.sh --verbose # show per-check detail
#
# Exit codes:
#   0 — all OK (may have WARN, no FAIL)
#   1 — at least one FAIL
#   2 — at least one FAIL + WARN
#
# Cross-platform: works in Git Bash / WSL / native bash. Avoid GNU-only flags.

set -u

VERBOSE=0
[ "${1:-}" = "--verbose" ] && VERBOSE=1

# ANSI colours (fallback to plain if TERM=dumb or non-tty)
if [ -t 1 ] && [ "${TERM:-dumb}" != "dumb" ]; then
    C_OK=$'\033[32m'   # green
    C_WARN=$'\033[33m' # yellow
    C_FAIL=$'\033[31m' # red
    C_RESET=$'\033[0m'
    C_BOLD=$'\033[1m'
else
    C_OK=""
    C_WARN=""
    C_FAIL=""
    C_RESET=""
    C_BOLD=""
fi

# Counters
FAIL_COUNT=0
WARN_COUNT=0
OK_COUNT=0

# Status helpers
ok()    { echo "${C_OK}[OK]${C_RESET}    $1 — ${2:-}"; OK_COUNT=$((OK_COUNT + 1)); }
warn()  { echo "${C_WARN}[WARN]${C_RESET}  $1 — ${2:-}"; WARN_COUNT=$((WARN_COUNT + 1)); }
fail()  { echo "${C_FAIL}[FAIL]${C_RESET}  $1 — ${2:-}"; FAIL_COUNT=$((FAIL_COUNT + 1)); }
vlog()  { [ $VERBOSE -eq 1 ] && echo "  · $1"; }

# Python interpreter — cached resolution. Python is a hard dep for several
# checks (lint_settings/lint_agents/lint_routing); reused here for portable
# mtime computation (avoids GNU `find -printf` and `bc` in Git Bash/BusyBox).
_PYTHON=""
resolve_python() {
    if [ -z "$_PYTHON" ]; then
        if command -v python >/dev/null 2>&1; then _PYTHON="python"
        elif command -v python3 >/dev/null 2>&1; then _PYTHON="python3"
        fi
    fi
    [ -n "$_PYTHON" ] && echo "$_PYTHON"
}

# Max mtime (epoch sec, integer) of any file under a directory.
# Portable: walks via Python — no GNU `find -printf`, no `stat -c %Y`.
# Echoes empty string on error or empty dir.
max_mtime() {
    local dir="$1"
    local py
    py=$(resolve_python) || return 1
    [ -z "$py" ] && return 1
    "$py" -c "import os, sys
mt = 0
for root, _, files in os.walk(sys.argv[1]):
    for f in files:
        try:
            t = os.path.getmtime(os.path.join(root, f))
            if t > mt:
                mt = t
        except OSError:
            pass
print(int(mt) if mt > 0 else '')" "$dir" 2>/dev/null
}

# Resolve project root (script lives in .claude/scripts/doctor.sh)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# .claude/scripts → .claude → project root
CLAUDE_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$CLAUDE_DIR")"

cd "$PROJECT_ROOT" || { echo "Cannot cd to project root"; exit 1; }

echo
echo "${C_BOLD}=== Claude-Kit System Health ===${C_RESET}"
echo "Project: $PROJECT_ROOT"
echo

# ---------------------------------------------------------------------------
# 1. MCP layer — binaries + Ollama + cfg
# ---------------------------------------------------------------------------

# qex binary
QEX_FOUND=0
for path in "$(command -v qex 2>/dev/null)" "$HOME/.cargo/bin/qex" "$HOME/.cargo/bin/qex.exe" "$HOME/.local/bin/qex"; do
    if [ -n "$path" ] && [ -x "$path" ]; then
        QEX_FOUND=1
        vlog "qex found: $path"
        break
    fi
done

# Ollama
OLLAMA_UP=0
if curl -s --max-time 1 http://localhost:11434/ 2>/dev/null | grep -q "running"; then
    OLLAMA_UP=1
fi

# sentrux binary
SENTRUX_UP=0
if command -v sentrux >/dev/null 2>&1; then
    SENTRUX_UP=1
    vlog "sentrux: $(sentrux --version 2>&1 | head -1)"
fi

# context7 cfg
CONTEXT7_CFG=0
if [ -f "$HOME/.claude.json" ] && grep -q '"context7"' "$HOME/.claude.json" 2>/dev/null; then
    CONTEXT7_CFG=1
elif [ -f ".mcp.json" ] && grep -q '"context7"' ".mcp.json" 2>/dev/null; then
    CONTEXT7_CFG=1
fi

# Optional MCPs from .mcp.json
OPTIONAL_MCPS=""
if [ -f ".mcp.json" ]; then
    for srv in codegraph ast-grep serena graphify github qt-mcp playwright sequential-thinking; do
        if grep -q "\"$srv\"" .mcp.json 2>/dev/null; then
            OPTIONAL_MCPS="$OPTIONAL_MCPS $srv=cfg"
        fi
    done
fi

# Verdict for MCP layer
MCP_SUMMARY=""
[ $QEX_FOUND -eq 1 ] && MCP_SUMMARY="$MCP_SUMMARY qex=UP" || MCP_SUMMARY="$MCP_SUMMARY qex=DOWN"
[ $OLLAMA_UP -eq 1 ] && MCP_SUMMARY="$MCP_SUMMARY ollama=UP" || MCP_SUMMARY="$MCP_SUMMARY ollama=DOWN"
[ $SENTRUX_UP -eq 1 ] && MCP_SUMMARY="$MCP_SUMMARY sentrux=UP" || MCP_SUMMARY="$MCP_SUMMARY sentrux=DOWN"
[ $CONTEXT7_CFG -eq 1 ] && MCP_SUMMARY="$MCP_SUMMARY context7=cfg" || MCP_SUMMARY="$MCP_SUMMARY context7=nocfg"
MCP_SUMMARY="$MCP_SUMMARY$OPTIONAL_MCPS"

# qex needs Ollama; if qex UP but Ollama DOWN → warn
if [ $QEX_FOUND -eq 1 ] && [ $OLLAMA_UP -eq 0 ]; then
    warn "MCP servers" "$MCP_SUMMARY (Ollama down — qex semantic search unavailable)"
elif [ $QEX_FOUND -eq 0 ] && [ $SENTRUX_UP -eq 0 ]; then
    fail "MCP servers" "$MCP_SUMMARY (core MCPs unavailable)"
else
    ok "MCP servers" "$MCP_SUMMARY"
fi

# ---------------------------------------------------------------------------
# 2. Config layer — settings.json, agents lint
# ---------------------------------------------------------------------------

# settings.json JSON validity
if [ -f ".claude/settings.json" ]; then
    # Pipe via stdin to avoid MSYS-path issues on Windows Git Bash
    if cat ".claude/settings.json" | python -c "import json,sys; json.load(sys.stdin)" 2>/dev/null \
       || cat ".claude/settings.json" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
        # Run lint_settings if available
        if [ -f ".claude/scripts/lint_settings.py" ]; then
            LINT_OUT=$(python .claude/scripts/lint_settings.py 2>&1 || python3 .claude/scripts/lint_settings.py 2>&1)
            LINT_EXIT=$?
            if [ $LINT_EXIT -eq 0 ]; then
                ok "Settings lint" "all critical patterns present"
            elif [ $LINT_EXIT -eq 2 ]; then
                fail "Settings lint" "$(echo "$LINT_OUT" | tail -1)"
            else
                warn "Settings lint" "$(echo "$LINT_OUT" | tail -1)"
            fi
        else
            ok "Settings lint" "JSON valid (lint_settings.py not found, skipped detailed check)"
        fi
    else
        fail "Settings lint" "settings.json is not valid JSON"
    fi
else
    warn "Settings lint" ".claude/settings.json not found"
fi

# agents lint
if [ -f ".claude/scripts/lint_agents.py" ] && [ -d ".claude/agents" ]; then
    LINT_OUT=$(python .claude/scripts/lint_agents.py .claude/agents/ 2>&1 || python3 .claude/scripts/lint_agents.py .claude/agents/ 2>&1)
    if echo "$LINT_OUT" | grep -q "Errors:  0"; then
        AGENT_COUNT=$(echo "$LINT_OUT" | grep "Checked:" | head -1 | grep -oE "[0-9]+" | head -1)
        ok "Agents lint" "${AGENT_COUNT:-?}/${AGENT_COUNT:-?} valid"
    else
        fail "Agents lint" "$(echo "$LINT_OUT" | grep -E "Errors|error" | head -3 | tr '\n' ' ')"
    fi
else
    warn "Agents lint" "lint_agents.py or .claude/agents/ not found"
fi

# ---------------------------------------------------------------------------
# 3. Routing consistency — agents mcp:server:tool ↔ ROUTING.md
# ---------------------------------------------------------------------------

if [ -f ".claude/mcp/ROUTING.md" ] && [ -d ".claude/agents" ]; then
    # Prefer Python lint_routing.py (strict canonical-aware check).
    # Fallback to inline bash grep — устойчивый к коротким формам в bullet'ах
    # за счёт парсинга `**Canonical refs:**` блоков как authoritative-источника.
    LINT_PY=".claude/scripts/lint_routing.py"
    LINT_OUT=""
    LINT_EXIT=99

    if [ -f "$LINT_PY" ]; then
        if command -v python >/dev/null 2>&1; then
            LINT_OUT=$(python "$LINT_PY" --quiet 2>&1)
            LINT_EXIT=$?
        elif command -v python3 >/dev/null 2>&1; then
            LINT_OUT=$(python3 "$LINT_PY" --quiet 2>&1)
            LINT_EXIT=$?
        fi
    fi

    if [ $LINT_EXIT -eq 0 ]; then
        # Python линтер дал OK (возможно с non-blocking orphan warnings).
        N_REFS=$(grep -rhoE "mcp:[a-z_-]+:[a-zA-Z_-]+" .claude/agents/ 2>/dev/null | sort -u | wc -l | tr -d ' ')
        ok "Routing sync" "${N_REFS} mcp:server:tool refs — canonical (via lint_routing.py)"
    elif [ $LINT_EXIT -eq 1 ]; then
        fail "Routing sync" "$(echo "$LINT_OUT" | grep -E '^\[FAIL\]' | head -3 | tr '\n' '|')"
    elif [ $LINT_EXIT -eq 2 ]; then
        # Strict-mode warnings (orphans). Non-blocking for doctor — лишь сигнал.
        warn "Routing sync" "orphan tools listed in ROUTING.md (non-blocking, see lint_routing.py --strict)"
    else
        # Fallback: lint_routing.py не доступен или python отсутствует.
        # Канон — `**Canonical refs:**` строки в ROUTING.md.
        AGENT_MCPS=$(grep -rhoE "mcp:[a-z_-]+:[a-zA-Z_-]+" .claude/agents/ 2>/dev/null | sort -u)
        # Извлечь tools из Canonical refs строк (preferred) + любых mcp__ или mcp: упоминаний (fallback).
        CANON_REFS=$(grep -E "^\*\*Canonical refs:\*\*" .claude/mcp/ROUTING.md 2>/dev/null \
            | grep -oE "mcp:[a-z_-]+:[a-zA-Z_-]+" | sort -u)
        if [ -z "$CANON_REFS" ]; then
            # Совсем старый ROUTING.md без Canonical блоков — fallback на все упоминания.
            CANON_REFS=$(grep -oE "mcp__[a-z_-]+__[a-zA-Z_-]+|mcp:[a-z_-]+:[a-zA-Z_-]+" .claude/mcp/ROUTING.md 2>/dev/null \
                | sed 's/mcp__/mcp:/;s/__/:/g' | sort -u)
        fi

        MISSING=""
        while IFS= read -r tool; do
            [ -z "$tool" ] && continue
            if ! echo "$CANON_REFS" | grep -qF "$tool"; then
                MISSING="$MISSING $tool"
            fi
        done <<< "$AGENT_MCPS"

        if [ -z "$MISSING" ]; then
            TOOL_COUNT=$(echo "$AGENT_MCPS" | wc -l | tr -d ' ')
            ok "Routing sync" "$TOOL_COUNT mcp:server:tool refs — canonical (bash fallback)"
        else
            fail "Routing sync" "agents reference unknown MCP tools (not in ROUTING.md):$MISSING"
        fi
    fi
else
    warn "Routing sync" ".claude/mcp/ROUTING.md or .claude/agents/ not found"
fi

# ---------------------------------------------------------------------------
# 4. Indexes — qex & sentrux state
# ---------------------------------------------------------------------------

# qex index existence and age
QEX_INDEX_PATH=".qex"
if [ $QEX_FOUND -eq 1 ] && [ -d "$QEX_INDEX_PATH" ]; then
    # Approximate age via max mtime under .qex/. Portable: max_mtime() uses
    # Python (no GNU `find -printf`), shell arithmetic (no `bc`).
    QEX_MTIME=$(max_mtime "$QEX_INDEX_PATH")
    if [ -n "$QEX_MTIME" ]; then
        NOW=$(date +%s)
        AGE_SEC=$((NOW - QEX_MTIME))
        AGE_DAYS=$((AGE_SEC / 86400))
        if [ $AGE_DAYS -gt 7 ]; then
            warn "Indexes" "qex index age: ${AGE_DAYS} days (consider /qex-reindex)"
        else
            ok "Indexes" "qex index age: ${AGE_DAYS} days"
        fi
    else
        warn "Indexes" "qex index dir exists but empty"
    fi
elif [ $QEX_FOUND -eq 1 ]; then
    warn "Indexes" "qex installed but no .qex/ index (run /qex-reindex to create)"
elif [ $SENTRUX_UP -eq 1 ]; then
    ok "Indexes" "sentrux available (qex not in this project)"
else
    vlog "Indexes: skipped (no core MCP active)"
fi

# ---------------------------------------------------------------------------
# 5. Hooks — executable bit
# ---------------------------------------------------------------------------

if [ -d ".claude/hooks" ]; then
    case "$OSTYPE" in
        msys*|cygwin*|win32*)
            # NTFS не имеет POSIX executable bit → проверка бессмысленна.
            # Hooks на Windows запускаются через `bash` явно, +x не требуется.
            vlog "Hooks executable: skipped on $OSTYPE (no POSIX executable bit on NTFS)"
            ;;
        *)
            TOTAL_HOOKS=$(find .claude/hooks -name "*.sh" -type f | wc -l | tr -d ' ')
            EXEC_HOOKS=$(find .claude/hooks -name "*.sh" -type f -perm -u+x 2>/dev/null | wc -l | tr -d ' ')
            if [ "$TOTAL_HOOKS" = "$EXEC_HOOKS" ]; then
                ok "Hooks executable" "${TOTAL_HOOKS}/${TOTAL_HOOKS} +x"
            else
                warn "Hooks executable" "${EXEC_HOOKS}/${TOTAL_HOOKS} +x (run: chmod +x .claude/hooks/**/*.sh)"
            fi
            ;;
    esac
else
    warn "Hooks executable" ".claude/hooks/ not found"
fi

# ---------------------------------------------------------------------------
# 6. Plans integrity — orphan multi-phase folders
# ---------------------------------------------------------------------------

if [ -d "plans" ]; then
    PLAN_COUNT=$(find plans -maxdepth 1 -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
    DIR_PLAN_COUNT=$(find plans -maxdepth 1 -mindepth 1 -type d ! -name "_archive" 2>/dev/null | wc -l | tr -d ' ')

    ORPHAN=""
    while IFS= read -r dir; do
        [ -z "$dir" ] && continue
        if [ ! -f "$dir/plan.md" ]; then
            ORPHAN="$ORPHAN ${dir##plans/}"
        fi
    done < <(find plans -maxdepth 1 -mindepth 1 -type d ! -name "_archive" 2>/dev/null)

    TOTAL=$((PLAN_COUNT + DIR_PLAN_COUNT))
    if [ -z "$ORPHAN" ]; then
        ok "Plans integrity" "${TOTAL} plans (${PLAN_COUNT} single, ${DIR_PLAN_COUNT} multi-phase), no orphans"
    else
        warn "Plans integrity" "${TOTAL} plans, orphan multi-phase folders:$ORPHAN"
    fi
else
    vlog "Plans: directory not found (no plans yet — that's fine)"
fi

# ---------------------------------------------------------------------------
# Final verdict
# ---------------------------------------------------------------------------

echo
echo "${C_BOLD}Verdict:${C_RESET}"
echo "  $OK_COUNT OK, $WARN_COUNT WARN, $FAIL_COUNT FAIL"

if [ $FAIL_COUNT -gt 0 ] && [ $WARN_COUNT -gt 0 ]; then
    echo "  ${C_FAIL}❌ Has failures + warnings.${C_RESET} Fix failures first."
    exit 2
elif [ $FAIL_COUNT -gt 0 ]; then
    echo "  ${C_FAIL}❌ Has failures.${C_RESET} System not healthy."
    exit 1
elif [ $WARN_COUNT -gt 0 ]; then
    echo "  ${C_WARN}⚠️ Healthy with warnings${C_RESET} — informational, not blocking."
    exit 0
else
    echo "  ${C_OK}✅ Healthy.${C_RESET}"
    exit 0
fi
