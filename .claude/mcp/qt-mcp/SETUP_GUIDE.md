# qt-mcp — полный гайд установки

## Архитектура

```
Claude Code ──MCP(stdio)──▶ qt-mcp server ──TCP:9142──▶ probe inside PySide6 app
                                                              │
                                                              ▼
                                                 QApplication, QWidget tree
```

Probe — это маленькая Python-библиотека, которая встраивается в **уже запущенное** PySide6-приложение и слушает JSON-RPC на `localhost:9142`. MCP-сервер (отдельный процесс, который запускает Claude Code) подключается к этому порту и транслирует команды.

**Следствия:**
- Если приложение не запущено или probe не активирован — все MCP-tools возвращают «no connection».
- Probe **внутри** процесса, видит реальные QObject-ы и thread affinity. Это сильнее, чем внешний UI-automation.
- Для headless-окружения (CI) нужен qt-pilot (Linux/Xvfb), не qt-mcp.

## Установка пакета

⚠️ **`qt-mcp` пока не опубликован на PyPI** (v0.1.0, ранний проект 0xCarbon).
Установка идёт **из git** напрямую — uv это поддерживает:

```powershell
cd D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles
uv add --dev "qt-mcp @ git+https://github.com/0xCarbon/qt-mcp.git"
```

> `--dev`: probe нужен только для разработки/отладки. uv запишет git-зависимость в `pyproject.toml` с пином commit-hash в `uv.lock`.

Проверить:

```powershell
python -c "import qt_mcp; print(qt_mcp.__version__)"
# 0.1.0
ls .venv/Scripts/qt-mcp.exe
# должен существовать
```

> Когда qt-mcp появится на PyPI — заменишь git-зависимость на обычную: `uv add qt-mcp`.

## Интеграция probe — где врезать

В проекте `run.py` — это только **launcher** (re-exec в правильный venv). Настоящая инициализация `QApplication` находится в:

📍 [`multiprocess_prototype/frontend/app.py:57`](../../../multiprocess_prototype/frontend/app.py)

```python
def run_gui(process: "GuiProcess") -> None:
    """Создать QApplication и запустить Qt event loop."""
    app = QApplication.instance() or QApplication(sys.argv)
    # ← вот сюда вставлять probe
```

Минимально-инвазивный вариант — env-флаг, чтобы prod-поведение не менялось:

```python
def run_gui(process: "GuiProcess") -> None:
    """Создать QApplication и запустить Qt event loop."""
    app = QApplication.instance() or QApplication(sys.argv)

    # qt-mcp probe — активируется только при QT_MCP_PROBE=1
    import os
    if os.environ.get("QT_MCP_PROBE") == "1":
        try:
            from qt_mcp.probe import install
            install()  # слушает localhost:9142
            process._log_info("qt-mcp probe installed on localhost:9142", module="startup")
        except ImportError:
            process._log_warning("qt-mcp probe requested but qt_mcp not installed", module="startup")

    # 1. Применить тему
    apply_default_theme(app)
    # ... остальная инициализация
```

**Куда:** строки 56-58 в `app.py`, **после** создания `QApplication`, **до** `apply_default_theme(app)`. Логирование — через `process._log_info` / `process._log_warning` (это паттерн модуля, не `print`).

## Запуск с probe

```powershell
$env:QT_MCP_PROBE = "1"
python multiprocess_prototype\run.py
```

В логе должно появиться `[qt-mcp] probe installed, listening on localhost:9142`. Это сигнал — приложение готово к интроспекции через MCP.

## Конфигурация MCP

В `.mcp.json`:

```json
"qt-mcp": {
  "command": "uv",
  "args": ["run", "qt-mcp"]
}
```

`uv run` запускает бинарь `qt-mcp.exe` из проектного `.venv/Scripts/` (куда `uv add` положил его при установке). Без глобальной установки, без uvx-кэша — версия пакета связана с `uv.lock` проекта. После правки `.mcp.json` — перезапуск Claude Code.

## Цикл работы

1. В одном терминале запускаешь приложение с probe:
   ```powershell
   $env:QT_MCP_PROBE = "1"
   python multiprocess_prototype\run.py
   ```
2. В Claude Code — `/mcp` показывает qt-mcp `connected`.
3. Просишь агента: «Сделай screenshot главного окна и опиши widget tree». Агент дёргает `mcp__qt_mcp__screenshot` и `mcp__qt_mcp__widget_tree`.
4. После работы — закрываешь приложение. Probe умирает вместе с процессом.

## Windows-специфика

| Аспект | Статус | Комментарий |
|--------|--------|-------------|
| Probe (intercept Qt events) | ✅ работает | Не зависит от display server |
| Widget tree / properties | ✅ работает | Чистый Qt API |
| Screenshot | ⚠️ зависит от Qt-настроек | На Win10 — через `QPixmap::grabWindow`. Если падает — обновить PySide6 до последней 6.10+ |
| Multi-monitor | ⚠️ может выдавать только активный | Указать `--window-id` явно при `screenshot` |

Docs репозитория явно упоминают X11/Wayland для скриншотов. На Windows это путь через Qt-абстракцию — обычно работает, но если будут артефакты, fallback — использовать `screen-view-mcp` (внешний скриншотер).

## Конфликт с многопроцессным фреймворком

Important: в проекте — **multiprocess архитектура** (`SystemLauncher → ProcessManagerProcess → дочерние процессы`). PySide6 GUI обычно живёт в одном из дочерних процессов (`frontend_module`).

Probe слушает порт `9142` — если по какой-то причине порт занят (например, два запуска параллельно), probe упадёт. Можно переопределить порт:

```python
from qt_mcp.probe import install
install(port=9143)
```

И в `.mcp.json` пробросить env qt-mcp серверу:

```json
"qt-mcp": {
  "command": "uvx",
  "args": ["qt-mcp"],
  "env": {
    "QT_MCP_PORT": "9143"
  }
}
```

## Troubleshooting

### MCP «connected», но все tools возвращают «no probe»

Probe не активирован в приложении. Проверь:
1. `$env:QT_MCP_PROBE` — должно быть `1`.
2. Лог приложения — есть ли `[qt-mcp] probe installed`?
3. Порт 9142 не занят: `netstat -ano | findstr :9142`.

### `uv add qt-mcp` падает с conflict

Версия PySide6 в `pyproject.toml` может конфликтовать с зависимостями qt-mcp. Поставь через `--no-sync`:

```powershell
uv add --dev --no-sync qt-mcp
```

И вручную проверь pyproject.toml на ограничения.

### Probe ломает запуск приложения

Если probe ломает что-то в твоём event loop — выключи через env (`$env:QT_MCP_PROBE = ""`) и удали import. Probe должен быть **opt-in**.

## Использование в агентах

Добавь в промпт Tester / Debugger:

```
**qt-mcp для GUI smoke:** перед написанием pytest-qt теста — запусти
приложение с QT_MCP_PROBE=1 и через mcp__qt_mcp__widget_tree /
screenshot убедись, что виджет реально показывается. Это экономит
итерации vs. слепое написание тестов.
```

## Ссылки

- Репо: https://github.com/0xCarbon/qt-mcp
- Альтернатива для CI: https://github.com/neatobandit0/qt-pilot (Linux/Xvfb)
- pytest-qt: https://pytest-qt.readthedocs.io/
