---
description: Show plan status — task completion progress
---

Покажи прогресс по планам:

0. **Ledger (обзор без перечитывания всех планов):** прочитай `plans/README.md` —
   таблицы «Active» / «Archived». Это единый индекс: что открыто, что в архиве,
   с кратким остатком. Для общего «что у нас незакрыто» — этого достаточно, не
   читай каждый план. Если ledger расходится с реальными `[DONE]`-статусами файлов —
   отметь рассинхрон (и предложи поправить строку в `plans/README.md`).

1. **Текущая ветка:**
   ```bash
   git branch --show-current
   ```
   Извлеки slug из имени ветки (всё после `feat/`, `fix/`, `refactor/`, `docs/` и т.д.).

2. **Найди план** (планы date-prefixed: `plans/YYYY-MM-DD_<slug>.md`):
   - **Single-file:** glob `plans/*_<slug>.md` (шире — `plans/*<slug>*.md`).
   - **Multi-phase:** каталог `plans/*_<slug>*/` — прочитай `plan.md` **и все** `phase-*.md`:
     ```bash
     ls plans/*_<slug>*.md 2>/dev/null                              # single-file план(ы)
     ls -d plans/*_<slug>*/ 2>/dev/null                             # каталог(и) плана
     ls plans/*_<slug>*/plan.md plans/*_<slug>*/phase-*.md 2>/dev/null  # multi-phase: plan + все фазы
     ```
   - Если не найден — fallback: поиск по `Refs:` в коммитах текущей ветки
     (портируемо, без GNU-only `grep -P`/`\K` — работает и на macOS/BSD grep):
     ```bash
     git log main..HEAD --format=%B | grep -oE "Refs: [^[:space:]]+" | sed 's/^Refs: //'
     ```
   - Если всё ещё не найден — покажи список всех файлов в `plans/`

3. **Для найденного плана:**
   - Прочитай файл(ы)
   - Посчитай задачи по статусам: `[PENDING]`, `[IN_PROGRESS]`, `[DONE]`
   - Покажи frontmatter (Slug, Дата, Статус, Ветка)

4. **Формат вывода (на русском):**
   ```
   ## План: <название>
   **Slug:** <slug>  |  **Ветка:** <branch>  |  **Статус:** IN_PROGRESS
   **Прогресс:** ████████░░ 8/10 задач (80%)

   ### Phase 1: <name> ✅
   - [DONE] Task 1.1: ...
   - [DONE] Task 1.2: ...

   ### Phase 2: <name> 🔄
   - [DONE] Task 2.1: ...
   - [PENDING] Task 2.2: ...
   ```

5. **Если нет привязанного плана:** покажи таблицу «Active» из ledger
   `plans/README.md` (а не сырой `ls plans/`):
   ```
   ⚠️ Нет привязанного плана для ветки `<branch>` (нормально для hotfix/experiment).
   Активные планы (из plans/README.md):
   - 2026-05-01_auth-rbac.md — IN_PROGRESS — остаток: RBAC tests
   - 2026-05-03_graph-validation.md — DRAFT
   ```

Если $ARGUMENTS содержит конкретный slug или путь — показать именно его.
Если пусто — показать план для текущей ветки.

$ARGUMENTS
