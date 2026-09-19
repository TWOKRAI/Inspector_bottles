# Debugger agent memory — re-entry point

> Curate this file AS YOU WORK, not just at session end — Claude Code injects
> the first 200 lines / 25 KB of this file into every `debugger` agent's
> system prompt (see `.claude/CLAUDE.md` → "Subagent-memory (нативная CC)").
> Past that ceiling content is silently truncated and this file stops working
> as a re-entry point — keep it short and current, not exhaustive.

## Re-entry

What a fresh `debugger` agent must know walking back into this cluster: which
bug/regression it currently owns, which hypotheses were already ruled out
this pass (so it does not re-test them), and how the LAST pass ended — fixed,
escalated to `investigator` after two failed iterations, or still
reproducing.

**Append-only:** this file merges via `merge=union` (`.gitattributes`), which
stays conflict-free only for content that never changes in place — add one
dated line per update, newest at the bottom, and never edit an existing line
in place (editing produces a silent duplicate across two parallel worktrees
of this role instead of a merge conflict — Task 2.4 review R7).

```
- YYYY-MM-DD · owns: <bug/regression> · verified: <hypotheses ruled out this pass> · state: <fixed / escalated / still reproducing>
```

## Lessons

Capture-rail entries for this role only — see `.claude/CLAUDE.md` → "Когда
захватывать" for the WHEN/FORBID gate this list follows (cross-role rules
still go in the shared `.claude/memory/`, not here). One lesson = one line,
appended to the END of this list — append-only, so two parallel worktrees of
this same role each adding their own line merge without conflict (Task 2.4,
"Коллизия параллельной записи").

Format (example only, not a real entry):

```
- [Title](file.md) — one-line hook (whole line ≤ 150 chars)
```
