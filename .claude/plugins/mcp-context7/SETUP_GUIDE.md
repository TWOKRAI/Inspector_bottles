# Context7 — SETUP_GUIDE

> Краткий путь установки. Подробности (когда полезен, платформенные пути,
> troubleshooting) — в [`README.md`](README.md).

**Context7** — MCP-сервер актуальной документации внешних библиотек. Ключевое
отличие от qex/sentrux: он настраивается **на уровне пользователя**
(`~/.claude.json`), а НЕ на уровне проекта. Поэтому его **нет** в проектном
`.mcp.json` — и это намеренно (он общий для всех твоих проектов на машине).

## Prerequisites

- **Node.js ≥ 18** + `npx` (проверка: `node --version`).

## 1. Install (one-time, per machine)

```bash
npx -y ctx7 setup --claude
```

Откроется браузер для OAuth (free tier, без карты). Setup сам добавит блок
`context7` в `~/.claude.json` (Windows: `%USERPROFILE%\.claude.json`).

## 2. Wire the MCP server

Делать ничего не нужно — `setup --claude` уже вписал launcher в user-level
`~/.claude.json`. В проектный `.mcp.json` context7 **не** добавляется. Сниппета
у плагина нет намеренно: project-level конфиг для context7 был бы ошибкой.

## 3. Restart & smoke-test

1. Перезапусти Claude Code.
2. `/mcp` → `context7` в списке серверов.

## 4. Use it / routing in this project

- Актуальные доки быстро меняющейся либы → `mcp__context7__query-docs` (оркестратор
  роутит сюда по карте `core/mcp/ROUTING.md`).
- Когда НЕ нужен: внутренний код проекта (→ qex), стабильные API (Claude уже знает).

## Troubleshooting

- Не отвечает → проверь блок `context7` в `~/.claude.json`; перезапусти
  `npx -y ctx7 setup --claude`; убедись `node --version` ≥ 18.

Полный раздел — [`README.md`](README.md) → «Troubleshooting».

## Uninstall

Удали блок `context7` из `~/.claude.json` (или перезапусти setup для обновления
user-level конфига).

## Security notes

- Setup использует OAuth (free tier); токен хранится в `~/.claude.json` (user-level,
  вне репозитория — не коммитится).
- Наружу уходит только запрос (имя библиотеки / вопрос), не твой код.
