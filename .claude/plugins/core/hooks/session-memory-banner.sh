#!/usr/bin/env bash
# SessionStart hook — one-line memory STATUS, not a content renderer. Task
# 2.4 it2, cto verdict docs/reviews/2026-09-14_cto-verdict-e1-memory-banner.md:
# CC itself loads the FULL .claude/memory/MEMORY.md index natively via
# `autoMemoryDirectory` (native_memory.py) — this hook only reports whether
# that's wired. Read-only; wiring is `doctor --fix`'s job. States (all exit
# 0): no store / empty / wired / not wired. "wired" = autoMemoryDirectory in
# settings.local.json equals resolved .claude/memory (whitespace-insensitive).

set +e

index=".claude/memory/MEMORY.md"; settings_local=".claude/settings.local.json"
if [ ! -f "$index" ]; then
  printf '\n🧠 Project memory not initialized — run /core:memory:init to start the store.\n'
  exit 0
fi

# Fence-strip -- skeleton's illustrative "- [...]" lines inside ``` don't count.
content=$(awk '/^```/{fence=!fence; next} !fence' "$index" 2>/dev/null)
count=$(printf '%s\n' "$content" | grep -c '^- \[')

if [ "$count" -eq 0 ]; then
  printf '\n🧠 Project memory is empty (.claude/memory/MEMORY.md) — nothing to recall yet.\n'
  exit 0
fi

expected=$(cd .claude/memory 2>/dev/null && pwd -P)
wired=""
if [ -n "$expected" ] && [ -f "$settings_local" ]; then
  # Both sides whitespace-stripped: pretty (native_memory) or compact JSON.
  tr -d '[:space:]' <"$settings_local" 2>/dev/null |
    grep -qF "\"autoMemoryDirectory\":\"$(printf %s "$expected" | tr -d '[:space:]')\"" && wired=1
fi

if [ -n "$wired" ]; then
  printf '\n🧠 Memory: %s entries · loaded natively (.claude/memory)\n' "$count"
else
  printf '\n🧠 Memory: %s entries\n   not wired → plugin doctor . --fix\n   read .claude/memory/MEMORY.md\n' "$count"
fi
exit 0
