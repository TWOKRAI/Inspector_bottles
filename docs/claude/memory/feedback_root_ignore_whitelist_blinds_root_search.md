---
name: feedback_root_ignore_whitelist_blinds_root_search
description: "Root .ignore (`/*` qex whitelist) makes rg and the Grep tool return zero hits for .claude/, docs/, plans/ when searched from the repo root, and qex does not index them — a silent false 'none found'; git grep sees them; search by explicit path or git grep; generated files in docs/ reach an agent only by an explicit link (корневой .ignore — белый список: docs/ скрыт от rg и qex, виден git grep; сгенерированное в docs/ доходит до агента только ссылкой)"
role: reviewer
module: []
mechanism: [dev-tooling, agents]
metadata:
  type: feedback
  last-verified: 2026-11-11
---

An absence claim ("no file mentions X", "zero callers") never rests on rg or the Grep tool run from the repo root: the root `.ignore` is a qex index whitelist (`/*` plus multiprocess_framework, multiprocess_prototype, Services, Plugins, backend_ctl, scripts), and rg and Claude Code's Grep use the same `ignore` crate and honour it — exit 0, no warning.

**Why:** 2026-10-12, review of the new Haiku `Explore` agent: `rg -l "web-researcher" . --glob '!.claude/worktrees'` -> empty (with `--hidden` too); Grep tool at the root -> "No files found"; `git grep -l web-researcher` -> 10 files; `rg --debug` -> `ignoring .\.claude … from ".\\.ignore", original "/*"`. The agent prompt suggested exactly the root form, so it would have reported a false "not found" for `.claude/`, `docs/`, `plans/`.

**Second case, 2026-11-11 (atlas reference tree):** `rg -l "ICommandManager \(9\)" .` from the root -> empty, `git grep` -> finds it; `docs/` is outside the whitelist, so qex does not index it either. Consequence for generated content: a file written under `docs/` (e.g. `docs/atlas/`) never reaches an agent through search; it arrives only if a prompt or `CLAUDE.md` «Ключевые пути» links its path, and only `git grep` finds it by content. A plan that says "the agent will find the generated map" is wrong until that link exists.

**How to apply:** search `.claude/`, `docs/`, `plans/` by explicit path (`rg … .claude --glob '!worktrees'`) or with `git grep`, and say which. `git grep` skips untracked files, so a zero that decides a verdict is checked both ways. Never write a root rg/Grep into a brief or an agent prompt. Generated reference files meant for agents: link them by path from `CLAUDE.md` or the prompt, or place them outside `docs/`.

Related: [[feedback_an_absence_assertion_needs_a_reachability_check]], [[feedback_a_diff_based_rescue_omits_untracked_files]], [[feedback_zero_observations_looks_like_a_result]]
