---
name: project-command-bus-p4-4
description: TRH P4.4 command-bus plan — remove double dispatch, CommandManager as library, +lifecycle feedback
metadata:
  type: project
---

TRH P4.4 (главная работа P4) — план `plans/2026-05-31_transport-router-hub/p4.4_command-bus.md`.
Статус 2026-06-05: **P4.4.0 recon DONE** + **B2 (сверено с comm-system §4)** + **P4.4.1 + P4.4.1b DONE**
(ветка `feat/command-bus`, коммиты aadb38c7 core, 1e7d7b49 cleanup). kind-router по `type` в receive()
(`_dispatch_command`: type=command→CM, авто-reply по request_id, manages_own_reply, strangler-fallback с
warning); process.command+register_update свёрнуты в команды CM. P4.4.1b: удалены
register_commands_with_router + _make_command_handler (копии команд в message_dispatcher) → дупликация
реестра устранена. framework 3221 passed, qt-smoke OK (0 strangler-warnings).

**Доп. рефакторинги:** ✅ регулировщик вынесен в метод `_route_by_kind` (603a4918, = «kind-router»);
✅ `message_dispatcher`→`event_dispatcher` (8b62c753, рейн 14 файлов — объект держит только события+heartbeat).
**P4.4.2 (observability-seam) ОТМЕНЕНА:** comm-system §4/§9.1 сохраняет CommandManager как «фасад+timing»;
перенос = override + ломает паритет (handle_command зовут и не из транспорта); пробел уже закрыт B2.
P4.4.3 core (один резолвер) достигнут B2. **Далее P4.4.6** (integration + ADR + синхрон comm-system).

**Сверка с comm-system-target-architecture §4 (ревью B+):** «два диспетчера не дубль» = про ДВИЖКИ (один
Dispatcher, B2 не нарушает), НЕ про дупликацию РЕЕСТРА команд (корень баг-класса telemetry/auto_register_ipc).
B2 убирает корень; канон COMMUNICATION_ARCHITECTURE.md совместим. Кросс-линк в §4. TODO P4.4.6: синхрон §4/§9.4.

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
