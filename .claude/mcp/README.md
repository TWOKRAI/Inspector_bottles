# MCP-инфраструктура

Здесь живёт всё, что нужно Claude Code для работы с MCP-серверами в проекте.
Папка `.claude/mcp/` рассчитана на копирование вместе с `.claude/` в новые проекты.

## Состав

| Файл | Назначение |
|------|------------|
| `mcp.template.json` | Эталон проектного `.mcp.json` (qex + sentrux) |
| `qex-launcher.py` | Запускает `qex` с правильной моделью под платформу (4b Windows / 8b macOS) |
| `bootstrap.py` | Автонастройка нового проекта — ставит зависимости, копирует template (кросс-платформа: macOS/Linux/Windows) |
| `README.md` | Этот файл |

## MCP-серверы

| Сервер | Уровень | Назначение | Когда вызывать |
|--------|---------|------------|----------------|
| **qex** | проектный (`.mcp.json`) | Семантический поиск по коду (Ollama + BM25) | «где используется X», рефакторинг, смена API |
| **sentrux** | проектный (`.mcp.json`) | Архитектурный health-gate (DSM, метрики, gaps) | до/после рефакторинга, перед `/ship`, поиск циклов |
| **Context7** | user-level (`~/.claude.json`) | Актуальная документация библиотек | работа с PySide6, Pydantic, PyTorch и др. быстро меняющимися либами |

Подробнее о ролях qex vs sentrux — в `CLAUDE.md` (секции «MCP: qex» и «MCP: sentrux»).

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

## Как qex знает корень проекта

`qex-launcher.py` лежит в `.claude/mcp/`, но qex'у нужен путь к корню проекта (для индексации).
Скрипт вычисляет его так:

```python
_script_dir = os.path.dirname(os.path.realpath(__file__))    # .claude/mcp
workspace = os.path.dirname(os.path.dirname(_script_dir))    # корень
```

`realpath` нужен потому что `scripts/qex-launcher.py` — симлинк на `.claude/mcp/qex-launcher.py` (для обратной совместимости с историческими ссылками в документации). Без `realpath` workspace бы вычислялся неправильно при запуске через симлинк.

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
