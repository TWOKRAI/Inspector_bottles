# Handoff: gui-service после 1b.2b-pre (2026-09-26)

**Состояние:** main = `ae0eebde` (lifecycle 1.6 соседа поверх нашего `3783296f`). Радиус
registers_module + prototype/adapters на нём — 305 passed, 3 skipped. Живых стендов нет.
Worktree'ы `.claude/worktrees/gui-1b2b-pre{,-tester}` можно удалить (ветки слиты / вишня взята).

## Закрыто

| Задача | Merge | Приёмка |
|---|---|---|
| 1b.2b-pre — `from_catalog` строит копии регистров (ADR-RM-007) | `3783296f` | `docs/reviews/2026-09-25_gui-1b2b-pre-lead.md` |

Решение владельца 2026-09-25: **проверка значения — сначала фронт, потом бэкенд, одним механизмом**;
описание регистра плагина — единственная истина. Раздел в `phase-1b-recipe-service.md` («Проверка
значения регистра…»), задачи 1b.2c / 1b.2d в `plan.md`.

## Следующий шаг: 1b.2c — вердикт бэкенда доходит до формы

Цель: отказ бэкенда на правку поля → поле в форме откатывается, оператор видит текст ошибки.
Сейчас это самое слабое место схемы: бэкенд отвергает (`SchemaBase.validate_assignment` в
`cmd_set_config`, `process_module/plugins/base.py:1623`), но GUI этого не узнаёт.

Разведка (по коду, **живьём не подтверждено** — Step 1 задачи):
- путь: `FieldSetHandler.apply` → `TopologyBridge.on_field_set` (`frontend/bridge/topology_bridge.py:184`)
  → `CommandSender.send_field_command` (`frontend_module/bridge/command_sender.py:114`) →
  `send_command` → `process.relay` через ProcessManager (`_route_command`, :97). Ответа никто не ждёт,
  `request_id` нет.
- `debounce_ms` склеивает правки слайдера (coalescing) — ответ относится к последнему значению пачки.
- `cmd_set_config` при исключении `setattr` — что именно уходит отправителю (ошибка команды или
  ничего), не проверено. Команда может быть и `set_<field>` у плагина, а не generic.
- Вопросы к дизайну: есть ли у `process.relay` обратный путь ответа (механизм `reply_to_request` из
  1.3b); откат в форме — через `revert` того же `Action` (undo-стек) или отдельным `notify_field_changed`.

Канон: tester RED в worktree до кода → developer/teamlead → инъекции лида → живой стенд
(`backend_ctl`: `set_register` неверным значением, форма) → reviewer синхронно. Бриф — по
`executor-brief.md` (хук `lint-brief`: FILES ≤ 6 и считает пути до следующего раздела).
Сосед (4a): на `base.py` планов нет, lifecycle сейчас не ведёт (Ф2 ждёт L-6); порты 9800–9899.

## Открыто / ненадёжно

- Копия регистра мягче оригинала: `list`/`dict` без типа элементов (10 полей, 7 регистров),
  валидаторы `line_filter` и унаследованные из `Services` у `otel_export` → 1b.2d. Греп по
  `Plugins/` — не инвентарь (я так ошибся в этой сессии: пропустил `otel_export`).
- `validate()` менеджера проверяет только `FieldMeta` (min/max/доступ), тип и `Literal` — только
  при записи. Подсвечивает ли форма ошибку по `validate()` — не проверено.
- 1b.2b (сборка GUI без `PluginRegistry`) по-прежнему в очереди за T4.x — ждёт ревью владельцем
  `plans/frontend-constructor/gui-bootstrap-design.md`.
- `phase-1b-recipe-service.md` — 37.6 КБ при бюджете 32 КБ (раздел 1b.5 — 9.7 КБ); разбить.
- Старое из прошлого handoff: `test_watcher.py::test_foreign_file_in_the_same_directory_is_ignored`
  (macOS), `test_build_matches_snapshot` в общем прогоне, Linux (Orin) не проверялся.
