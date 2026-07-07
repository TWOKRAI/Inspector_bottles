# backend_ctl — инструкция для агентов

Как агенту **отлаживать живой бэкенд без GUI и без qt-mcp**: целиться в любой процесс
по имени, слать router-команды, читать состояние, делать live-запись регистров.

`backend_ctl.BackendDriver` — тонкий TCP-клиент к `SocketChannel` хоста (ProcessManager).
Шлёт **те же** router-сообщения, что GUI через `CommandSender`. Driver = «GUI по сокету».

> **Статус:** MCP-обёртка (P3, Ф1 Task 1.7) **готова** — сервер `backend-ctl`
> ([`mcp_server.py`](mcp_server.py), stdio, без SDK-зависимостей). Имена инструментов
> зеркалят методы driver: `mcp__backend-ctl__capabilities` / `get_status` /
> `introspect_handlers` / `send_command` / `set_register` / `state_get` / `log_tail` /
> `events` / … Если инструменты доступны в сессии — используй их вместо Bash-сниппетов.
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
| «Что пользователь нажал в GUI?» (события кнопок/табов агенту) | **backend_ctl** (`ui_tap` → события `ui.event` в `events`) |
| Состояние **виджетов**, клики, снимок UI | qt-mcp (`QT_MCP_PROBE=1`) — НЕ backend_ctl |
| Поиск/рефакторинг исходников | qex / Serena / Grep — driver видит только runtime |

## Режимы отладки (бэкенд / фронтенд / совместно)

| Режим | Как | Что видно |
|-------|-----|-----------|
| **Бэкенд отдельно** (headless, без Qt) | `BackendHarness` в тестах или `BACKEND_CTL=1` + strip_gui | introspect/state/логи/регистры — весь этот файл |
| **Фронтенд** (GUI поднят) | полный запуск `BACKEND_CTL=1 python run.py` → `drv.ui_tap("gui")` | нажатия кнопок и переключения табов приходят агенту событиями `ui.event` (`data.record`: kind/text/path/ts); смоук цепочки без клика — `drv.ui_tap_ping("gui")`; инспекция/клики виджетов — qt-mcp (`QT_MCP_PROBE=1`) |
| **Совместно** (корреляция UI ↔ бэкенд) | один driver: `ui_tap("gui")` + `log_tail(процесс)` + `state_subscribe("**")` | единый событийный поток с ts: «кнопка → команда → лог → state-дельта» — видно, чем ответил бэкенд на клик |

**Киллер-фича:** `introspect_handlers(process)` за секунду ловит баг «нет приёмника»
(команда есть в `CommandManager`, но не в router `message_dispatcher`, или у плагина нет
worker-side обработчика регистра) — без единого клика в GUI.

## Предусловия

1. Система должна **работать** с открытым гейтом сокета. По умолчанию гейт уже открыт:
   [`backend/config/system.yaml`](../multiprocess_prototype/backend/config/system.yaml) →
   `backend_ctl.enabled: true`, `port: 8765`, `host: 127.0.0.1`.
   Escape-hatch без правки yaml: `BACKEND_CTL=1 [BACKEND_CTL_PORT=9001] python run.py`.
2. Запуск системы в фоне (НЕ блокировать сессию):
   ```bash
   cd "d:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles"
   python multiprocess_prototype/run.py     # run_in_background: true
   ```
   Дать ~6-8 c на старт. Останавливать — **только** через TaskStop по task_id
   (НЕ `taskkill /IM python.exe` — это убьёт чужие процессы).

## Канонический рецепт (Bash + Python)

Driver — синхронный, контекст-менеджер сам connect/close. Запускать одним сниппетом:

```bash
cd "d:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles" && python - <<'PY'
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
| `introspect_handlers(process)` | ключи router `message_dispatcher` + команды `CommandManager` |
| `introspect_registers(process)` | имена регистров + поля (**пусто = нет worker-side приёмника**) |
| `introspect_status(process)` / `get_status(process)` | имя, воркеры, состояние процесса |
| `router_stats(p)` / `queues(p)` / `worker_status(p)` | типизированно (dataclass + `.raw`): счётчики router'а / глубины очередей / статус воркеров |
| `capabilities()` / `introspect_capabilities(p)` | «контактная книжка»: свод команд/регистров/каналов по всем процессам (или карточка одного) |
| `set_register(process, register, field, value)` | live-запись регистра (`register_update`, ключи `{register, field, value}`) |
| `set_register_verified(process, register, field, value)` | verify-probe (Ф1.6): write → readback `introspect.registers` → diff (`verified`/`expected`/`actual`) — ловит молчаливые no-op'ы |
| `send_command(target, command, args=None)` | прямая команда процессу (форма `CommandSender.send_command`) |
| `system_command({"cmd": ..., ...})` | system-команда в ProcessManager (`process.start`/`stop`/`worker.*`/…) |
| `state_subscribe(pattern)` | подписка на state-дерево; пуши `state.changed` → событийный канал |
| `ui_tap("gui")` / `ui_untap("gui")` | подписка на UI-события gui (кнопки/табы) → пуши `ui.event` в событийный канал |
| `ui_tap_ping("gui", note=...)` | синтетическое `ui.event` тем же путём доставки — проверка цепочки без клика |
| `subscribe(cb)` / `events(timeout)` | событийный канал: колбэк или слив накопленных push-событий |
| `request(message, timeout=None)` | низкоуровневый: готовый router-dict → ответ по `request_id` |

Все обёртки возвращают `result` из ответа, либо `{"success": False, "error": "timeout"/"not connected"/...}`.

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
