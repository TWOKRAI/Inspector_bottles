# core — фундамент, на котором стоят остальные плагины

**Категория:** core · **Default:** on (обязателен, нельзя выключить) · мигрировано в Phase 3 из `hooks/{core,git,_lib}`, `agents/_template.md`, `commands/{memory,infra,analysis,team}`, `modes/_stack.md`, `memory/`, `scripts/`, `mcp/{ROUTING,README}`, `platforms/`, общих частей `templates/`.

Lifecycle-хуки (session-start, session-end, pre-commit, protect-branch/readonly), шаблоны агентов, базовые slash-команды (`/core:memory:search`, `/core:team:team`, `/core:team:hire`, `/core:team:wrap-up`, `/core:quality:doctor`), скелет памяти, linter-скрипты, MCP-routing, per-OS платформы, общие шаблоны проекта. Все остальные плагины зависят от core.
