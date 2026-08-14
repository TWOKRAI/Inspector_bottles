---
name: Plan dual-save rule
description: Always save plan to project plans/ alongside Claude Code internal plan — format depends on phase count
type: feedback
originSessionId: 43255063-69e2-4666-ae65-c58b98a1329a
---
When creating a plan (whether via /plan command or Claude Code plan mode), ALWAYS save the project plan to `plans/` with proper frontmatter (Slug, Дата, Статус, Ветка).

**Why:** Claude Code plan mode saves to `~/.claude/plans/` (internal, not in git). But the project convention (CLAUDE.md "Plan-Driven Development") requires plans in `plans/` with frontmatter, branch linkage, and `Refs:` trailer in commits. These are two separate systems — the internal plan is for Claude's workflow, the project plan is for traceability and git history.

**CRITICAL — this has been violated multiple times.** The internal Claude Code plan file is NOT a substitute for the project plan. User cannot see it in git, cannot reference it in commits, cannot review it in PRs.

**How to apply:**
0. **BEFORE entering plan mode:** decide slug, create `plans/<slug>.md` FIRST
1. **Format selection** (decide BEFORE creating the file):
   - **Single-phase / simple plan:** `plans/<slug>.md` (one file)
   - **Multi-phase plan (2+ phases):** `plans/<slug>/plan.md` (directory — allows phase logs, artifacts)
   - Convention from CLAUDE.md: `plans/<slug>.md` (дефолт) или `plans/<slug>/plan.md` (multi-phase)
2. When entering plan mode or creating a plan for a non-trivial task:
   - Let Claude Code save its internal plan as usual
   - ALSO create project plan with frontmatter (Slug, Дата, Статус, Ветка, Автор)
   - Create branch `<type>/<slug>`
   - First commit = `docs(plans): создан план <slug>` with the plan file
3. All subsequent commits MUST include `Refs: plans/<slug>.md` or `Refs: plans/<slug>/plan.md` trailer
4. On plan completion, update Статус to DONE
