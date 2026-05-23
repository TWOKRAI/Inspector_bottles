# plans/ — task plans (plan-driven workflow)

Manager (`/plan <task>`) creates one plan per non-trivial task. **Дата ISO всегда в имени** — для хронологического поиска.

- **Single plan (без фаз):** `plans/YYYY-MM-DD_<slug>.md` (один файл).
- **Multi-phase plan (с фазами):** `plans/YYYY-MM-DD_<slug>/plan.md` + `plans/YYYY-MM-DD_<slug>/phase-1.md`, `phase-2.md`, …

`<slug>` follows the convention in [`.claude/commands/dev/plan.md`](../.claude/commands/dev/plan.md): `kebab-case`, `<domain>-<topic>`, ≤ 40 chars. No bare counters (`PLAN-001`).

`YYYY-MM-DD` — день создания плана (когда Manager вызван `/plan`).

## Lifecycle

1. **`/plan <task>`** → Manager writes plan file (или папку для multi-phase) и creates branch `<type>/<slug>` (`feat`/`fix`/`refactor`/`docs`).
2. **`/implement Task X.Y`** → Developer implements the task, commits с `Refs: plans/YYYY-MM-DD_<slug>.md` (или `.../phase-N.md` для multi-phase) trailer, flips status `[PENDING]` → `[DONE]`.
3. **`/ship`** → verifies `Refs:` trailers on the branch, suggests closing the plan (`Status: DONE`) when all tasks are done.
4. **`/plan-status`** → progress bar for the plan on the current branch.

## Поиск планов

```bash
# По slug (находит независимо от даты):
ls plans/*_<slug>*

# По периоду:
ls plans/2026-05-*    # за май 2026
ls plans/2026-Q2*     # с шаблоном квартала (если используешь)

# По коммитам:
git log --grep="Refs: plans/" --oneline
git log --grep="Refs: plans/2026-05" --oneline    # коммиты по планам мая
```

## Template

New plans start from [`.claude/templates/PLAN.template.md`](../.claude/templates/PLAN.template.md).

Manager выбирает: single-file (атомарная задача, < 50 строк ТЗ) или multi-phase (2+ независимых этапов).

## Archive

Completed plans stay in `plans/` (история) пока не:
- Merged into a long-lived doc (e.g. `docs/architecture/`)
- Moved to `plans/_archive/` if cluttering the active list

Either is fine — don't delete plans, the `Refs:` history depends on them. Дата в имени позволяет легко найти "что делалось в Q2 2026".

## Why this structure

- **Plan name** (с датой) ≡ branch name ≡ `Refs:` trailer = единая нить task → code → commits → reviewer context.
- Дата в имени папки/файла — **хронологический поиск без git log** (`ls plans/` сортирует по времени автоматически).
- Agents в новой сессии восстанавливают контекст из `plans/YYYY-MM-DD_<slug>.md`, no human handoff needed.
- `git log --grep="Refs: plans/<slug>"` returns the whole task history in one query.

## Migration from old format (если есть legacy планы)

Старые планы без даты (`plans/<slug>.md` или `plans/<slug>/`) остаются как есть — конвенция применяется только к **новым** планам после внедрения. Если хочется унифицировать — переименуй вручную, добавив дату создания (см. `git log --diff-filter=A -- plans/<slug>.md` для определения даты).
