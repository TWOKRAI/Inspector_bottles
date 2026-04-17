# .claude/ — Dev Company Configuration

Универсальная конфигурация агентной системы разработки. Переносима между проектами.
Проектная специфика — в корневом `CLAUDE.md`.

---

## Файлы

| Файл | Назначение | Загрузка |
|---|---|---|
| `CLAUDE.md` | Workflow компании (универсальный) | Всегда |
| `../CLAUDE.md` | Проектный контекст (специфика) | Всегда |
| `settings.json` | Разрешения, хуки, statusLine | Конфиг |
| `settings.local.json` | Локальный override (gitignored) | Конфиг |
| `mcp.json` | MCP-серверы (qex) | Конфиг |

---

## Команда (agents/)

| Агент | Модель | Роль |
|---|---|---|
| `manager` | Opus | Декомпозиция задачи, ТЗ с уровнями сложности |
| `teamlead` | Opus | Старший разработчик — Senior+ задачи, экспресс-ревью |
| `developer` | Sonnet | Реализация кода по ТЗ |
| `tester` | Sonnet | Тесты по acceptance criteria |
| `docs-writer` | Haiku | Документация, docstrings |
| `reviewer` | Opus | Финальный код-ревью (архитектура + безопасность + IPC + PyQt) |
| `_template` | — | Шаблон для `/hire` |

---

## Команды (commands/)

### Workflow

| Команда | Действие |
|---|---|
| `/plan` | Manager → декомпозиция → план в `plans/` |
| `/implement` | Developer → реализация Task X.Y |
| `/test` | Tester → тесты |
| `/review` | Reviewer → код-ревью → апрув/правки |
| `/docs` | Docs Writer → документация |
| `/ship` | Финальная проверка: validate + тесты + линтер |
| `/team` | Показать состав компании |
| `/hire` | Создание нового агента по шаблону |
| `/pipeline` | **Полный автомат:** plan → implement → test → review → ship |

### Проектные (Inspector_bottles)

| Команда | Действие |
|---|---|
| `/validate` | Валидация структуры фреймворка |
| `/fw-test` | Тесты фреймворка |
| `/qex-status` | Статус qex-индекса |
| `/qex-reindex` | Переиндексация кодовой базы |
| `/run-proto` | Запуск прототипа |
| `/cold-start` | Холодный старт сервисов |

---

## Скиллы (skills/)

| Скилл | Назначение |
|---|---|
| `/add-process-module` | Создание нового ProcessModule |
| `/add-register-schema` | Добавление схемы регистров |
| `/qex-search` | Семантический поиск (гибрид) |
| `/debug-issue` | Дебаггинг фреймворка |
| `/refactor-code` | Рефакторинг с qex-first |

---

## Хуки (hooks/)

| Скрипт | Тип | Действие |
|---|---|---|
| `validate-safe-command.sh` | PreToolUse (Bash) | Блокирует опасные команды |
| `autoformat-python.sh` | PostToolUse (Edit/Write) | `ruff format` + `ruff check --fix` |
| `check-imports.sh` | PostToolUse (Edit/Write) | Проверка синтаксиса Python |

---

## Как перенести в другой проект

1. Скопировать `.claude/` в новый проект
2. Создать корневой `CLAUDE.md` с проектной спецификой
3. Удалить проектные команды/скиллы (или адаптировать)
4. Обновить `mcp.json` и `settings.json` под стек проекта
5. Универсальные агенты и workflow-команды работают сразу
