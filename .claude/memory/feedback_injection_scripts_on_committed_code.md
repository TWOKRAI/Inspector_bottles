---
name: injection-scripts-on-committed-code
description: Break-injection scripts that restore files with `git checkout` must run on committed code, and multi-path variables must run under bash — both traps hit on gui-service 1.3b/1b.5 (2026-09-25)
metadata:
  type: feedback
  last-verified: 2026-09-25
---

Commit the fix before running a break-injection script whose restore step is `git checkout -- <file>`.

**Why:** on gui-service 1.3b the fix was still uncommitted; the first injection's `git checkout` restored HEAD,
silently deleting the fix, and the next three injections ran against unfixed code (their patches did not even
apply). Recovered only because a stray `cp` backup existed. Separately, zsh does not word-split an unquoted
`$TS="a b c"`, so `pytest $TS` ran nothing and printed nothing — two injection runs looked like "no output"
instead of failing loudly.

**How to apply:**
- Commit (or WIP-commit) first; then every injection restores from git safely.
- Run injection loops via `bash -c '...'` (or arrays), and treat an empty result line as a broken harness,
  never as "0 red".
- Related: [[merge-radius-skips-live-and-contract-tests]].
