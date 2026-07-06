# Rubric: severity & category justification

**Dimension:** Did the reviewer assign the right category and severity, with a
justification that matches the canonical scale?

Canonical severity scale (single source of truth: `dev/agents/reviewer.md` →
"Severity scale"): **blocker** = security, spec; **major** = architecture, IPC, UI,
tests; **minor** = quality.

Deferred LLM-judge path. Temperature 0. Output **Unknown** when the output does not
state or imply a severity. Ambiguous scores (0.4–0.6) → human-review queue.

| Score | Anchor |
|-------|--------|
| 1.0 | Every finding's category matches the defect, and the implied severity matches the canonical scale (e.g. a hardcoded secret is security/blocker, not a quality nit). |
| 0.75 | Categories correct; one finding's severity is one notch off but defensible. |
| 0.5 | One finding mis-categorised (e.g. a security issue labelled quality) OR a blocker softened to a nit. |
| 0.25 | Multiple mis-categorisations, or a blocking issue treated as cosmetic. |
| 0.0 | Severity is inverted: a cosmetic issue blocks, or a security/spec blocker is dismissed. |
| Unknown | The output gives no category/severity signal to judge. |
