# MCP-инфраструктура

Здесь живёт всё, что нужно Claude Code для работы с MCP-серверами в проекте.
Папка `.claude/mcp/` рассчитана на копирование вместе с `.claude/` в новые проекты.

## Состав

| Файл | Назначение |
|------|------------|
| `mcp.template.json` | Эталон проектного `.mcp.json` (qex + sentrux + serena + qt-mcp) |
| `qex-launcher.py` | Запускает `qex` с правильной моделью под платформу (4b Windows / 8b macOS) |
| `bootstrap.py` | Автонастройка нового проекта — ставит зависимости, копирует template (кросс-платформа: macOS/Linux/Windows) |
| `README.md` | Этот файл |
| `qex/`                | Документация qex: quick-start, полный гайд, шаблоны (.ignore, hook, MCP-конфиг) |
| `sentrux/`            | Документация sentrux: метрики, slash-команды + шаблон `rules.template.toml` |
| `context7/`           | Документация Context7: установка, платформы, troubleshooting |
| `serena/`             | Документация Serena: LSP-семантика для рефакторинга и точных references |
| `qt-mcp/`             | Документация qt-mcp: инспекция запущенного PySide6 (widget tree, screenshots) |
| `pytest-runner/`      | **⚠️ Отложено** — pytest MCP-сервер: ресёрч кандидатов, причины отложения, чек-лист возврата |
| `PORTABLE.md`         | Пошаговый чеклист переноса MCP-инфраструктуры в новый проект |

## MCP-серверы

| Сервер | Уровень | Назначение | Когда вызывать |
|--------|---------|------------|----------------|
| **qex** | проектный (`.mcp.json`) | Семантический поиск по коду (Ollama + BM25) | «где похоже на X», рефакторинг, смена API |
| **sentrux** | проектный (`.mcp.json`) | Архитектурный health-gate (DSM, метрики, gaps) | до/после рефакторинга, перед `/ship`, поиск циклов |
| **Context7** | user-level (`~/.claude.json`) | Актуальная документация библиотек | работа с PySide6, Pydantic, PyTorch и др. быстро меняющимися либами |
| **serena** | проектный (`.mcp.json`) | LSP-уровневый refactor: точные references, rename, symbol-edit | rename, extract, «все вызовы метода X» |
| **qt-mcp** | проектный (`.mcp.json`) | Инспекция запущенного PySide6: widget tree, screenshots, клики | дебаг GUI, smoke-проверки frontend, воспроизведение сценариев |

**Отложено:**
- `test-runner` — pytest MCP-сервер. На 2026-05 в реестрах нет зрелого опубликованного пакета (`test-runner-mcp` 404 в npm, `jwilger/mcp-pytest-runner` 404 в GitHub). Pytest сейчас вызывается через встроенный Bash MCP. Подробнее: [pytest-runner/README.md](pytest-runner/README.md).

Подробнее о ролях qex vs sentrux — в `CLAUDE.md` (секции «MCP: qex» и «MCP: sentrux»).
Подробнее о ролях qex vs serena — в `serena/README.md` (раздел «Когда звать»).

## Документация MCP-серверов

| Документ | Что внутри |
|----------|------------|
| [qex/README.md](qex/README.md) | Quick-start qex (5 шагов) |
| [qex/SETUP_GUIDE.md](qex/SETUP_GUIDE.md) | Полный гайд: архитектура, Windows + macOS, диагностика |
| [sentrux/README.md](sentrux/README.md) | Метрики, slash-команды, сценарии использования |
| [sentrux/rules.template.toml](sentrux/rules.template.toml) | Шаблон архитектурных правил для нового проекта |
| [context7/README.md](context7/README.md) | Установка Context7, платформы, troubleshooting |
| [serena/README.md](serena/README.md) | Quick-start Serena: что это, vs qex, конфиг |
| [serena/SETUP_GUIDE.md](serena/SETUP_GUIDE.md) | Полная установка Serena: uv tool, LSP, troubleshooting |
| [qt-mcp/README.md](qt-mcp/README.md) | Quick-start qt-mcp: probe в PySide6, ключевые tools |
| [qt-mcp/SETUP_GUIDE.md](qt-mcp/SETUP_GUIDE.md) | Полная установка qt-mcp: интеграция probe в run.py, Windows-нюансы |
| [pytest-runner/README.md](pytest-runner/README.md) | **⚠️ Отложено** — статус pytest MCP, альтернатива через Bash MCP |
| [pytest-runner/SETUP_GUIDE.md](pytest-runner/SETUP_GUIDE.md) | Детальный ресёрч: проверенные кандидаты, чек-лист возврата |
| [PORTABLE.md](PORTABLE.md) | Чеклист переноса в новый проект |

## Установка в новый проект

### Быстрый путь — через bootstrap

**macOS / Linux:**
```bash
# 1. Скопировать .claude в новый проект
cp -r /path/to/Inspector_bottles/.claude /path/to/new-project/

# 2. Запустить bootstrap
cd /path/to/new-project
python3 .claude/mcp/bootstrap.py

# 3. Если Context7 ещё не настроен (на новой машине)
npx -y ctx7 setup --claude

# 4. Перезапустить Claude Code
```

**Windows (PowerShell или cmd):**
```powershell
# 1. Скопировать .claude
Copy-Item -Recurse C:\path\to\Inspector_bottles\.claude C:\path\to\new-project\

# 2. Запустить bootstrap
cd C:\path\to\new-project
python .claude\mcp\bootstrap.py

# 3. Context7 (если ещё не настроен)
npx -y ctx7 setup --claude

# 4. Перезапустить Claude Code
```

### Что делает bootstrap

1. **sentrux** — `brew install sentrux/tap/sentrux` (macOS) или подсказывает install-команду для Linux/Windows
2. **ollama** — проверяет наличие, подсказывает `ollama pull qwen3-embedding:{8b|4b}` под платформу
3. **node/npx** — проверяет, нужен для Context7
4. **`.mcp.json`** — копирует `mcp.template.json` в корень проекта (с защитой от перезаписи существующего)
5. **`.sentrux/rules.toml`** — копирует шаблон архитектурных правил (с защитой от перезаписи)

Подробнее о Context7 — в [context7/README.md](context7/README.md).

### Дополнительные MCP (вне bootstrap)

Serena, qt-mcp и test-runner-mcp в `bootstrap.py` **не автоматизированы** — у каждого свой стек (uv tool / pip / npm) и условия активации. Установить по гайдам:

```powershell
# Serena (LSP-семантика)
uv tool install -p 3.13 serena-agent@latest --prerelease=allow
# подробнее: serena/SETUP_GUIDE.md

# qt-mcp (инспекция PySide6) — требует probe в frontend/app.py + env QT_MCP_PROBE
uv add --dev "qt-mcp @ git+https://github.com/0xCarbon/qt-mcp.git"
# подробнее: qt-mcp/SETUP_GUIDE.md
```

После всех установок — перезапуск Claude Code и проверка `/mcp` (ожидаемо: 4 проектных + Context7).

## Как qex знает корень проекта

`qex-launcher.py` лежит в `.claude/mcp/`, но qex'у нужен путь к корню проекта (для индексации).
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

## Ручная установка (если bootstrap не подходит)

```bash
# 1. sentrux
brew install sentrux/tap/sentrux            # macOS
# или install.sh для Linux, exe для Windows

# 2. ollama + модель
brew install ollama                         # macOS
ollama pull qwen3-embedding:8b              # macOS / Linux
# ollama pull qwen3-embedding:4b            # Windows

# 3. .mcp.json
cp .claude/mcp/mcp.template.json .mcp.json

# 4. Context7 (user-level, один раз на машину)
npx -y ctx7 setup --claude
```

## Troubleshooting

**`/mcp` показывает qex как failed:**
- Запусти `ollama serve` (или `/cold-start`)
- Проверь модель: `ollama list | grep qwen3-embedding`
- Проверь бинарь: `which qex`

**`/mcp` показывает sentrux как failed:**
- Проверь бинарь: `which sentrux`
- Проверь subcommand: `sentrux mcp --help` (должен быть `Start the MCP server`)

**Context7 не отвечает:**
- Проверь `~/.claude.json` — должен быть блок `context7` с API key
- Перезапусти `npx -y ctx7 setup --claude` для повторной авторизации
