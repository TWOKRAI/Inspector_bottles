#!/usr/bin/env bash
# SessionStart hook — emit one-line MCP availability status for the orchestrator.
#
# Goal: inform the main agent at session start which MCP servers are reachable
# in THIS session, so it can route work correctly. This is NOT a "silent
# failure protection" (Claude Code's `/mcp` command already shows MCP state) —
# it's an early signal so the orchestrator does not delegate to subagents that
# would then hit an unavailable MCP.
#
# Complements core/session-health-check.sh (which only warns about Ollama).
# This hook covers the full MCP arsenal.
#
# Output format (one line, stdout):
#   MCP: qex=UP|DOWN ollama=UP|DOWN sentrux=UP|DOWN context7=cfg|nocfg <optional...>
#
# Conventions:
#   UP    — binary present AND (where applicable) dependency reachable
#   DOWN  — binary missing or dependency unreachable
#   cfg   — config file present (for user-level MCPs like context7)
#   nocfg — config file missing
#
# Exit always 0 — non-blocking info hook.

OUT="MCP:"

# --- qex (semantic search) — needs binary + Ollama for embeddings
QEX_STATE="DOWN"
if command -v qex >/dev/null 2>&1 || [ -x "$HOME/.cargo/bin/qex" ] || [ -x "$HOME/.cargo/bin/qex.exe" ] || [ -x "$HOME/.local/bin/qex" ]; then
    QEX_STATE="UP"
fi
OUT="$OUT qex=$QEX_STATE"

# --- Ollama — required by qex for embeddings
OLLAMA_STATE="DOWN"
if curl -s --max-time 1 http://localhost:11434/ 2>/dev/null | grep -q "running"; then
    OLLAMA_STATE="UP"
fi
OUT="$OUT ollama=$OLLAMA_STATE"

# --- sentrux (architectural metrics)
SENTRUX_STATE="DOWN"
if command -v sentrux >/dev/null 2>&1; then
    SENTRUX_STATE="UP"
fi
OUT="$OUT sentrux=$SENTRUX_STATE"

# --- context7 (user-level, presence of config in ~/.claude.json or .mcp.json)
CONTEXT7_STATE="nocfg"
if [ -f "$HOME/.claude.json" ] && grep -q '"context7"' "$HOME/.claude.json" 2>/dev/null; then
    CONTEXT7_STATE="cfg"
elif [ -f "$PWD/.mcp.json" ] && grep -q '"context7"' "$PWD/.mcp.json" 2>/dev/null; then
    CONTEXT7_STATE="cfg"
fi
OUT="$OUT context7=$CONTEXT7_STATE"

# --- Optional MCPs (only report if .mcp.json mentions them)
if [ -f "$PWD/.mcp.json" ]; then
    for srv in codegraph ast-grep serena graphify github qt-mcp playwright sequential-thinking; do
        if grep -q "\"$srv\"" "$PWD/.mcp.json" 2>/dev/null; then
            OUT="$OUT $srv=cfg"
        fi
    done
fi

echo "$OUT"
exit 0
