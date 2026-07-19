# backend_ctl — инструкция для агентов

Как агенту **отлаживать живой бэкенд без GUI и без qt-mcp**: целиться в любой процесс
по имени, слать router-команды, читать состояние, делать live-запись регистров.

`backend_ctl.BackendDriver` — тонкий TCP-клиент к `SocketChannel` хоста (ProcessManager).
Шлёт **те же** router-сообщения, что GUI через `CommandSender`. Driver = «GUI по сокету».

> **Статус:** MCP-обёртка (P3, Ф1 Task 1.7) **готова** — сервер `backend-ctl`
> ([`mcp_server.py`](mcp_server.py), stdio, без SDK-зависимостей). Имена инструментов
> зеркалят методы driver: `mcp__backend-ctl__capabilities` / `get_status` /
> `introspect_handlers` / `send_command` / `set_register` / `state_get` / `log_tail` /
> `events_page` / … Если инструменты доступны в сессии — используй их вместо Bash-сниппетов.
> Включение: плагин `mcp-backend-ctl` (`.claude/plugins/mcp-backend-ctl/`) в
> `.claude/enabled.yaml` (или запись `backend-ctl` в `.mcp.json`:
> `.venv/bin/python -m backend_ctl.mcp_server`). Бэкенд поднимается отдельно (`BACKEND_CTL=1`).

## Когда использовать (routing)

| Задача | Инструмент |
|--------|-----------|
| «Что умеет процесс? есть ли приёмник команды/регистра?» | **backend_ctl** (`introspect_*`) |
| «Применить параметр в живой процесс (live field-write)» | **backend_ctl** (`set_register`) |
| «Запустить/остановить процесс, послать system-команду» | **backend_ctl** (`system_command`) |
| «Проверить что GUI-кнопка реально дергает бэкенд» | сперва backend_ctl (доказать backend-путь), потом qt-mcp (GUI-путь) |
| «Что пользователь нажал в GUI?» (события кнопок/табов агенту) | **backend_ctl** (`ui_tap` → события `ui.event` в `events_page(plane="ui")`) |
| Состояние **виджетов**, клики, снимок UI | qt-mcp (`QT_MCP_PROBE=1`) — НЕ backend_ctl |
| Поиск/рефакторинг исходников | qex / Serena / Grep — driver видит только runtime |

## Режимы отладки (бэкенд / фронтенд / совместно)

| Режим | Как | Что видно |
|-------|-----|-----------|
| **Бэкенд отдельно** (headless, без Qt) | `BackendHarness` в тестах или `BACKEND_CTL=1` + strip_gui | introspect/state/логи/регистры — весь этот файл |
| **Фронтенд** (GUI поднят) | полный запуск `BACKEND_CTL=1 python run.py` → `drv.ui_tap("gui")` | нажатия кнопок и переключения табов приходят агенту событиями `ui.event` (`data.record`: kind/text/path/ts); смоук цепочки без клика — `drv.ui_tap_ping("gui")`; инспекция/клики виджетов — qt-mcp (`QT_MCP_PROBE=1`) |
| **Совместно** (корреляция UI ↔ бэкенд) | **`drv.debug_session()` — одна кнопка**: ui_tap (жесты+команды GUI) + log_tail на все процессы + state_subscribe; выключение — `debug_stop()` | единый событийный поток с ts/seq: «клик (ui.event kind=button, seq=41) → команда GUI→бэкенд (kind=command, seq=42) → log.record → state.changed» — разрыв между уровнями локализует баг |

**Киллер-фича:** `introspect_handlers(process)` за секунду ловит баг «нет приёмника»
(команда есть в `CommandManager`, но не в router `message_dispatcher`, или у плагина нет
worker-side обработчика регистра) — без единого клика в GUI.

## Предусловия

1. Система должна **работать** с открытым гейтом сокета. По умолчанию гейт уже открыт:
   [`backend/config/system.yaml`](../multiprocess_prototype/backend/config/system.yaml) →
   `backend_ctl.enabled: true`, `port: 8765`, `host: 127.0.0.1`.
   Escape-hatch без правки yaml: `BACKEND_CTL=1 [BACKEND_CTL_PORT=9001] python run.py`.
2. Запуск системы в фоне (НЕ блокировать сессию), из корня репозитория:
   ```bash
   python multiprocess_prototype/run.py     # run_in_background: true
   ```
   Дать ~6-8 c на старт. Останавливать — **только** через TaskStop по task_id
   (НЕ `taskkill /IM python.exe` — это убьёт чужие процессы).

## Канонический рецепт (Bash + Python)

Driver — синхронный, контекст-менеджер сам connect/close. Запускать одним сниппетом:

```bash
# из корня репозитория:
python - <<'PY'
from backend_ctl import BackendDriver
with BackendDriver(port=8765) as drv:
    print("HANDLERS:", drv.introspect_handlers("preprocessor"))
    print("REGISTERS:", drv.introspect_registers("preprocessor"))
    print("STATUS:", drv.introspect_status("preprocessor"))
PY
```

## Шпаргалка API

| Метод | Назначение |
|-------|-----------|
| `system_overview(timeout=)` | **B.3, первая команда сессии**: компактная сводка всех процессов (статус/воркеры/router/очереди/память) + telemetry fps + счётчики driver'а + `anomalies`-подсказки (router_dropped, queue_depth, fps_zero_while_running, recent_recovery, late_replies, events_evicted, …) |
| `introspect_handlers(process)` | ключи router `message_dispatcher` + команды `CommandManager` |
| `introspect_registers(process)` | имена регистров + поля (**пусто = нет worker-side приёмника**) |
| `introspect_status(process)` / `get_status(process)` | имя, воркеры, состояние процесса |
| `router_stats(p)` / `queues(p)` / `worker_status(p)` | типизированно (dataclass + `.raw`): счётчики router'а / глубины очередей / статус воркеров |
| `capabilities()` / `introspect_capabilities(p)` | «контактная книжка»: свод команд/регистров/каналов по всем процессам (или карточка одного). MCP-инструмент принимает `format="concise"` (только имена, кратно дешевле) / `"help"` (пример вызова + какое push-событие в какую плоскость + корреляционные ключи) / `"detailed"` (дефолт) и `process`-фильтр (B.4) |
| `set_register(process, register, field, value)` | live-запись регистра (`register_update`, ключи `{register, field, value}`) |
| `set_register_verified(process, register, field, value)` | verify-probe (Ф1.6): write → readback `introspect.registers` → diff (`verified`/`expected`/`actual`) — ловит молчаливые no-op'ы |
| `send_command(target, command, args=None)` | прямая команда процессу (форма `CommandSender.send_command`) |
| `system_command({"cmd": ..., ...})` | system-команда в ProcessManager (`process.start`/`stop`/`worker.*`/…) |
| `state_subscribe(pattern)` | подписка на state-дерево; пуши `state.changed` → событийный канал |
| `ui_tap("gui")` / `ui_untap("gui")` | подписка на UI-события gui: жесты (kind=button/tab) И намерения — команды GUI→бэкенд через перехват двери CommandSender (kind=command/system_command) → пуши `ui.event` (общий seq) |
| `ui_tap_ping("gui", note=...)` | синтетическое `ui.event` тем же путём доставки — проверка цепочки без клика |
| `debug_session(logs_level=, state_pattern=, log_processes=)` / `debug_stop()` | ВСЯ отладочная плоскость одним вызовом: ui_tap + log_tail (по умолчанию на все процессы топологии) + state_subscribe; дизайн — `plans/2026-07-06_constructor-master/debug-plane-idea.md` |
| `events_page(plane=, cursor=, limit=)` | **B.1**: курсорное НЕдеструктивное чтение событий по плоскостям (`state`/`logs`/`errors`/`stats`/`telemetry`/`ui`/`other`/`all`); ответ `{items[{seq,event}], next_cursor, dropped, bookmark}` — несколько читателей не мешают друг другу, потеря из кольца видна в `dropped`, `bookmark` = «читать только новое» |
| `await_condition(kind, spec, timeout=)` | **B.2**: серверное ожидание вместо поллинга — `state_path` (`{path, value}` в read-model), `event_matches` (`{plane, pattern}` glob по command/path), `metric_threshold` (`{path, op, value}`); таймаут возвращает диагноз (`waited`/`last_seen`/`events_seen`), не пустоту; требует активной подписки (watch_like_gui/state_subscribe) |
| `subscribe(cb)` / `events(timeout)` | событийный канал: колбэк на каждый push; `events` — **устаревший** деструктивный дренаж (крадёт события у параллельных читателей; удаление в F.1) — используй `events_page` |
| `events_stats()` | счётчики hub'а: per-plane seq/размер/вытеснено |
| `telemetry_set(process, metric, enabled=, interval_sec=, plane=)` | **точечно** поменять ОДНУ метрику/правило телеметрии (merge — соседей не сносит); `plane="publisher"` (частота публикации) или `"throttle"` (central rate-limit) |
| `telemetry_reconfigure(process="all", publish=, throttle=, mode=)` | секцией: publisher-gate и/или central-троттл; `mode="replace"` (дефолт) применяет ЦЕЛИКОМ (**wipe** неуказанных) — для одной метрики предпочитай `telemetry_set` |
| `telemetry_snapshot(process=None, metric=None)` | **локальный** снимок телеметрии (0 IPC): read-model поверх `state.changed`; наполняется после `watch_like_gui`; фильтр по процессу/суффиксу метрики + ключ process/worker |
| `telemetry_history(path, limit=None)` | **локальная** история метрики (спарклайн без БД): кольцевой буфер (fps/latency_ms/uptime/effective_hz/cycle_duration_ms) |
| `observability_tail(process)` / `observability_untail(process)` | live ЛОГИ+ОШИБКИ+СТАТИСТИКА процесса (то, что GUI получает через `ObservabilityTailActivator`); записи по плоскостям — `observability_records(kind=)` |
| `watch_like_gui()` / `unwatch()` | ВЕСЬ приёмный профиль GUI одной командой: state.subscribe (processes/system/devices/calibration) + observability.tail на все процессы + **авто-переподписка** после авто-рестарта |
| `introspect_memory(process)` | инвентарь памяти (SHM/пул займов/очереди) — только статистика; секции best-effort (`null`, не ошибка) |
| `request(message, timeout=None)` | низкоуровневый: готовый router-dict → ответ по `request_id` |

Все обёртки возвращают `result` из ответа, либо `{"success": False, "error": "timeout"/"not connected"/...}`.
Все имена доступны как MCP-инструменты (полный каталог — `tools/list`).
После реконнекта MCP-сервера подписки (`state_subscribe`/`log_tail`/`ui_tap`/`watch`) восстанавливаются автоматически (Task 0.3/F2).

**Safety-режимы MCP-сервера** (Phase 3, флаги сервера или env `BACKEND_CTL_MCP_MODE`):
`--read-only` — только чтение+подписки (write/escalated скрыты и блокируются;
`send_command` пропускает лишь `introspect.*`/`state.get*`); `--disable-destructive` —
блок разрушающих. Инструменты несут annotations (`readOnlyHint`/`destructiveHint`).
Неизвестный инструмент → подсказка ближайших имён; блок → список доступных.

**Мультиклиент (D.2, streamable-HTTP):** `python -m backend_ctl.mcp_server_sdk --http`
[`--http-bind 127.0.0.1:8901`] — несколько агентов на одной живой системе одновременно
(каждая MCP-сессия = свой driver/сокет/`session`, изоляция поверх D.1a; завершение сессии
снимает её подписки). **Требует бэкенд с `session_isolation=ON`** (`BACKEND_CTL_SESSION_ISOLATION=1`)
— иначе fail-fast отказ. Safety-режим per-server (нужны разные — два инстанса на разных портах).
Дефолт остаётся stdio. Детали — [`DECISIONS.md`](DECISIONS.md) BCTL-ADR-005, [`README.md`](README.md).

### Примеры

```python
# Live field-write: применить параметр плагина в работающий процесс
drv.set_register_verified("preprocessor", "resize", "target_width", 640)

# Управление жизненным циклом процесса
drv.system_command({"cmd": "process.start", "process_name": "camera"})
drv.system_command({"cmd": "process.stop",  "process_name": "camera"})

# Управление воркерами процесса (worker.* команды процесса-владельца)
drv.send_command("camera", "worker.stop",  {"worker_name": "grabber"})
drv.send_command("camera", "worker.start", {"worker_name": "grabber"})
```

### Диагностика «нет приёмника» (Этап 2 proof)

```python
h = drv.introspect_handlers("preprocessor")
# если "register_update" ОТСУТСТВУЕТ в router-handlers → у плагина нет worker-side
# приёмника: GUI/driver шлёт, но никто не читает. Диагноз без GUI.
```

## Тесты против живого бэкенда (headless)

Нужен живой бэкенд в тесте — используй `BackendHarness` (headless, без GUI, с
гарантированным teardown), не поднимай прототип вручную:

```python
from backend_ctl.harness import BackendHarness
with BackendHarness(with_base=True) as drv:      # старт → driver → гарантированный стоп
    print(drv.worker_status("preprocessor").status)
```

Или фикстура `headless_backend`. Прогон: `python -m pytest backend_ctl -m harness_smoke`.

> Регресс 1.1 ЗАКРЫТ (Ф1.1b): push `state.changed` доходит до внешнего сокет-driver'а
> через мост push→канал в `RouterManager._deliver_by_targets` (у не-процесса нет
> очереди → доставка через одноимённый `SocketChannel`).

## Подводные камни

- **`request()` нельзя звать из приёмного потока бэкенда** (дедлок, контракт P0.5). Агенту
  это не грозит: driver — внешний процесс, его запросы идут через сокет.
- **ProcessManager — отдельный OS-процесс.** Дотянуться до процесса можно только через
  «дверь» (SocketChannel в PM); без запущенной системы driver вернёт `not connected`.
- **Таймаут = не баг по умолчанию.** `{"error": "timeout"}` часто значит «нет приёмника /
  процесс не отвечает» — это сам по себе диагностический результат.
- **Только localhost, без аутентификации** — dev-инструмент. В проде гейт `enabled: false`.
- **Кадры/SHM через сокет НЕ гоняем** (Dict at Boundary) — только команды/состояние.

## Связанное

- **«Контактная книжка» — ЧИТАЙ ПЕРВОЙ:** [`docs/contracts/CAPABILITIES.md`](../docs/contracts/CAPABILITIES.md)
  — полный каталог команд (с описаниями), регистров и каналов всех процессов; генерируется
  из runtime (`python -m backend_ctl.dump_capabilities`), исходники читать не нужно.
  Runtime-эквивалент: `drv.capabilities()`.
- Dev-README (устройство, запуск): [`backend_ctl/README.md`](README.md)
- Готовый прогон-пример: [`backend_ctl/smoke_proof.py`](smoke_proof.py)
- Driver: [`backend_ctl/driver.py`](driver.py)
- Поднятие endpoint: [`process_manager_module/process/backend_ctl_endpoint.py`](../multiprocess_framework/modules/process_manager_module/process/backend_ctl_endpoint.py)
- MCP-сервер: [`backend_ctl/mcp_server.py`](mcp_server.py) (stdio JSON-RPC), инструменты: [`backend_ctl/mcp_tools.py`](mcp_tools.py)
- План/статус: [`plans/_archive/2026-05-31_backend-control-mcp/`](../plans/_archive/2026-05-31_backend-control-mcp/) (P3 закрыт Ф1 Task 1.7, см. `plans/2026-07-06_constructor-master/plan.md`)
- ADR-RTR-008 (request-response в RouterManager)
```
