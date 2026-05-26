---
name: feedback-qt-mcp-smoke-verification
description: После любой задачи, переписывающей Qt-виджет или вкладку, обязательно запускать прототип и делать qt_snapshot — pytest-qt unit-тесты не доказывают что реальная сборка работает
metadata:
  type: feedback
---

После Qt-задач (новый виджет, переписанный таб, изменение MVP-вью) **обязательно** делай smoke-верификацию через qt-mcp, не довольствуйся отчётом «pytest-qt N passed».

**Why:** pytest-qt запускает виджет изолированно с mock ctx; реальное приложение инстанцирует таб через `frontend/app.py` с настоящим `PluginRegistry`/`RecipeManager`/`StateProxy`. Несоответствие сигнатур, отсутствующие зависимости в DI или сломанный layout в комбинации с другими табами **не ловятся unit-тестами**. Зафиксировано 2026-05-26 на Task 5.7 (RecipesTab MVP) — пользователь напомнил.

**How to apply:**
1. После любой задачи, которая создаёт/переписывает Qt-виджет (`tabs/*/tab.py`, `widgets/*.py`), запусти прототип: `python -m multiprocess_prototype.run` (или через `/run-proto`) в фоне.
2. `qt_find_widget` или `qt_snapshot` целевой вкладки — проверь что layout рисуется без `MainWindow` падения.
3. Если таб с кнопками — `qt_object_tree` плюс выборочный `qt_click` на безопасной кнопке («Создать», «Обновить»). Кнопки с разрушительными эффектами («Удалить», «Сделать активным») — без клика, только проверка `enabled` через `qt_widget_details`.
4. Закрыть прототип после проверки (`TaskStop` для фонового процесса).
5. Если qt-snapshot показывает поломку — задача **не done**, возвращаешь в дев на фикс.

Связано: skill `verify-done` (общий гейт «прежде чем сказать done»), feedback_widget_qt_patterns (специфичные ловушки Qt — setFlags/blockSignals/EditTriggers), feedback_mvp_pattern (MVP-виджеты особенно нуждаются в smoke, так как presenter unit-тесты не покрывают view).
