# HANDOFF — телеметрия + backend-control (для нового чата)

**Дата:** 2026-06-03 · **Ветка:** `feat/comm-system-target-architecture` · **План:** `plans/comm-system-target-architecture.md`

Сессия по реализации P0 плана comm-system. Главная незакрытая задача — **live-телеметрия процессов** (вкладка «Processes» показывает «—»).

---

## Закоммичено (6 коммитов, всё с тестами)

| Commit | Что |
|---|---|
| `57c156cb` | план comm-system + REVIEW + evidence + COMMUNICATION_ARCHITECTURE.md |
| `bc7fc6c6` | robor.lua → .gitignore (чужой файл) |
| `41cf496a` | §11 п.1 — удалён shadow `bridge.py` (import-smoke ✅) |
| `1343d48f` | §11 п.10 — console help (итерация по List[Dict], 105 тестов) |
| `d684387a` | §9.7 — StatsManager dead-wire убран (77 тестов) |
| `e369e2b9` | **backend-control universal**: адаптер `reply_to=<host>` + `backend_ctl/telemetry_probe.py` (192 теста) |

## В дереве (UNCOMMITTED)
- `multiprocess_prototype/orchestrator.py` — телеметрия-фикс (wrapped re-sync). **ПРИМЕНЁН, НО НЕ ПОМОГ** (см. ниже). Решить: оставить/откатить после диагностики.
- `multiprocess_framework/modules/logger_module/core/logger_manager.py` — **частичный M5** (TeamLead-агент упал; удалён `_route_via_router`, но остались мёртвые `router_manager`/`enable_router_routing`/`messages_routed`). M5 нужно доделать целиком (4 файла: logger_manager + error_manager + logger_adapter + process_managers).

---

## 🎉 Что построено и работает: backend-control как headless-харнесс

**Видение владельца:** backend-control должен дублировать всю коммуникацию + сигналы GUI, чтобы тестировать бэкенд **без GUI**. Это работает:
- `backend_ctl/driver.py` (`BackendDriver`) — TCP-клиент к SocketChannel (`reply_to=ProcessManager` по дефолту), request/reply, обёртки `introspect_handlers/status/registers`, `set_register`, `send_command`.
- Адаптер-фикс (`socket_bridge_adapter.py`, committed): подставляет `reply_to=<host>` → request/reply работает для ЛЮБОГО драйвера, даже без явного reply_to.
- **`backend_ctl/telemetry_probe.py`** — headless-диагностика: `BACKEND_CTL=1 python -m backend_ctl.telemetry_probe`. Поднимает систему через `bootstrap()`, шлёт introspect/state.* через driver, гасит PID-specific.
- Запуск headless: `from multiprocess_prototype.main import bootstrap; l=bootstrap(); l.start(); l.wait_until_ready(30); ...; l.shutdown()`.
- Запуск GUI с qt-mcp: `QT_MCP_PROBE=1 BACKEND_CTL=1 INSPECTOR_AUTH_DEV_AUTO_LOGIN=1 python multiprocess_prototype/run.py` → qt-mcp probe на localhost:9142. Авто-логин dev/admin.

**Расширить (видение, todo):** добавить `BackendDriver` приём **push** (unsolicited state.changed/логи/события — сейчас `_dispatch` матчит только ответы по request_id, строка ~167). Тогда driver полностью реплицирует GUI-подписку. Это P1.5b из `plans/2026-05-31_backend-control-mcp/HANDOFF.md`.

---

## 🔴 ГЛАВНАЯ ЗАГАДКА (нерешена) — телеметрия

### Симптом
GUI вкладка «Processes»: «Всего: 5, **Активно: 0, Средний FPS: —**», карточки camera_0 → «FPS: —». При этом **кадры идут** (верхний FPS 22 — frame-путь работает, это НЕ state-телеметрия).

### Что выяснил probe'ом (ground truth, headless)
1. **`state.subscribe` ЕСТЬ в `message_dispatcher` ProcessManager** (introspect.handlers вернул 46 хендлеров, включая state.*). Регистрация ОК.
2. **`introspect.handlers`/`introspect.status` (к ProcessManager) → success=True** (отвечают).
3. **`state.subscribe` и `state.get` (к ProcessManager) → success=False (TIMEOUT)**.

### Загадка
`introspect.*` и `state.*` — **оба** wrapped (через `register_commands_with_router` → `_make_command_handler` → `cm.handle_command` + `reply_to_request`), **оба** к ProcessManager. Но introspect отвечает, а state.* — timeout. **Различие специфично для `state.*`-хендлеров, НЕ в RAW-vs-wrapped** (я менял orchestrator с RAW `register_message_handlers` на wrapped `register_commands_with_router` — НЕ помогло, state.* всё равно timeout).

### Следующий шаг — ИНСТРУМЕНТАЦИЯ (плана «DEBUG в 3 точках»)
Рассуждением не решить. Добавить временные DEBUG-print (или INFO) и прогнать `telemetry_probe`:
1. **`handle_state_subscribe`** (`state_store_manager.py:276`) — печатать на ВХОДЕ (вызывается ли вообще?) и на ВЫХОДЕ (что возвращает).
2. **`_make_command_handler._handler`** (`process_lifecycle.py:144`) — для key=`state.subscribe`: печатать result + вызывается ли `reply_to_request` + что вернул.
3. **`reply_to_request`** (`router_manager.py:410`) — печатать cid, reply_target, отправлен ли ответ.
4. Также добавить в `telemetry_probe` печать СЫРОГО ответа (`drv.request` возвращает result; при timeout — `{success:False,error:timeout}`).

**Гипотезы для проверки:**
- (a) `handle_state_subscribe` НЕ вызывается через cm.handle_command (несовпадение сигнатуры `handler(self, msg)` vs как CommandManager передаёт args — data vs full msg; `expects_full_message`)? → проверить как CommandManager.handle_command зовёт хендлеры state.* (зарегистрированы БЕЗ expects_full_message в `StateStoreManager.register_commands`).
- (b) `handle_state_subscribe` вызывается и возвращает, но `reply_to_request` для state.* теряет ответ (роутинг reply в system-очередь ProcessManager не резолвит pending адаптера)?
- (c) state.* reply перехватывается/потребляется до резолва (напр. self-resolve guard `router_manager.py:503` — но он только для type=response)?

### ВАЖНО ещё не проверено
- **Публикует ли `ProcessMonitor` телеметрию `processes.*`?** `state.get(processes)` тоже timeout (та же загадка) → не смог прочитать дерево. Как почините state.get reply — сразу видно: есть данные → backend ОК, баг в доставке дельт gui; пусто → ProcessMonitor не публикует (`process_monitor.py:178 _publish_state` → `ssm.handle_state_set` локально).
- **Работает ли GUI-телеметрия СЕЙЧАС?** Последний qt-mcp тест (с RAW-фиксом) показал «—». С wrapped-фиксом GUI НЕ перепроверял. Перепроверить: запустить GUI (команда выше) → qt-mcp `currentIndex=2` на QTabWidget → screenshot вкладки Processes → живые числа vs «—». Память `feedback_qt_mcp_smoke_verification`.

---

## Контекст по диспетчеризации (важно для понимания)
- Входящие IPC `type=command` диспатчатся ТОЛЬКО через `router.message_dispatcher` (`system_threads.py:88`). Команды только в CommandManager «молча дропаются».
- `register_commands_with_router` (`process_lifecycle.py:104`) синкает ВСЕ команды CommandManager в message_dispatcher (wrapped с reply). Зовётся в `ProcessModule.initialize:155` (до state.* — те регистрируются в `_setup_state_store` ПОЗЖЕ, на `process_manager_process.py:162`) И в `run():607` (после builtins).
- `register_message_handler` оставляет ПЕРВУЮ регистрацию (verified: мой RAW на :162 не перетирался re-sync'ом в run()).
- Оркестратор = `multiprocess_prototype/orchestrator.py::ProcessManagerProcessApp` (имя процесса «ProcessManager», логирует в stdout, отдельной папки логов НЕТ; per-process логи детей — `logs/prototype_2/<name>/`).

## Память (релевантно)
`project_telemetry_subscription_bug` (исходный диагноз — частично устарел: state.subscribe ТЕПЕРЬ в dispatcher), `project_backend_control_mcp`, `feedback_qt_mcp_smoke_verification`, `feedback_no_global_taskkill` (стоп прототипа только PID-specific!), `project_priority_product_over_engine`.

## Остаток P0 (после телеметрии)
M5 целиком · §11 quick-wins (п.2/3/4/11/13/14/16-19) · потеря сообщений (п.20-22, критичный `_route_to_worker`) · RolesPanel/get_field (п.5/6).
