---
name: feedback_backend_driver_needs_connect_before_shutdown
description: "BackendDriver из Python без connect() молча отвечает accepted=False / not connected — сим (apps/line_sim, порт 8766) кажется «не принимает shutdown» / BackendDriver without connect() returns accepted=False, not connected"
module: [tools/backend_ctl, prototype/apps]
mechanism: [live-stand]
metadata:
  type: feedback
---

**Ловушка.** На стенде C-16 сим `apps/line_sim` гасили из Python. Прототип гасится MCP-инструментом
`backend-ctl` (порт 8765), а у сима свой порт 8766, туда MCP не ходит. Поэтому сим гасили
скриптом `BackendDriver(port=8766)`. Без `connect()` драйвер не бросает исключение, а возвращает
отказ, который похож на отказ сервера.

**Замер (2026-10-21, стенд letter_robot_sim):**
- `BackendDriver(port=8766).system_shutdown()` → `{'accepted': False, 'pm_gone': False}`, `elapsed_s 0.0`;
- `system_command({'command': 'shutdown'})` → `{'success': False, 'error': 'not connected'}`, порт 8766 открыт;
- `d.connect()`, затем `system_shutdown()` → `{'accepted': True, 'pm_gone': True}` за 0,72 с, порт закрыт, процесс сима вышел с кодом 0.

**Правило.**
- Скрипт с `BackendDriver` сначала вызывает `connect()`.
- `accepted=False` при `elapsed_s 0.0` означает, что драйвер не подключён, а не что команду отверг сервер.
- Не путать с «сим не поддерживает shutdown»: из-за этой путаницы ушли две лишние попытки.

**Триггер.** Гасить или опрашивать второй бэкенд (сим `line_sim` на 8766, любой порт кроме 8765) из Python, а не MCP-инструментом.
