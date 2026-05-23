---
description: Запуск точки входа проекта — по pyproject [project.scripts], make run, или python -m <package>
---

Запусти основную точку входа проекта. Определи её по приоритету:

## Шаги

1. **Если есть `pyproject.toml` с `[project.scripts]`** — выбери первую запись и запусти через uv:
   ```bash
   uv run <script-name> $ARGUMENTS
   ```

2. **Иначе если есть `Makefile` с целью `run`**:
   ```bash
   make run ARGS="$ARGUMENTS"
   ```

3. **Иначе если есть `src/<package>/__main__.py`** (или `<package>/__main__.py`):
   ```bash
   uv run python -m <package> $ARGUMENTS
   ```

4. **Иначе если есть `src/<package>/cli.py` или `app.py` или `main.py`**:
   ```bash
   uv run python -m <package>.<module> $ARGUMENTS
   ```

5. **Если ничего не найдено** — спроси у пользователя путь к точке входа и предложи добавить `[project.scripts]` в `pyproject.toml`.

## Подсказки

- Если падает с `ModuleNotFoundError` — выполни `uv sync` (или `make install`).
- Если падает с UI/GUI ошибкой — проверь что соответствующая optional-группа установлена: `uv sync --group <ui-group>` (см. `pyproject.toml` → `[dependency-groups]`).
- Если процесс крашится — спроси, нужно ли запустить `/debug` для диагностики.

## Project-specific override

Если в `.claude/modes/_stack.md` есть секция "Entry point" — следуй ей вместо алгоритма выше.

$ARGUMENTS
