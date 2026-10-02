---
date: 2026-10-02
topic: layer-render волна 5 — Task 2.4a влита; дальше спека 2.4b
machine: Windows
branch: feat/layer-render
---

## Состояние

- **2.4a влита** `be42ba755` (реализация `6c242c9e5`, инъекции `20368ee6d`, правки ревью `a696ec57d`, закрытие `d4126d5f6`).
  Радиус после слияния: layer_render + line_sim + dataset_gen 1578 passed, 3 skipped; до слияния ещё ml_train 141, Plugins/sim 743.
  Спека — `plans/layer-render/phase-2-core-2.4a.md` (ревью спеки 2 итерации). Матрица — `docs/reviews/2026-10-02_task-2.4a-lead-injections.md`.
- `main` не двигался (сосед — сессия 19, transport-single-policy: SHA сообщить до движения `main`).
- agentId трека: reviewer спеки `ad12e5fcbddf2455c`, tester `abd50f618b77d078d`, developer `a7aa8eddb36a6a74f`, reviewer кода `afc0aa8cf3f434b74`.
  Для 2.4b: developer — тот же (re-summon по agentId, спеку отдать с SHA и приказом перечитать); tester и reviewer кода — свежие.
- Память: `feedback_pytest_import_order_hides_a_cycle` (dual-write, `d4126d5f6`).

## Next step

1. Спека Task 2.4b (лид): `ObjectFactory` → `layer_render.factory`, `RenderedObject`; `line_sim.ObjectFactory.make` → `LayeredObject`
   (второй конструктор из `RenderedObject`); `preview` на `RenderedObject`; эталоны кадров прежние. Разведка: приватные `_preset`,
   `_catalog`, `_build_defect_blob`, `_DEFECT_*` трогают тесты. Файл спеки — отдельный (`phase-2-core-2.4b.md`): `phase-2-core.md` у бюджета.
2. Стадия 0 → слепой tester в worktree → developer → инъекции → ревью → слияние.

## Open

- Follow-up: `compose_layers` на стеке без слоёв на канве падает сырым `ValueError: max() iterable argument is empty`.
- Follow-up: `line_sim` `test_font_tool_rejects_font_without_glyph`, `test_letter_catalog_tool_missing_letter` красные с
  `PYTHONIOENCODING=utf-8` (и до 2.4a) — декодирование stderr подпроцесса.
- К 2.4b: докстринг `layer_render/preset.py` ссылается на `dataset_gen.core.config.GeneratorConfig`, `catalog_bridge`, LS-007/013.
- 6.4: CLI-границы шире регистра `center_crop` (0.1..5.0) — в докстринге, не исправлено.
- `docs/claude/OPEN_QUESTIONS.md` 168 КБ при бюджете 32 КБ — отдельной задачей.
