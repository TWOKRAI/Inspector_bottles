# qex — семантический поиск по кодовой базе

Эта папка — **всё, что нужно для настройки qex + Qdrant + Ollama в новом проекте**.
Скопируй её целиком в новый проект, пройди 5 шагов ниже, и поиск работает.

## Что это

**qex-mcp-v2** — локальный MCP-сервер (Rust), который делает гибридный (BM25 + dense)
семантический поиск по кодовой базе. Встраивается в Claude Code через MCP.

- **BM25** индексирует Tantivy — локальный файл в `~/.qex/`.
- **Dense-векторы** считает Ollama (`qwen3-embedding:4b`, 2560-dim) и складывает в Qdrant (локальный или облачный).
- **Чанкинг** — tree-sitter по AST (классы, функции, методы).
- **Ignore-правила** читаются из `.gitignore` и `.ignore` (как у ripgrep) автоматически.

Полная документация с архитектурой, диагностикой и решениями проблем — в [SETUP_GUIDE.md](./SETUP_GUIDE.md).

## Quick-start (5 шагов)

Предполагается, что бинарник `qex-mcp-v2`, Qdrant и Ollama уже установлены глобально
(инструкции в [SETUP_GUIDE.md](./SETUP_GUIDE.md), секции 3–6). Для **нового проекта**:

### 1. Скопируй шаблон `.ignore` в корень проекта

```bash
cp docs/claude/qex/templates/ignore.template .ignore
```

Открой `.ignore` и отредактируй whitelist-блок под свой проект — оставь только активные
рабочие директории, всё остальное исключи. Это критично для качества поиска:
меньше шума = чище ранжирование. См. комментарии внутри шаблона.

### 2. Добавь MCP-сервер в `~/.claude.json`

Открой шаблон `templates/mcp-config.json.snippet`, скопируй JSON и вставь в
`~/.claude.json` → `projects` → `<путь к новому проекту>`. Замени три плейсхолдера:

- `<PROJECT_ABSOLUTE_PATH>` — абсолютный путь к корню нового проекта
- `<QEX_BINARY_PATH>` — абсолютный путь к `qex-mcp-v2` (обычно `~/.local/bin/qex-mcp-v2` на macOS)
- `<COLLECTION_NAME>` — уникальное имя коллекции Qdrant для этого проекта (например `myproj_index`)

> **Важно:** коллекцию именуй уникально на каждый проект, чтобы индексы разных проектов не смешивались в одной Qdrant.

### 3. Холодный старт инфраструктуры

```bash
# Qdrant (Docker — контейнер создаётся один раз, потом просто start)
docker start qdrant

# Ollama — ОБЯЗАТЕЛЬНО до запуска Claude Code
ollama serve &

# Проверка, что оба подняты
curl -s http://localhost:6333/healthz && echo " Qdrant OK"
curl -s http://localhost:11434/       && echo " Ollama OK"
```

### 4. Перезапусти Claude Code

Чтобы новая MCP-конфигурация подхватилась. В VS Code: `Cmd+Shift+P → Developer: Reload Window`.

### 5. Первая индексация

В чате с Claude Code:

```
mcp__qex__index_codebase(path="<PROJECT_ABSOLUTE_PATH>", force=true)
```

Через 1–5 минут (зависит от размера кодовой базы) — готово. Проверка:

```
mcp__qex__get_indexing_status(path="<PROJECT_ABSOLUTE_PATH>")
mcp__qex__search_code(path="<PROJECT_ABSOLUTE_PATH>", query="главный класс приложения")
```

## Ежедневный запуск

```bash
docker start qdrant
ollama serve &
# Запускаешь Claude Code — qex поднимается автоматически
```

## Когда переиндексировать

- После крупных изменений кода — `mcp__qex__index_codebase(path=..., force=true)`.
- После смены embedding-модели — `clear_index` → удалить коллекцию в Qdrant → `index_codebase(force=true)`.
- После правок `.ignore` — обязательно `clear_index` + `index_codebase(force=true)`, иначе исключённые файлы останутся в индексе.
- Опционально: git post-commit hook для автоматической переиндексации — см. `templates/post-commit.hook.sh`.

## Когда НЕ нужен qex

- Знаешь точный путь файла → используй Read / Grep напрямую, это быстрее и точнее.
- Ищешь по точному имени символа, которое уникально → Grep с `-n` быстрее.
- qex нужен, когда ищешь **по смыслу** или **не помнишь путь**.

## Структура папки

```
docs/claude/qex/
├── README.md                       # этот файл
├── SETUP_GUIDE.md                  # полный гайд (Windows + macOS, диагностика, облако)
└── templates/
    ├── ignore.template             # шаблон .ignore для whitelist-фильтра
    ├── mcp-config.json.snippet     # JSON для ~/.claude.json
    └── post-commit.hook.sh         # опциональный git hook для auto-reindex
```

## Ссылки

- [SETUP_GUIDE.md](./SETUP_GUIDE.md) — полный мануал (архитектура, Qdrant Cloud, диагностика, типичные проблемы)
- [templates/ignore.template](./templates/ignore.template) — шаблон .ignore
- [templates/mcp-config.json.snippet](./templates/mcp-config.json.snippet) — MCP-конфиг
- [templates/post-commit.hook.sh](./templates/post-commit.hook.sh) — git hook
