---
name: reference_qt_mcp_launch
description: qt-mcp probe поднимается ТОЛЬКО с env QT_MCP_PROBE=1 (порт 9142); без неё qt-mcp «не подключается»
metadata:
  type: reference
---

Чтобы qt-mcp работал с прототипом, запускать с переменной окружения:

```
QT_MCP_PROBE=1 python multiprocess_prototype/run.py
```

- probe слушает `localhost:9142`, активируется ТОЛЬКО при `QT_MCP_PROBE=1` (см. `frontend/app.py:59-71`, `from qt_mcp.probe import install`). Обычный запуск `run.py` без переменной → probe OFF → qt-mcp «не к чему подключиться» (выглядит как «qt-mcp не настраивается», хотя всё цело).
- Проверка живости: `qt_list_windows` → MainWindow; `qt_find_widget pattern=FPS` → StatusLabel с числом.
- **Флуд `[SocketChannel:backend_ctl] bad line skipped: Expecting value line 1 column 1`** — НЕ про qt-mcp. Это сокет backend-control на порту **8765** (`backend/config/system.yaml: backend_ctl.enabled:true, port:8765`), в него прилетает не-JSON. Безобидный warning, в проде `enabled:false`.
- **Очистка процессов:** прототип спавнит ~8-9 реальных процессов; `TaskStop` bash-родителя может оставить осиротевшие multiprocessing-дети. Порты PM: 9142 (probe), 8765 (backend_ctl) — если в `netstat -ano` их нет в LISTENING, живого инстанса нет. Глобальный `taskkill /IM python.exe` ЗАПРЕЩЁН (зацепит ollama/qex/сессию) — см. [[feedback_no_global_taskkill]]; чистить по PID через netstat→PID. Контеншн камеры от сирот виден в старт-логе нового инстанса.

Связано: [[feedback_qt_mcp_smoke_verification]] (smoke должен скриншотить PreviewWindow, не только FPS).
