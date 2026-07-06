#!/usr/bin/env bash
# SessionStart hook — surface project memory at session start so the agent
# re-primes on accumulated lessons AND knows when to capture new ones.
#
# Reads .claude/memory/MEMORY.md (the human-maintained index), echoes its entry
# lines capped at top-N, and always prints the capture gate. Read-only — it
# NEVER writes; capture is the agent's job via /memory:remember.
#
# Three states, all non-blocking (exit 0):
#   - no MEMORY.md       -> store not initialized: nudge /core:memory:init + gate
#   - MEMORY.md, 0 real  -> initialized but empty: nudge first capture + gate
#   - MEMORY.md, N real  -> show top-N index + recall/gate footer
#
# Why the gate lives here: the plugin bootstrap does not yet deploy the root
# .claude/CLAUDE.md layer (Phase 1), so this always-on SessionStart banner is
# currently the only always-loaded carrier of the capture discipline in a fresh
# project. Keep this gate in sync with .claude/CLAUDE.md -> "Когда захватывать".

set +e

index=".claude/memory/MEMORY.md"
gate="Capture with /core:memory:remember when: fix took >1 try · recurring trap · user rule · non-trivial decision"

# State 1 — no store yet (fresh project): make the subsystem discoverable.
if [ ! -f "$index" ]; then
  echo ""
  echo "🧠 Project memory not initialized — run /core:memory:init to start the store."
  echo "   $gate"
  exit 0
fi

# Real entries are "- [Title](file.md)" lines OUTSIDE fenced code blocks. The
# bundled skeleton ships illustrative "- [...]" lines INSIDE ``` fences (format
# doc + examples); strip fenced regions first so an untouched skeleton counts
# as zero rather than printing those placeholders as if they were real memories.
entries=$(awk '/^```/{fence=!fence; next} !fence' "$index" 2>/dev/null | grep -E '^- \[' 2>/dev/null)

# State 2 — initialized but still empty: nudge the first capture, no index.
if [ -z "$entries" ]; then
  echo ""
  echo "🧠 Project memory is empty (.claude/memory/MEMORY.md) — nothing to recall yet."
  echo "   $gate"
  exit 0
fi

# State 3 — populated: show the capped index + recall/gate footer.
count=$(printf '%s\n' "$entries" | wc -l | tr -d ' ')
cap=12

echo ""
echo "🧠 Project memory — $count entries (.claude/memory/MEMORY.md):"
printf '%s\n' "$entries" | head -n "$cap" | sed 's/^- /   /'
if [ "$count" -gt "$cap" ]; then
  echo "   ... +$((count - cap)) more — read MEMORY.md or /core:memory:search <query>"
fi
echo "   Recall before acting · $gate"

exit 0
