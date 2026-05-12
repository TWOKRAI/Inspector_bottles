---
description: Карта IPC-каналов (FieldRouting / send_message / subscribe)
---

Запусти AST-сканер IPC:

```bash
python scripts/channel_map/channel_map.py
```

Что находит:
- **declarations** — `FieldRouting(channel="X")` и аналоги (настраивается в `detect.channel_constructors`).
- **sends** — первый аргумент или kwarg `target=`/`targets=` у методов из `detect.send_methods` (по умолчанию `send_message`).
- **subscribes** — каналы в `detect.subscribe_methods` (опционально).

Конфиг: [scripts/channel_map/channel_map.toml](../../scripts/channel_map/channel_map.toml). Детали в [README.md](../../scripts/channel_map/README.md).

Полезные варианты:
- `python scripts/channel_map/channel_map.py --group-by file --format json` — диф между ветками.
- `python scripts/channel_map/channel_map.py --root multiprocess_framework/modules/frontend_module` — только один модуль.

**Когда использовать:**
- Перед переименованием канала: «кто декларирует X, кто шлёт в X».
- Поиск «висящих» отправок (`send` без парной `declaration`).
- Аудит роутинга при рефакторинге.

`?` в выводе = аргумент не строковый литерал (динамический канал). Это сигнал, не ошибка.

$ARGUMENTS
