# Plan: <название на русском>

- **Slug:** <slug>
- **Дата:** YYYY-MM-DD
- **Статус:** DRAFT
- **Ветка:** (заполняется после создания)

## Контекст

Зачем нужен этот план, что меняем, ограничения. 2-5 предложений.

## Цели

- Цель 1 — измеримая
- Цель 2 — измеримая

## Out of scope

- Что **не** будем делать в рамках этого плана
- Почему отложили

## Phase 1: <название фазы>

**Цель фазы:** одна фраза.

### Task 1.1: <короткое название>
- **Статус:** [PENDING]
- **Файлы:** `path/to/file.py`, `path/to/other.py`
- **Acceptance:** что должно работать после Task
- **Refs:** опц. — ADR-XXX, issue#NN

Описание задачи: что именно сделать. Если нужны заметки по реализации — здесь.

### Task 1.2: <короткое название>
- **Статус:** [PENDING]
- **Файлы:** `...`
- **Acceptance:** `...`

## Phase 2: <название фазы>

(аналогично)

## Открытые вопросы

- [ ] Вопрос 1 — кто отвечает
- [ ] Вопрос 2

## Решения (decisions log)

- **YYYY-MM-DD:** выбрали X над Y, потому что Z.

---

> **Хранение**: дата ISO всегда в имени.
> - Single (без фаз): `plans/YYYY-MM-DD_<slug>.md`.
> - Multi-phase: `plans/YYYY-MM-DD_<slug>/plan.md` + `phase-N.md`.
>
> Workflow: `/plan` создаёт файл/папку → `git checkout -b <type>/<slug>` → `/implement Task X.Y` → commit с `Refs: plans/YYYY-MM-DD_<slug>.md` (или `.../phase-N.md`) → `/ship` закрывает план когда все `[DONE]`.
> Подробнее: [`.claude/commands/dev/plan.md`](../.claude/commands/dev/plan.md), [`.claude/COMMIT_GUIDE.md`](../.claude/COMMIT_GUIDE.md), [`.claude/templates/plans-readme.template.md`](plans-readme.template.md).
