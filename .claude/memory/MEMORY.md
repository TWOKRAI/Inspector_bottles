# MEMORY — index

> **Status: empty by design.** Пусто на старте, заполняется автоматически по
> правилам `auto memory` из системного промпта (или вручную через `/core:memory:init`).

## Что это

Project-local memory store — `.claude/memory/`, git-tracked, портативна вместе
с репо. Каждая запись — отдельный `.md` файл с frontmatter (`name`,
`description`, `metadata.type`, опц. `metadata.last-verified: YYYY-MM-DD`).
Этот файл — только индекс (одна строка на запись).

Правила записи/чтения, типы (`user`/`feedback`/`project`/`reference`), capture
rail — `.claude/CLAUDE.md` → «Memory (OVERRIDE)». Механический контроль —
`.claude/plugins/core/scripts/memory_lint.py`.

## Формат строки

```
- [Title in ~50 chars](filename.md) — one-line hook (whole line ≤ 150 chars)
```

Строка целиком — ≤ 150 символов (порог `line-too-long` линта). Например:

```
- [Russian-only user-facing output](feedback_russian.md) — все ответы и docs на русском
- [User is solo dev](user_role.md) — single maintainer, no team conventions
```

## Команды

- `/core:memory:init` — создать первый каркас (только в новом проекте).
- `/core:memory:status` — что сейчас лежит в `.claude/memory/`.
- `/core:memory:search <query>` — найти запись по содержанию.
- `/core:memory:remember [урок]` — захватить урок вручную.

## Секции

### Feedback
- [Сигнал «отпусти соседа» — в момент факта](feedback_unblocking_signal_at_the_moment_of_fact.md) — метка после всей эскалации: 13 тестов зелёные, живьём 5.7 с как до правки
- [Новый план — среди соседей](feedback_a_new_plan_must_be_placed_among_its_neighbours.md) — таблица владения + обратные ссылки в чужие планы

### User
_(empty)_

### Project
- [Порядок 2026-09-22: merge line-sim → Ф3/Ф5 → Пульт](project_work_order_2026_09_22_line_sim_then_pult.md) — утверждён владельцем; ветка = правда
- [GUI: рецепт и auth — бэкенд, Пульт — сервис](project_gui_services_composition_2026_09_23.md) — сборка из сервисов, 09-23
- [Железо владельца и роли машин](project_hardware_roles_2026_09_23.md) — RTX 3050 4 ГБ = симулятор, Orin NX 16 = линия

### Reference
_(empty)_

---

> Не путать с `~/.claude/projects/<project>/memory/` (нативный путь Claude
> Code) — мы намеренно переопределяем его на `.claude/memory/` ради
> портативности. Per-project, не входит в seed.
