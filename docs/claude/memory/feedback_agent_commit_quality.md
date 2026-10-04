---
name: Agent commit message quality
description: Developer agents produce poor commit messages — Director must verify/amend
type: feedback
originSessionId: 94232869-20f7-4636-b47b-ddae61570b64
---

Правило перенесено в `.claude/skills/project-rules/SKILL.md` §4 (2026-10-04).

**Why:** Observed in Phase 1 of settings-mvp — developer used Latin transliteration of Russian words in commit subject. The commit hook checks trailers but not language quality.


1. When delegating to developer agent: include explicit instruction "commit subject in English or Russian, NEVER transliterated Latin (e.g. `navigaciya`, `inkapsulacia`)".
2. After agent claims commit done, **before** `git push`: `git log --oneline -1` → check subject.
3. If transliterated and not yet pushed/referenced anywhere → amend immediately.
4. If already pushed or quoted in handoff/plan/PR → leave it (live with it), add a note in next commit body if needed. Do NOT retroactively amend — SHA churn is worse than ugly subject.

**Observed cases:**
- Phase 1 settings-mvp — `navigaciya v presentere`
- Phase 5 tab-template (2cc0db7) — `dirty pri zapuske, inkapsulacia` — caught after push to handoff 4c3204c, left as-is
