---
description: Meta-audit of .claude/ — agent/command frontmatter, orphaned slash scripts, MEMORY links, hooks
---

Запусти аудит инфраструктуры `.claude/`:

```bash
python scripts/claude_md_audit/claude_md_audit.py
```

Что проверяется:
- **agents** — frontmatter (`description`) в `.claude/plugins/*/agents/**/*.md`
- **commands** — frontmatter в `.claude/commands/**/*.md`
- **skills** — каждая `.claude/skills/<name>/` имеет `SKILL.md`
- **slash_scripts** — slash-команды, ссылающиеся на `python scripts/x.py` или `bash scripts/x.sh`, не упоминают несуществующих файлов *(закрывает класс багов «висящая команда»)*
- **memory_links** — `[Title](file.md)` в `MEMORY.md` указывает на существующий файл
- **hooks_settings** — хуки в `.claude/settings.json` ссылаются на существующие скрипты

Конфиг: [scripts/claude_md_audit/claude_md_audit.toml](../../scripts/claude_md_audit/claude_md_audit.toml). Детали и kind'ы issue — [README.md](../../scripts/claude_md_audit/README.md).

Полезные варианты:
- `python scripts/claude_md_audit/claude_md_audit.py --format json` — для CI.
- `python scripts/claude_md_audit/claude_md_audit.py --no-strict` — отчёт без падения.
- `python scripts/claude_md_audit/claude_md_audit.py --claude-dir ../other/.claude` — аудитить чужой проект.

**Когда использовать:**
- После апдейта/upgrade'а seed'а — проверить, что миграция не оставила висящих ссылок.
- В CI как gate перед merge в `main`.
- При onboarding'е репо — быстрый sanity-check инфраструктуры.
- После добавления нового агента/команды/скилла — убедиться что всё связано.

**Замечания:**
- Frontmatter parser — простой `key: value`, без YAML-вложенности. Для сложного frontmatter (списки, объекты) — учитывается только «поле есть/нет».
- `slash_scripts` ловит формат `python scripts/...` / `bash scripts/...` / `uv run scripts/...`. Команды, оркеструющие MCP-инструменты или агентов, — вне scope.

$ARGUMENTS
