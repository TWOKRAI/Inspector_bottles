# Serena — LSP-based семантический MCP

[Serena](https://github.com/oraios/serena) — open-source MCP-сервер от Oraios, который превращает LLM в IDE-уровневого ассистента: точная навигация по символам, references, rename, безопасный refactor. Работает поверх **LSP** (Language Server Protocol).

## Когда звать (vs qex / sentrux)

| Задача | Инструмент |
|--------|-----------|
| «Где упоминается похожая логика?» (семантика) | `qex` |
| «Найди **все references** на `SchemaBase.to_dict`» (точно, по символу) | **Serena** |
| Rename / extract method через LSP | **Serena** |
| Цикличность модулей, метрики архитектуры | `sentrux` |
| Документация PySide6/Pydantic | `Context7` |

**qex отвечает «где похоже», Serena — «где именно».** Не дублируют друг друга — дополняют. Эти три плюс sentrux/Context7 закрывают разные слои анализа кода.

## Быстрый старт (Windows)

```powershell
# 1. uv должен быть установлен (см. SETUP_GUIDE.md)
uv --version

# 2. Поставить Serena
uv tool install -p 3.13 serena-agent@latest --prerelease=allow

# 3. Проверить
serena --version

# 4. Активировать проект (один раз)
cd D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles
serena project activate
```

## Подключение к Claude Code

Уже добавлено в `.mcp.json` (см. `mcp.template.json`):

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

После установки — перезапусти Claude Code и проверь `/mcp`. Serena должна быть зелёной.

## Что внутри (ключевые tools)

- `find_symbol` — точный поиск символа по имени/типу
- `find_references` — все места использования символа
- `replace_symbol_body` — переписать тело функции/класса без regex
- `insert_after_symbol` / `insert_before_symbol` — структурная вставка
- `get_symbols_overview` — обзор символов файла/модуля
- `read_file` / `list_dir` / `search_for_pattern` — навигация
- `execute_shell_command` — обёртка над shell (с ограничениями)

LSP-бэкенд для Python — `pyright` или `python-lsp-server` (выбирает Serena автоматически).

## Полный гайд

См. [SETUP_GUIDE.md](SETUP_GUIDE.md) — установка uv, конфигурация LSP, troubleshooting на Windows.

## Ссылки

- Репо: https://github.com/oraios/serena
- Доки: https://github.com/oraios/serena/blob/main/README.md
- Список clients: Claude Code, Claude Desktop, Cursor, Cline, Windsurf
