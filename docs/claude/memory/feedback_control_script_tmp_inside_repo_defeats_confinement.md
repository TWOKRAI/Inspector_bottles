---
name: control-script-tmp-inside-repo-defeats-confinement
description: "ad-hoc control scripts must use the OS temp dir (C:), not a dir under the repo, or confine_preset_paths returns ok and the \"outside roots\" control lies / контрольный скрипт, временный каталог вне репозитория"
mechanism: [probes, test-infra]
role: tester
metadata:
  type: feedback
---

REPO_ROOT is itself an allowed root for `confine_preset_paths`. A control script that makes its tmp dir under the worktree
(`data/`, cwd) puts the "outside" PNG inside an allowed root -> `preset.preview` returns ok, not `invalid`.

**Why:** pytest's `tmp_path` lives on C: (outside the repo on D:), so tests are right; only my hand-rolled control script was wrong (Task 1.3h-a).
**How to apply:** in scratch controls use `tempfile.mkdtemp()` with no `dir=`; also clean up with `python -c shutil.rmtree` since `rm -rf` on the worktree is permission-denied in Bash.
