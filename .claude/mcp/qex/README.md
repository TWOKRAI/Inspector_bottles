# qex — семантический поиск по кодовой базе

Эта папка — **всё, что нужно для настройки qex + Ollama в новом проекте**.
Скопируй её целиком в новый проект, пройди 5 шагов ниже, и поиск работает.

## Что это

**qex** (v0.0.2, feature `vector`) — локальный MCP-сервер (Rust), который делает
гибридный (BM25 + dense) семантический поиск по кодовой базе. Встраивается в Claude Code через MCP.

- **BM25** индексирует Tantivy — локальный файл в `~/.qex/`.
- **Dense-векторы** считает Ollama (`qwen3-embedding:4b`, 2560-dim) и складывает в `~/.qex/` (JSON-файл, brute-force cosine).
- **Чанкинг** — tree-sitter по AST (классы, функции, методы).
- **Ignore-правила** читаются из `.gitignore` и `.ignore` (как у ripgrep) автоматически.

Docker и Qdrant **не нужны**. Единственная внешняя зависимость — Ollama.

Полная документация с архитектурой, диагностикой и решениями проблем — в [SETUP_GUIDE.md](./SETUP_GUIDE.md).

## Quick-start (5 шагов)

Предполагается, что бинарник `qex` и Ollama уже установлены глобально
(инструкции в [SETUP_GUIDE.md](./SETUP_GUIDE.md), секции 3–5). Для **нового проекта**:

### 1. Скопируй шаблон `.ignore` в корень проекта

```bash
cp .claude/mcp/qex/templates/ignore.template .ignore
```

Открой `.ignore` и отредактируй whitelist-блок под свой проект — оставь только активные
рабочие директории, всё остальное исключи. Это критично для качества поиска:
меньше шума = чище ранжирование. См. комментарии внутри шаблона.

### 2. Создай `.mcp.json` в корне проекта

Скопируй шаблон `templates/mcp-config.json.snippet` в `.mcp.json` (корень проекта).
Замени два плейсхолдера:

- `<QEX_BINARY_PATH>` — абсолютный путь к `qex` (обычно `~/.cargo/bin/qex` на macOS, `~\.cargo\bin\qex.exe` на Windows)
- `<PROJECT_ABSOLUTE_PATH>` — абсолютный путь к корню проекта

### 3. Запусти Ollama

```bash
# Ollama — ОБЯЗАТЕЛЬНО до запуска Claude Code
ollama serve &

# Проверка
curl -s http://localhost:11434/ && echo " Ollama OK"
```

### 4. Перезапусти Claude Code

Чтобы новая MCP-конфигурация подхватилась. В VS Code: `Ctrl/Cmd+Shift+P → Developer: Reload Window`.

### 5. Первая индексация

В чате с Claude Code:

```
mcp__qex__index_codebase(path="<PROJECT_ABSOLUTE_PATH>", force=true)
```

Через 30-40 минут (зависит от размера кодовой базы и GPU) — готово. Проверка:

```
mcp__qex__get_indexing_status(path="<PROJECT_ABSOLUTE_PATH>")
mcp__qex__search_code(path="<PROJECT_ABSOLUTE_PATH>", query="главный класс приложения")
```

## Ежедневный запуск

```bash
ollama serve &
# Запускаешь Claude Code — qex поднимается автоматически
```

## Когда переиндексировать

- После крупных изменений кода — `mcp__qex__index_codebase(path=..., force=true)`.
- После смены embedding-модели — `clear_index` → `index_codebase(force=true)`.
- После правок `.ignore` — обязательно `clear_index` + `index_codebase(force=true)`, иначе исключённые файлы останутся в индексе.
- Опционально: git post-commit hook для автоматической переиндексации — см. `templates/post-commit.hook.sh`.

## Когда НЕ нужен qex

- Знаешь точный путь файла → используй Read / Grep напрямую, это быстрее и точнее.
- Ищешь по точному имени символа, которое уникально → Grep с `-n` быстрее.
- qex нужен, когда ищешь **по смыслу** или **не помнишь путь**.

## Структура папки

```
.claude/mcp/qex/
├── README.md                       # этот файл
├── SETUP_GUIDE.md                  # полный гайд (Windows + macOS, диагностика)
└── templates/
    ├── ignore.template             # шаблон .ignore для whitelist-фильтра
    ├── mcp-config.json.snippet     # JSON для .claude/mcp.json
    └── post-commit.hook.sh         # опциональный git hook для auto-reindex
```

## Ссылки

- [SETUP_GUIDE.md](./SETUP_GUIDE.md) — полный мануал (архитектура, диагностика, типичные проблемы)
- [templates/ignore.template](./templates/ignore.template) — шаблон .ignore
- [templates/mcp-config.json.snippet](./templates/mcp-config.json.snippet) — MCP-конфиг
- [templates/post-commit.hook.sh](./templates/post-commit.hook.sh) — git hook
## Launcher options

**Default** (used automatically by `claude-kit add qex`): see `manifest.yaml` → `mcp_servers.qex`.

```
command: python
args: [".claude/mcp/qex-launcher.py"]
```

Only one launcher — qex bootstraps itself via the local Python interpreter.

Switching: edit `.mcp.json` manually (it's not regenerated for non-manifest content).
