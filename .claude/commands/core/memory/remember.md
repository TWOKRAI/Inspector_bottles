---
description: Capture a lesson into memory now (Karpathy format) — gate → grep-dedup → file → line in MEMORY.md
---

Manual lesson capture **at the moment of a verified transition** (red→green, fix confirmed,
decision made) or **at a Task boundary** (X.Y done → X.Y+1 in a multi-phase plan).
One lesson = one file. This is the main capture-rail trigger — don't wait for
`/core:team:wrap-up` (see `dev.md` → "Memory discipline (capture at Task boundary)").

## Arguments

`$ARGUMENTS` — the gist of the lesson, one phrase (optional). If empty — derive the lesson from
the context of the last verified transition in the session.

## Gate (don't write if it doesn't pass)

Capture only when the WHEN-gate from `.claude/CLAUDE.md` → Memory
(OVERRIDE) → "Capture rail — when to write" fires:

- the fix took more than one attempt (the root cause wasn't obvious);
- you hit the same trap again;
- the user gave a rule / correction / preference;
- a non-trivial decision was made that isn't in the code, git log, or plan.

Doesn't pass → say "nothing to capture" and stop. **Don't invent a lesson**
and don't record what code / git / the plan / `CLAUDE.md` already store (FORBID).

## Steps

1. **Phrase the lesson** as one sentence (it also serves as the dedup key) and pick a type:
   `feedback` (how I should work) · `project` (current work/decision) ·
   `user` (who the user is) · `reference` (external pointer).

2. **Dedup — grep for EACH key separately** before writing anything. A whole
   phrase almost never matches (one quoted pattern = a contiguous substring) — search
   for individual words from the lesson AND 1-2 synonyms via `-e`, targeting the
   `description:` lines of existing entries:
   ```bash
   grep -rinl --include='*.md' -e 'word1' -e 'synonym1' -e 'word2' .claude/memory/ 2>/dev/null
   ```
   Even one hit → open the file, decide near-match: yes → **UPDATE** (add the nuance /
   repeat / escalation), fix the line in `MEMORY.md`, **stop here** (don't
   multiply duplicates). Zero hits across **all** variants → a new file (step 3).

3. **No match → new file** `.claude/memory/<kebab-slug>.md` in Karpathy format:
   ```markdown
   ---
   name: <kebab-slug>
   description: <one line — recall matches on it>
   metadata:
     type: feedback | project | user | reference
     last-verified: YYYY-MM-DD
   ---

   <the fact in one paragraph.>

   **Why:** <why it matters / where it came from — date, trigger>
   **How to apply:** <how to apply it next time; required for feedback/project>

   Related: [[related-memory-slug]]
   ```
   Relative dates → absolute ("today" → YYYY-MM-DD). `last-verified` is
   the date of THIS entry/fact check; `memory_lint.py` flags it `stale` if it's
   older than 90 days (or `memory_stale_days` from `_stack.md`) — update the date at
   the next check/UPDATE, not only when the file is created.

4. **Index.** Add one line to the right section of `.claude/memory/MEMORY.md`:
   ```
   - [Title](slug.md) — <short hook>
   ```
   Index ≤200 lines, one line per entry.

5. **Confirm** in one line: create or update, file path, type.

## Don't

- Don't duplicate what's already in the code / git / the plan / `CLAUDE.md`.
- Don't create a new file when a near-match exists — update the existing one.
- Don't write entries "for later" without a fired gate.
- Don't touch another project's memory.
