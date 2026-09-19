---
module_code: {{CODE}}
---

# {{MODULE_NAME}} — Architecture Decisions

Per-module ADR (Architecture Decision Records). Heading format:
`## ADR-{{CODE}}-NNN: <title>`. Aggregator (`scripts/aggregate_context`)
collects a table of all ADRs into `docs/PROJECT_CONTEXT.md`.

**When to create an ADR:**
- The decision affects the module's design and isn't obvious from the code.
- Alternatives were discussed.
- A year from now you'll want to remember **why**, not just "how".

**When NOT to create one:**
- Trivial fix / rename / format.
- An obvious decision with no alternatives.

**Frontmatter `module_code:`** — required. Used by the aggregator for the
index and stable links. Must be unique in the project (see
`docs/PROJECT_CONTEXT.md` → "Module codes" table). Auto-derived from the
folder name if omitted (uppercase initials), but setting it explicitly is better.

---

## ADR-{{CODE}}-001: <short title>

**Date:** YYYY-MM-DD
**Status:** Accepted | Proposed | Deprecated | Superseded-by-ADR-{{CODE}}-NNN
**PR:** PR-XX (opt., link to the pull request)

### Context

What the problem is, what constraints frame it, what forces are pushing the
choice. 2-6 sentences. Good to include hard constraints: deadlines,
performance, regulatory, runtime constraints.

### Decision

What we're doing. Active voice. "We use X" / "We do NOT use Y".
If multi-step — a numbered list.

### Alternatives

List the plausible alternatives, each in 1-2 sentences:

- **Option A:** _short description_ — rejected because …
- **Option B:** _short description_ — rejected because …

### Consequences

What becomes easier / harder.

- **+** Positive (capability, cost reduction)
- **+** Positive
- **−** Negative (trade-off, debt accepted)
- **−** Negative

### Implementation pointers (opt.)

Where this decision materializes in the code:

- `interface.py:42` — the function embodying the rule
- `_impl/<file>.py:N` — the concrete implementation

### Revisit when (opt.)

What event should trigger reopening this decision?

- _Example: "a 2nd worker pool appears", "Python 3.13 GA", "throughput > 10k rps"_

---

## ADR-{{CODE}}-002: <next decision>

...
