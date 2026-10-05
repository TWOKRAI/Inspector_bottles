---
name: Plan-Driven Development workflow
description: Plan→Branch→Commits traceability system — slug naming, Refs trailer, plan commits
type: project
originSessionId: 147f353c-8c5e-4b3e-bac2-c30e97cc4744
---
Plan-Driven Development system implemented 2026-05-12. New plans follow strict conventions.

**Why:** Previously plans scattered across 3+ locations, branches named arbitrarily, no traceability.

**How to apply:**
- New plans always in `plans/` (root), slug naming: kebab-case `<domain>-<what>`, max 40 chars
- Frontmatter: Slug, Дата, Статус (DRAFT/IN_PROGRESS/DONE/ABANDONED), Ветка
- Branch = `<type>/<slug>` (e.g., `feat/auth-rbac`). Standard: `feat/` not `feature/`
- Commits from plan MUST include `Refs: plans/<slug>.md` trailer
- Plan creation/closure = separate `docs(plans):` commits. Status updates OK in code commits
- `/plan` creates plan + branch + initial commit. `/plan-status` shows progress
- `/ship` validates Refs presence. Legacy branches without plans = no blocking
- Hybrid structure: single file by default, directory for large plans (Manager's discretion)
- Phase 2 (future): `validate_commit.py` hook enforcement for Refs when plan exists
