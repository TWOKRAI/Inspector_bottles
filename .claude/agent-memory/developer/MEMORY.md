# Memory Index

- [F4.8 diff scope mismatch](project_f48_diff_scope_mismatch.md) — run_migration() touches 4 recipe files, owner only approved 2; blocked, not applied
- [Commit trailer no-wrap](feedback_commit_trailer_no_wrap.md) — outdated as of 2026-07: parser now tolerates Why:/Layer: wrapping (folds as continuation); single-line still recommended
- [pre-commit stash collision](feedback_precommit_stash_collision.md) — sibling's own note: 2+ agents committing same non-worktree checkout races pre-commit's global stash, can orphan a patch and lose unstaged edits
- [pre-commit collision recovery](feedback_precommit_collision_recovery.md) — blast radius grows across retries (8x observed); recover with `git show :path > path` (checkout/restore blocked); cap retries at 2-3
- [parallel commit sweep](feedback_parallel_commit_sweep.md) — staged-but-uncommitted files get swept into a sibling agent's commit when both commit in the same non-worktree checkout
- [Commit Layer whitelist source](reference_commit_layer_whitelist_source.md) — real ALLOWED_LAYERS lives in scripts/validate_commit/validate_commit.py, not the all-comments .claude/commit-layers.txt
- [Verify heuristic fix against golden recipes](feedback_verify_heuristic_fix_against_golden_recipes.md) — before "fixing" a blueprint.py join heuristic, run full prototype suite; an audit-flagged issue may be a documented trade-off
- [Worktree base drift](feedback_worktree_base_drift.md) — assigned worktree can be many commits behind main; verify freshness before trusting referenced plan/review docs
- [Observability facade extension](project_observability_facade_extension.md) — 4 touchpoints to add a new observability.* toggle; feature_flags.py explicitly excludes logs/stats/commands
- [Golden snapshot diff before regen](feedback_golden_snapshot_diff_before_regen.md) — write a field-diff script before UPDATE_BUILD_SNAPSHOTS=1; confirm purely additive, don't rubber-stamp
- [Silent observability plane](project_silent_observability_plane.md) — `_log_*` = тихий no-op без logger; у QueueRegistry/SRM его нет в проде → счётчик растёт, логов ноль
- [state_store TestLazyPrune flake](project_state_store_lazy_prune_flake.md) — red only inside full 5150-test run, never isolated; pre-existing, unrelated to logger/command_module work
