---
description: Run the project's entry point — via pyproject [project.scripts], make run, or python -m <package>
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
- Если процесс крашится — спроси, нужно ли запустить `/dev:debug` для диагностики.

## Smoke-режим (live-smoke для `/dev:pipeline` S5)

Когда нужен **не** полный прогон, а лишь проверка «приложение стартует» (S5 live-smoke
gate перед ревью) — добавь non-destructive флаг к шагам выше, чтобы entrypoint
поднялся и сразу вышел, не делая реальной работы:
```bash
uv run python -m <package> --version   # или --help
```
Цель — поймать import-cycle при старте, broken entrypoint, misconfigured env. Если
у entrypoint нет `--version`/`--help` — достаточно `uv run python -c "import <package>"`.
Падение на этом шаге = STOP перед S6 (см. `/dev:pipeline` → шаг 3 Live-smoke).

## Project-specific override

Если в `.claude/modes/_stack.md` есть секция "Entry point" — следуй ей вместо алгоритма выше.

$ARGUMENTS
