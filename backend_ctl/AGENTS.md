# backend_ctl — инструкция для агентов

Как агенту **отлаживать живой бэкенд без GUI и без qt-mcp**: целиться в любой процесс
по имени, слать router-команды, читать состояние, делать live-запись регистров.

`backend_ctl.BackendDriver` — тонкий TCP-клиент к `SocketChannel` хоста (ProcessManager).
Шлёт **те же** router-сообщения, что GUI через `CommandSender`. Driver = «GUI по сокету».

> **Статус:** MCP-обёртка (P3) ещё не готова — отдельного `mcp__backend_ctl__*` инструмента
> НЕТ. Пока driver вызывается через Bash + Python-сниппет (см. ниже). Когда появится
> MCP-сервер, имена инструментов будут зеркалить методы driver (`introspect_status`/
> `set_register`/…).

## Когда использовать (routing)

| Задача | Инструмент |
|--------|-----------|
| «Что умеет процесс? есть ли приёмник команды/регистра?» | **backend_ctl** (`introspect_*`) |
| «Применить параметр в живой процесс (live field-write)» | **backend_ctl** (`set_register`) |
| «Запустить/остановить процесс, послать system-команду» | **backend_ctl** (`system_command`) |
| «Проверить что GUI-кнопка реально дергает бэкенд» | сперва backend_ctl (доказать backend-путь), потом qt-mcp (GUI-путь) |
| Состояние **виджетов**, клики, снимок UI | qt-mcp (`QT_MCP_PROBE=1`) — НЕ backend_ctl |
| Поиск/рефакторинг исходников | qex / Serena / Grep — driver видит только runtime |

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
| `set_register(process, plugin, field, value)` | live-запись регистра (`register_update`) |
| `send_command(target, command, args=None)` | прямая команда процессу (форма `CommandSender.send_command`) |
| `system_command({"cmd": ..., ...})` | system-команда в ProcessManager (`process.start`/`stop`/`worker.*`/…) |
| `request(message, timeout=None)` | низкоуровневый: готовый router-dict → ответ по `request_id` |

Все обёртки возвращают `result` из ответа, либо `{"success": False, "error": "timeout"/"not connected"/...}`.

### Примеры

```python
# Live field-write: применить параметр плагина в работающий процесс
drv.set_register("preprocessor", "resize", "width", 640)

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

- Dev-README (устройство, запуск): [`backend_ctl/README.md`](README.md)
- Готовый прогон-пример: [`backend_ctl/smoke_proof.py`](smoke_proof.py)
- Driver: [`backend_ctl/driver.py`](driver.py)
- Поднятие endpoint: [`process_manager_module/process/backend_ctl_endpoint.py`](../multiprocess_framework/modules/process_manager_module/process/backend_ctl_endpoint.py)
- План/статус: [`plans/2026-05-31_backend-control-mcp/`](../plans/2026-05-31_backend-control-mcp/) (P3 = MCP-обёртка, ещё не сделана)
- ADR-RTR-008 (request-response в RouterManager)
```
