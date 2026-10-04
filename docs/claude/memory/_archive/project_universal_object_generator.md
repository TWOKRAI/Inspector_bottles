---
name: project-universal-object-generator
description: Layer/augmentation mechanism is a universal object/image generator for any product — letters on disks are only the first consumer
metadata:
  type: project
---

Owner's framing (2026-10-01): the shared mechanism for the line simulator and training-data generation
(`plans/layer-render`, future `Services/layer_render`) is a **universal object/image generator — a system of
layers and augmentation**, meant for different objects and products. It is NOT a "letter generator".
Background is layers too (solid fill at the bottom, belt texture with transparent gaps above, objects, camera effects).

**Why:** the owner will reuse it for other products; letter-specific code would have to be rewritten per product.

**How to apply:** names of modules/presets/CLI stay product-neutral; letters, fonts, symmetry overrides, class lists
are preset/catalog data, not code. A new product = new preset + catalog. Glyph rendering is one sprite-source kind
among image/catalog, photo cut-out, solid fill. Related: [[project-letters-task-scope]].

**Update 2026-10-01 (owner + CTO verdict, `plans/layer-render/cto-verdict-2026-10-01.md`):** the owner's top priority is a
**good layer editor** on top of ONE mechanism. `Services/layer_render` is the whole rendering service (background stack,
object layers, sources, effects, crop, preset, factory, catalog, preview) with one scene function `render_scene` that the
sim, the training generator and the editor all call. `line_sim` keeps only belt/encoder/passport; `dataset_gen` keeps only
training concerns (labels, symmetry, export, torch). The owner said "свести к одному": the old `DatasetEngine` path must be
migrated onto the layer preset and removed (Task 6.5) — never leave two ways to assemble an image. Scene effects are saved
in the preset (revises earlier "live only" O-2).

**How to apply:** a question "where does this drawing code go?" has one answer — `layer_render`; a second render path
anywhere is a defect, not a convenience. Editor features are judged by "what the editor shows is byte-identical to the sim frame".
