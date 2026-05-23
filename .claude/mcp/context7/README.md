# Context7 — актуальная документация библиотек

**Context7** — MCP-сервер, который подтягивает актуальную документацию библиотек прямо в контекст Claude Code. Когда агент работает с любой быстро меняющейся либой (frontend frameworks, ORM, GUI toolkits, ML SDK) — Context7 даёт ему свежие доки вместо устаревших из обучающей выборки.

## Отличие от qex и sentrux

| Сервер | Уровень | Что делает |
|--------|---------|------------|
| **qex** | проектный (`.mcp.json`) | Семантический поиск по **твоему** коду |
| **sentrux** | проектный (`.mcp.json`) | Архитектурное здоровье **твоего** проекта |
| **Context7** | **user-level** (`~/.claude.json`) | Актуальные доки **внешних** библиотек |

Context7 настраивается **один раз на машину**, а не на проект. Поэтому он не в `.mcp.json`, а в `~/.claude.json`.

## Установка

### Требования

- **Node.js** ≥ 18 + npx

### Шаги

```bash
# 1. Запусти setup (откроется браузер для OAuth, free tier без карты)
npx -y ctx7 setup --claude

# 2. Перезапусти Claude Code
```

Setup автоматически добавит блок `context7` в `~/.claude.json`.

### Проверка

В Claude Code выполни `/mcp` — Context7 должен быть в списке серверов.

Или вручную проверь файл:

```bash
# macOS / Linux
cat ~/.claude.json | grep -A5 context7

# Windows (PowerShell)
Get-Content ~\.claude.json | Select-String -Pattern "context7" -Context 0,5
```

## Платформенные особенности

| Платформа | Путь конфига | Установка Node |
|-----------|-------------|----------------|
| macOS | `~/.claude.json` | `brew install node` |
| Linux | `~/.claude.json` | nvm или пакетный менеджер |
| Windows | `%USERPROFILE%\.claude.json` | [nodejs.org](https://nodejs.org) или `winget install OpenJS.NodeJS` |

## Когда полезен

- Быстро меняющийся фреймворк (frontend, GUI, ORM, ML SDK)
- Версионные миграции (Pydantic v1 → v2, и т.п.)
- Любая либа, где LLM-знания устарели

## Когда НЕ нужен

- Работа только с внутренним кодом проекта → используй qex
- Стабильные API (stdlib Python, SQLite) → Claude уже знает

## Troubleshooting

**Context7 не отвечает:**
- Проверь `~/.claude.json` — должен быть блок с `context7`
- Перезапусти `npx -y ctx7 setup --claude`
- Убедись что Node.js ≥ 18: `node --version`

**`npx` не найден:**
- Установи Node.js (см. таблицу выше)
- После установки перезапусти терминал

**Free tier — есть ли лимиты?**
- Да, но для обычной разработки хватает. Rate limit мягкий.
