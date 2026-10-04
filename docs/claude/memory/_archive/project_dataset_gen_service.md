---
name: project-dataset-gen-service
description: "Services/dataset_gen DONE — universal cut-and-paste synthetic dataset generator (class + angle), preset ru_letters_disk; training service is next"
metadata:
  node_type: memory
  type: project
  originSessionId: f4ea6a5a-bd26-4d67-a5d7-46bc7170194d
---

Services/dataset_gen — DONE 2026-06-12 (branch feat/dataset-gen-service, commit 0b91b283, plan plans/dataset-gen-service.md). Universal cut-and-paste generator: core knows nothing about letters; task = YAML preset (presets/ru_letters_disk.yaml, 33 RU letters on disks, 128×128, 0–360°). One engine feeds disk export + lazy torch SyntheticDataset + QC preview grid. 56 tests.

Key non-obvious findings:
- Symmetry auto-detector needs rotation center (size-1)/2, NOT size/2 — half-pixel error gives 1px shift at 180° and false asymmetry.
- Absolute pixel-diff threshold gets diluted by large invariant region (letter on disk): П falsely passed as 180°-symmetric. Fixed with rel_threshold (d180 < 0.3 × median diff at probe angles).
- Glyph must be centered by actual ink bbox, not PIL anchor="mm" (font metrics offset ~2.5px breaks symmetry).
- cv2.imread/imwrite fail on Cyrillic paths on Windows → imread_unicode/imwrite_unicode (np.fromfile+imdecode).

Verified e2e: full={О}, 180={Ж,И,Н,Ф,Х}, С and П → none. Sprites in gitignored data/dataset_gen/ru_letters/ (regenerate: python -m Services.dataset_gen.tools.make_ru_letter_sprites).

NEXT: paired training service (two-headed model, angle loss masked by angle_valid) — contract = SampleLabel + SyntheticDataset target dict {class_index: long, angle: (sin,cos) float32, angle_valid: bool}. User planned to provide a paired prompt for it.
