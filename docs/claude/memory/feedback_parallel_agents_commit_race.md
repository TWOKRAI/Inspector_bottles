---
name: feedback-parallel-agents-commit-race
description: Параллельные developer/teamlead агенты на одной ветке без worktree склеивают коммиты и теряют файлы из-за race condition pre-commit hook
metadata:
  type: feedback
---

При запуске **5+ агентов параллельно** через `Agent` tool без `isolation: "worktree"`, и при наличии в проекте `pre-commit-session-log.sh` hook'а, который auto-stage'ит `docs/sessions/YYYY-MM-DD.md` — содержимое разных задач может склеиться в один коммит, а файлы одной из задач полностью пропасть из коммита.

**Конкретный случай 2026-05-24 (Phase 0 Foundation):**
- Запустил 5 параллельных агентов (Task 0.1/0.2/0.3/0.5/0.7).
- Коммит `829176c` имел сообщение «FrameRouter helper из Task 0.1», но содержимое — `StateAdapterBase` из Task 0.2. Файлы Task 0.1 (`multiprocess_prototype/backend/routing/`) остались untracked.
- Task 0.3 и 0.5 уперлись в session-limit Anthropic и не успели сделать `git commit` — пришлось спасать отдельным коммитом `965dc10`.
- Pre-commit hook конфликтовал на ходу с auto-fixes (rolling back the stash) когда были staged + unstaged + untracked одновременно.

**Why:** session-log hook + параллельный git add от агентов = непредсказуемая последовательность staging. Сообщение коммита не отражает diff.

**Конкретный случай 2026-05-26 (Phase 5, Tasks 5.4+5.5):**
- Запустил всего **2 агента параллельно** (по предыдущему правилу — допустимо).
- Task 5.4 коммитнул свой `test_replace_blueprint.py` (ee704141) штатно.
- Task 5.5 (RecipeStateAdapter) написал свои файлы (`recipe_adapter.py`, тесты), но ещё не успел вызвать `git commit`.
- Task 5.4 запустил **docs(plans)** коммит (`git add plans/...`) — но `git commit` подхватил и **уже изменённые файлы Task 5.5** через session-log hook (`git add docs/sessions/...`). Коммит **315a6b6a** заявлен как docs, по факту 274+252 строк нового framework-кода Task 5.5.
- Подтверждение race **даже на 2 агентах**. Файлы не потеряны, но git history соврала о содержимом.

**How to apply (обновлено 2026-05-26):**
1. **Для 2+ параллельных агентов** — давай каждому `isolation: "worktree"`. Любая параллель без worktree рискует race'ом из-за session-log hook'а.
2. **Если worktree не используется** — запускай агентов **строго последовательно** (по одному). «Макс 2» — устаревший компромисс, доказал свою ненадёжность.
3. **После каждого коммита агента — обязательно `git show <hash> --stat`** чтобы проверить что diff соответствует commit message. Не доверяй отчётам агентов про «коммит прошёл».
4. **Session-limit риск:** перед запуском tooling-heavy агента (teamlead с 40+ tool_uses) — лучше один-два за раз, не 5. Иначе плохая утилизация: 3 готовы, 2 теряют контекст.
5. **Спасение прерванного агента**: его файлы обычно остаются на диске как `??`/staged. Проверь тестами что они валидны (`pytest path/to/tests`), потом закоммить отдельным «recovery» коммитом с явной пометкой в сообщении.
6. **Сломанную историю** на локальной ветке можно исправить через `git reset --soft <hash>` + повторные коммиты. Если ветка не запушена — допустимо оставить as-is, перед PR squash или amend.

Связано: правило plan-driven dev (Refs trailer обязателен и в спасательных коммитах).
