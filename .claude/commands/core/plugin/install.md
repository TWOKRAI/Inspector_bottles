---
description: Install a plugin — consume form <plugin>@<marketplace> (α, delegated to Claude Code) OR git source <git-url> (β, our git-clone + wire)
allowed-tools: Bash(claude-kit-claude plugin install*)
---

Команда `plugin install` различает источник по аргументу и направляет в нужную ветку (`classify_source`). Две формы:

**α (consume) — `<plugin>@<marketplace>`.** Делегат-установка: файлы качает сам Claude Code из marketplace-кэша. Команда лишь пишет пин в enabled.yaml и печатает шаг `/plugin install <ref>`, который нужно выполнить внутри Claude Code, чтобы реально поставить плагин.

**β (git) — `<git-url>` (любой `https://…`, `git@…`, `.git`, `file://…`).** Мы сами `git clone` репозиторий в `.claude/plugins/_external/<id>/`, удаляем чужой `.git/`, и **наш** composer wireит плагин — его mcpServers / hooks / permissions попадают в `.mcp.json` / `settings.json`. Установка чужого плагина = выполнение чужого кода: перед вливанием показывается diff (что добавится в артефакты) и запрашивается подтверждение. В неинтерактивной среде confirm недоступен → передай `--yes`.

Использование:
- consume: `/core:plugin:install <plugin>@<marketplace> [--id <id>] [--version X]`
- git β: `/core:plugin:install <git-url> [--ref <branch|tag|sha>] [--subdir <relpath>] [--id <id>] [--yes]`

Опции β: `--ref` — ветка/тег/sha для clone; `--subdir` — путь к `.claude-plugin/plugin.json`, если он НЕ в корне репо (без `--subdir` и при отсутствии манифеста в корне команда подскажет точный путь); `--id` — имя в managed-namespace (default — из repo-name); `--yes` — пропустить confirm (CI / неинтерактив).

```bash
claude-kit-claude plugin install $ARGUMENTS
```
