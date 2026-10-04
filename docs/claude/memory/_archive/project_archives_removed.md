---
name: Архивные прототипы удалены
description: Все архивы прототипа удалены (v1/v2 и multiprocess_prototype_backup); хвосты в конфигах вычищены 2026-07-03
type: project
---
**Факт (обновлено 2026-07-03):** архивов прототипа в репозитории больше НЕТ:
- `multiprocess_prototype/` — единственный активный прототип (бывший `_2`, переименован);
- `multiprocess_prototype_v2/` — удалён давно;
- `multiprocess_prototype_backup/` (694 файла) — удалён коммитом e128b930 (2026-06-24), владелец подтвердил «можно смело удалять» и удалил его и на второй машине.

**Why:** старая версия этой памяти и CLAUDE.md описывали backup как «frozen snapshot — не трогать»; после удаления это сбивало с толку, а в конфигах оставались мёртвые упоминания.

**How to apply:**
- Хвосты вычищены 2026-07-03: `tests/test_plugin_chain.py` + `tests/conftest.py` (импортировали backup — pytest падал на collection), `.tmp_factcheck/` (случайно закоммиченный мусор из e128b930), упоминания в `pyproject.toml`, `.pre-commit-config.yaml`, `scripts/*.toml`, `.claude/security-patterns.json`; в `.sentrux/rules.toml` оставлено одно правило-страховка `from="*"` (по прецеденту v2).
- CLAUDE.md раздел «История версий и архив» обновлён — CRITICAL-блок про backup снят.
- Если где-то в доках/планах встретится упоминание backup — это история, не живая директория.
