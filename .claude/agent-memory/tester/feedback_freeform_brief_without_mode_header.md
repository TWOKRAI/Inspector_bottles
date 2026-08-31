---
name: feedback-freeform-brief-without-mode-header
description: When the orchestrator hands a detailed self-contained brief with no MODE/INTERFACE header but its own explicit red/green + forbidden-paths protocol, follow the brief's protocol rather than mechanically forcing MODE:regression
metadata:
  type: feedback
---

The tester agent definition says: header missing/malformed → fall back to `MODE: regression`
(reads `git diff`, judges pass/fail against a change already made). But `MODE: regression`'s
own first step ("read what changed via git diff") can directly conflict with a brief that
explicitly forbids `git diff`/`log`/`show` — which happens when the brief is itself a complete,
self-consistent independent-acceptance protocol (expects a red/green split BEFORE any fix,
names forbidden paths explicitly, asks for per-criterion red/green in the report).

**Why:** RT-2 (telemetry-stage6, 2026-08-18) brief had no `MODE:`/`INTERFACE:`/`TASK:` header
at all, but was otherwise a complete RED-style protocol matching this project's standing
"independent tester, always, forbidden diff/plan/author-tests" convention (project CLAUDE.md,
"Task launch convention" table, stage 1: independent acceptance tests run before the author's
own, synchronous, forbidden paths named explicitly). Mechanically forcing `MODE: regression`
would have meant reading `git diff` — directly violating the brief's own explicit prohibition.

**How to apply:** when the header is absent but the free-form brief (a) names explicit
forbidden paths (plan/diff/author's tests), (b) frames the run as "expect a red/green split
before any fix, report which is which", treat it as RED-mode-equivalent and follow the brief's
own explicit rules over the generic fallback — but say so explicitly in the report ("no
standard header; treating as RED-mode equivalent because X"), don't silently reinterpret.
Still honor every hard constraint the brief states (no commit, no touching app logic) even
where they're stricter than the agent definition's own defaults. See also
[[feedback_framework_tests_cannot_import_prototype]] for a concrete case this style of brief
produced.
