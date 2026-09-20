---
name: shared-tree-provenance-forensics
description: How to reconstruct who wrote what in a shared working tree with several live sessions — pre-commit patch files, fsck WIP stashes, identical mtimes; and why explicit-path staging does not protect a shared file
metadata:
  type: project
---

Three live sessions share one working tree on this repo (closure, otel, perf, 2026-09-06). Two
facts make foreign edits travel under someone else's commit message:

1. The pre-commit framework stashes EVERY unstaged change to tracked files on EVERY commit and
   re-applies it afterwards. Evidence: `~/.cache/pre-commit/patch<ts>-<pid>` — one file per
   commit (12 on 2026-09-05/06, 77–86 KB each = the foreign diff of the moment). All rewritten
   files get the same mtime to the millisecond (21:51:36.97 on five unrelated files) — an
   identical mtime means a git operation, not an editor.
2. Explicit-path staging protects against NEIGHBOUR files only. A file already `M` with a
   foreign hunk goes whole: 5de49b0d staged `docs/claude/memory/MEMORY.md` for one index line and
   carried 48/91 lines of another session's compression (disclosed in 6ac5044d).

**How to apply:** at a merge gate, `git show --stat` per commit against the message (a one-line
claim with a 48/91 diffstat is the signature); `git fsck --unreachable --no-reflogs` lists dropped
`WIP on <branch>` stashes with timestamps; the patch-file sizes show when foreign changes were
partly committed (77903 → 31269 B between two commits). Verdict rule: one worktree per writing
session; the shared tree belongs to one owner; index files (MEMORY.md, OPEN_QUESTIONS.md) are
lead-owned, others add per-topic files and the lead adds the index line at merge.
