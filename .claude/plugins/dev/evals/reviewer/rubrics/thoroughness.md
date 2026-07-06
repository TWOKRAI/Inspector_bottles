# Rubric: thoroughness

**Dimension:** Did the reviewer apply the base checklist and exactly the
specializations the diff triggers, without skipping a relevant dimension?

Reference: `dev/agents/reviewer.md` — Base checklist (always) + opt-in specializations
(Architecture, Module Contract, IPC/Concurrency, Security, UI Thread-safety).

Deferred LLM-judge path. Temperature 0. Output **Unknown** if the diff's triggered
specializations cannot be inferred from the output alone. Ambiguous (0.4–0.6) → queue.

| Score | Anchor |
|-------|--------|
| 1.0 | Base checklist applied; every specialization the diff triggers is exercised; none irrelevant ones forced. |
| 0.75 | All triggered specializations covered; one base-checklist item lightly treated. |
| 0.5 | One triggered specialization missed, or an irrelevant one applied. |
| 0.25 | Multiple triggered specializations missed; review is shallow relative to the diff. |
| 0.0 | Base checklist not applied; the review ignores the spec/acceptance criteria. |
| Unknown | Output too terse to tell which dimensions were checked. |
