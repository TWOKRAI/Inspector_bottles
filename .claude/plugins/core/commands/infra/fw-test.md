---
description: Run the project's tests (pytest or make test)
---

Запусти тесты проекта.

## Приоритет

1. **Если есть `Makefile` с целью `test`:**
   ```bash
   make test
   ```

2. **Иначе если есть `pyproject.toml` / `pytest.ini` / `tests/`:**
   ```bash
   uv run pytest -q
   ```

3. **Если у проекта свой test runner** (указано в `.claude/modes/_stack.md` → "Test runner"):
   следуй той инструкции.

## После прогона

Покажи итог:
- Сколько прошло / упало / skipped.
- Если есть FAIL — выведи короткий список (имена тестов + первая строка ошибки).
- Предложи `/dev:debug` для диагностики падающих тестов.

## Подсказки

- Windows: используй `py -3` или `python3` если `python` указывает на 2.x.
- Если pytest не установлен — `uv add --group dev pytest pytest-cov`.

$ARGUMENTS
