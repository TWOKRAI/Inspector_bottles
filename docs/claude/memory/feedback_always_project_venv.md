---
name: feedback-always-project-venv
description: Всегда использовать проектный .venv интерпретатор; uv run без --no-sync падает на резолве extras и берёт не тот env
metadata:
  type: feedback
---

Всегда использовать **проектный `.venv`** (`Inspector_bottles/.venv`) как интерпретатор — для запуска, тестов и MCP-серверов. НЕ полагаться на `uv run` без флага, который пересобирает окружение.

**Why:** `uv run -- python …` пытается заново резолвить зависимости и падает на конфликте extras (`inspector-bottles[ml-torch]` / `setuptools>=82`), либо берёт не тот интерпретатор. Из-за этого qt-mcp висел в статусе `cfg` (сервер из `.mcp.json` не стартовал). Владелец: «может не тот интерпретатор» → «запомни что всегда проектный».

**How to apply:**
- Команды/тесты: `.venv/Scripts/python.exe` (Windows) или `run.py` (он сам делает venv-guard и re-exec в `.venv`).
- MCP-серверы в `.mcp.json`, запускаемые через uv: добавлять `uv run --no-sync` — берёт существующий `.venv` без пересборки (фикс qt-mcp применён 2026-06-15).
- `qt_mcp` 0.1.0 установлен именно в проектном `.venv`; probe-хук в [app.py](multiprocess_prototype/frontend/app.py) активируется `QT_MCP_PROBE=1` (порт 9142).

Связано: [[reference_qt_mcp_launch]], [[feedback_qt_mcp_always_probe]].
