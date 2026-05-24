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

**How to apply:**
1. **Для 4+ параллельных агентов** — давай каждому `isolation: "worktree"`. Потом merge'и руками одним приёмом.
2. **Если worktree не используется** — запускай не больше 2 агентов параллельно, остальные последовательно.
3. **После каждого параллельного batch — обязательно `git log --stat` и `git show <hash> --stat`** чтобы проверить что diff соответствует commit message. Не доверяй отчётам агентов про «коммит прошёл».
4. **Session-limit риск:** перед запуском tooling-heavy агента (teamlead с 40+ tool_uses) — лучше один-два за раз, не 5. Иначе плохая утилизация: 3 готовы, 2 теряют контекст.
5. **Спасение прерванного агента**: его файлы обычно остаются на диске как `??`/staged. Проверь тестами что они валидны (`pytest path/to/tests`), потом закоммить отдельным «recovery» коммитом с явной пометкой в сообщении.

Связано: правило plan-driven dev (Refs trailer обязателен и в спасательных коммитах).
