---
name: always-latest-models
description: "Owner rule — always use the newest Claude models (Opus 5.5, Sonnet 5.5 as of 2026-10-02) and switch to new ones when released; prefer tier aliases over version pins (правило владельца: всегда последние модели)"
mechanism: [owner-decision, agents]
metadata:
  type: feedback
---

Правило перенесено в `.claude/skills/project-rules/SKILL.md` §5 (2026-10-04). Ниже — доказательная база урока.

Always take the latest Claude models: as of 2026-10-02 that is Opus 5.5, Sonnet 5.5, Haiku 4.5, Fable 5.1. When newer ones ship, move to them.

**Why:** owner's correction during the `prompt-audit` run (2026-10-02). Pinned versions in prompts, templates and lint allow-lists (`claude-opus-4-8`, `Sonnet 4.6`, `Sonnet 5`, `Opus 5`) had already gone stale while agent frontmatter used aliases and stayed current.

**How to apply:**
- Agent frontmatter and prose: use tier aliases `opus` / `sonnet` / `haiku` / `fable`. They resolve to the newest model of the tier, so they never go stale.
- Do not write a version next to a role name in prose ("Sonnet 4.6") unless the text is about that exact version.
- A pin is allowed only for a stated reason (cost, reproducibility) and gets a comment naming it.
- When a new model ships, update `CURRENT_MODELS` / `KNOWN_MODELS` in `.claude/plugins/core/scripts/lint_agents.py` and the allow-list in its test, in the same change.

Related: [[project-rules-ste-80]]
