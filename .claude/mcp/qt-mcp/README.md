# qt-mcp — MCP для инспекции PySide6-приложений

[qt-mcp](https://github.com/0xCarbon/qt-mcp) — MCP-сервер от 0xCarbon, позволяющий LLM-агенту «видеть и тыкать» запущенное PySide6-приложение: widget tree, properties, скриншоты, клики, изменение свойств, инспекция QGraphicsScene/VTK. Аналог Playwright, но для desktop Qt.

## Когда звать

| Задача | Инструмент |
|--------|-----------|
| Юнит-тест виджета через QTest | `pytest-qt` (как было) |
| «Покажи мне widget tree запущенного приложения» | **qt-mcp** |
| «Сделай screenshot главного окна» | **qt-mcp** |
| Smoke-проверка: видно ли поле, кликабельна ли кнопка | **qt-mcp** |
| Воспроизведение пользовательского сценария | **qt-mcp** |
| Дебаг «почему виджет не виден» (свойства, геометрия) | **qt-mcp** |

Цель — закрыть слепую зону между unit-тестом (pytest-qt) и ручным smoke. Агент может зайти в живой `multiprocess_prototype/run.py`, посмотреть `frontend_module` глазами, отчитаться о состоянии.

## ⚠️ Важно: требует модификации приложения

В отличие от Serena/qex, qt-mcp работает **через probe внутри процесса PySide6**. Без активации probe — сервер не получит доступ к Qt-объектам. Два способа:

**Способ A — env (рекомендую):**

```powershell
$env:QT_MCP_PROBE = "1"
python multiprocess_prototype\run.py
```

Probe автоактивируется при старте приложения.

**Способ B — явный вызов в коде:**

```python
# multiprocess_prototype/run.py (после QApplication)
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

if os.environ.get("QT_MCP_PROBE"):  # включается только по env
    from qt_mcp.probe import install
    install()
```

Probe слушает `localhost:9142` (JSON-RPC) — MCP-сервер коннектится к этому порту.

## Быстрый старт (Windows)

```powershell
# 1. Установка из git (на PyPI пока не опубликован, v0.1.0)
uv add --dev "qt-mcp @ git+https://github.com/0xCarbon/qt-mcp.git"

# 2. Врезать probe в frontend/app.py (см. SETUP_GUIDE.md)

# 3. Запустить прототип с probe
$env:QT_MCP_PROBE = "1"
python multiprocess_prototype\run.py

# 4. В Claude Code — теперь qt-mcp видит запущенное приложение
```

## Подключение к Claude Code

Уже добавлено в `.mcp.json`:

```json
"qt-mcp": {
  "command": "uv",
  "args": ["run", "qt-mcp"]
}
```

`uv run` запускает бинарь `qt-mcp.exe` из проектного `.venv/Scripts/` — без глобальной установки. После правки кода + запуска приложения — перезапусти Claude Code и проверь `/mcp`.

## Ключевые tools (11 шт)

| Tool | Что делает |
|------|-----------|
| `widget_tree` | snapshot всего дерева виджетов |
| `inspect_widget` | свойства одного виджета по id |
| `set_property` | изменить свойство (text, geometry, etc.) |
| `invoke_slot` | дёрнуть slot/method |
| `click` / `type` / `key` | имитация ввода |
| `screenshot` | PNG главного окна или виджета |
| `list_windows` | все top-level окна |
| `qgraphics_scene` | инспекция QGraphicsScene |
| `vtk_scene` | поддержка VTK/PyVista |
| `object_tree` | QObject-дерево (не только виджеты) |

## Полный гайд

См. [SETUP_GUIDE.md](SETUP_GUIDE.md) — интеграция probe в `run.py`, troubleshooting на Windows, конфликты с pytest-qt.

## Гочи на стеке Inspector_bottles

Из практики baseline-снимка Phase 2 (2026-05-18):

* **Bash, не PowerShell** — Claude Code на Windows запускает background-задачи через bash. Используй `QT_MCP_PROBE=1 python multiprocess_prototype/run.py` (POSIX), не `$env:` форму.
* **Probe врезан в `frontend/app.py:run_gui()`** — это код дочернего процесса `gui`. Сигнал успеха в логе: `[INFO] [gui] startup: qt-mcp probe installed on localhost:9142`.
* **Жди ≥12 сек после запуска** — re-exec venv + загрузка фреймворка + старт `gui` процесса. Иначе `qt_list_windows` → `Failed to connect to probe`.
* **`MainWindow ""` без title** — нормально, различай окна по `objectName`.
* **НЕ под pytest** — probe и pytest-qt конфликтуют по порту 9142. Env-флаг ставь только для ручного/agent smoke.

Подробности — секция «Project-specific quirks» в SETUP_GUIDE.md.

## Ссылки

- Репо: https://github.com/0xCarbon/qt-mcp
- Альтернатива (Linux/CI): https://github.com/neatobandit0/qt-pilot
- Pro-вариант от Qt Group: [Squish MCP](https://www.qt.io/blog/enhance-squish-gui-testing-with-ai-assistants-using-the-new-mcp-sample)
