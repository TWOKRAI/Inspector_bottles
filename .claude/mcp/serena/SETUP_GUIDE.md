# Serena — полный гайд установки

## Архитектура

```
Claude Code  ──MCP──▶  serena (stdio)  ──LSP──▶  pyright / python-lsp-server
                              │
                              └──▶  ripgrep / file ops
```

Serena делает то, что обычный текстовый поиск не умеет:
- **Точные references** — не «где встречается строка `to_dict`», а где именно вызывается метод `SchemaBase.to_dict`.
- **Символ-level edit** — `replace_symbol_body` не сломает соседнюю функцию.
- **Семантика типов** — учитывает scope, импорты, MRO.

## Зависимости

| Компонент | Зачем | Установка (Windows) |
|-----------|-------|---------------------|
| `uv` ≥ 0.5 | Установщик Python-инструментов | `winget install astral-sh.uv` или `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| Python 3.13 | runtime Serena (uv подтянет сам) | автоматически через `uv tool install -p 3.13` |
| Node.js (опц.) | pyright LSP-сервер | `winget install OpenJS.NodeJS.LTS` (если pyright не подтянулся) |

> Проект на Python 3.12, но Serena работает на собственном Python 3.13 — конфликта нет, это изолированная установка `uv tool`.

## Установка

```powershell
# Проверь uv
uv --version
# Если нет — installer:
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Поставить Serena
uv tool install -p 3.13 serena-agent@latest --prerelease=allow

# Проверь установку
serena --version
serena --help
```

Бинарь окажется в `%USERPROFILE%\.local\bin\serena.exe` (uv добавит в PATH сам).

## Активация проекта

Активация **автоматическая**: при первом старте MCP-сервера Serena (`uvx ... --project .` из `.mcp.json`) она создаёт `.serena/project.yml` и `.serena/memories/` в корне проекта. Никаких ручных команд не нужно.

Если хочется создать конфиг вручную до старта MCP:

```powershell
serena project create .
# Опционально с указанием языков и сразу индексацией:
serena project create . --language python --index
```

Папку `.serena/` нужно добавить в `.gitignore` — там кэш LSP и project-конфиг:

```
# .gitignore
.serena/
```

Полезные команды:

```powershell
serena project index .          # обновить LSP-индекс
serena project health-check .   # диагностика проекта
serena project --help           # все subcommands
```

> ⚠️ В версии 1.3.0 нет команды `serena project activate` — конфиг создаётся через `create`, а активным проект становится при подключении MCP-сервера с флагом `--project .`.

## Конфигурация MCP

В `.mcp.json` (или `mcp.template.json` для bootstrap-распространения) добавляется блок:

```json
"serena": {
  "command": "uvx",
  "args": [
    "--from", "serena-agent",
    "serena", "start-mcp-server",
    "--context", "ide-assistant",
    "--project", "."
  ]
}
```

**Параметры:**
- `--context ide-assistant` — режим помощника IDE (минимум лишних tools).
- `--project .` — путь проекта (резолвится относительно cwd Claude Code).

После правки `.mcp.json` — **перезапуск Claude Code** обязателен.

## Проверка после установки

1. `/mcp` — Serena должна быть `connected`.
2. В чате: «Покажи мне все references на `SchemaBase.to_dict`» — должен дёрнуть `mcp__serena__find_references`.
3. Если LSP отвалился — `serena` падает в текстовый fallback (видно в логах).

## Troubleshooting

### `uvx` не найден

```powershell
where.exe uvx
# Если пусто — uv не в PATH. Перезапусти терминал или:
$env:Path += ";$env:USERPROFILE\.local\bin"
```

### LSP не стартует для Python

Serena сама подтягивает `pyright` через npm/npx. Если Node нет:

```powershell
# Поставить Node
winget install OpenJS.NodeJS.LTS
# Перезапустить терминал, проверить
node --version
npx --version
```

Альтернатива — `python-lsp-server` через pip:

```powershell
uv pip install --system python-lsp-server[all]
```

И в `.serena/project.yml` указать:

```yaml
language_servers:
  python: pylsp
```

### Конфликт с qex

Не возникает — это разные слои. qex отвечает на «где похоже» (BM25 + dense), Serena — на «где именно по символу» (LSP). Оба слота в `.mcp.json` нужны.

### Долгий первый запуск

LSP-сервер прогревается 30-60 сек на больших codebase (Inspector_bottles ~20 модулей). После прогрева — мгновенный отклик.

## Использование в агентах

Добавь в промпт агента (Developer / TeamLead / Reviewer) после правил про qex/sentrux:

```
**Serena-first для рефакторинга:** при rename, extract, поиске точных
references — звать `mcp__serena__find_references` или
`mcp__serena__replace_symbol_body` вместо Edit+Grep.
```

## Ссылки

- Репо: https://github.com/oraios/serena
- LSP-протокол: https://microsoft.github.io/language-server-protocol/
- pyright (Python LSP): https://github.com/microsoft/pyright
