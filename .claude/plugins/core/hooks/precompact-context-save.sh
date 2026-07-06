#!/usr/bin/env bash
# PreCompact hook — runs BEFORE the agent compacts conversation context.
# Symmetric to restore-context.sh (which runs PostCompact).
#
# Why: when Claude compacts a long session, fine-grained decisions get
# summarised and may be lost. This hook injects an instruction prompting
# the agent to persist anything load-bearing into .claude/memory/ FIRST,
# before compaction throws it away.
#
# This hook is read-only — it does NOT modify files itself. The agent does
# the saving (using its existing memory rules), which keeps git diffs clean
# and lets the agent decide what's actually worth keeping.

cat <<'PRECOMPACT'
## PreCompact checkpoint

Context is about to be compacted. Before that happens, audit what
**must survive** compaction and is NOT yet persisted on disk:

1. **Decisions taken this session** that aren't yet in:
   - `.claude/memory/` (long-term rules / feedback / project facts)
   - `plans/<slug>.md` (current task plan)
   - `docs/sessions/YYYY-MM-DD.md` (session journal, via `/core:team:wrap-up`)

   If a non-trivial decision was made and lives only in chat — save it now
   (memory rules in `.claude/CLAUDE.md` → "Memory (OVERRIDE)").

2. **Active plan state** — is `plans/<slug>.md` up to date with what was
   actually done? If steps were marked done in chat but not in the plan
   file, fix that now (1 Edit call).

3. **Open questions / blockers** the user still needs to answer — drop
   them into `docs/sessions/YYYY-MM-DD.md` so the next session sees them.

If nothing of the above applies — say so in one line and let compaction
proceed. Do **not** invent things to save.
PRECOMPACT
