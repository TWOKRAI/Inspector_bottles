# sentrux — SETUP_GUIDE

> Краткий путь «установить → подключить → проверить». Полное описание метрик,
> сценариев рефакторинга и архетипов правил — в [`README.md`](README.md).

**sentrux** — структурный health-gate (один Rust-бинарь, без рантайм-зависимостей),
подключённый в этом проекте как MCP-сервер + 8 команд `/mcp-sentrux:sentrux-*`.

## Prerequisites

- Бинарь `sentrux` в `PATH` (ставится ниже). Других зависимостей нет — грамматики
  (51 языковой парсер, ~30 MB) скачиваются при первом запуске автоматически.

## 1. Install

| Платформа | Команда |
|-----------|---------|
| macOS | `brew install sentrux/tap/sentrux` |
| Linux | `curl -fsSL https://raw.githubusercontent.com/sentrux/sentrux/main/install.sh \| sh` |
| Windows | скачать `sentrux-windows-x86_64.exe` из [latest release](https://github.com/sentrux/sentrux/releases/latest) → переименовать в `sentrux.exe` → положить в каталог из `PATH` (напр. `%USERPROFILE%\.cargo\bin\`) |

Проверка: `sentrux --version` → `sentrux X.Y.Z`.

## 2. Wire the MCP server

Launcher объявлен **inline** в [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json)
→ `mcpServers.sentrux` (`command: sentrux`, `args: ["mcp"]`). `claude-kit-project new` /
`claude-kit-claude plugin enable mcp-sentrux` прописывает его в проектный `.mcp.json` автоматически —
вручную добавлять ничего не нужно. Сниппета у плагина нет намеренно: альтернативного
launcher'а здесь не предлагается, а дефолтный уже задан в `plugin.json`.

Переключение launcher'а (редко) — правка `.mcp.json` руками (он не регенерится для
non-manifest содержимого).

## 3. Restart & smoke-test

1. Перезапусти Claude Code (VS Code: `Ctrl/Cmd+Shift+P` → `Developer: Reload Window`).
2. `/mcp` → `sentrux` должен быть зелёным.
3. `sentrux check` → строка `Quality: NNNN` + список правил.

## 4. Use it / routing in this project

- Старт сессии — `/mcp-sentrux:sentrux-health` (quality_signal + bottleneck).
- Перед рефакторингом — `/mcp-sentrux:sentrux-baseline`; после — `/mcp-sentrux:sentrux-diff`.
- Перед `/dev:ship` — `/mcp-sentrux:sentrux-gaps` + `/mcp-sentrux:sentrux-check`.
- MCP-роутинг (когда оркестратор зовёт sentrux напрямую) — карта `core/mcp/ROUTING.md`.

Полная таблица команд, метрик и архетипов правил — [`README.md`](README.md).

## Troubleshooting

- `/mcp` показывает sentrux как failed → проверь `which sentrux` (бинарь в PATH) +
  перезапусти окно Claude Code.
- `session_end` говорит «no baseline» → сначала `/mcp-sentrux:sentrux-baseline`,
  потом правки, потом `/mcp-sentrux:sentrux-diff`.

Полный раздел диагностики — [`README.md`](README.md) → «Диагностика».

## Uninstall

- Убрать бинарь из `PATH` (или удалить `sentrux` / `sentrux.exe`).
- Удалить блок `sentrux` из проектного `.mcp.json`.
- Опц. удалить `.sentrux/` (rules + baseline-кэш).

## Security notes

- sentrux читает только локальное дерево исходников (как ripgrep — уважает
  `.gitignore` / `.ignore`); код наружу не отправляет.
- Бинарь ставится из официальных release'ов — проверяй источник
  (<https://github.com/sentrux/sentrux/releases>).
