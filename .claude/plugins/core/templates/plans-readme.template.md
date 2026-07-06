# plans/ — task plans (plan-driven workflow)

Manager (`/dev:plan <task>`) creates one plan per non-trivial task. **Дата ISO всегда в имени** — для хронологического поиска.

- **Single plan (без фаз):** `plans/YYYY-MM-DD_<slug>.md` (один файл).
- **Multi-phase plan (с фазами):** `plans/YYYY-MM-DD_<slug>/plan.md` + `plans/YYYY-MM-DD_<slug>/phase-1.md`, `phase-2.md`, …

`<slug>` follows the convention in [`.claude/commands/dev/plan.md`](../.claude/commands/dev/plan.md): `kebab-case`, `<domain>-<topic>`, ≤ 40 chars. No bare counters (`PLAN-001`).

`YYYY-MM-DD` — день создания плана (когда Manager вызван `/dev:plan`).

## Lifecycle

1. **`/dev:plan <task>`** → Manager writes plan file (или папку для multi-phase), creates branch `<type>/<slug>` (`feat`/`fix`/`refactor`/`docs`) **и регистрирует план строкой в ledger «Active» ниже**.
2. **`/dev:implement Task X.Y`** → Developer implements the task, commits с `Refs: plans/YYYY-MM-DD_<slug>.md` (или `.../phase-N.md` для multi-phase) trailer, flips status `[PENDING]` → `[DONE]`.
3. **`/dev:ship`** → verifies `Refs:` trailers on the branch; когда все задачи `[DONE]` → закрывает план (`Status: DONE`) **и архивирует его (archive-on-done): `git mv` в `_archive/<YYYY-Qn>/` + перенос строки в ledger «Archived»**.
4. **`/dev:plan-status`** → читает ledger (обзор всех планов без перечитывания) + progress bar для плана текущей ветки.

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

New plans start from [`.claude/plugins/core/templates/PLAN.template.md`](../.claude/plugins/core/templates/PLAN.template.md).

Manager выбирает: single-file (атомарная задача, < 50 строк ТЗ) или multi-phase (2+ независимых этапов).

## Ledger — единый индекс (не перечитывай все планы)

Этот файл — **ledger** (файл учёта): агент в новой сессии читает его ОДИН раз,
чтобы узнать «что открыто», вместо перечитывания каждого плана. Держи две таблицы
актуальными (`/dev:plan` добавляет строку, `/dev:ship` переносит в Archived).

### Active

| План | Тип | Статус | Остаток |
|------|-----|--------|---------|
| _(пусто — `/dev:plan` добавит первую строку)_ | | | |

### Archived

Завершённые планы → [`_archive/<YYYY-Qn>/`](_archive/) (квартал по дате в имени:
Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec). Per-quarter индекс —
`_archive/<YYYY-Qn>/README.md`.

## Archive-on-done (конвенция)

План, у которого **все** Task/фазы `[DONE]` (остаток — только backlog или гейт
будущего релиза), покидает активный набор:

1. `git mv plans/<plan> plans/_archive/<YYYY-Qn>/<plan>` — квартал по дате в имени.
2. Допиши строку в `_archive/<YYYY-Qn>/README.md` (релиз + одна заметка); создай файл с шапкой, если квартала ещё нет.
3. Перенеси запись из «Active» в «Archived» выше.
4. **Никогда не удаляй** план — история `Refs:` зависит от него. **Не архивируй** план с открытыми пунктами (даже с мелкими неблокерами — держи в «Active» с пометкой остатка).

`/dev:ship` выполняет это при закрытии последней задачи; `/dev:plan` регистрирует
план в «Active»; `/dev:plan-status` сверяет таблицы с файлами планов.

## Why this structure

- **Plan name** (с датой) ≡ branch name ≡ `Refs:` trailer = единая нить task → code → commits → reviewer context.
- Дата в имени папки/файла — **хронологический поиск без git log** (`ls plans/` сортирует по времени автоматически).
- Agents в новой сессии восстанавливают контекст из `plans/YYYY-MM-DD_<slug>.md`, no human handoff needed.
- `git log --grep="Refs: plans/<slug>"` returns the whole task history in one query.

## Migration from old format (если есть legacy планы)

Старые планы без даты (`plans/<slug>.md` или `plans/<slug>/`) остаются как есть — конвенция применяется только к **новым** планам после внедрения. Если хочется унифицировать — переименуй вручную, добавив дату создания (см. `git log --diff-filter=A -- plans/<slug>.md` для определения даты).
