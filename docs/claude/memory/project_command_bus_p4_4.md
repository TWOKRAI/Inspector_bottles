---
name: project-command-bus-p4-4
description: TRH P4.4 command-bus plan — remove double dispatch, CommandManager as library, +lifecycle feedback
metadata:
  type: project
---

TRH P4.4 (главная работа P4) — план `plans/2026-05-31_transport-router-hub/p4.4_command-bus.md`.
Статус 2026-06-05: **P4.4.0 recon DONE** + **развилка пересмотрена → B2** (ветка `feat/command-bus`,
коммиты d1f6d4d3, 05bf3a86). Далее P4.4.1.

**РЕШЕНИЕ B2 (kind-router), НЕ B1:** recon-факт «все команды несут `type=command`» сделал kind-router
реализуемым. B1 (один диспетчер) делал CommandManager полым, message_dispatcher свалкой. **B2:**
`message_dispatcher`→`kind_router` (резолв по `type`); `CommandManager` ВЛАДЕЕТ таблицей команд (резолв
по `command` 1 раз). process.command/register_update → команды CM; state.changed → event-ветка; хак
auto_register_ipc уходит. «Меньше слоёв» = меньше полых компонентов, а не -1 lookup.

**Recon-выводы (на коде):** двойной резолв = `message_dispatcher.dispatch(command)` → generic-closure
`_make_command_handler` → `cm.handle_command` → `cm.dispatcher.dispatch(command)`. Все prod-команды
EXACT_MATCH (pattern/fallback только в тестах). 3 обходных хендлера — РАЗНЫЕ ключи в одном
message_dispatcher → **коллизии для B НЕТ by-design**. **Блокер P4.4.1:** `get_commands()` не отдаёт
callable+expects_full_message → нужен `CommandManager.iter_handler_infos()`. EXACT_MATCH register
«первая-побеждает» → рекомендация: `register_command` router-aware (убрать closure+re-sync). state.*
двойная регистрация гасится `auto_register_ipc=False`. **Рекомендация: P4.4.4 lifecycle — отдельным подпланом.**

**Цель:** убрать двойную диспетчеризацию приёма команд (две инстанции `dispatch_module.Dispatcher`:
`RouterManager.message_dispatcher` + `CommandManager.dispatcher`, обе резолвят по `command`).
**Вариант B (решение владельца, «меньше слоёв»):** CommandManager регистрирует хендлеры прямо
в `message_dispatcher`, свой второй Dispatcher снимает с живого пути → CM = чистая библиотека,
один диспетчер. + сквозная observability (context-manager/inline, НЕ новый pipeline) + reply на
общем шве. **Новое требование:** опциональный lifecycle-feedback команды (accepted/running/
progress/completed/failed) через correlation_id — интерим=`type=event`+`seq`, финал=`type=response`.

**Блокер из ревью (не забыть!):** есть command-хендлеры МИМО CommandManager, зарегистрированные
напрямую в `message_dispatcher` по ключу-команде — `process.command` (process_manager_process.py:173),
`register_update` (plugin_orchestrator.py:259), `state.changed` (process_module.py:276). Наивный
kind-router «type==command→CM» их украдёт. Вариант B убирает коллизию by-design (все ключи в одном
диспетчере). P4.4.0 (recon, read-only) обязан инвентаризировать их первым.

7 задач P4.4.0–P4.4.6, strangler, регресс на ВСЕХ IPC → integration+qt-smoke. ADR-COMM-005.
Связано: [[feedback-fewer-layers]], [[project-transport-router-hub]], [[project-command-engine-audit]].
