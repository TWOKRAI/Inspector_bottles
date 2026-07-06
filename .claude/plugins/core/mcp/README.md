# MCP-инфраструктура

Здесь живёт всё, что нужно Claude Code для работы с MCP-серверами в проекте.
Папка `.claude/plugins/core/mcp/` рассчитана на копирование вместе с `.claude/` в новые проекты.

## Состав

| Файл | Назначение |
|------|------------|
| `qex-launcher.py` | Запускает `qex` с правильной моделью под платформу (4b Windows / 8b macOS) |
| `README.md` | Этот файл |
| `qex/`                | Документация qex: quick-start, полный гайд, шаблоны (.ignore, hook, MCP-конфиг) |
| `sentrux/`            | Документация sentrux: метрики, slash-команды + шаблон `rules.template.toml` |
| `context7/`           | Документация Context7: установка, платформы, troubleshooting |
| `PORTABLE.md`         | Пошаговый чеклист переноса MCP-инфраструктуры в новый проект |

## MCP-серверы

### Core (документированы в seed, активируются bootstrap'ом)

| Сервер | Уровень | Назначение | Когда вызывать |
|--------|---------|------------|----------------|
| **qex** | проектный (`.mcp.json`) | Семантический поиск по коду (Ollama + BM25) | «где используется X», fuzzy intent, рефакторинг |
| **sentrux** | проектный (`.mcp.json`) | Архитектурный health-gate (DSM, метрики, gaps) | до/после рефакторинга, перед `/dev:ship`, поиск циклов |
| **Context7** | user-level (`~/.claude.json`) | Актуальная документация библиотек | работа с любыми внешними библиотеками |

### Optional (документированы в `mcp/<name>/`, активируются по необходимости в конкретном проекте)

| Сервер | Когда нужен | Документация |
|--------|-------------|--------------|
| **qt-mcp** | Только если проект использует **PyQt5/PySide6 GUI** — runtime inspection (widget tree, скриншоты, клики) | [qt-mcp/](qt-mcp/) |
| **graphify** | Architectural overview / knowledge graph — для onboarding в новый кодбейз и периодического review | [graphify/](graphify/) |
| **serena** | Symbol-level операции (refs, renames, moves) через LSP — **experimental**, см. known issues | [serena/](serena/) |
| **codegraph** | Function-level **callers/callees/impact** + framework routing (URL→handler); SQLite, без Ollama/GPU, file-watcher | [codegraph/](codegraph/) |
| **github** | Official GitHub MCP (Issues/PR/Actions/Projects); remote OAuth или локальный binary + PAT | [github/](github/) |
| **ast-grep** | Структурный AST-поиск **и переписывание** (codemod) на 20+ языках; rules для проектных линтов | [ast-grep/](ast-grep/) |
| **playwright** | Browser automation + UI verification (navigate, screenshot, click). Закрывает дыру **web-UI verify-done** | [playwright/](playwright/) |
| **sequential-thinking** | Externalized chain-of-thought scratchpad. Полезен investigator/teamlead на 3-й гипотезе или эскалации | [sequential-thinking/](sequential-thinking/) |

> Подробнее о ролях qex vs sentrux vs graphify vs serena vs codegraph — в корневом `CLAUDE.md` шаблона
> (раздел "Tool routing"). Один и тот же запрос можно адресовать разным инструментам —
> правила маршрутизации помогают агенту выбирать нужный.

### Не в core, обсуждаются в ROADMAP

См. `../docs/ROADMAP.md` § D — кандидаты для будущих opt-in модулей:
**claude-context** (конкурент qex), **preflight** (валидатор промптов),
**container-use** (изолированные dev env), **claude-mem** (семантика над сессиями).

> **codegraph** перенесён из § D в Optional (см. таблицу выше) — реализован как opt-in модуль
> `mcp/codegraph/`. Закрывает дыру function-level call graph + impact analysis, которой
> не было у qex/sentrux/graphify.

### Не MCP, но в инфраструктуре `.claude/`

| Модуль | Назначение | Документация |
|--------|-----------|--------------|
| **observability** | OTel-телеметрия + ccusage/ccstatusline для замера токенов и tool calls (`CLAUDE_CODE_ENABLE_TELEMETRY=1` + Docker stack или statusline-инструменты) | [`../observability/`](../observability/) |

## Документация MCP-серверов

### Core

| Документ | Что внутри |
|----------|------------|
| [qex/README.md](qex/README.md) | Quick-start qex (5 шагов) |
| [qex/SETUP_GUIDE.md](qex/SETUP_GUIDE.md) | Полный гайд: архитектура, Windows + macOS, диагностика |
| [sentrux/README.md](sentrux/README.md) | Метрики, slash-команды, сценарии использования |
| [sentrux/rules.template.toml](sentrux/rules.template.toml) | Шаблон архитектурных правил для нового проекта |
| [context7/README.md](context7/README.md) | Установка Context7, платформы, troubleshooting |
| [PORTABLE.md](PORTABLE.md) | Чеклист переноса в новый проект |

### Optional

| Документ | Что внутри |
|----------|------------|
| [qt-mcp/README.md](qt-mcp/README.md) + [SETUP_GUIDE.md](qt-mcp/SETUP_GUIDE.md) | PyQt/PySide runtime inspection — для GUI-проектов |
| [graphify/README.md](graphify/README.md) + [SETUP_GUIDE.md](graphify/SETUP_GUIDE.md) | Knowledge graph кодбейза — для архитектурного обзора |
| [serena/README.md](serena/README.md) + [SETUP_GUIDE.md](serena/SETUP_GUIDE.md) | LSP-symbol retrieval — experimental, см. known issues |
| [codegraph/README.md](codegraph/README.md) + [SETUP_GUIDE.md](codegraph/SETUP_GUIDE.md) | Pre-indexed call graph (callers/callees/impact), framework routing — SQLite, без Ollama |
| [github/README.md](github/README.md) + [SETUP_GUIDE.md](github/SETUP_GUIDE.md) | Official GitHub MCP — Issues/PR/Actions/Projects, OAuth scope filtering |
| [ast-grep/README.md](ast-grep/README.md) + [SETUP_GUIDE.md](ast-grep/SETUP_GUIDE.md) | Structural search + **rewrite** (codemods) across 20+ languages |

## Установка в новый проект

### Быстрый путь — через claude-kit

`.mcp.json` создаётся автоматически при `claude-kit-project new` (или `claude-kit-claude plugin enable <plugin-id>`).
Генератор берёт `mcp_servers:` блоки выбранных компонентов из `manifest.yaml` и собирает `.mcp.json` с нуля.

После создания проекта через `claude-kit-project new`:

```bash
# Если Context7 ещё не настроен (на новой машине)
npx -y ctx7 setup --claude

# Перезапустить Claude Code и проверить
> /mcp
```

> `.ignore` (qex whitelist) создаётся не через bootstrap, а через `qex-launcher.py`
> при первом старте qex — так его жизненный цикл привязан к активации qex, а не к
> отдельному ручному шагу. Bootstrap проверяет только зависимости.

Подробнее о Context7 — в [context7/README.md](context7/README.md).

## Как qex знает корень проекта

`qex-launcher.py` лежит в `.claude/plugins/mcp-qex/`, но qex'у нужен путь к корню проекта (для индексации).
Скрипт вычисляет его так:

```python
_script_dir = os.path.dirname(os.path.realpath(__file__))    # .claude/mcp
workspace = os.path.dirname(os.path.dirname(_script_dir))    # корень
```

`realpath` нужен для корректного вычисления корня проекта независимо от способа запуска скрипта.

## Платформенная разница в qex

| Платформа | Embedding-модель | Размерность | Бинарь по умолчанию |
|-----------|------------------|-------------|---------------------|
| macOS / Linux | `qwen3-embedding:8b` | 4096 | `~/.local/bin/qex` |
| Windows | `qwen3-embedding:4b` | 2560 | `~/.cargo/bin/qex.exe` |

Логика в `qex-launcher.py` через `platform.system()`. Можно переопределить через env `QEX_BIN`.

## Ручная установка зависимостей

```bash
# 1. sentrux
brew install sentrux/tap/sentrux            # macOS
# или install.sh для Linux, exe для Windows

# 2. ollama + модель
brew install ollama                         # macOS
ollama pull qwen3-embedding:8b              # macOS / Linux
# ollama pull qwen3-embedding:4b            # Windows

# 3. .mcp.json генерируется claude-kit из manifest.yaml
#    (см. `claude-kit-project new` или `claude-kit-claude plugin enable <plugin-id>`)

# 4. Context7 (user-level, один раз на машину)
npx -y ctx7 setup --claude
```

## Troubleshooting

**`/mcp` показывает qex как failed:**
- Запусти `ollama serve` (или `/core:infra:cold-start`)
- Проверь модель: `ollama list | grep qwen3-embedding`
- Проверь бинарь: `which qex`

**`/mcp` показывает sentrux как failed:**
- Проверь бинарь: `which sentrux`
- Проверь subcommand: `sentrux mcp --help` (должен быть `Start the MCP server`)

**Context7 не отвечает:**
- Проверь `~/.claude.json` — должен быть блок `context7` с API key
- Перезапусти `npx -y ctx7 setup --claude` для повторной авторизации
