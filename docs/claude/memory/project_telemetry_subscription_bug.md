---
name: project-telemetry-subscription-bug
description: "Processes-tab telemetry «—»: SERVER+IPC+GUI-receive РАБОТАЮТ; process-level replay DONE (16e14084); остаток — widget-level late-binding (lazy tab) + нет издателей FPS/latency/health"
metadata:
  type: project
---

GUI live-телеметрия (вкладка «Процессы»: статус/FPS/uptime/Гц) показывала «—». **Серверный root-cause найден и закрыт 2026-06-03** (ветка `feat/comm-system-target-architecture`).

**SERVER-side (ЗАКРЫТО + verified probe'ом):**
- Корень: конфликт двух путей регистрации `state.*` в одном `message_dispatcher`. `StateStoreManager.initialize()` (`state_store_manager.py:98`) безусловно зовёт **RAW** `register_message_handlers(router)` — хендлер `handle_state_subscribe` возвращает dict, но НЕ зовёт `reply_to_request`. Параллельно идёт **wrapped**-путь (`register_commands_with_router` → `_make_command_handler`, который отвечает). `base_dispatcher.register_handler` — «первая регистрация побеждает» (`if key in self.handlers: return False`). RAW регистрируется раньше → прилипает → reply нет → `state.subscribe`/`state.get` timeout. `introspect.*` живут только в CommandManager → всегда wrapped → отвечают (отсюда асимметрия introspect ✅ / state.* ❌).
- **Фикс:** `StateStoreManager(auto_register_ipc=False)` в `multiprocess_prototype/orchestrator.py` — отключает RAW-регистрацию, единственный владелец ключей state.* = CommandManager+wrapped. Флаг добавлен в `__init__`+`initialize()`; дефолт `True` (legacy/тесты). +2 теста. 493 теста зелёные.
- **Verified** `backend_ctl/telemetry_probe.py`: `state.subscribe`→`success=True,sub_id`; `state.get(processes)`→полное дерево (все процессы `running`, fps/uptime). **ProcessMonitor публикует телеметрию — backend OK.**

**GUI receive-path (ПРОВЕРЕНО рантайм-probe'ом 2026-06-03, гипотезы a/б ОПРОВЕРГНУТЫ):**
Инструментация stdout-print (4 точки) на запущенном прототипе показала: весь путь сервер→IPC→GUI РАБОТАЕТ.
- `ProcessMonitor._publish_state` фаер 780×; `handle_state_set` proceed=True, delta!=None 156× (throttle режектит лишние uptime — норма).
- `DeltaDispatcher.dispatch` → `stats={'gui':1}` 150× — сервер рассылает `state.changed` подписчику gui.
- `GuiStateProxy.on_state_changed` вызван 300× — **GUI получает дельты, десериализует, гонит в Qt main thread** (`_dispatch_via_qt`→`@Slot _on_state_deltas`→`bridge.dispatch(state_delta)`→`state_updated`→`GuiStateBindings._on_state_msg`). Гипотезы (а) request_id и (б) `{gui}_system` vs `["data"]` — НЕ причина (state.changed идёт в system-канал, который пумпает штатный message_processor; data_receiver на `["data"]` — для кадров, отдельно).
- ⚠️ ВАЖНО про измерения: probe через `self._log_info` ВНУТРИ StateStore/DeltaDispatcher/GuiStateProxy НЕ писал в файл (логгер этих объектов не подключён) → дал ложное «dispatch=0». Доверять только `print(flush=True)` в stdout или `self.process._log_info` (процессный логгер). Урок: не делать выводы по отсутствию лога из объекта с непроверенной проводкой логгера.

**РЕАЛЬНЫЙ остаток — рассогласование путей в `widgets/tabs/processes/_panels.py:295-349` (`_connect_bindings`):**
Карточки `AllProcessesPanel` подписаны на пути, которые бэкенд НЕ публикует:
- **FPS**: bind `processes.{name}.state.fps` — издателя НЕТ (FPS воркера публикуется как `processes.{name}.workers.{w}.effective_hz`). → всегда «—».
- **Latency**: bind `processes.{name}.state.latency_ms` — издателя НЕТ вообще. → «—».
- **Активно/Обрывы/Средний FPS**: bind `system.health.active/broken_wires/avg_fps` — издателя НЕТ (фреймворковый `state_store_module/health/monitor.py` публикует `system.health.overall/<name>`, другие ключи, и не подключён в прототипе). → дефолты «Активно: 0».
- **status**: bind `processes.{name}.state.status` — издатель ЕСТЬ (`_broadcast_status_change`→`_publish_state`), но это **разовая** дельта на старте; непрерывно идёт только `state.uptime` (карточки на него не подписаны). Подозрение на startup-race + отсутствие initial-state replay на subscribe (GUI подписался — текущее значение не реплеится).

**Фикс (Option A — бэкенд публикует ожидаемые пути; выбор владельца 2026-06-03):**

✅ **СДЕЛАНО — process-level initial replay (`16e14084`):** `handle_state_subscribe` адресно шлёт новому подписчику снимок текущих листьев store по pattern (`_replay_initial_state` + `iter_matches`). +3 теста. Решает startup-race для process-level подписки. НО визуально GUI ещё «—» — см. оставшиеся gap'ы ниже.

⏳ **ОСТАЛОСЬ (verify-done скриншот: индикаторы серые, FPS/Latency «—», Активно 0):**
1. **Widget-level late-binding gap (НОВОЕ, отдельно от process-replay).** Вкладка «Процессы» — **LazyTabWidget** (создаётся при первом открытии). `AllProcessesPanel._connect_bindings` (`_panels.py:295`) регистрирует биндинги ПОСЛЕ того, как разовые статус-дельты прошли. Process-level replay (на subscribe GuiProcess при старте) этого НЕ покрывает — нужен **widget-level replay**: при `GuiStateBindings.bind()` сразу применить закэшированное значение (bindings/GuiStateProxy._cache его уже хранят), либо ре-реплей при создании ленивой вкладки. Контракт статуса ВЕРНЫЙ: `StatusIndicator.set_state("running")`→зелёный (`status_indicator.py` DEFAULT_COLORS), просто дельта не доходит до позднего виджета.
2. **FPS — нет источника вообще.** За ~12000 publish'ей НИ ОДНОГО `workers.*.effective_hz`/`workers.*.status` (только `state.status` 96× + `state.uptime` 11496×). Heartbeat-sender (`process_heartbeat.py:75-83`) включает `workers_status` через `get_all_workers_status()`, но `WorkerManager.get_worker_status` похоже НЕ отдаёт `effective_hz` (есть только у IdleWorker). → нужно: воркеры репортят hz → ProcessMonitor агрегирует в `processes.X.state.fps`.
3. **Latency** `processes.X.state.latency_ms` — издателя нет (из `workers.*.cycle_duration_ms`).
4. **system.health.active/avg_fps/broken_wires** — издателя нет (ProcessMonitor должен публиковать: active=кол-во running и т.д.).

**Целевая архитектура:** «ответить на request/reply» — ответственность транспорта (RouterManager.receive), не обёртки. P2 вносит авто-reply по `request_id` в `receive()`/`message_dispatcher` → асимметрия RAW/wrapped исчезнет, флаг `auto_register_ipc` сведётся к защите от двойной регистрации. См. [[project_backend_control_mcp]], план `plans/comm-system-target-architecture.md` (P0 запись 2026-06-03 + P2).

**How to apply:** НЕ трогать сервер/IPC/transport — они проверены и работают (publish→dispatch→gui receive). Чинить контракт путей в `_panels.py._connect_bindings` ↔ `process_monitor._publish_state`. Probe `BACKEND_CTL=1 python -m backend_ctl.telemetry_probe` — headless-чек backend. Для рантайм-диагностики GUI: `QT_MCP_PROBE=1 python -u multiprocess_prototype/run.py` + `print(flush=True)` в нужных точках (НЕ `self._log_info` объектов с непроверенной проводкой).
