# PROJECT_NAME — Проектный контекст

## Проект

Краткое описание проекта в 1-2 предложениях. На основе чего, для чего, в каком стеке.

## Архитектура

- **Слой 1:** что делает
- **Слой 2:** что делает
- **Слой 3:** что делает

## Ключевые пути

| Что | Путь |
|-----|------|
| **Главный пакет** | `src/PROJECT_NAME/` |
| Тесты | `tests/` |
| Документация | `docs/` |
| Диаграммы | `docs/diagrams/` |
| Планы (Plan-Driven Dev) | `plans/` |
| Точка входа | `main.py` или `src/PROJECT_NAME/__main__.py` |

## Стек

- Python 3.12 (см. `pyproject.toml`)
- Основные зависимости: pydantic, loguru, ... (адаптируй)
- Тесты: pytest, pytest-cov
- Quality gates: ruff, mypy, bandit
- Пакетный менеджер: uv

## Правила проекта

1. **Стиль:** ruff (lint + format), автоматический в pre-commit
2. **Типы:** mypy gradual, type hints в новом коде обязательны
3. **Тесты:** обязательны при изменении логики
4. **Секреты:** только в `.env` (gitignored), не в коде
5. **Commit-сообщения:** Conventional Commits + trailers `Why:` и `Layer:`

## Команды разработки

| Команда | Что делает |
|---------|-----------|
| `make check` | ruff + mypy + bandit |
| `make test` | pytest с coverage |
| `make gate` | полный gate перед commit |
| `make diagrams` | генерация UML/dependency-графов |
| `/plan <task>` | декомпозиция задачи (Manager-агент) |
| `/implement` | реализация (Developer-агент) |
| `/ship` | финальная проверка перед merge |

## Документация по `.claude/`

- [`.claude/BOOTSTRAP.md`](.claude/BOOTSTRAP.md) — установка стека с нуля
- [`.claude/STACK.md`](.claude/STACK.md) — описание всех инструментов
- [`.claude/VSCODE_EXTENSIONS.md`](.claude/VSCODE_EXTENSIONS.md) — VS Code расширения

## MCP-серверы

- **qex** — семантический поиск кода (`/qex-status`)
- **sentrux** — архитектурный анализ (`/sentrux-health`)
- **context7** — актуальная документация библиотек
