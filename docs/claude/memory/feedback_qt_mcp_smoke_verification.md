---
name: feedback-qt-mcp-smoke-verification
description: После любой задачи, переписывающей Qt-виджет или вкладку, обязательно запускать прототип и делать qt_snapshot — pytest-qt unit-тесты не доказывают что реальная сборка работает
metadata:
  type: feedback
---

Правило перенесено в `.rules/gui.md` и `.claude/commands/dev/implement.md` (§4) (2026-10-04).

**Why:** pytest-qt запускает виджет изолированно с mock ctx; реальное приложение инстанцирует таб через `frontend/app.py` с настоящим `PluginRegistry`/`RecipeManager`/`StateProxy`. Несоответствие сигнатур, отсутствующие зависимости в DI или сломанный layout в комбинации с другими табами **не ловятся unit-тестами**. Зафиксировано 2026-05-26 на Task 5.7 (RecipesTab MVP) — пользователь напомнил.


Связано: skill `verify-done` (общий гейт «прежде чем сказать done»), feedback_widget_qt_patterns (специфичные ловушки Qt — setFlags/blockSignals/EditTriggers), feedback_mvp_pattern (MVP-виджеты особенно нуждаются в smoke, так как presenter unit-тесты не покрывают view).
