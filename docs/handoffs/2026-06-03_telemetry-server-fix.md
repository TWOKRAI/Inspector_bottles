---
date: 2026-06-03
topic: Телеметрия — серверный root-cause state.* request/reply (RAW↔wrapped конфликт) найден и закрыт
machine: Windows
branch: feat/comm-system-target-architecture
---

## Session goal
Закрыть баг live-телеметрии: вкладка «Процессы» показывала «—» (статус/FPS/uptime). Заодно владелец уточнил курс: **сделать все уровни коммуникации согласованными, с чёткой ответственностью и без конфликтов** (дух ветки comm-system). Решение принято — НЕ копить телеметрию в ultracode-backlog, а добить в max-режиме (глубокий single-path баг fan-out не ускоряет).

## Done
- **Серверный root-cause найден (подтверждён чтением кода + probe'ом, не рассуждением)** и **закрыт**. Коммит `8041e8ef`.
- Фикс: флаг `StateStoreManager(auto_register_ipc=False)` — отключает RAW-регистрацию state.* из `initialize()`, оставляя единственного владельца ключей = CommandManager + wrapped-путь (с `reply_to_request`). router сохранён (нужен `DeltaDispatcher` для push дельт).
- **Verified headless** (`BACKEND_CTL=1 python -m backend_ctl.telemetry_probe`): ДО — `state.subscribe`/`state.get` → `timeout`; ПОСЛЕ — `success=True` + полное дерево телеметрии (все процессы `running`, fps/uptime). **Побочно: ProcessMonitor ПУБЛИКУЕТ телеметрию → backend OK.**
- +2 юнит-теста на флаг; 493 теста зелёные (state_store + process_lifecycle).
- Документация: план comm-system (P0 запись 2026-06-03 + связь с P2 авто-reply), memory `project_telemetry_subscription_bug` обновлён (dual-write), заведён `plans/ULTRACODE_BACKLOG.md`.

## What did NOT work
- **Прошлый orchestrator-фикс «применён, но не помог» (из старого HANDOFF) — теперь понятно почему:** автор добавил wrapped-путь на уровне оркестратора, но НЕ заметил, что RAW-регистрация идёт **внутри** `StateStoreManager.initialize()` (`state_store_manager.py:98`) и побеждает по правилу «первая регистрация» (`base_dispatcher.register_handler:39` → `if key in self.handlers: return False`). Поэтому переключение orchestrator RAW↔wrapped ничего не меняло — RAW всё равно прилипал первым.
- **Ложная гипотеза №1 (отвергнута):** «дело в correlation-id драйвера». Неверно — и `introspect.*`, и `state.*` идут через один `send_command → request()`, оба несут `request_id`. Различие НЕ в билете драйвера.
- **Ложная гипотеза №2 (отвергнута):** «дело в RAW-vs-wrapped как таковом / несовпадение сигнатуры `_extract_data`». Неверно — `_extract_data` корректно достаёт `data`. Точная причина — **порядок + конфликт регистрации** (RAW занимает ключ раньше wrapped), а не сам факт wrapping.
- **Probe с `| tail -40` завис без вывода** — `tail` буферизует до закрытия пайпа (конца процесса), интерим-прогресс не виден. Перезапуск с `python -u` **без** `tail` (потоковый вывод в фон-файл) сразу показал прогресс. Урок: для headless-probe НЕ пускать через `tail`.

## Key decisions made
- **Канон ответственности (зафиксирован в плане):** «ответить на request/reply» принадлежит **транспорту** (`RouterManager.receive`), а НЕ обёртке хендлера. Текущая зависимость reply от способа регистрации (RAW не отвечает / wrapped отвечает) — архитектурная асимметрия. Целевое снятие — **P2: авто-reply по `request_id` в `receive()`/`message_dispatcher`**; тогда флаг `auto_register_ipc` сведётся к защите от двойной регистрации. При P2 — **убрать reply из `_make_command_handler`**, иначе двойной ответ.
- Фикс сделан как **P0-интерим** (low-risk флаг, дефолт `True`=legacy для тестов/`in_memory_router`), а не как рискованная правка горячего транспорта — её место в P2 с отдельными тестами.
- **Ultracode только для независимой мелочи** (M5/§11/message-loss), глубокие single-path баги — max-режим. Список — `plans/ULTRACODE_BACKLOG.md`.

## Next step
Запустить прототип + qt-mcp snapshot вкладки «Процессы» (память `feedback_qt_mcp_smoke_verification`): если GUI всё ещё «—» — чинить **GUI-сторону** (план P0, строка 401): (а) `StateProxy.subscribe` без `request_id` + ложный успех; (б) `state.changed` уходит в `{gui}_system`, а GUI опрашивает `["data"]` (`process.py:131`). Серверная часть больше не подозреваемый.

## Files changed
**Закоммичено (`8041e8ef`):**
- `multiprocess_framework/modules/state_store_module/manager/state_store_manager.py` — флаг `auto_register_ipc`
- `multiprocess_prototype/orchestrator.py` — `auto_register_ipc=False` + комментарий
- `multiprocess_framework/modules/state_store_module/tests/test_state_store_manager.py` — +2 теста (ruff-format нормализовал файл)
- `plans/comm-system-target-architecture.md` — P0 запись 2026-06-03 + связь P2
- `plans/ULTRACODE_BACKLOG.md` — новый
- `docs/claude/memory/project_telemetry_subscription_bug.md` + `MEMORY.md` — обновлены (dual-write)
- `docs/sessions/2026-06-03.md` — авто-лог (pre-commit hook)

**НЕ закоммичено (важно для следующей сессии):**
- `multiprocess_framework/modules/logger_module/core/logger_manager.py` — ⚠️ **частичный M5, СЛОМАН** (предыдущий TeamLead-агент упал: убран `_route_via_router`, но остались мёртвые `router_manager`/`enable_router_routing`/`messages_routed`). В новом чате: либо доделать M5 целиком (4 файла: logger_manager + error_manager + logger_adapter + process_managers), либо `git checkout -- multiprocess_framework/modules/logger_module/core/logger_manager.py` и начать M5 заново.
