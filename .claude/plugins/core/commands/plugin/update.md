---
description: Update a pinned plugin <id> — consume (re-pin version/sha) OR git β (re-clone to a new ref + atomic swap + recompose)
allowed-tools: Bash(claude-kit-claude plugin update*)
---

Команда `plugin update` различает источник плагина по записи в enabled.yaml и направляет в нужную ветку.

**α (consume).** Перепинивает уже закреплённый плагин: сохраняет существующий `source`, обновляет только `version`/`sha` и пересобирает артефакты. Плагин должен уже иметь `source` (сначала `pin`).

**β (git).** Для git-managed плагина (установлен в `.claude/plugins/_external/<id>/`): мы заново клонируем репозиторий на указанный `--ref` (или текущий tracked-ref), атомарно подменяем дерево и обновляем `sha` в lockfile, затем recompose. Перед операцией создаётся backup `.claude/`; на любом сбое — откат дерева И артефактов (транзакционность). Локальные правки в `_external/<id>/` теряются — β-код throwaway (gitignored, воспроизводится re-clone по lockfile).

Использование:
- consume: `/core:plugin:update <id> [--version X | --sha Y]`
- git β: `/core:plugin:update <id> [--ref <branch|tag|sha>] [--yes]`

```bash
claude-kit-claude plugin update $ARGUMENTS
```
