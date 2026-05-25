# claude_md_audit

Meta-аудит инфраструктуры `.claude/`: frontmatter, ссылки, осиротевшие slash-команды, валидность хуков. Stdlib-only, Python 3.12+.

Закрывает класс багов «slash-команда ссылается на скрипт, которого нет» и «агент без description».

## Быстрый старт

```bash
python scripts/claude_md_audit/claude_md_audit.py
python scripts/claude_md_audit/claude_md_audit.py --format json
python scripts/claude_md_audit/claude_md_audit.py --no-strict
python scripts/claude_md_audit/claude_md_audit.py --claude-dir ../other-project/.claude
```

## Что проверяется

| Чек | Что ловит |
|-----|-----------|
| **agents** | Frontmatter `--- ... ---` в `.claude/agents/**/*.md`, обязательные поля (по умолчанию `description`) |
| **commands** | Frontmatter в `.claude/commands/**/*.md`, обязательные поля (по умолчанию `description`) |
| **skills** | В каждой `.claude/skills/<name>/` должен быть `SKILL.md` |
| **slash_scripts** | Slash-команда упоминает `python scripts/x.py` или `bash scripts/x.sh` — файл должен существовать в `project_root` |
| **memory_links** | `[Title](file.md)` в `MEMORY.md` → файл существует в той же папке |
| **hooks_settings** | В `.claude/settings.json` все хуки, ссылающиеся на `.claude/hooks/*.sh|*.py`, существуют |

Отключи ненужные чеки в `[checks]` секции конфига.

## Типы issue (`kind`)

| Kind | Смысл |
|------|-------|
| `agent_missing_frontmatter` | Нет блока `--- ... ---` |
| `agent_missing_field` | Поле не задано или пустое |
| `command_missing_frontmatter` / `command_missing_field` | То же для slash-команд |
| `command_orphan_script` | Slash ссылается на `scripts/x.py`, которого нет (как был баг с `/todo-inventory`) |
| `skill_missing_skill_md` | `skills/<name>/` без `SKILL.md` |
| `memory_broken_link` | `MEMORY.md` ссылается на отсутствующий файл |
| `settings_invalid_json` | `.claude/settings.json` не парсится |
| `hook_missing_script` | Хук в settings.json ссылается на отсутствующий `.claude/hooks/...` |

## Exit-коды

| Код | Когда |
|-----|-------|
| `0` | Чисто |
| `1` | Есть находки (под `strict=true`) |
| `2` | `.claude/` не существует / плохой конфиг |

## Когда полезно

- Перед merge — pre-commit/CI gate на консистентность `.claude/`.
- После апдейта `claude-kit upgrade` — поймать рассинхронизацию.
- При проверке чужого репо со seed — узнать, не сломано ли что-то.
- В sync-back scenario — проверить, что после обратной синхронизации в seed canonical не битый.

## Ограничения

- Парсер frontmatter — простой `key: value`, без YAML-вложенности. Многострочные значения (например, `tools:` со списком) учитываются как «есть значение», без проверки структуры.
- `slash_scripts` ловит только команды формата `python scripts/...` / `bash scripts/...` / `uv run scripts/...`. Команды, упоминающие MCP-инструменты или агентов — не проверяются.
- `hooks_settings` парсит только `.claude/settings.json` (project). `~/.claude/settings.json` (user-level) — вне scope.
- Не проверяет содержательную корректность — только наличие файлов и обязательных полей.
