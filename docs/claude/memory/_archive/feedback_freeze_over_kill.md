---
name: feedback_freeze_over_kill
description: Владелец предпочитает FREEZE, а не KILL для мёртвого/дремлющего кода — не удалять, замораживать
metadata:
  type: feedback
---

Владелец при выборе судьбы мёртвого/дремлющего кода стабильно выбирает **FREEZE (сохранить), а не KILL (удалить)**.

Прецеденты:
- `actions_module` (2026-07-08): решил сохранить, хотя ActionBus не прод-путь undo (ADR-COMM-002 не исполняется) — [[project_actions_module_keep]].
- GATE G2 форм (2026-07-10, «я бы не удалял»): 4 механизма схема→виджет — 7b binding-aware / 7c entity_editor / 7d WidgetRegistry все dead-in-prod (верифицировано), но НЕ удалять; активный = 7a legacy, остальные → frozen-tier. См. [[project_forms_mechanism_g2]] / `plans/2026-07-06_constructor-master/e4-forms-mechanism-diff.md`.

**Why:** дремлющий рабочий+тестированный код — капитал/опциональность (напр. 7b — готовый reactive/undoable write, если ADR-COMM-002 оживёт). Цена хранения ниже риска потери.

**How to apply:** не предлагать удаление dead-кода как дефолт. Для мёртвого/дремлющего механизма предлагать FREEZE-ярус (core/optional/**frozen** карты H.1 + `.sentrux/rules.toml` boundaries: заморожённое НЕ обрастает новыми зависимостями, новые фичи туда не текут). KILL — только если владелец явно санкционировал (per-item одобренный коммит, GATE G4/H.2). «Унификация N→1» = сузить АКТИВНЫЙ путь до одного, а не физически удалить остальные.
