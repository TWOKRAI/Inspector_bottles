---
description: Run the Manager agent (Sonnet) — decompose a task and write the spec
---

> Before decomposing, consider `/core:quality:dashboard` first — a one-command
> snapshot of project state (plans, architecture, tests, recent activity) that
> gives the Manager current context cheaply.

Запусти агента **manager** (subagent_type: "manager", model: sonnet).

Передай ему:
1. Задачу пользователя: $ARGUMENTS
2. Контекст: «Прочитай CLAUDE.md, изучи релевантный код, создай план в `plans/`»
3. Если есть существующие планы — укажи путь

**Slug-конвенция (обязательна для Manager):**
- Формат: `kebab-case`, `<домен>-<суть>`, max 40 символов
- Примеры: `auth-rbac`, `graph-port-validation`, `phase7-plugin-config`
- **Не использовать:** голые счётчики (PLAN-001)
- Phase-номер допустим как смысловое имя (`phase7-plugin-config`)

**Хранение (дата ISO всегда в имени — для хронологического поиска):**
- Дефолтный корень: `plans/` (корень проекта). Всегда сохранять сюда, если пользователь не указал другой путь явно.
- **Single plan (один файл, без фаз):** `plans/YYYY-MM-DD_<slug>.md` — для простых задач (< 50 строк ТЗ).
- **Multi-phase plan (с фазами):** `plans/YYYY-MM-DD_<slug>/` (папка), внутри:
  - `plan.md` — метаплан / overview / index фаз.
  - `phase-1.md`, `phase-2.md`, ... — фазовые планы.
- **Дата** — день создания плана (когда вызван `/dev:plan`), ISO формат.
- **Выбор формата:** Manager решает по сложности (single для атомарных, multi-phase когда 2+ независимых этапов).

**Шаблон плана:** [`.claude/plugins/core/templates/PLAN.template.md`](../../core/templates/PLAN.template.md) — используй его структуру (frontmatter + Phase/Task с `[PENDING]`/`[DONE]` + Open questions + Decisions log) как отправную точку. Удали ненужные секции, но не frontmatter.

**Обязательный frontmatter:**
```markdown
# Plan: <название на русском>

- **Slug:** <slug>
- **Дата:** YYYY-MM-DD
- **Статус:** DRAFT
- **Ветка:** (заполняется ниже)
```

После получения плана:
1. Прочитай созданный файл
2. Оцени качество декомпозиции
3. Определи тип ветки по Conventional Commits type:
   - Новая фича → `feat/<slug>`
   - Рефакторинг → `refactor/<slug>`
   - Баг → `fix/<slug>`
   - Документация → `docs/<slug>`
4. **Сначала создай ветку, потом коммить план** (важен порядок: commit-msg hook требует `Refs:` если на ветке `<type>/<slug>` уже есть `plans/<slug>.md`):
   ```bash
   git checkout -b <type>/<slug>
   ```
5. Обнови поле `Ветка:` в плане → значение `<type>/<slug>`.
6. **Зарегистрируй план в ledger** `plans/README.md` — добавь строку в таблицу
   «Active» (план · тип · статус `DRAFT` · краткий остаток). Ledger — единый
   индекс, чтобы будущая сессия не перечитывала все планы. (`/dev:ship` перенесёт
   строку в «Archived» при закрытии — archive-on-done.)
7. Сделай коммит плана с self-Refs (укажи точный путь; `git add plans/` включает и
   обновлённый ledger):
   ```bash
   # Single plan:
   git add plans/
   git commit -m "docs(plans): создать план <slug>

   Why: зафиксировать план перед реализацией
   Layer: docs
   Refs: plans/YYYY-MM-DD_<slug>.md"

   # Multi-phase plan:
   git add plans/
   git commit -m "docs(plans): создать план <slug> (multi-phase)

   Why: зафиксировать план перед реализацией
   Layer: docs
   Refs: plans/YYYY-MM-DD_<slug>/plan.md"
   ```
   (если в проекте `.claude/commit-layers.txt` пуст — строку `Layer:` пропусти).
   `Refs:` всегда указывает на конкретный файл (`plan.md` или `phase-N.md`), не на папку.
7. Покажи пользователю: краткое резюме плана + имя ветки + первая Task для `/dev:implement`
