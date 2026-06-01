# backend_ctl — headless driver управления бэкендом (dev-инструмент)

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

1. Поднять систему с открытым гейтом:
   ```bash
   BACKEND_CTL=1 python run.py            # порт по умолчанию 8765
   BACKEND_CTL=1 BACKEND_CTL_PORT=9001 python run.py
   ```
   Без `BACKEND_CTL=1` endpoint не существует (в проде по умолчанию выключен).

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
| `set_register(process, plugin, field, value)` | live-запись регистра (`register_update`) |
| `request(message, timeout=None)` | низкоуровневый: готовый router-dict → ответ по `request_id` |

Все обёртки возвращают `result` из ответа (или `{"success": False, "error": ...}` при
таймауте/обрыве). Сообщения строятся `message_module.build_command_message` /
`build_system_command_message` — один источник правды с GUI.

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
