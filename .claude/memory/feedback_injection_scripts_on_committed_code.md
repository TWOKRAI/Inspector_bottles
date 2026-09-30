---
name: injection-scripts-on-committed-code
description: "Break-injection scripts that restore files with `git checkout` must run on committed code, and multi-path variables must run under bash — both traps hit on gui-service 1.3b/1b.5 (2026-09-25)"
metadata:
  node_type: memory
  type: feedback
  last-verified: 2026-09-27
  originSessionId: 59c9cbad-07d6-46c5-850e-0b76582ec758
  modified: 2026-09-27T14:47:31.394Z
---

Commit the fix before running a break-injection script whose restore step is `git checkout -- <file>`.

**Why:** on gui-service 1.3b the fix was still uncommitted; the first injection's `git checkout` restored HEAD,
silently deleting the fix, and the next three injections ran against unfixed code (their patches did not even
apply). Recovered only because a stray `cp` backup existed. Separately, zsh does not word-split an unquoted
`$TS="a b c"`, so `pytest $TS` ran nothing and printed nothing — two injection runs looked like "no output"
instead of failing loudly.

**How to apply:**
- Commit first; then every injection restores from git safely. A WIP commit must carry a valid Conventional
  subject + `Why:`/`Layer:` — the commit-msg hook rejects `wip-...`, and a following `git reset --soft HEAD~1`
  then drops the REAL previous commit (robot-protocol-v2 T2.V, 2026-09-27: developer's commit silently unwound,
  recovered by `git reset --soft <sha>`). Never chain `commit && ... ; reset HEAD~1` without checking the commit
  exit code; prefer restoring from an in-memory copy of the file instead of a WIP commit.
- Run injection loops via `bash -c '...'` (or arrays), and treat an empty result line as a broken harness,
  never as "0 red".
- Run the injected pytest with `PYTHONDONTWRITEBYTECODE=1` and delete the module's `.pyc` after the
  restore. robot-protocol-v2 T2.1 (2026-09-27): an injection that MOVES a line keeps the file size, the
  restore lands in the same second, so Python's mtime+size check reused the injected `.pyc` — the correct
  code then failed its own test and looked like a real regression.
- Assert each textual patch applies exactly once (`src.count(old) == 1`, else report PATCH-MISS and skip);
  never count a non-applied patch as "0 tests died". Normalise `\n` -> `\r\n` when the target file is CRLF.
  line-sim 1.3h-b (2026-09-29): `Plugins/sim/pult_web/plugin.py` is CRLF — 6 of 22 multi-line patches silently
  did not match and would have read as "unguarded"; the count check caught it.
- Repeated 2026-09-30 (Task 4.5e, transport-single-policy): the lead's own quick fix was left uncommitted, a one-line
  `sed` injection was reverted with `git checkout -- <file>` and the fix vanished; the second injection then "passed
  by prediction" against the reverted file. Saved only by a `cp` backup made before the loop. Rule, no exceptions for
  "just a one-liner": `git commit` first, then inject; after each revert `git diff --quiet` must be clean AND the
  injection must be verified to have applied (`git diff --quiet` NON-clean after the patch).
- Related: [[merge-radius-skips-live-and-contract-tests]].
