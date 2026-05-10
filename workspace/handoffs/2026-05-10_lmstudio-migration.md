---
date: 2026-05-10
topic: Миграция Ollama → LM Studio (Mac MLX + Win GGUF) + завершение реорганизации `.claude/`
machine: macOS (M2 Max, Darwin arm64)
branch: refactor/t1.1-plugin-composition
---

## Session goal

Изначально: добавить sentrux MCP + проверить статус qex.
Расширилось до: реорганизация всей `.claude/` инфраструктуры в обоих проектах (Inspector_bottles + obsidian) под двух-машинный workflow (Win днём, Mac вечером).

Финальный поворот: пользователь хочет переход с **Ollama на LM Studio** для embeddings — на macOS с MLX-backend (×3-4 быстрее), на Windows с GGUF-backend (как Ollama сейчас).

## Done

### Inspector_bottles (`/Users/twokrai/Project_code/Inspector_bottles`)
- Установлен **sentrux** 0.5.7 (`brew install sentrux/tap/sentrux`)
- Установлен **Context7** через OAuth (user-level в `~/.claude.json`)
- Создана `.claude/mcp/` — кросс-платформенная MCP-инфраструктура:
  - `mcp.template.json` — эталон для `.mcp.json`
  - `qex-launcher.py` — auto-detect ОС (8b macOS / 4b Windows)
  - `bootstrap.py` — Python health-check для Win+Mac+Linux
  - `README.md` — документация
- Старый `scripts/qex-launcher.py` теперь симлинк на `.claude/mcp/qex-launcher.py`
- Очищен `settings.json` от мусора: 5 hook-фантомов, wiki-allowlist, Qdrant URLs
- Создано 6 slash-команд: `/qex-status`, `/qex-reindex`, `/validate`, `/fw-test`, `/run-proto`, `/cold-start` (все кросс-платформа)
- Удалён legacy: `platforms/mcp.{macos,windows}.json` (с WORKSPACE_PATH от чужого проекта)
- Создан `platforms/settings.local.windows.json` (симметрия с macos)
- В корневом `CLAUDE.md` добавлена секция «MCP: sentrux»
- Полностью переписан `.claude/README.md` (без university-блока)

### obsidian (`/Users/twokrai/Project_code/obsidian`)
- Создана `.claude/mcp/` (README + bootstrap.py) — документирует 4 MCP-сервера: `qex`, `qex_inspector`, `knowledgeos`, `blender`
- Удалён устаревший `mcp.json.example` (использовал Qdrant старого формата)
- Удалён `.DS_Store`
- Расширен statusLine: `branch | qdrant | ollama` (Ollama раньше не отображалась)
- Создан план миграции: [`workspace/plans/2026-05-10_qex_migration.md`](../../obsidian/workspace/plans/2026-05-10_qex_migration.md) — 5 этапов, 17 задач, риски и откат

## What did NOT work / dead ends

- **`npx -y ctx7 setup --claude` через мой Bash** — пользователь отклонил permission, выполнил сам в своём терминале (правильное решение, OAuth-flow требует TTY и браузера)
- **`mcp.template.json` сравнение в bootstrap.py** — изначально не игнорировал поле `_comment` → ложный warning «отличается от template». Поправлено через `_normalized()` функцию
- **README автора sentrux** говорит args `["--mcp"]` — на самом деле subcommand `["mcp"]`. Поправлено в template
- **`/Users/twokrai/Project_code/.claude/`** — пользователь думал что там есть папка, её нет. Это `obsidian/.claude/`, а не родительская

## Key decisions made

- **Разделить obsidian и Inspector_bottles** конфигурации, не объединять. Обоснование: разные домены (Knowledge vs Code), wiki-хуки активно мешают на Edit в коде, allowlist'ы расходятся, modes/language policy разные
- **Skills `kb-discover` + `kb-lint` оставить только в obsidian** (там они для wiki-pipeline). В Inspector_bottles их быть не должно — это наследство копипасты
- **MCP в obsidian не трогать прямо сейчас** (4 рабочих сервера на Qdrant). Миграция через план
- **Bootstrap.py вместо bootstrap.sh** — Python работает на macOS+Linux+Windows одинаково
- **LM Studio предпочтительнее чистого MLX** — qex не поддерживает MLX напрямую, на Win MLX вообще не работает, ломает twin-machine workflow

## Next step

Решить с пользователем стратегию миграции на LM Studio. Узнать: какая версия LM Studio установлена (`lms --version`), какие модели уже скачаны (`lms ls`), запущен ли headless server (`curl -s http://localhost:1234/v1/models`).

Затем — в этой же или следующей сессии:
1. Скачать **одинаковую** embedding-модель в подходящих форматах (MLX на Mac / GGUF на Win)
2. Поправить `qex-launcher.py` в Inspector_bottles → `BASE_URL=http://localhost:1234/v1`
3. Решить судьбу obsidian: совмещать миграцию с qex Qdrant→feature-vector или отдельно

## Files changed (Inspector_bottles)

```
M  .claude/CLAUDE-SETUP.md
M  .claude/README.md
D  .claude/mcp.json
D  .claude/mcp.json.example
M  .claude/platforms/README.md
D  .claude/platforms/mcp.macos.json
D  .claude/platforms/mcp.windows.json
M  .claude/settings.json
M  CLAUDE.md
T  scripts/qex-launcher.py     (regular file → symlink)
A  .claude/commands/cold-start.md
A  .claude/commands/fw-test.md
A  .claude/commands/qex-reindex.md
A  .claude/commands/qex-status.md
A  .claude/commands/run-proto.md
A  .claude/commands/validate.md
A  .claude/mcp/                 (new directory: README, bootstrap.py, qex-launcher.py, mcp.template.json)
A  .claude/platforms/settings.local.windows.json
A  .mcp.json                    (path к qex обновлён)
A  workspace/handoffs/2026-05-10_lmstudio-migration.md  (этот файл)
```

## Files changed (obsidian)

```
M  .claude/settings.json        (statusLine + ollama)
D  .claude/.DS_Store
D  .claude/mcp.json.example
A  .claude/mcp/README.md
A  .claude/mcp/bootstrap.py
A  workspace/plans/2026-05-10_qex_migration.md
```

## Полезный контекст для нового чата

**Установлено на этой macOS-машине:**
- Homebrew 5.1.10
- Ollama (UP, модели: `qwen3-embedding:4b`, `:8b`)
- sentrux 0.5.7
- Node v20.20.2 + npx
- Context7 настроен (user-level)
- LM Studio установлен (по словам пользователя — версию не проверяли)
- qex-mcp-v2 в `~/.local/bin/qex-mcp-v2` (старая версия с Qdrant, для obsidian)

**Twin-machine workflow:**
- Windows днём (winget доступен)
- macOS вечером (M2 Max, Apple Silicon → MLX можно использовать)
- Синхронизация через git (`.claude/` в репозиториях)
- Локальные индексы (`~/.qex/`, `~/.ollama/`) не синхронизируются

**Решение по миграции LM Studio:**
- На Mac: MLX-backend (Apple Silicon → ~3x быстрее embeddings)
- На Win: GGUF-backend (как Ollama сейчас)
- Один и тот же URL в qex: `http://localhost:1234/v1`
- Headless mode: `lms server start --port 1234`
- Embeddings из Ollama и LM Studio несовместимы → переиндексация обязательна
