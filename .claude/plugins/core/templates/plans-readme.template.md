# plans/ — task plans (plan-driven workflow)

Manager (`/dev:plan <task>`) creates one plan per non-trivial task. **Дата ISO всегда в имени** — для хронологического поиска.

- **Single plan (без фаз):** `plans/YYYY-MM-DD_<slug>.md` (один файл).
- **Multi-phase plan (с фазами):** `plans/YYYY-MM-DD_<slug>/plan.md` + `plans/YYYY-MM-DD_<slug>/phase-1.md`, `phase-2.md`, …
- **Plan layout v2 (большой план):** `plan.md` (контракт) + `tasks/<id>.md` (одна задача — один файл) + `amendments.md` (правки после approve, только дописывание); бюджеты размера проверяет `plans_ledger.py status --check`.

`<slug>` follows the convention in [`.claude/commands/dev/plan.md`](../.claude/commands/dev/plan.md): `kebab-case`, `<domain>-<topic>`, ≤ 40 chars. No bare counters (`PLAN-001`).

`YYYY-MM-DD` — день создания плана (когда Manager вызван `/dev:plan`).

## Lifecycle

1. **`/dev:plan <task>`** → Manager writes plan file (или папку для multi-phase), creates branch `<type>/<slug>` (`feat`/`fix`/`refactor`/`docs`) **и регистрирует план строкой в ledger «Активные» ниже** (`python3 scripts/plans_ledger.py add <plan>`).
2. **`/dev:implement Task X.Y`** → Developer implements the task, commits с `Refs: plans/YYYY-MM-DD_<slug>.md` (или `.../phase-N.md` для multi-phase) trailer, flips status `[PENDING]` → `[DONE]`.
3. **`/dev:ship`** → verifies `Refs:` trailers on the branch; когда все задачи `[DONE]` → закрывает план (`Status: DONE`) **и архивирует его (archive-on-done): `python3 scripts/plans_ledger.py close <plan>` — `git mv` в `_archive/<YYYY-Qn>/` + перенос строки в «Архив»**.
4. **`/dev:plan-status`** → `python3 scripts/plans_ledger.py status` — обзор всех планов без перечитывания + progress bar для плана текущей ветки.

## Layout v2

Структура каталога плана после `tasks/<id>.md` (Task 2.3+), одна строка на элемент:

```
plans/YYYY-MM-DD_<slug>/
├── plan.md              # контракт: цель, one-line индекс задач, гейты, Бюджет
├── tasks/<id>.md         # тело одной задачи (шаблон TASK.template.md)
├── tasks/<id>.result.md  # итог задачи (<= 2 KB): SHA, числа приёмки, отступления
├── amendments.md         # изменения после approve — только дописывание
├── decisions.md          # обоснования решений по фазам/задачам
├── contract.lock         # заморожен approve; читают amend/status --check
└── SUMMARY.md            # пишет close — читай архивный план через него, не открывая каталог
```

Команды (`scripts/plans_ledger.py`), одна строка на команду:

- `status --check --plan <plan>` — гейт на план (перед approve/hand-back).
- `approve <plan>` — заморозить контракт, записать `contract.lock`.
- `amend <plan>` — записать одобренную поправку, обновить `contract.lock`.
- `brief <id> [--plan <plan>]` — спавн-готовый бриф из `tasks/<id>.md`.
- `summary <plan>` — превью `SUMMARY.md` перед `close`.
- `close <plan>` — архивировать (пишет `SUMMARY.md`, затем `git mv`).

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

Этот файл — **ledger** (файл учёта, машиночитаемый): агент в новой сессии читает его
ОДИН раз, чтобы узнать «что открыто», вместо перечитывания каждого плана. Таблицы
ведёт скрипт `scripts/plans_ledger.py`, а `claude-kit-claude plugin doctor` сверяет их
с файлами (`--fix` архивирует закрытый план и добавляет недостающую строку):

```bash
python3 scripts/plans_ledger.py status            # сверка: задачи N/M, фаза, находки
python3 scripts/plans_ledger.py add <plan>        # зарегистрировать / освежить строку
python3 scripts/plans_ledger.py close <plan>      # archive-on-done (git mv + строка в «Архив»)
```

Колонки: **план** — путь относительно `plans/` (ссылкой или как есть); **ветка**;
**фаза** — фаза первой открытой задачи; **задачи** — `закрыто/всего` по заголовкам
`### Task X.Y` (задача закрыта, если отмечены все её чекбоксы или в «Порядок
выполнения» у неё `[DONE]`); **статус** — `DRAFT` / `ACTIVE` / `DONE` / `ARCHIVED`
(`DONE` сверяй с git: `git merge-base --is-ancestor <ветка> main`); **обновлено** — дата.

## Активные

| план | ветка | фаза | задачи | статус | обновлено |
|------|-------|------|--------|--------|-----------|

## Архив

Завершённые планы → [`_archive/<YYYY-Qn>/`](_archive/) (квартал по дате в имени:
Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec). Per-quarter индекс —
`_archive/<YYYY-Qn>/README.md`.

| план | ветка | фаза | задачи | статус | обновлено |
|------|-------|------|--------|--------|-----------|

## Archive-on-done (конвенция)

План, у которого **все** задачи закрыты (остаток — только backlog или гейт будущего
релиза), покидает активный набор — `python3 scripts/plans_ledger.py close <plan>`:

1. `git mv plans/<plan> plans/_archive/<YYYY-Qn>/<plan>` — квартал по дате в имени.
2. Строка в `_archive/<YYYY-Qn>/README.md` (файл создаётся, если квартала ещё нет).
3. Строка ledger переезжает из «Активные» в «Архив» со статусом `ARCHIVED`.
4. **Никогда не удаляй** план — история `Refs:` зависит от него. **Не архивируй** план с открытыми задачами (скрипт откажет, rc=1) — держи его в «Активные».

## Why this structure

- **Plan name** (с датой) ≡ branch name ≡ `Refs:` trailer = единая нить task → code → commits → reviewer context.
- Дата в имени папки/файла — **хронологический поиск без git log** (`ls plans/` сортирует по времени автоматически).
- Agents в новой сессии восстанавливают контекст из `plans/YYYY-MM-DD_<slug>.md`, no human handoff needed.
- `git log --grep="Refs: plans/<slug>"` returns the whole task history in one query.

## Migration from old format (если есть legacy планы)

Старые планы без даты (`plans/<slug>.md` или `plans/<slug>/`) остаются как есть — конвенция применяется только к **новым** планам после внедрения. Если хочется унифицировать — переименуй вручную, добавив дату создания (см. `git log --diff-filter=A -- plans/<slug>.md` для определения даты).
