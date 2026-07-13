---
name: f48-diff-scope-mismatch
description: F4.8 gui_positions canonicalization touches 4 recipe files, not the 2 covered by the owner-approved diff report — blocked, not applied
metadata:
  type: project
---

`run_migration()` from `multiprocess_prototype/recipes/migrations/canonicalize_gui_positions.py`,
run against the real `multiprocess_prototype/recipes/` directory (2026-07-11, attempted on branch
`feat/constructor-f4-8-apply` from main `7a58c0a1`), changes **4** files, not the 2 the owner
approved in `plans/2026-07-06_constructor-master/f4.8-canonicalization-diff.md`:

- `phone_sketch.yaml` (approved, 43 lines removed — matches the report exactly)
- `hikvision_letter_robot.yaml` (approved, 61 lines removed — matches the report exactly)
- `camera_robot_calibration.yaml` (**NOT in the approved report** — has the same top-level
  `gui_positions` duplicate, 31 lines removed)
- `dataset_circle_capture.yaml` (**NOT in the approved report** — top-level `gui_positions` is a
  YAML *alias* `*id001` pointing at `blueprint.metadata.gui_positions` `&id001`; migration still
  deletes the top-level alias key, net diff 1 insertion/2 deletions: drops the `&id001` anchor tag
  since only one reference remains)

Root cause: the diff report's author (per its own text) only scanned/reported on two files by
name; they didn't grep the whole `recipes/` directory for the top-level `gui_positions:` key. A
directory-wide grep (`grep -rn "^gui_positions:" multiprocess_prototype/recipes/*.yaml`) finds it
in all 4 files immediately.

**Why:** the task's explicit STOP condition ("если diff отличается или задет любой другой
файл/ключ — не коммить") is written for exactly this case. Applying `run_migration()` to the
whole directory silently reaches beyond what the owner reviewed.

**How to apply:** before re-attempting F4.8 apply, either (a) get owner sign-off on the two extra
files' diffs (they're the same kind of dead-duplicate removal, likely fine, but not yet reviewed),
or (b) scope `run_migration()` to only the two approved files (it takes a `recipes_dir` — filter
by filename before calling, or migrate the two files directly). Do not run the unscoped call again
without re-checking this. Related: [[project_arch_boundaries_plan]] if that memory exists —
recipe-module consolidation work is touching the same files around the same time (task 4.5/C2/C3
in the same plan).
