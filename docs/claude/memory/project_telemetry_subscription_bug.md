---
name: project-telemetry-subscription-bug
description: "Processes-tab telemetry «—»: SERVER-side root cause FOUND+FIXED 2026-06-03 (RAW vs wrapped state.* registration conflict); GUI-side a/b may remain"
metadata:
  type: project
---

GUI live-телеметрия (вкладка «Процессы»: статус/FPS/uptime/Гц) показывала «—». **Серверный root-cause найден и закрыт 2026-06-03** (ветка `feat/comm-system-target-architecture`).

**SERVER-side (ЗАКРЫТО + verified probe'ом):**
- Корень: конфликт двух путей регистрации `state.*` в одном `message_dispatcher`. `StateStoreManager.initialize()` (`state_store_manager.py:98`) безусловно зовёт **RAW** `register_message_handlers(router)` — хендлер `handle_state_subscribe` возвращает dict, но НЕ зовёт `reply_to_request`. Параллельно идёт **wrapped**-путь (`register_commands_with_router` → `_make_command_handler`, который отвечает). `base_dispatcher.register_handler` — «первая регистрация побеждает» (`if key in self.handlers: return False`). RAW регистрируется раньше → прилипает → reply нет → `state.subscribe`/`state.get` timeout. `introspect.*` живут только в CommandManager → всегда wrapped → отвечают (отсюда асимметрия introspect ✅ / state.* ❌).
- **Фикс:** `StateStoreManager(auto_register_ipc=False)` в `multiprocess_prototype/orchestrator.py` — отключает RAW-регистрацию, единственный владелец ключей state.* = CommandManager+wrapped. Флаг добавлен в `__init__`+`initialize()`; дефолт `True` (legacy/тесты). +2 теста. 493 теста зелёные.
- **Verified** `backend_ctl/telemetry_probe.py`: `state.subscribe`→`success=True,sub_id`; `state.get(processes)`→полное дерево (все процессы `running`, fps/uptime). **ProcessMonitor публикует телеметрию — backend OK.**

**GUI-side (может остаться — плановые P0 a/б, НЕ проверял после server-фикса):**
- (а) `StateProxy.subscribe` без `request_id` + ложный успех при `router=None` (`state_proxy.py`); старое подозрение `_send_sync` (ждёт sync-ответ от async `router.send`) — частично оно же.
- (б) `state.changed` доставляется в `{gui}_system`, а GUI опрашивает только `["data"]` (`process.py:131`).
- Канонический фикс GUI — перевести `StateProxy.subscribe` на `router.request()` (план P2).

**Целевая архитектура:** «ответить на request/reply» — ответственность транспорта (RouterManager.receive), не обёртки. P2 вносит авто-reply по `request_id` в `receive()`/`message_dispatcher` → асимметрия RAW/wrapped исчезнет, флаг `auto_register_ipc` сведётся к защите от двойной регистрации. См. [[project_backend_control_mcp]], план `plans/comm-system-target-architecture.md` (P0 запись 2026-06-03 + P2).

**How to apply:** server-часть телеметрии РАБОТАЕТ. Если GUI всё ещё «—» — чинить GUI-сторону (a/б), не сервер. Probe `BACKEND_CTL=1 python -m backend_ctl.telemetry_probe` — быстрый headless-чек backend без GUI.
