# Plan: <название на русском>

- **Slug:** <slug>
- **Дата:** YYYY-MM-DD
- **Статус:** DRAFT
- **Plan review:** PENDING | APPROVED <date> | CHANGES <n>
- **Ветка:** `<type>/<slug>` — машинно-читаемое поле: по нему гейт `Refs:`, гейт
  инъекций и баннер сессии находят план. Одна ветка; нарратив — отдельным пунктом.

## Что где живёт

| Что | Где живёт | Почему |
|---|---|---|
| Контракт: цель, задачи одной строкой, гейты, бюджет | `plan.md`, ≤ 16 KB (однофайловый план — ≤ 32 KB) | лид читает его каждую сессию |
| Тело задачи | `tasks/<id>.md`, ≤ 8 KB (или инлайн в `plan.md` для малого плана — см. ниже) | исполнитель читает только свою задачу |
| Итог задачи | `tasks/<id>.result.md`, ≤ 2 KB | SHA, числа приёмки, отступления — не план и не контракт |
| Изменения после approve | `amendments.md`, нумерованные, только дописывание | рост области виден числом, бюджет пересчитывается в той же записи |
| Статус | леджер `plans/README.md` + маркеры в «Порядке выполнения» | данные, не проза |
| Итог плана (при закрытии) | `SUMMARY.md`, пишет `close` | архивный план читают через него, не открывая каталог |
| Журнал, замеры, handoff | `docs/sessions/<дата>.md` | в план не пишется |
| Долг вне задач | `plans/_backlog.md` | в план не пишется |

Бюджеты размера выше проверяет `python3 scripts/plans_ledger.py status --check` — план не может
незаметно вырасти в журнал.

## Контекст

Зачем нужен этот план, что меняем, ограничения. 2-5 предложений.

## Цели

- Цель 1 — измеримая
- Цель 2 — измеримая

## Out of scope

- Что **не** будем делать в рамках этого плана
- Почему отложили

## Бюджет

Ставка/оценка на план или на фазу (например: "$X–Y all-in на задачу при доле
лида N%"). Обязательна для гейта — `status --check`/`approve` без секции
`## Бюджет`/`## Budget` дают находку `NO_BUDGET`. Пересчёт — записью в
`amendments.md` после каждой фазы, не правкой этой секции напрямую.

## Порядок выполнения

### Phase 1: <название фазы>

**Цель фазы:** одна фраза.

- Task 1.1: <короткое название> **[VERTICAL SLICE]** [PENDING]
- Task 1.2: <короткое название> [PENDING]

> **[VERTICAL SLICE] обязателен для multi-layer фич** — Task 1.1 должен пройти через ВСЕ затрагиваемые слои в минимальной форме (одно поле в схеме + один method + один endpoint/UI элемент). Это даёт feedback loop в первом же Task, а не в конце Phase. Если фича в одном слое (bug fix, single-layer feature) — пометку убрать. См. `agents/manager.md` → "Vertical slice — правило декомпозиции".

### Phase 2: <название фазы>

- Task 2.1: <короткое название> [PENDING] (зависит от 1.1, 1.2)

Тело каждой задачи — отдельный файл `tasks/<id>.md`, скопированный из
[`TASK.template.md`](TASK.template.md): его метки (`TASK`/`ROLE`/`CHAIN`/
`DESIGN`/`FILES`/`REDS`/`ACCEPTANCE`/`TESTS`/`OUT OF SCOPE`) читают
`plans_ledger.py brief <id>` и гейт `status --check --plan <p>` (каждая
открытая задача обязана нести Files/Acceptance/Handoff; Files — не больше
8 путей). Итог задачи после закрытия — `tasks/<id>.result.md` (≤ 2 KB).

## Малый план (single-file, < 50 строк ТЗ)

Без каталога `tasks/` — тело задачи пишется прямо здесь, под заголовком фазы,
тем же блоком, что гейт проверяет по месту (Files/Acceptance/Handoff):

### Task 1.1: <короткое название> **[VERTICAL SLICE]**
- **Статус:** [PENDING]
- **Файлы:** `path/to/file.py`, `path/to/other.py`
- **Acceptance:** end-to-end сценарий — что можно продемонстрировать после Task (CLI invocation / HTTP request / UI click → видимый результат)
- **Module contract:** new-full | new-lite | public-api-change | impl-only | n/a
- **Handoff:** <role>(<artifact>) → <role>(<artifact>) → … → lead
- **Gate:** TaskCompleted | [RED] | [docs] | [skip-gate]
- **Refs:** опц. — ADR-XXX, issue#NN

Описание задачи: что именно сделать. Если нужны заметки по реализации — здесь.

### Task 1.2: <короткое название>
- **Статус:** [PENDING]
- **Файлы:** `...`
- **Acceptance:** `...`
- **Module contract:** new-full | new-lite | public-api-change | impl-only | n/a
- **Handoff:** <role>(<artifact>) → <role>(<artifact>) → … → lead
- **Gate:** TaskCompleted | [RED] | [docs] | [skip-gate]

## Injections

> Обязательна, если ветка этого плана меняла `tests/**` (гейт Task 6.2 —
> `/dev:ship` и pre-push hook блокируют push без этой секции или без
> `plans/<slug>/injections.md`). Одна строка на инъекцию: свойство теста,
> какое красное ожидалось при break-injection, какое красное реально
> наблюдалось.

| property | predicted red | observed red |
|---|---|---|
| <что проверяет тест> | <ожидаемое сообщение/поведение при поломке кода> | <что реально показал прогон> |

## Открытые вопросы

- [ ] Вопрос 1 — кто отвечает
- [ ] Вопрос 2

## Решения (decisions log)

- **YYYY-MM-DD:** выбрали X над Y, потому что Z.

---

> **Хранение**: дата ISO всегда в имени.
> - Single (без фаз, < 50 строк ТЗ): `plans/YYYY-MM-DD_<slug>.md` — тела задач инлайн (см. «Малый план» выше).
> - Plan layout v2 (по умолчанию для всего остального): `plans/YYYY-MM-DD_<slug>/plan.md` + `tasks/<id>.md` + `amendments.md`.
> - Multi-phase (legacy, без `tasks/`): `plans/YYYY-MM-DD_<slug>/plan.md` + `phase-N.md`.
>
> Workflow: `/dev:plan` создаёт файл/папку → `git checkout -b <type>/<slug>` → `python3 scripts/plans_ledger.py approve <plan>` (для каталога) → `/dev:implement <id>` (v2: первый шаг — `plans_ledger.py brief <id>`) → commit с `Refs: plans/YYYY-MM-DD_<slug>/plan.md` → `/dev:ship` закрывает план, когда все задачи `[DONE]`/`[SKIPPED]`/`[CANCELLED]`, командой `python3 scripts/plans_ledger.py close <plan>` (пишет `SUMMARY.md`).
> Подробнее: [`.claude/plugins/dev/commands/plan.md`](../.claude/commands/dev/plan.md), [`.claude/COMMIT_GUIDE.md`](../.claude/COMMIT_GUIDE.md), [`.claude/plugins/core/templates/plans-readme.template.md`](plans-readme.template.md), [`.claude/plugins/core/templates/TASK.template.md`](TASK.template.md).
