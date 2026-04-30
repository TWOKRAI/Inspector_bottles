# .claude/ — Конфигурация KnowledgeOS

Агентная система двух команд: IT-Компания и Исследовательский Университет.
Проектный контекст — в корневом `CLAUDE.md`.

---

## Файлы конфигурации

| Файл | Назначение |
|------|-----------|
| `CLAUDE.md` | Workflow обеих команд (универсальный) |
| `../CLAUDE.md` | Проектный контекст (пайплайн, правила, пути) |
| `CLAUDE-SETUP.md` | Установка: Python, ffmpeg, Ollama, API ключи |
| `settings.json` | Разрешения инструментов, хуки, statusLine |
| `settings.local.json` | Локальный override (gitignored) |
| `mcp.json` | MCP-серверы (qex семантический поиск) |

---

## IT-Компания по разработке

Агенты: `agents/company/`

| Агент | Модель | Роль |
|-------|--------|------|
| `manager` | Sonnet 4.6 | Декомпозиция задачи → ТЗ с уровнями сложности (Task X.Y) |
| `teamlead` | Opus 4.6 | Старший разработчик — Senior+ задачи, экспресс-ревью |
| `developer` | Sonnet 4.6 | Реализация кода по ТЗ, smoke-тесты, коммиты |
| `reviewer` | Opus 4.6 | Финальный код-ревью (архитектура + безопасность) |
| `tester` | Sonnet 4.6 | Тесты по acceptance criteria |
| `docs-writer` | Haiku 4.5 | Документация, docstrings, README |
| `_template` | — | Шаблон для `/hire` (в корне agents/) |

### Workflow разработки

```
/plan → /implement → /test → /review → /docs → /ship
Полный автомат: /pipeline
Нанять нового специалиста: /hire
```

### Пороги сложности

| Объём | Исполнитель |
|-------|-------------|
| 1-3 файла, <80 строк | Director (main) |
| 4-9 файлов | Developer → TeamLead (экспресс-ревью) |
| 10+ файлов, архитектура | Manager → Developer → Reviewer |

---

## Исследовательский Университет

Агенты: `agents/university/`

| Агент | Модель | Роль |
|-------|--------|------|
| `sci-transcriber` | Sonnet 4.6 | Видео/аудио URL → транскрипт в `knowledge/raw/videos/` |
| `sci-curator` | Sonnet 4.6 | Организует inbox → raw → создаёт/обновляет wiki-статьи |
| `sci-researcher` | Opus 4.6 | Глубокий Q&A по wiki, перекрёстный анализ источников |
| `sci-synthesizer` | Opus 4.6 | Несколько источников → новая сводная wiki-статья |
| `sci-translator` | Sonnet/Haiku | EN→RU перевод (Haiku <300 слов, Sonnet для технического) |

### Workflow знаний

```
/transcribe <url> → /curate → wiki
                           → /synthesize <тема> → wiki
                           → /research <вопрос>
/translate <файл>  → {файл}_ru.md
```

---

## Команды (commands/)

### Университет

| Команда | Файл | Действие |
|---------|------|----------|
| `/transcribe` | `transcribe.md` | URL → скачать → Whisper → `raw/videos/` |
| `/curate` | `curate.md` | inbox + raw → wiki-статьи + индекс |
| `/research` | `research.md` | Вопрос → Q&A по wiki |
| `/synthesize` | `synthesize.md` | Тема → сводная wiki-статья |
| `/translate` | `translate.md` | Файл → {файл}_ru.md (Haiku/Sonnet) |

### IT-Компания

| Команда | Файл | Действие |
|---------|------|----------|
| `/pipeline` | `pipeline.md` | Полный цикл разработки |
| `/plan` | `plan.md` | Manager → декомпозиция → ТЗ |
| `/implement` | `implement.md` | Developer → реализация Task X.Y |
| `/test` | `test.md` | Tester → тесты |
| `/review` | `review.md` | Reviewer → код-ревью |
| `/docs` | `docs.md` | Docs Writer → документация |
| `/ship` | `ship.md` | Финальная проверка перед merge |

### Общие

| Команда | Файл | Действие |
|---------|------|----------|
| `/team` | `team.md` | Показать обе команды |
| `/hire` | `hire.md` | Создать нового агента по шаблону |

---

## Хуки (hooks/)

| Скрипт | Тип | Действие |
|--------|-----|----------|
| `validate-safe-command.sh` | PreToolUse (Bash) | Блокирует опасные команды |
| `autoformat-python.sh` | PostToolUse (Edit/Write) | `ruff format` + `ruff check --fix` |
| `check-imports.sh` | PostToolUse (Edit/Write) | Проверка синтаксиса Python |

---

## Добавить нового специалиста

1. Запусти `/hire <роль>` — создаст агента по шаблону
2. Выбери папку: `agents/company/` (IT) или `agents/university/` (наука)
3. Заполни: name, description, model, tools, workflow
4. Обнови таблицы в `.claude/CLAUDE.md` и `README.md`
5. При необходимости добавь команду в `commands/`
