---
name: project-letters-task-scope
description: Letter-disk task — only letter + angle matter, disks have no defects; ml_inference always shows top-1, below threshold marked, robot never acts on it
metadata:
  type: project
---

Owner's decisions (2026-10-01) for the letter classifier (`plans/letters-retrain`):
- Goal is **letter and angle**. Defects are out of scope — "disks will be without defects"; measure with sim `defect_rate 0`.
- The label is **always shown**; below `confidence_threshold` it is marked (`below_threshold`, orange «<порог»).
  The robot still never acts below threshold — `word_layout` checks the flag AND its own `min_confidence` (NaN = below).
- Training fonts: a set of system Cyrillic fonts + the real cut-outs; DejaVu Sans/Mono are held out (the sim's fonts) to test generalisation.
- Sim letter geometry must match reality: letter height 0.486·D, stroke 0.081·D (measured on 229 real frames) — the old sim catalog was 26 % too big.

**Why:** the network was silent (<0.5) on ~50 % of sim disks; part of it was an unrealistic sim, part one-font training.

**How to apply:** don't add defect handling to this task; never let a below-threshold prediction reach a robot job.
Related: [[project-universal-object-generator]].
