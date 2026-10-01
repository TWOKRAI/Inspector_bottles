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
