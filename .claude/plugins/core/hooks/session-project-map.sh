#!/usr/bin/env bash
# SessionStart hook — one-line project-map banner.
#
# Surfaces the project map up-front so the agent orients before blind-searching
# the codebase. Three states:
#   1. docs/PROJECT_CONTEXT.md exists -> print indexed-module count + mtime.
#   2. map missing but per-module CONTEXT.md files exist -> nudge to rebuild.
#   3. neither -> silent.
#
# ASCII-only output (safe on cp1251 consoles); runs from the project root like
# the other SessionStart hooks; always exit 0 — never blocks session start.

set +e

map="docs/PROJECT_CONTEXT.md"

if [ -f "$map" ]; then
  # Count module rows inside the CONTEXT-INDEX block. A populated registry has a
  # header row + a separator row + N data rows; the un-aggregated placeholder
  # has no table rows at all. So: rows>=2 -> modules = rows-2, else 0.
  rows=$(awk '
    /CONTEXT-INDEX:BEGIN/ {f=1; next}
    /CONTEXT-INDEX:END/   {f=0}
    f && /^\|/            {n++}
    END                   {print n+0}
  ' "$map" 2>/dev/null)
  [ -z "$rows" ] && rows=0
  if [ "$rows" -ge 2 ]; then modules=$((rows - 2)); else modules=0; fi

  # Portable mtime (date only): GNU stat, then BSD stat, then GNU `date -r`.
  mtime=$(stat -c %y "$map" 2>/dev/null | cut -d' ' -f1)
  [ -z "$mtime" ] && mtime=$(stat -f %Sm -t %Y-%m-%d "$map" 2>/dev/null)
  [ -z "$mtime" ] && mtime=$(date -r "$map" +%Y-%m-%d 2>/dev/null)
  [ -z "$mtime" ] && mtime="?"

  echo "Project map: $map ($modules modules, updated $mtime)"
  exit 0
fi

# Map missing — but do per-module CONTEXT.md files exist anywhere worth indexing?
found=$(find . -name CONTEXT.md \
  -not -path '*/.claude/*' \
  -not -path '*/.venv/*' \
  -not -path '*/node_modules/*' \
  -not -path '*/.git/*' 2>/dev/null | head -1)
if [ -n "$found" ]; then
  echo "Project map missing - run /core:quality:sync-context"
fi

exit 0
