# BOOTSTRAP — Полный dev-стек для нового проекта

Точка входа для разворачивания инфраструктуры разработки в новом Python-проекте на основе текущей конфигурации.
Описывает: что копировать, что устанавливать, в каком порядке, на macOS и Windows.

> **TL;DR — 5 шагов:**
> 1. Скопировать `.claude/`, `CLAUDE.md`, `Makefile`, `pyproject.toml`, `.pre-commit-config.yaml`
> 2. Установить системные пакеты (Make, Graphviz, Ollama, Node)
> 3. `uv sync --group dev --group diagrams`
> 4. `python .claude/mcp/bootstrap.py` + `npx -y ctx7 setup --claude`
> 5. `uv run pre-commit install && uv run pre-commit install --hook-type pre-push`

---

## Часть 1. Что копировать в новый проект

### Обязательно

| Что | Путь | Назначение |
|-----|------|-----------|
| `.claude/` | целиком в корень | Агенты, команды, хуки, MCP, режимы, шаблоны |
| `CLAUDE.md` | корень | Проектный контекст (АДАПТИРОВАТЬ под новый проект) |
| `Makefile` | корень | Единая точка входа (check, test, gate, diagrams) |
| `.pre-commit-config.yaml` | корень | Quality gates (ruff, mypy, bandit) |
| `.gitignore` | корень | Адаптировать (см. секцию для diagrams) |
| `.gitmessage` | корень | Шаблон commit-сообщений с trailers |

### Опционально (по необходимости)

| Что | Путь | Когда нужно |
|-----|------|-------------|
| `.sentrux/rules.toml` | корень | Когда есть архитектурные слои |
| `pyproject.toml` | корень | Для Python-проектов (шаблон в `.claude/templates/`) |
| `docs/diagrams/` | корень | Структура для diagrams-as-code |
| `scripts/validate_commit/` | корень | Git hook для commit-сообщений |

### Не копировать

| Что | Почему |
|-----|--------|
| `.mcp.json` | Генерируется `bootstrap.py` |
| `.sentrux/baseline.json` | Генерируется первым `session_start` |
| `.qex-reindex.log` | Артефакт индексации |
| `.venv/`, `__pycache__/` | Локальные кэши |
| `CLAUDE.local.md`, `.claude/settings.local.json` | Локальные настройки (gitignored) |

---

## Часть 2. Системные зависимости

### macOS

```bash
# Базовое
brew install make graphviz ollama node uv

# MCP-серверы
brew install sentrux/tap/sentrux           # архитектурный анализ
ollama pull qwen3-embedding:8b              # embedding для qex (4096-dim)
```

### Windows

```powershell
# Через winget (или скачать installers вручную)
winget install GnuWin32.Make                # для Makefile
winget install Graphviz                     # для pydeps SVG
winget install Ollama.Ollama                # для qex
winget install OpenJS.NodeJS.LTS            # для Context7
winget install astral-sh.uv                 # Python пакетный менеджер

# Альтернатива через choco:
# choco install make graphviz ollama nodejs uv

# MCP-серверы
# sentrux: скачать с https://github.com/sentrux/sentrux/releases
ollama pull qwen3-embedding:4b              # embedding для qex (2560-dim)
```

**ВАЖНО Windows:** после установки Graphviz убедись что `C:\Program Files\Graphviz\bin` в PATH.
Проверка: `dot -V` должно вывести версию.

---

## Часть 3. VS Code расширения

Полный список с обоснованием — в [`VSCODE_EXTENSIONS.md`](VSCODE_EXTENSIONS.md).

**Минимум для нового проекта:**

```bash
# Diagrams
code --install-extension hediet.vscode-drawio
code --install-extension jebbs.plantuml
code --install-extension bierner.markdown-mermaid

# Python
code --install-extension charliermarsh.ruff
code --install-extension ms-python.python
code --install-extension ms-python.mypy-type-checker

# Claude Code
code --install-extension anthropic.claude-code
```

---

## Часть 4. Установка Python-окружения

```bash
# 1. Создать venv и установить зависимости
uv sync --group dev --group diagrams

# 2. Установить pre-commit хуки
uv run pre-commit install                       # на pre-commit
uv run pre-commit install --hook-type pre-push  # на pre-push (mypy)

# 3. Проверить что инструменты работают
uv run ruff --version
uv run mypy --version
uv run bandit --version
uv run pyreverse --version
uv run pydeps --version
```

---

## Часть 5. MCP-инфраструктура

```bash
# 1. Bootstrap MCP-серверов (создаёт .mcp.json из шаблона)
python .claude/mcp/bootstrap.py

# 2. Context7 (один раз на машину, user-level)
npx -y ctx7 setup --claude

# 3. Перезапустить Claude Code

# 4. Проверить
> /mcp        # qex, sentrux, context7 — все зелёные
```

Подробности по MCP — [`mcp/README.md`](mcp/README.md) и [`mcp/PORTABLE.md`](mcp/PORTABLE.md).

---

## Часть 6. Sentrux baseline

После установки sentrux + индексации qex:

```bash
# 1. Скопировать шаблон правил
cp .claude/templates/sentrux-rules.template.toml .sentrux/rules.toml

# 2. Адаптировать .sentrux/rules.toml под слои нового проекта
#    (см. комментарии в шаблоне)

# 3. Зафиксировать baseline
/sentrux-baseline

# 4. Проверить здоровье
/sentrux-health
```

---

## Часть 7. Первый запуск — проверочный чек-лист

```bash
# 1. Линт
uv run ruff check .

# 2. Типы
uv run mypy <main-package> --ignore-missing-imports

# 3. Безопасность
uv run bandit -r <main-package> -c pyproject.toml -q

# 4. Тесты (если есть)
uv run pytest

# 5. Диаграммы
uv run pyreverse -o puml -p Project <main-package> -d docs/diagrams/classes/

# 6. Если установлен make
make help     # увидеть все targets
make check    # ruff + mypy + bandit
make gate     # полный gate
```

---

## Часть 8. Адаптация под новый проект

### CLAUDE.md (корень)

Адаптируй секции:
- **Проект** — описание
- **Архитектура** — модули, слои
- **Ключевые пути** — где что лежит
- **Стек** — версии Python, фреймворки
- **Правила проекта** — специфические инварианты

### pyproject.toml

Замени:
- `name`, `version`, `description`
- Список зависимостей под свой стек
- `[tool.pytest.ini_options].testpaths` под структуру тестов
- `[tool.mypy].exclude` под исключения
- `[tool.coverage.run].source` под основной пакет

### Makefile

Замени переменные в начале файла:
- `FRAMEWORK` → главный пакет
- `PROTOTYPE`, `SERVICES`, `PLUGINS` → подпакеты (или удалить)

### .sentrux/rules.toml

Замени `[[layers]]` и `[[boundaries]]` под слои нового проекта.

---

## Связанные документы

| Документ | Что внутри |
|----------|------------|
| [`STACK.md`](STACK.md) | Полный стек инструментов с обоснованием |
| [`VSCODE_EXTENSIONS.md`](VSCODE_EXTENSIONS.md) | VS Code расширения по категориям |
| [`CLAUDE-SETUP.md`](CLAUDE-SETUP.md) | Краткий гайд по `.claude/` (без dev-стека) |
| [`mcp/PORTABLE.md`](mcp/PORTABLE.md) | Детальный перенос MCP-серверов |
| [`mcp/qex/SETUP_GUIDE.md`](mcp/qex/SETUP_GUIDE.md) | Полный гайд установки qex |
| [`templates/`](templates/) | Готовые шаблоны pyproject, pre-commit, Makefile |

---

## Troubleshooting

| Проблема | Решение |
|----------|---------|
| `pre-commit: command not found` | `uv add --group dev pre-commit` + `uv run pre-commit install` |
| `make: command not found` (Windows) | Установить GnuWin32.Make или вызывать команды напрямую: `uv run ruff check .` |
| `dot: command not found` для pydeps | Установить Graphviz и добавить в PATH |
| VS Code Marketplace не работает | Проверить `http.proxy` в `settings.json` (закомментировать если прокси не запущен) |
| Кракозябры в cmd-выводе на Windows | Это CP866. Нормально для bash-терминала, не баг |
| `pyreverse` падает на >500 KB файле | `.gitignore` уже игнорирует `docs/diagrams/classes/*.puml` |

**VS Code прокси-проблема:** если включён `"http.proxy"` в `settings.json` но прокси не запущен —
Marketplace падает. Закомментировать строку и Reload Window.
