---
name: always-latest-models
description: Owner rule — always use the newest Claude models (Opus 5.5, Sonnet 5.5 as of 2026-10-02) and switch to new ones when released; prefer tier aliases over version pins
metadata:
  type: feedback
---

Правило перенесено в `.claude/skills/project-rules/SKILL.md` §5 (2026-10-04).

**Why:** owner's correction during the `prompt-audit` run (2026-10-02). Pinned versions in prompts, templates and lint allow-lists (`claude-opus-4-8`, `Sonnet 4.6`, `Sonnet 5`, `Opus 5`) had already gone stale while agent frontmatter used aliases and stayed current.


Related: [[project-rules-ste-80]]
