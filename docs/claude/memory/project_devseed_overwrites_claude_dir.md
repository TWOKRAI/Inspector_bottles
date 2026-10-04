---
name: project-devseed-overwrites-claude-dir
description: "claude-kit upgrade (devseed) перетирает часть .claude/ — ценное класть только в preserved-места; _stack.md был шаблоном с плейсхолдерами и врал про Layer-trailer; также: .claude helper system migrated to claude-kit v1.0.0 native plugin format; how to update it"
merged_from: [project_claude_kit_migration]
metadata:
  node_type: memory
  type: project
  originSessionId: a30dc0c4-173f-4906-87e3-7f7992305a87
  modified: 2026-08-15T21:22:30.382Z
---

Правило перенесено в `.claude/CLAUDE.md` («Standing rules») (2026-10-04). Ниже — доказательная база урока.

`.claude/` этого проекта собран claude-kit (devseed, `enabled.yaml` schema 2, seed_version 1.0.0).
`claude-kit upgrade --apply` **перетирает** часть дерева, и молча: ошибки нет, правило просто
перестаёт действовать.

**Переживает upgrade (`=preserved`) — сюда можно класть проектное:**
`CLAUDE.md` (корневой и `.claude/`), `.claude/modes/_stack.md`, `settings.local.json`,
`commit-layers.txt`. Плюс всё вне `.claude/`: `docs/claude/memory/`, `plans/`, `docs/`.

**Не переживает — восстанавливать из backup после каждого upgrade:**
`settings.json` (permissions, hooks, statusLine), остальные `modes/*`, composed-файлы
(`.mcp.json`), orphan-хуки не удаляются, но и не обновляются.

**Живой пример вреда (2026-08-16):** `_stack.md` пролежал незаполненным шаблоном seed'а —
`{{PROJECT_NAME}}`, `{{PACKAGE}}`, src-layout, «Python 3.11+», `uv run pytest -q`. Мало того
что плейсхолдеры: он **противоречил** проекту в критичном месте — «`Layer:` trailer disabled
by default», тогда как здесь `Layer:` обязателен и commit-hook без него отклоняет коммит.
Ещё codegraph / github / sequential-thinking были помечены выключенными при `enabled: true`
в `enabled.yaml`. Файл читается модами перед задачей — то есть дезинформация была на пути
исполнения. Заполнен правдой в этот же день.

**Why:** seed таргетит standalone-Python-dev (src-layout, uv-pytest, Layer опционален),
а здесь четырёхслойный фреймворк с обязательными трейлерами и своим тест-раннером.
Дефолты seed'а здесь не нейтральны — они неверны.

**How to apply:** перед `claude-kit upgrade --apply` — backup (`--backup-dir .claude/_backups`),
после — diff `settings.json` и `modes/*` с backup. Проектные факты класть в `_stack.md` или
`CLAUDE.md`, никогда в перетираемые `modes/*`. См. [[project_claude_kit_migration]].

## Слито из project_claude_kit_migration (_archive/project_claude_kit_migration.md)

Inspector_bottles `.claude/` was migrated (2026-07-05) from the old flat claude-kit v0.2.0 layout to **claude-kit v1.0.0 native plugin format**.

**Source of truth for the seed = `/Users/twokrai/Project_code/devseed`** (the `claude-kit` CLI project, v1.0.0). The older `/Users/twokrai/Project_code/claude_seed` (shell `apply-seed.sh`, v0.4.1) is the deprecated predecessor — do NOT update from it.

**How the .claude system is structured now:**
- `.claude/plugins/<id>/` — source of truth per plugin (core, dev, lang-python, mcp-*, security, observability, skills-*).
- `.claude/enabled.yaml` (schema 2) — declarative on/off + pins. Edit this, then run sync.
- `.claude/{commands,agents,skills}/` — **generated** (materialized, namespaced e.g. `commands/core/…`, `commands/dev/…`). Tracked in `.plugin-materialized.json`.
- `.mcp.json` + `.claude/settings.json` — **generated** from each plugin's `plugin.json` mcpServers / `settings.partial.json`. `.mcp.json` is gitignored (regenerable). Never hand-edit generated artifacts — edit the owning plugin source, then re-sync.

**Canonical update commands (run from devseed venv):**
- `/Users/twokrai/Project_code/devseed/.venv/bin/claude-kit-project init . --apply` — lay down/refresh plugins + compose.
- `.../claude-kit-claude plugin sync .` — recompose `.mcp.json` + `settings.json` after enabled.yaml or partial edits.
- `.../claude-kit-claude plugin doctor .` — validate.

**Enabled MCP (8 stdio + 2 consume):** ast-grep, codegraph, graphify, qex, qt-mcp, sentrux, sequential-thinking, serena + context7/github (marketplace consume). Off: knowledge, hello-world, playwright.

**devseed MCP-command bugs found while dogfooding (2026-07-05) — FIXED in devseed template `src/claude_kit_claude/template/plugins/`:**
- `mcp-ast-grep`: `npx -y @ast-grep/mcp` (npm 404) → `uvx --from git+https://github.com/ast-grep/ast-grep-mcp ast-grep-server` (also needs `ast-grep` CLI: `brew install ast-grep`).
- `mcp-qt`: `uvx qt-mcp` (not on PyPI) → `uvx --from git+https://github.com/0xCarbon/qt-mcp python -m qt_mcp.server`.
- `mcp-graphify`: `uvx graphify-mcp serve …` (not on PyPI) → `uvx --from "graphifyy[mcp]" python -m graphify.serve graphify-out/graph.json`. graphify has NO official Claude marketplace plugin (issue #146 open) — it's a skill (`graphify install`) + MCP over a built graph.
- `mcp-sequential-thinking`: template had empty mcpServers (enabling did nothing) → inlined `npx -y @modelcontextprotocol/server-sequential-thinking`. Same latent gap remains in `mcp-playwright`.

All 8 stdio MCP verified via initialize+tools/list handshake: ast-grep·codegraph·graphify·qex·qt-mcp·sentrux·sequential-thinking·serena. graphify needs `graphify-out/graph.json` built first (`graphify update .`). `preferredLanguage: ru` is a project-local override in `plugins/core/settings.partial.json` (init preserves it without `--force`; devseed default is `en`). See also [[project_commit_format]].
