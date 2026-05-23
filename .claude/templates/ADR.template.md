# ADR-{{NUMBER}}: {{TITLE}}

- **Status:** PROPOSED | ACCEPTED | DEPRECATED | SUPERSEDED-BY-ADR-NNNN
- **Date:** {{DATE}}
- **Authors:** {{AUTHORS}}
- **Tags:** _(comma-separated — e.g. mcp, memory, agents)_

## Context

What problem are we solving? What is the situation that forces a decision?
2-6 sentences. Include hard constraints (deadlines, regulatory, team-size,
runtime) that bound the solution space.

## Decision

What we will do, stated as one or two concrete actions. Active voice.
"We will use X" / "We will not use Y".

If the decision is multi-step, list steps in order.

## Alternatives considered

For each plausible alternative, in 1-2 sentences:
- **Option A:** _(brief description)_ — rejected because ...
- **Option B:** _(brief description)_ — rejected because ...

## Consequences

What becomes easier / harder after this decision?

- **+** Positive consequence (capability gained, cost reduced)
- **+** Positive consequence
- **−** Negative consequence (trade-off accepted, debt taken on)
- **−** Negative consequence

## Implementation pointers

Optional. If the decision lands code/config in specific files, list them
so future readers can trace decision → code:

- `path/to/file.py:42` — function that embodies the rule
- `.claude/mcp/<name>/` — config that follows from this ADR

## Revisit when

Optional. What event would make us reopen this decision?
Examples: "team grows past 5", "moving to multi-region", "Python 3.13 GA".

---

> Workflow: `/adr <title>` creates this file at `docs/claude/DECISIONS/NNNN-<slug>.md`.
> Once status flips to ACCEPTED, reference the ADR number in code/CLAUDE.md/STACK.md
> where the rule shows up, so the chain is bidirectional.
