# Memory Index

- [F4.8 diff scope mismatch](project_f48_diff_scope_mismatch.md) — run_migration() touches 4 recipe files, owner only approved 2; blocked, not applied
- [Commit trailer no-wrap](feedback_commit_trailer_no_wrap.md) — Why:/Layer: must be single physical line each, or commit-msg hook rejects them as missing
- [pre-commit stash collision](feedback_precommit_stash_collision.md) — sibling's own note: 2+ agents committing same non-worktree checkout races pre-commit's global stash, can orphan a patch and lose unstaged edits
- [pre-commit collision recovery](feedback_precommit_collision_recovery.md) — blast radius grows across retries (8x observed); recover with `git show :path > path` (checkout/restore blocked); cap retries at 2-3
- [parallel commit sweep](feedback_parallel_commit_sweep.md) — staged-but-uncommitted files get swept into a sibling agent's commit when both commit in the same non-worktree checkout
