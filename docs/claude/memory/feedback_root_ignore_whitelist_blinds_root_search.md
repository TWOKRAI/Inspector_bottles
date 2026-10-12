---
name: feedback_root_ignore_whitelist_blinds_root_search
description: "Root .ignore (`/*` qex whitelist) makes rg and the Grep tool return zero hits for .claude/, docs/, plans/ when searched from the repo root — a silent false 'none found'; search those by explicit path or git grep (корневой .ignore ослепляет rg и Grep от корня: ложное «не найдено»)"
role: reviewer
module: []
mechanism: [dev-tooling, agents]
metadata:
  type: feedback
  last-verified: 2026-10-12
---

An absence claim ("no file mentions X", "zero callers") never rests on rg or the Grep tool run from the repo root: the root `.ignore` is a qex index whitelist (`/*` plus multiprocess_framework, multiprocess_prototype, Services, Plugins, backend_ctl, scripts), and rg and Claude Code's Grep use the same `ignore` crate and honour it — exit 0, no warning.

**Why:** 2026-10-12, review of the new Haiku `Explore` agent: `rg -l "web-researcher" . --glob '!.claude/worktrees'` -> empty (with `--hidden` too); Grep tool at the root -> "No files found"; `git grep -l web-researcher` -> 10 files; `rg --debug` -> `ignoring .\.claude … from ".\\.ignore", original "/*"`. The agent prompt suggested exactly the root form, so it would have reported a false "not found" for `.claude/`, `docs/`, `plans/`.

**How to apply:** search `.claude/`, `docs/`, `plans/` by explicit path (`rg … .claude --glob '!worktrees'`) or with `git grep`, and say which. `git grep` skips untracked files, so a zero that decides a verdict is checked both ways. Never write a root rg/Grep into a brief or an agent prompt.

Related: [[feedback_an_absence_assertion_needs_a_reachability_check]], [[feedback_a_diff_based_rescue_omits_untracked_files]], [[feedback_zero_observations_looks_like_a_result]]
