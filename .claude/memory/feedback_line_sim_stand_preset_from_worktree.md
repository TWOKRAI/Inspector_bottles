---
name: feedback-line-sim-stand-preset-from-worktree
description: Live line_sim stand from a fresh worktree cannot exercise preset.commit until you give it a .yaml preset plus a catalog beside it — four gates in order
metadata:
  type: feedback
---

A fresh worktree has no `data/` (gitignored), and `apps/line_sim/pipeline.yaml` points
`preset_path` at a catalog dir, not a `.yaml`. `POST /api/preset/commit` then hits, in order:
1. `bad_request` "плагин собран не из .yaml-пресета" — point BOTH `preset_path` lines (scene
   ~85, preview ~168) at a temp `.yaml` outside the repo;
2. `invalid` ScenePreset — body needs `catalog_dir` or layers;
3. `invalid` "Каталог классов не найден" — catalog must exist;
4. `invalid` "путь вне разрешённых каталогов" — catalog must sit under the stand's repo root or
   next to the preset: copy `data/line_sim/letter_catalog_rep` (16K, exists in `merge-main` /
   `ls-layer` worktrees) beside the temp preset.
Only then a stale `base_rev` yields `conflict` (409), and the preset file stays byte-identical.

**Why:** R-4 live check, 2026-09-29 — four restarts/probes to reach the conflict branch.
**How to apply:** revert the `pipeline.yaml` edit afterwards WITHOUT `git checkout --` (denied
by permissions): `sed` back by line number, then restore CRLF (`sed -i 's/$/\r/'`) — sed writes LF
and leaves a phantom `M`. Related: [[feedback-node-page-harness-blind-to-browser-defaults]].
