---
name: brainstorm
description: >
  Pre-plan brainstorming. Activates BEFORE /dev:plan when the user has a fuzzy
  idea, multiple competing approaches, or hasn't decided on direction yet.
  Generates a small set of distinct options with trade-offs and forces a
  pick before any planning starts. Distinct from `grill-me` (which attacks
  an EXISTING plan); brainstorm is for when there is no plan yet.
  Triggers: "what could we do about", "how should we approach", "give me
  options for", "I'm not sure how to", "brainstorm", "/brainstorm".
---

# Pre-plan brainstorming

The user has an idea but no concrete plan. Your job is to **shrink the
decision space**, not write code. Do not jump to implementation.

## Workflow

1. **Restate the goal in one sentence.** If you can't, ask one clarifying
   question first — do not guess.

2. **Generate 2–4 genuinely distinct approaches.** Distinct means:
   different mechanism, different trade-off, different cost — not the same
   approach with cosmetic variation. If you can only think of one,
   say so honestly.

3. **For each approach, give:**
   - **Mechanism** — one sentence on how it works
   - **Cost** — concrete (files touched, dependencies added, person-hours)
   - **Risk** — the specific failure mode, not "may have issues"
   - **Reversibility** — easy / medium / hard to undo
   - **Ground truth check** (если применимо) — какой MCP подтвердит/опровергнет жизнеспособность опции: `sentrux:dsm` для архитектурного выбора, `codegraph_explore` для оценки blast radius альтернативы, `context7:query-docs` для library-выбора. Если MCP не подключён — пометь "checked manually" в Cost.

4. **Recommend one** and say why in one line. The recommendation can be
   "none of these — we need more information about X first."

5. **Stop.** Do not start implementing. Wait for the user to pick, push
   back, or ask for more options.

## Rules

- No code in this phase. Pseudo-code is fine to clarify a mechanism, but
  no edits.
- If two approaches are 90% similar, merge them — keep options actually
  different.
- Push back on the premise if it's flawed: "the question assumes X, but
  X may not be true because Y."
- If the user already picked an approach implicitly, surface that —
  don't pretend they're undecided.

## When NOT to use this skill

- User asked a direct question with one obvious right answer → just answer.
- User has a plan already → use `grill-me` to stress-test it instead.
- Task is < 20 lines of code → just propose and implement; brainstorming
  is overhead for trivial work.

## Output format

```
**Goal:** <one sentence>

**Option A — <name>**
- Mechanism: ...
- Cost: ...
- Risk: ...
- Reversibility: easy | medium | hard
- Ground truth check: <MCP used | manually | n/a>

**Option B — <name>**
- ...

**Recommendation:** <A | B | none — need X first>
**Why:** <one line>

(Stopping here. Pick one or push back.)
```
