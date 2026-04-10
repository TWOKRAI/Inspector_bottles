# .claude/ — Конфигурация Claude Code

Индекс содержимого папки. **Не путать с проектной документацией** — та лежит в `Inspector_prototype/multiprocess_framework/docs/`.

---

## Основные файлы

| Файл | Назначение | В контексте? |
|---|---|---|
| `CLAUDE.md` | Главный проектный контекст: архитектура, правила, стек | **Всегда** |
| `CLAUDE.local.md` | Локальные настройки (не коммитится) | **Всегда** |
| `settings.json` | Permissions (allow/ask/deny), хуки, statusLine | Нет (конфиг) |
| `settings.local.json` | Локальный override permissions (не коммитится) | Нет (конфиг) |
| `mcp.json` | MCP-серверы: qex (Qdrant+Ollama) | Нет (конфиг) |

---

## Субагенты (`agents/`)

Загружаются только когда Claude Code создаёт субагент — **не влияют на базовый контекст**.

| Агент | Когда использовать |
|---|---|
| `framework-architect` | Ревью архитектурных решений, ADR, Dict at Boundary |
| `ipc-routing-checker` | Проверка смешения `targets` и `channel` в IPC |
| `test-runner` | Запуск тестов с правильным PYTHONPATH |
| `pyqt-ui-reviewer` | Ревью PyQt5: thread-safety, утечки QObject, сигналы/слоты |
| `security-reviewer` | Ревью безопасности: pickle, IPC, shared memory, PyQt |

---

## Скиллы (`skills/`)

Загружаются только при явном вызове `/skill-name` — **не влияют на базовый контекст**.

| Скилл | Команда | Назначение |
|---|---|---|
| `add-process-module` | `/add-process-module` | Чек-лист создания нового ProcessModule |
| `add-register-schema` | `/add-register-schema` | Добавление схемы в `registers/` |
| `qex-search` | `/qex-search` | `search_code` = вектор (Qdrant) + BM25 + гибрид; в паре с Grep |
| `debug-issue` | `/debug-issue` | Дебаггинг с учётом IPC, процессов, PyQt |
| `refactor-code` | `/refactor-code` | Рефакторинг: qex-first, тесты, ADR |

---

## Slash-команды (`commands/`)

Загружаются только при вызове — **не влияют на базовый контекст**.

| Команда | Действие |
|---|---|
| `/validate` | `python Inspector_prototype/scripts/validate.py` |
| `/fw-test` | `python Inspector_prototype/scripts/run_framework_tests.py` |
| `/qex-status` | Статус qex-индекса |
| `/qex-reindex` | Переиндексация кодовой базы |
| `/run-proto` | Запуск прототипа инспекции бутылок |
| `/cold-start` | Холодный старт: Qdrant + Ollama + venv |

---

## Хуки (`hooks/`)

| Скрипт | Тип | Триггер | Действие |
|---|---|---|---|
| `validate-safe-command.sh` | PreToolUse | Bash | Блокирует опасные команды (rm -rf /, curl\|sh, …) |
| `autoformat-python.sh` | PostToolUse | Edit, Write | `ruff format` + `ruff check --fix` на изменённом `.py` |

---

## Справочники (не в .claude, загружаются по запросу)

Перенесены в `docs/claude/` для экономии токенов — Claude Code **не загружает их автоматически**:

- `docs/claude/CLAUDE_FOLDER_OVERVIEW.md` — обзор папки `.claude/`: роли файлов, settings, хуки, MCP, эффективность
- `docs/claude/FRAMEWORK_RULES_EXTRACT.md` — развёрнутый конспект правил фреймворка
- `docs/claude/FRAMEWORK_CONSTRUCTOR_OVERVIEW.md` — нарратив «конструктор»
- `docs/claude/qex/SETUP_GUIDE.md` — полная инструкция по настройке qex MCP (quick-start: `docs/claude/qex/README.md`)

