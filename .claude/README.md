# .claude/ — Конфигурация Claude Code

Самодостаточная система управления проектом **Inspector_bottles**.
Проектный контекст (архитектура, стек, правила) — в корневом [`CLAUDE.md`](../CLAUDE.md).

> **Кросс-платформа.** Windows + macOS: `bootstrap.py` и `qex-launcher.py` определяют ОС автоматически, hooks работают через Git Bash.

---

## Документация

| Файл | Что внутри | Когда читать |
|------|-----------|--------------|
| [`BOOTSTRAP.md`](BOOTSTRAP.md) | **Полная установка стека в новый проект** (системные пакеты, Python, MCP, VS Code) | Создаёшь новый проект |
| [`STACK.md`](STACK.md) | Описание всех инструментов: что делает, зачем нужен, как использовать | Хочешь понять стек |
| [`VSCODE_EXTENSIONS.md`](VSCODE_EXTENSIONS.md) | VS Code расширения по категориям + рекомендуемые `settings.json` | Настраиваешь IDE |
| [`CLAUDE-SETUP.md`](CLAUDE-SETUP.md) | Краткий гайд по `.claude/` (только Claude Code часть) | Только MCP / агенты |
| [`templates/README.md`](templates/README.md) | Готовые шаблоны конфигов (pyproject, pre-commit, Makefile, ...) | Копируешь в новый проект |
| [`mcp/PORTABLE.md`](mcp/PORTABLE.md) | Детальный перенос MCP-серверов | Перенос MCP вручную |

---

## Структура

```
.claude/
├── BOOTSTRAP.md           # ★ Главный гайд установки стека (новый)
├── STACK.md               # ★ Описание всех инструментов (новый)
├── VSCODE_EXTENSIONS.md   # ★ VS Code расширения (новый)
├── CLAUDE-SETUP.md        # Краткий гайд по .claude/
├── CLAUDE.md              # Режимы + language policy
├── README.md              # Этот файл
├── settings.json          # Permissions, hooks, statusLine
├── settings.local.json    # Локальный override (gitignored)
├── agents/company/        # 10 агентов (manager, developer, reviewer, investigator...)
├── commands/              # 37 slash-команд по категориям
│   ├── dev/               #   цикл разработки (8)
│   ├── quality/           #   метрики и анализ качества (15) — +arch-review
│   ├── analysis/          #   инспекция кода (3)
│   ├── spec/              #   спецификации (2)
│   ├── infra/             #   инфраструктура (6) — +diagrams
│   └── team/              #   команда и документация (4)
├── modes/                 # dev.md, spec.md
├── hooks/                 # SessionStart / PreToolUse / PostToolUse / PostCompact
├── skills/                # (расширяемо, kb-* удалены)
├── mcp/                   # MCP-инфраструктура (qex, sentrux, context7)
├── templates/             # ★ Шаблоны для нового проекта (новое)
│   ├── pyproject.template.toml
│   ├── pre-commit-config.template.yaml
│   ├── Makefile.template
│   ├── gitignore.template
│   ├── sentrux-rules.template.toml
│   └── claude-md.template.md
├── memory/                # Git-tracked project memory
└── platforms/             # settings.local шаблоны (macOS/Windows)
```

---

## Команды (`commands/`)

### `dev/` — Цикл разработки

| Команда | Действие |
|---------|----------|
| `/plan` | Manager → декомпозиция → ТЗ (Task X.Y) |
| `/plan-status` | Прогресс по плану текущей ветки |
| `/implement` | Developer → реализация задачи |
| `/test` | Tester → тесты по acceptance criteria |
| `/review` | Reviewer → код-ревью |
| `/debug` | Debugger → диагностика |
| `/ship` | Финальная проверка перед merge |
| `/pipeline` | Полный цикл: plan → implement → test → review → ship |

### `quality/` — Метрики и качество

| Команда | Действие |
|---------|----------|
| `/sentrux-health` | Снимок здоровья (scan + metrics) |
| `/sentrux-dsm` | Dependency Structure Matrix |
| `/sentrux-gaps` | Модули без тестов |
| `/sentrux-baseline` | Зафиксировать quality baseline |
| `/sentrux-diff` | Дельта с baseline |
| `/sentrux-check` | CI-friendly проверка правил (exit 0/1) |
| `/sentrux-rules` | Проверка `.sentrux/rules.toml` |
| `/sentrux-evolution` | Тренды метрик во времени |
| `/qex-status` | Статус qex-индекса |
| `/qex-reindex` | Инкрементальная переиндексация |
| `/qex-rebuild` | Полная переиндексация с нуля |
| `/code-stats` | Подсчёт LOC (stdlib) |
| `/code-stats-tokei` | Подсчёт LOC (tokei) |
| `/test-ratio` | Отношение тестов к коду |

### `analysis/` — Инспекция кода

| Команда | Действие |
|---------|----------|
| `/channel-map` | AST-карта IPC: FieldRouting + send_message |
| `/message-contracts` | Дамп SchemaBase/Message/BaseModel классов |
| `/todo-inventory` | TODO/FIXME/HACK с git blame |

### `spec/` — Спецификации

| Команда | Действие |
|---------|----------|
| `/spec` | Создать/обновить живое ТЗ |
| `/spec-sync` | Синхронизировать ТЗ с кодом |

### `infra/` — Инфраструктура

| Команда | Действие |
|---------|----------|
| `/validate` | `python scripts/validate.py` |
| `/fw-test` | `python scripts/run_framework_tests.py` |
| `/cold-start` | Ollama + venv init |
| `/run-proto` | Запуск прототипа |
| `/clean-cache` | Чистка Python-кэшей |

### `team/` — Команда

| Команда | Действие |
|---------|----------|
| `/team` | Показать состав |
| `/hire` | Создать нового агента |
| `/handoff` | Cross-machine context transfer |
| `/docs` | Docs Writer → документация |

---

## Агенты (`agents/company/`)

| Агент | Модель | Роль |
|-------|--------|------|
| `manager` | Opus | Декомпозиция → ТЗ (Task X.Y) |
| `teamlead` | Opus | Senior+ задачи, экспресс-ревью |
| `developer` | Sonnet | Реализация кода, smoke-тесты |
| `reviewer` | Opus | Код-ревью (архитектура + безопасность) |
| `tester` | Sonnet | Тесты по acceptance criteria |
| `debugger` | Sonnet | Тесты/runtime-ошибки: воспроизвести → найти → **пофиксить** (1-5 строк) |
| `investigator` | Opus | Cross-module архитектурные проблемы: **read-only** диагностика + отчёт |
| `docs-writer` | Haiku | README, STATUS, docstrings |
| `tech-writer` | Sonnet | ADR, ARCHITECTURE, RFC |
| `spec-writer` | Sonnet | Живое ТЗ (`docs/direction/`) |

**Пороги:** 1-3 файла → Director | 4-9 → Developer | 10+ → Manager → Developer → Reviewer

---

## Хуки (`hooks/`)

| Скрипт | Событие | Действие |
|--------|---------|----------|
| `session-health-check.sh` | SessionStart | Проверка Ollama (qex доступность) |
| `validate-safe-command.sh` | PreToolUse (Bash) | Блокирует опасные команды |
| `autoformat-python.sh` | PostToolUse (Edit/Write) | ruff format + check |
| `check-imports.sh` | PostToolUse (Edit/Write) | py_compile (синтаксис) |
| `filter-test-output.sh` | PostToolUse (Bash) | Фильтрация pytest — только ошибки |
| `restore-context.sh` | PostCompact | Восстановление критических правил после сжатия контекста |

---

## MCP-серверы

Подробнее: [`mcp/README.md`](mcp/README.md).

| Сервер | Назначение |
|--------|------------|
| **qex** | Семантический поиск по коду (Ollama + BM25) |
| **sentrux** | Архитектурный health-gate (DSM, метрики) |
| **Context7** | Документация библиотек (user-level) |

Установка: `python .claude/mcp/bootstrap.py`

---

## Memory (dual-write)

| Место | Git | Содержимое |
|-------|-----|------------|
| `~/.claude/projects/<hash>/memory/` | Нет | Всё (project, feedback, user, reference) |
| `docs/claude/memory/` | **Да** | project + feedback (между машинами) |

Правило: при записи → писать в **оба** места. Личное (user) — только локально.

---

## Двух-машинный workflow

После `git pull` на новой машине:
```bash
python .claude/mcp/bootstrap.py   # проверит зависимости
# /qex-reindex                    # если код изменился
```

`settings.local.json` — gitignored, шаблоны в `platforms/`.
