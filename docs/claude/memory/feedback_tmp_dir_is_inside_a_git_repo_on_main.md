---
name: tmp-dir-is-inside-a-git-repo-on-main
description: "On the owner's Windows box C:/Users/INNOTECH is itself a git repo on branch main, so a \"non-git\" pytest tmp_path is not non-git; use GIT_CEILING_DIRECTORIES / временный каталог внутри git-репозитория на Windows"
module: [scripts]
mechanism: [windows-env, test-infra]
role: tester
metadata:
  type: feedback
---

`git rev-parse --git-dir` succeeds inside `C:/Users/INNOTECH/AppData/Local/Temp/...` (toplevel `C:/Users/INNOTECH`, branch `main`). A test that claims "non-git directory" and relies on tmp_path alone tests nothing, and a branch-gated feature (`--check` ORDER_BLOCK_* only on main) would fire on the PARENT repo's `main`.

**Why:** found while writing blind tests for plans_progress `--sync-order` / `--check` (Task 2.3): the precondition `assert not git rev-parse` failed in 2 of 6 off-main cases.

**How to apply:** for "not a git repo" cases pass `env["GIT_CEILING_DIRECTORIES"] = str(root.parent)` to the CLI under test and to the precondition probe. Pair every "no finding off main" test with a control on main in the same test (the off-main assertion alone is green today). `git init` needs `symbolic-ref HEAD refs/heads/main` for a portable main branch. pytest-timeout is NOT installed in the venv: `@pytest.mark.timeout` is only an unknown-mark warning, so bound blocking calls with subprocess `timeout=`.
