---
name: feedback_a_recipe_test_must_run_the_same_check_as_the_launcher
description: "Тест рецепта звал validate_recipe_blueprint и был зелёным, а загрузчик (SystemBlueprint.check) отклонил рецепт: текстовый shape порта → провод несовместим, входы не подключены; владелец ждал долгий запуск стенда зря; остановка TaskStop не гасит процессы стенда"
module: [prototype/recipes, plugins/render, services/code_reader]
mechanism: [live-stand, test-assertions]
metadata:
  type: feedback
---

Владелец (2026-10-15): «почему так долго запускается», «это тоже запомни как проблему».

**Что случилось.** После правки `overlay_draw` (вход `frame` стал `image/*`) junior записал в `Port.shape` текст `"(H, W) или (H, W, 3)"`. Тесты рецепта (`test_qr_reader_sdk_demo.py`, `validate_recipe_blueprint` → `None`) были зелёными. Загрузчик отклонил рецепт: `Wire … image/gray (H, W) несовместим с draw.overlay_draw.frame`, затем два «Вход … не подключен» — следствие первой ошибки. Узнали на живом запуске, в окне координатора.

**Как применять.**
- Тест рецепта вызывает ту же проверку, что загрузчик (`SystemBlueprint.check()`), а не облегчённую.
- `Port.shape` — шаблон `(H, W, 3)` или пусто, не текст; для «любой формы» — пусто.
- Остановка стенда: `TaskStop` гасит обёртку `machine_gate`, процессы бэкенда (8765), `reader_tcp` (5000) остаются; завершать по PID (`taskkill /PID <pid> /T /F`), потом `netstat` по портам.
- Время старта стенда называть числом (старт → порт 8765 → кадр), не «долго».

Связано: [[feedback_a_source_frame_shape_must_not_crash_the_display]], план `plans/code-reader-gui/phase-4.md` (D5, D7).
