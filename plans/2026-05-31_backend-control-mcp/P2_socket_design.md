# P2 — SocketChannel + driver («GUI по сокету»): дизайн/контракт

- **Дата:** 2026-06-01 · **Зона:** framework (канал + билдер) + infra (driver) · **Уровень:** Senior
- **Статус:** 🟢 DESIGN утверждён владельцем → implement
- **Предпосылки:** P0.5 ✅ (`request()`/`reply_to_request`), P1 ✅ (introspect-команды)

> **Инвариант (владелец):** ВСЁ общение с бэкендом — строго через `RouterManager`
> (`router.request()` / `router.send()`). Сокет — обычный `IMessageChannel`, делает
> ТОЛЬКО байтовый I/O на границе. **Driver = «GUI по сокету»:** шлёт те же
> router-сообщения, что GUI через `CommandSender`. Протокол — один источник правды
> (общий билдер), не дублируется.

---

## 1. Модель: driver — это headless-GUI

GUI общается с бэкендом так: `CommandSender` строит dict-сообщение → кладёт в очередь
процесса → `RouterManager` маршрутизирует. Driver делает **ровно то же**, только
транспорт до системы — TCP-сокет вместо локальной очереди. Сообщение на проводе —
**GUI-идентичный router-dict** + 2 поля для ответа (GUI их не шлёт, т.к.
fire-and-forget):

```python
# Команда процессу X (форма CommandSender.send_command) + reply-поля:
{"type":"command", "command":"introspect.handlers", "data_type":"introspect.handlers",
 "sender":"backend_ctl", "targets":["preprocessor"], "data":{...},
 "request_id":"<corr>", "reply_to":"ProcessManager"}        # ← +2 поля

# Команда PM (форма CommandSender.send_system_command) + reply-поля:
{"type":"command", "command":"process.command", "data_type":"process.command",
 "sender":"backend_ctl", "targets":["ProcessManager"],
 "data":{"cmd":"process.start", "process_name":"camera"},
 "request_id":"<corr>", "reply_to":"ProcessManager"}        # ← +2 поля
```

`command`/`targets`/`data`/`type` — **байт-в-байт как GUI**. Добавлены только
`request_id` (корреляция P0.5) и `reply_to:"ProcessManager"` (driver не в
`queue_registry`, ответ физически приходит в очередь PM, где живёт сокет).

---

## 2. Общий билдер протокола (один источник правды) — `message_module`

Чтобы «GUI и driver шлют одинаковое» гарантировалось **кодом**, а не дисциплиной,
выносим построение dict-команд в чистый хелпер во фреймворке (нижний слой — импортится
и frontend'ом, и driver'ом без нарушения слоёв):

`multiprocess_framework/modules/message_module/builders/command_envelopes.py`
```python
def build_command_message(target, command, args=None, *, sender,
                          request_id=None, reply_to=None) -> dict:
    """Форма CommandSender.send_command (+ опц. reply-поля для request-response)."""
    msg = {"type":"command", "command":command, "data_type":command,
           "sender":sender, "targets":[target], "data":args or {}}
    if request_id is not None: msg["request_id"] = request_id
    if reply_to  is not None:  msg["reply_to"]  = reply_to
    return msg

def build_system_command_message(command: dict, *, sender,
                                 request_id=None, reply_to=None) -> dict:
    """Форма CommandSender.send_system_command (process.command-обёртка PM)."""
    msg = {"type":"command", "command":"process.command",
           "data_type":"process.command", "sender":sender,
           "targets":["ProcessManager"], "data":command}
    if request_id is not None: msg["request_id"] = request_id
    if reply_to  is not None:  msg["reply_to"]  = reply_to
    return msg
```

- **GUI:** `CommandSender.send_command/send_system_command` переписать на эти билдеры
  (вывод **байт-в-байт** прежний — поведение GUI не меняется, reply-поля не задаются).
- **Driver:** использует те же билдеры + задаёт `request_id`/`reply_to`.
- Тесты билдера + регрессия `test_command_sender.py` (вывод идентичен).

---

## 3. SocketChannel — обычный IMessageChannel (`router_module/channels/socket_channel.py`)

Серверный TCP-эндпоинт, сиблинг `QueueChannel`. Регистрируется в RouterManager хоста
(`register_channel` — by-design extension). Без бизнес-логики.

| Метод | Семантика |
|-------|-----------|
| `name -> "backend_ctl"` | имя = адрес для `channel=`-маршрутизации ответа |
| `channel_type -> "socket"` | |
| `send(message) -> dict` | **к driver'у:** `json.dumps(message)+"\n"` в клиентский сокет (под Lock). Зовётся ТОЛЬКО router'ом через `_resolve_channels(channel="backend_ctl")`. |
| `poll(timeout) -> []` | **no-op** (inbound — push через read-loop, не pull; имя без префикса `ProcessManager_` → receive-цикл его не опрашивает, и это верно) |
| `get_info()` | `{name,type,bound,connected,clients,rx,tx}` |
| `close()` | стоп accept-loop + закрыть сокеты |

**Внутри:** `__init__(name, host="127.0.0.1", port=8765, on_inbound=None)`. `start()`:
`socket/bind/listen` + accept-loop (daemon), на соединение — read-поток, читает
newline-JSON, `json.loads` → `on_inbound(msg)`. Битая строка → лог+skip, не падаем.
Запись под `Lock`. Wire: UTF-8 newline-delimited JSON, только dict; кадры/SHM НЕ гоняем.

---

## 4. Тонкий граничный адаптер (симметрия CommandSender, не «костыль»)

`on_inbound` связывает прочитанный сокетом dict с router'ом. **Без reshaping** —
сообщение уже GUI-формы (см. §1). Это сервер-сторона `CommandSender`:

```python
def on_inbound(self, msg: dict) -> None:               # msg уже router-сообщение
    corr = msg.get("request_id")
    try:
        result = self._router.request(msg, timeout=msg.get("timeout", 5.0))  # router API
    except Exception as exc:                            # noqa: BLE001
        result = {"success": False, "error": str(exc)}
    self._router.send({"type":"response", "channel":"backend_ctl",          # router API
                       "request_id": corr, "result": result})
```

- `request()` крутится в read-потоке сокета, резолвится в system-loop PM (другой
  поток) → **дедлок-контракт P0.5 соблюдён даром**.
- Ответ driver'у — `router.send(channel="backend_ctl")` → router сам резолвит канал →
  `SocketChannel.send()`. Адаптер сокет напрямую НЕ трогает.
- v1: запросы на одном соединении сериализуются (один read-поток) — для dev-driver'а
  достаточно; пул при необходимости позже.

---

## 5. Поток end-to-end (каждая стрелка — RouterManager)

```
driver: build_command_message(... , request_id, reply_to="ProcessManager")
   ▼ TCP (newline-JSON)
SocketChannel.read-loop → on_inbound → router.request(msg)        ← router API
   │  _deliver_by_targets → preprocessor.system-queue              ← router (как GUI)
   │  preprocessor: generic command-handler + reply_to_request     ← P0.5
   │     ответ targets=["ProcessManager"], request_id=corr, queue_type="system"
   │  → PM.system-queue → PM.receive() → _resolve_pending(corr)    ← router
   ▼ request() вернул result
   router.send({type:"response", channel:"backend_ctl", request_id:corr, result})  ← router API
   │  _resolve_channels(channel) → SocketChannel.send()            ← router
   ▼ TCP
driver: матч по request_id → отдаёт результат вызвавшему (Claude/MCP в P3)
```

**Адресация команд:** introspect.*/worker.* → прямая команда процессу
(`build_command_message`, generic command-путь P0.5 уже отвечает). process.*/blueprint.*/
system.* → PM-обёртка (`build_system_command_message`, `_handle_process_command` PM).

---

## 6. Driver (infra, `backend_ctl/driver.py`)

Socket-клиент + request-id matching (зеркало P0.5 над сокетом). Без бизнес-логики:
- `connect(host, port)`; читающий поток складывает ответы по `request_id` в pending.
- `request(msg, timeout)` — низкоуровневый: пишет dict+`\n`, ждёт ответ по `request_id`.
- Обёртки поверх билдеров (§2): `introspect_handlers(proc)`, `introspect_registers(proc)`,
  `introspect_status(proc)`, `list_processes()`, `get_status(proc)`,
  `set_register(proc, plugin, field, value)`, `send_command(target, cmd, args)`,
  `system_command(cmd, args)`.

---

## 7. Поднятие канала (хост = ProcessManager), гейт, shutdown

В `ProcessManagerProcess.initialize()`, **только при `BACKEND_CTL=1`**:
```python
if os.environ.get("BACKEND_CTL") == "1":
    self._bc_channel = SocketChannel("backend_ctl", host="127.0.0.1",
        port=int(os.environ.get("BACKEND_CTL_PORT", "8765")),
        on_inbound=self._make_bc_on_inbound())
    self.router_manager.register_channel(self._bc_channel)
    self._bc_channel.start()
```
- Без аутентификации (localhost dev-tool); гейт `BACKEND_CTL=1` + bind `127.0.0.1` —
  в проде не существует. Shutdown PM: `self._bc_channel.close()` (memory
  `feedback_no_global_taskkill` — PID-specific остановка процессов).

---

## 8. Тесты (full module-contract)

- **command_envelopes:** формы build_command/build_system_command; reply-поля опц.;
  регрессия — вывод идентичен прежнему CommandSender (`test_command_sender.py` зелёный).
- **SocketChannel (loopback TCP):** start/stop; newline-JSON парсинг; битая строка не
  роняет; `send` пишет клиенту; конкурентная запись под Lock; `get_info`.
- **on_inbound адаптер:** `router.request` вызван с тем же msg; ответ через
  `router.send(channel="backend_ctl")`; error-ветка (мок router).
- **Driver:** request-id matching; таймаут; реконнект.
- **Integration (loopback, фейковый router echo):** driver → SocketChannel →
  request→reply → ответ driver'у по request_id; неизвестный target → error.
- **README + Protocol** нового; ADR в `router_module/DECISIONS.md`.

---

## 9. Smoke (proof of value — Этап 2)

`BACKEND_CTL=1`, поднять рецепт headless → `driver.connect()` →
`driver.introspect_handlers("preprocessor")` → `register_update` ОТСУТСТВУЕТ в
`router_handlers` — диагноз за секунды, без GUI. Перед P3 (MCP).

---

## 10. Решено на ревью

- ✅ Driver = «GUI по сокету», wire = GUI-сообщение + `{request_id, reply_to}`.
- ✅ Общий билдер протокола в `message_module` (GUI + driver, один источник правды).
- ✅ introspect/worker.* → прямая команда; process.*/blueprint.* → PM-обёртка.
- Порт 8765 (env `BACKEND_CTL_PORT`); гейт только `BACKEND_CTL=1`; имя канала `backend_ctl`;
  request-timeout 5.0с (driver может переопределить полем `timeout`).

---

## 11. Объём (оценка)

- command_envelopes ~40 + тесты ~50; CommandSender refactor ~15
- SocketChannel ~150 + тесты ~140
- on_inbound адаптер ~50 + тесты ~70
- driver ~140 + тесты ~110
- PM-интеграция (гейт+поднятие+shutdown) ~35
- README + Protocol + ADR
- **Итого P2 ~900 строк** (код+тесты+docs). P3 (MCP-обёртка) — отдельно.

---

## 12. Чеклист «всё через RouterManager»

- [x] Inbound driver→X: `router.request` (НЕ прямая запись в очередь).
- [x] X→PM: `reply_to_request` + `_deliver_by_targets` (P0.5).
- [x] PM→driver: `router.send(channel="backend_ctl")` → `_resolve_channels` →
      `SocketChannel.send` (НЕ прямой вызов сокета в обход router).
- [x] SocketChannel — зарегистрированный `IMessageChannel`.
- [x] Сокет — только байтовый I/O (read/write line).
- [x] Протокол — общий билдер (GUI=driver), без дублирования.
