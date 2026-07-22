---
name: feedback-golden-snapshot-diff-before-regen
description: Before running UPDATE_BUILD_SNAPSHOTS=1 to fix a failing test_build_characterization.py, compute a precise field-level diff and confirm it's purely additive/expected — don't just trust "the test told me to regenerate"
metadata:
  type: feedback
---

`multiprocess_prototype/backend/tests/test_build_characterization.py` freezes the entire
assembled `proc_dict` (+ `orchestrator_config`) per real recipe as a golden JSON snapshot.
The file itself documents the sanctioned escape hatch: `UPDATE_BUILD_SNAPSHOTS=1 python -m
pytest .../test_build_characterization.py`. There is real precedent in this project for this
test going red for BOTH good and bad reasons on the same branch in one session (see the
`backend-ctl-proof-discipline` plan's "Вход плана — ЗАМЕРЕНО" section: one regression
(`a7266fef`, `.get("priority") or "normal"` idiom change) legitimately needed a snapshot
regen; that is a coincidence, not something to assume by default).

**Why this matters:** the failure's pytest diff output (`assert actual == expected`) on a
dict this large is truncated/unreadable in the terminal — you cannot eyeball whether the
diff is "just my new field" or "my new field PLUS something else I broke." Regenerating on
a truncated read is how a real regression gets silently baked into the new golden file.

**How to apply:** write a tiny throwaway script that imports `_canonical_build` and
`_golden_path` from the test module directly, computes both dicts, and walks them
recursively printing every differing leaf path (`ONLY IN ACTUAL` / `ONLY IN EXPECTED` /
`VALUE DIFFERS at <path>`). Confirmed this session (2026-07-21, adding
`observability.commands.log_success` + `managers.command.log_success` — an intentionally
additive field): the diff was EXACTLY 8 lines for phone_sketch and 11 for
hikvision_letter_robot, all `ONLY IN ACTUAL: ...log_success = False`, nothing else — only
then ran `UPDATE_BUILD_SNAPSHOTS=1`, then re-ran normally to confirm green, then
`git diff` on the two `.json` snapshot files as a final sanity check (should show ONLY the
new keys, one insertion per process + one in `orchestrator_config.sys_config.observability`).
If the diff shows anything you didn't intend to change, STOP — that's a real regression,
not a snapshot to rubber-stamp.
