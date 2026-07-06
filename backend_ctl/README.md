# backend_ctl — headless driver управления бэкендом (dev-инструмент)

> 🤖 **Агентам:** инструкция по использованию — [`AGENTS.md`](AGENTS.md) (когда звать,
> рецепт Bash+Python, диагностика «нет приёмника»). Этот README — про устройство.

Тонкий внешний клиент к работающей системе: подключается по TCP к `SocketChannel`
хоста (ProcessManager) и шлёт **те же** router-сообщения, что GUI через `CommandSender`.
Назначение — отлаживать бэкенд напрямую (целиться в процессы, слать команды, читать
состояние) без GUI и без qt-mcp. Промежуточный слой под MCP-обёртку (P3).

> **Инвариант:** всё общение с бэкендом — строго через `RouterManager`. Сокет делает
> только байтовый I/O на границе Claude↔driver. Driver = «GUI по сокету».
> Кадры/SHM через сокет НЕ гоняем (Dict at Boundary).

## Как это устроено

```
backend_ctl.BackendDriver ──TCP(newline-JSON)──► SocketChannel (в ProcessManager)
        │                                              │ on_inbound
        │                                       router.request(msg)   ← P0.5
        │                                              │ _deliver_by_targets
        │                                       любой процесс системы
        │                                              │ reply_to_request
        │                                       router.send(channel="backend_ctl")
        ◄──────────── ответ по request_id ◄───────────┘ SocketChannel.send
```

Одна «дверь» в хабе (ProcessManager) — через неё дотягиваешься до **любого** процесса
по имени (`targets=[process]`). Канал-в-каждом-процессе не нужен.

## Запуск

1. Поднять систему с открытым гейтом. **Два способа** (OR):

   **(a) Через `system.yaml` (основной для dev-прототипа)** —
   `multiprocess_prototype/backend/config/system.yaml`:
   ```yaml
   backend_ctl:
     enabled: true      # сокет поднимается всегда при старте
     port: 8765
     host: "127.0.0.1"
   ```

   **(b) Через env (escape-hatch для тестов/CI, без правки yaml):**
   ```bash
   BACKEND_CTL=1 python run.py            # порт по умолчанию 8765
   BACKEND_CTL=1 BACKEND_CTL_PORT=9001 python run.py
   ```
   Приоритет: гейт открыт если `backend_ctl.enabled` **ИЛИ** `BACKEND_CTL=1`.
   Порт: `BACKEND_CTL_PORT` (env) > `backend_ctl.port` (yaml) > 8765.
   В проде держать `enabled: false` и не выставлять env.

2. Подключиться драйвером:
   ```python
   from backend_ctl import BackendDriver

   with BackendDriver(port=8765) as drv:          # connect/close через контекст
       print(drv.introspect_handlers("preprocessor"))   # что умеет процесс
       print(drv.introspect_registers("preprocessor"))  # регистры (пусто = нет приёмника)
       drv.set_register("preprocessor", "resize", "width", 640)   # live field-write
       print(drv.system_command({"cmd": "process.start", "process_name": "camera"}))
   ```

## API (обёртки поверх общего билдера протокола)

| Метод | Что делает |
|-------|-----------|
| `send_command(target, command, args=None)` | прямая команда процессу (форма `CommandSender.send_command`) |
| `system_command(command)` | system-команда в ProcessManager (`process.command`-обёртка) |
| `introspect_handlers(process)` | ключи `message_dispatcher` + команды `CommandManager` |
| `introspect_registers(process)` | имена регистров + поля (пусто = нет worker-side приёмника) |
| `introspect_status(process)` / `get_status(process)` | имя, воркеры, состояние процесса |
| `introspect_router_stats(process)` / `introspect_queues(process)` | сырой dict: счётчики router'а / глубины очередей |
| `router_stats(process)` → `RouterStats` | типизированно: `sent_ok`/`received`/`middleware_dropped`/`errors` (+ `.raw`) |
| `queues(process)` → `QueueDepths` | типизированно: `sizes={тип: глубина\|None}` (+ `.raw`) |
| `worker_status(process)` → `WorkerStatus` | типизированно: `process`/`status`/`workers` (+ `.raw`) |
| `set_register(process, plugin, field, value)` | live-запись регистра (`register_update`) |
| `state_subscribe(pattern, subscriber=None)` | подписка на state-дерево (`state.subscribe`); пуши `state.changed` идут в событийный канал |
| `subscribe(callback)` / `unsubscribe(callback)` | колбэк на каждое push-событие (зовётся в reader-потоке) |
| `events(timeout=0.0, max_items=None)` | слить накопленные события (0=поллинг, >0=ждать до timeout, None=до события/close) |
| `request(message, timeout=None)` | низкоуровневый: готовый router-dict → ответ по `request_id` |

Все обёртки возвращают `result` из ответа (или `{"success": False, "error": ...}` при
таймауте/обрыве). Сообщения строятся `message_module.build_command_message` /
`build_system_command_message` — один источник правды с GUI.

### Событийный канал (push без reply)

Reply-путь матчит ответы по `request_id`. Push-сообщения **без** `request_id` (или
не матчащие ни один pending) — например `state.changed` — не дропаются, а идут в
**bounded-очередь** (deque `maxlen=event_queue_maxlen`, по умолчанию 1000; старые
вытесняются, не течёт) и синхронно рассылаются подписчикам. Reader-поток пишет,
клиентский поток читает через `events()`/`subscribe()` (thread-safe). Исключение
колбёка не роняет reader-поток (глотается, виден в `driver.event_errors`).

```python
with BackendDriver(port=8765) as drv:
    got = []
    drv.subscribe(got.append)                 # синхронный колбэк на каждое событие
    drv.state_subscribe("processes.**")        # подписка → сервер шлёт state.changed
    for evt in drv.events(timeout=2.0):        # либо поллинг накопленного
        print(evt["command"], evt["data"])
```

### Типизированные обёртки (Ф1 Task 1.2)

`router_stats()`/`queues()`/`worker_status()` возвращают dataclass'ы (`RouterStats`/
`QueueDepths`/`WorkerStatus`) — форма, а не логика: сырой introspect-ответ приводится к
явным полям, сырой dict всегда лежит в `.raw` (ничего не теряется). Отдельной
`introspect.wire`-команды в системе НЕТ (есть только `wire.configure`/`deconfigure` —
это действия), поэтому `wire_status()` не вводится.

```python
with BackendDriver(port=8765) as drv:
    rs = drv.router_stats("preprocessor")   # RouterStats(sent_ok=10, received=21, ...)
    print(rs.sent_ok, rs.middleware_dropped, rs.errors)
    print(drv.queues("preprocessor").sizes)          # {'system': None, 'data': 3}
    print(drv.worker_status("preprocessor").status)  # 'running'
```

## Тесты и headless-harness (Ф1 Task 1.3)

`backend_ctl/harness.py::BackendHarness` — pytest-инструмент headless-запуска прототипа
**без GUI** с гарантированным teardown (никаких висящих процессов — урок Ф0.4):

- **Честный headless:** процесс презентации (`gui`) исключается из топологии функцией
  `strip_gui()` ДО сборки `SystemBuilder` — Qt/LoginDialog не спавнится. Прод-код не
  трогается: harness собирает launcher из тех же публичных помощников прототипа.
- **Гарантированный teardown:** `stop()` зовёт `launcher.shutdown()` в watchdog-потоке с
  таймаутом и добивает поддерево **своего** оркестратора (scoped по pid — чужой бэкенд не
  трогает). Переживает зависший shutdown.

```bash
python -m pytest backend_ctl -m harness_smoke   # live: старт → introspect → стоп (<30с)
python -m pytest backend_ctl -q                 # весь модуль (быстрые + harness)
```

Фикстура `headless_backend` (session-scope, `backend_ctl/tests/conftest.py`) отдаёт
подключённый `BackendDriver` к headless-системе.

> **Известное ограничение (регресс 1.1, xfail):** `state_subscribe(...)` → push
> `state.changed` **НЕ доходит** до внешнего сокет-driver'а. DeltaDispatcher адресует push
> `targets=[subscriber]`+`queue_type="system"` → доставка в очередь `{subscriber}_system`
> через `queue_registry`; `backend_ctl` — не процесс системы, такой очереди нет, а
> `SocketChannel` вызывается только через `channel=`-резолв. Фикс — на уровне
> PM/DeltaDispatcher (вне scope 1.2/1.3). Тест помечен `xfail`.

## Proof of value (сценарий Этапа 2)

```python
with BackendDriver(port=8765) as drv:
    h = drv.introspect_handlers("preprocessor")
    # "register_update" ОТСУТСТВУЕТ в router_handlers → у плагина нет worker-side
    # приёмника. Диагноз за секунды, без единого клика в GUI.
```

## Безопасность

Dev-инструмент: bind `127.0.0.1`, гейт `BACKEND_CTL=1`, без аутентификации. В проде
endpoint не поднимается. Остановка — PID-specific (закрытие канала при shutdown PM),
без глобального taskkill.

## Связанное

- Канал: [`router_module/channels/socket_channel.py`](../multiprocess_framework/modules/router_module/channels/socket_channel.py)
- Адаптер: [`router_module/adapters/socket_bridge_adapter.py`](../multiprocess_framework/modules/router_module/adapters/socket_bridge_adapter.py)
- Поднятие: [`process_manager_module/process/backend_ctl_endpoint.py`](../multiprocess_framework/modules/process_manager_module/process/backend_ctl_endpoint.py)
- Билдер: [`message_module/builders/command_envelopes.py`](../multiprocess_framework/modules/message_module/builders/command_envelopes.py)
- ADR-RTR-008, план [`backend-control-mcp`](../plans/2026-05-31_backend-control-mcp/plan.md)
