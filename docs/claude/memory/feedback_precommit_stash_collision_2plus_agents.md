---
name: feedback-precommit-stash-collision-2plus-agents
description: "pre-commit's staged_files_only isolation (its own patch-based stash, not git stash) collides when 2+ agents commit concurrently in the same non-worktree checkout — reverts unrelated unstaged files tree-wide, blast radius grows with each retry; также: Хук session-log пишет в общий журнал при коммите ЛЮБОГО автора — двум писателям в одном дереве он гарантированно блокирует оба коммита, и MM в статусе не значит «обе стороны целы»; Параллельные developer/teamlead агенты на одной ветке без worktree склеивают коммиты и теряют файлы из-за race condition pre-commit hook"
merged_from: [feedback_a_hook_that_writes_a_shared_file_deadlocks_two_writers, feedback_parallel_agents_commit_race]
mechanism: "pre-commit, parallel-commits"
metadata:
  type: feedback
---

Observed independently by two agents on the same day (branch `fix/backend-ctl-hardening`,
2026-07-20): pre-commit's `staged_files_only` isolation snapshots *all* unstaged changes
tree-wide into a patch file before running hooks, then tries to `git apply` that patch
back afterward. When a second agent commits concurrently in the same working tree (no
`git worktree` isolation — see `feedback_git_stash_pop_wrong_stash.md` for a related but
distinct stash-based collision), a shared file the hooks touch on every commit
(`docs/sessions/<date>.md`, written by an "append session log" hook) has usually moved
by the time the patch tries to re-apply, so `git apply` aborts and pre-commit fails the
whole commit — leaving the patch orphaned in `~/.cache/pre-commit/patch<N>` and the
working tree reverted to a stale state for **every** file that was unstaged at stash
time, not just the colliding one.

Retrying blindly makes it worse: each retry re-snapshots whatever is unstaged *right
then* (including the other agent's freshly-reverted files), so the blast radius grows
across attempts — one incident escalated from 2 files to 9+ files across two agents'
work over 8 retries, including files neither agent's own commit even referenced.

**Why:** the project's shared pre-commit hooks (ruff-format auto-fix + append-session-log)
write to files tree-wide on every commit; under 2+ agents in one checkout this makes the
race near-certain, not theoretical.

**How to apply:**
- Prefer `git worktree` per concurrent agent (see the project's existing
  `feedback_worktree_for_parallel_samefile` guidance) — this failure mode doesn't occur
  across separate worktrees.
- If stuck without worktree isolation: cap retries at 2-3. After that, stop and escalate
  — do not keep retrying hoping the other agent finishes first.
- Recovery for files with a *staged* (index) copy that reverted in the working tree:
  `git show :path/to/file > path/to/file` restores the last-known-good content without
  invoking `git checkout`/`git restore` (both may be blocked by permission settings).
  Files that were only ever unstaged (never staged) have no safe recovery source — leave
  them for their owning agent, don't guess.
- Before assuming a commit landed, verify: `git log --oneline -3` + `git status --short`.
  "Commit failed" after this failure mode means "re-verify everything in the tree," not
  "nothing changed" — collateral files can revert even though your own commit never ran.

**Refined 2026-09-08 (three failed commits in a row, then reproduced and fixed).** The collision
does NOT need a second agent to be committing at the same time, and `git diff --name-only` being
empty proves nothing. `git commit -- <pathspec>` builds a TEMPORARY index from HEAD plus the
pathspec files; pre-commit computes "unstaged" against that temporary index, so any file that is
staged in the real index but outside the pathspec (here `docs/sessions/<date>.md`, staged by a
neighbour's earlier attempt) shows up as an unstaged diff, gets stashed, the session-log hook
appends to that same file, and the stash fails to re-apply at the hook's insertion point. Fix that
worked: bring the session file to HEAD in both tree and index (`git show HEAD:path > path && git add path`),
commit with the pathspec, then realign the index to the new HEAD the same way. The 19 dropped lines
were the hook's own record of a failed attempt — worthless, but keep a copy before dropping.
Line endings (CRLF in tree vs LF in index) were the wrong hypothesis; ruled out by the
`autocrlf=false` diff being empty and the fourth failure. See also
[[feedback_a_hook_that_writes_a_shared_file_deadlocks_two_writers]].

**Статус 2026-10-03:** хук `session-log` снят с pre-commit (Task 1.1 плана commit-mechanism, слияние `8b0eeac41`). Журнал пишет и коммитит `/core:team:wrap-up` (шаг 7, один явный путь). Урок остаётся в силе для любого хука, который стейджит общий файл; в ветках со старым `main` хук ещё работает.

## Слито из feedback_a_hook_that_writes_a_shared_file_deadlocks_two_writers (_archive/feedback_a_hook_that_writes_a_shared_file_deadlocks_two_writers.md)

**Хук `pre-commit`, который САМ пишет в общий файл, превращает двух писателей в
одном дереве во взаимную блокировку.** Замер 2026-09-08, две сессии в корневом
дереве: `append session log to docs/sessions/` дописывает `docs/sessions/<дата>.md`
при коммите **любого** автора. Дальше механика неизбежна: `pre-commit` прячет
незастейдженное в стеш, гоняет проверки, дописывает журнал — и не может наложить
стеш обратно, потому что конфликтует со своей же записью:

```
Stashed changes conflicted with hook auto-fixes... Rolling back
patch failed: docs/sessions/2026-09-08.md:144
patch does not apply
```

Отбиты **три** коммита подряд (два моих, один соседа). Проверки при этом
проходили ВСЕ — ruff, bandit, whitespace: падал сам `pre-commit` на откате стеша,
уже после зелёных хуков.

**Why:** пока хотя бы у одного писателя этот файл имеет незастейдженный diff, не
пройдёт НИЧЕЙ коммит, и симптом («patch does not apply» на чужом файле) уводит
искать причину в чужой работе. Диагноз стоил двух кругов переписки. Хуже: откат
стеша **вернул в дереве четыре чужих файла к HEAD**, и спасли их только индексные
копии.

**Механизм, установленный точно (третья попытка упала при ПУСТОМ `git diff`,
и это опровергло первое объяснение — «виноват незастейдженный diff»).**
`git commit -- <pathspec>` строит **временный индекс из HEAD плюс файлы
pathspec**. Файла журнала в pathspec нет, значит в этом временном индексе он
равен HEAD (146 строк), а в дереве лежит застейдженная версия (165). Разницу в
19 строк `pre-commit` видит как незастейдженную, стешит её, хук `session-log`
дописывает в тот же файл — и откат стеша не накладывается.

**Отсюда точная формулировка: ловушка срабатывает у ЛЮБОГО коммита с pathspec,
если в НАСТОЯЩЕМ индексе у файла журнала есть изменение относительно HEAD —
даже когда `git diff` пуст.** Первое объяснение («переносы строк», «грязный
индекс») было ложным: оно объясняло симптом и не предсказывало третий отказ.

**How to apply:**
1. Перед коммитом с pathspec в общем дереве: файл журнала должен быть равен HEAD
   **и в дереве, и в индексе** — `git show HEAD:<path> > <path> && git add <path>`.
   Проверка `git diff --name-only` пуста НЕ достаточна: она не видит разницы
   между индексом и HEAD. После коммита выровнять индекс по новому HEAD тем же
   способом.
2. Содержательную разницу версий журнала сверять с вырезанными `\r`
   (`diff <(tr -d '\r' < a) <(tr -d '\r' < b)`) — иначе CRLF показывает
   расхождение по КАЖДОЙ строке и прячет настоящую разницу в две записи.
3. **`MM` в `git status` говорит, что обе стороны СУЩЕСТВУЮТ, а не что обе
   целы.** Я построил на этой букве утверждение «ничего не потеряно» — и оно было
   ложным: рабочие копии четырёх файлов были откачены до HEAD, уцелели индексные.
   Целостность рабочей копии доказывается сравнением содержимого, а не наличием
   буквы в статусе.
4. Радикальное лекарство — **worktree на писателя**: сегодня же реализация Task
   4.13 шла в `.claude/worktrees/t413-impl` и ни во что не упёрлась.

Связано с [[feedback_precommit_stash_collision_2plus_agents]],
[[feedback_commit_takes_the_whole_index]],
[[feedback_a_peer_session_shares_the_tree]],
[[feedback_commit_takes_the_whole_index]].

**Статус 2026-10-03:** хук `session-log` снят с pre-commit (Task 1.1 плана commit-mechanism, слияние `8b0eeac41`). Журнал пишет и коммитит `/core:team:wrap-up` (шаг 7, один явный путь). Урок остаётся в силе для любого хука, который стейджит общий файл; в ветках со старым `main` хук ещё работает.

## Слито из feedback_parallel_agents_commit_race (_archive/feedback_parallel_agents_commit_race.md)

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

**Конкретный случай 2026-07-11 (Ф4.8 apply + план proto-frontend-carve):**
- 2 параллельных агента (developer + manager) без worktree. Коммиты не склеились, но manager создал свою ветку `docs/plan-proto-frontend-carve` **от вершины чужой ветки** `feat/constructor-f4-8-apply` (3fa6998e), а не от main — HEAD в общем дереве стоял на чужой ветке ([[worktree-stale-base]] в новой форме).
- Плюс оба могли переключать HEAD друг под другом между шагами. Разрулено SendMessage-координацией: проверять `git branch --show-current` перед каждой git-операцией; грязную базу пересаживать `git rebase --onto main <чужой-SHA>` перед merge.

**Апдейт инструмента 2026-08-05 (Claude Code 2.1.152 → 2.1.222):**
- 2.1.216 — worktree-изолированным субагентам запрещено перенаправлять git флагами (`--git-dir`, `-C`) и переменными окружения (`GIT_DIR`, `GIT_WORK_TREE`).
- 2.1.222 — изолированная сессия и её субагенты больше не выполняют разрушительные git-команды по основному чекауту; изоляция распространена на правки файлов и Bash во всех типах сессий.
- **Что это меняет:** путь «с worktree» стал надёжным — раньше изоляция держалась на дисциплине агента, теперь её держит харнесс. Параллель по 3+ агента с `isolation: "worktree"` больше не требует ручной сверки, куда он писал.
- **Что это НЕ меняет:** корень гонки — общий session-log pre-commit hook и общее рабочее дерево, а не обход git. Параллель **без** worktree ломается ровно так же, как 2026-05-26. Правило «без worktree — строго последовательно» остаётся в силе.
- Смежное: с 2.1.212 фоновый субагент по завершении **сам** коммитит, пушит и открывает draft PR — то есть теперь коммитить может даже тот агент, которого об этом не просили. Явно запрещай это в промпте (см. `.claude/CLAUDE.md`, «Subagents are background by default»).

**How to apply (обновлено 2026-08-05):**
1. **Для 2+ параллельных агентов** — давай каждому `isolation: "worktree"`. С 2.1.216/2.1.222 это уже не «надежда на дисциплину», а enforced-граница. Любая параллель без worktree по-прежнему рискует race'ом из-за session-log hook'а.
2. **Если worktree не используется** — запускай агентов **строго последовательно** (по одному). «Макс 2» — устаревший компромисс, доказал свою ненадёжность; апдейт 2.1.222 его не воскрешает.
3. **После каждого коммита агента — обязательно `git show <hash> --stat`** чтобы проверить что diff соответствует commit message. Не доверяй отчётам агентов про «коммит прошёл».
4. **Session-limit риск:** перед запуском tooling-heavy агента (teamlead с 40+ tool_uses) — лучше один-два за раз, не 5. Иначе плохая утилизация: 3 готовы, 2 теряют контекст.
5. **Спасение прерванного агента**: его файлы обычно остаются на диске как `??`/staged. Проверь тестами что они валидны (`pytest path/to/tests`), потом закоммить отдельным «recovery» коммитом с явной пометкой в сообщении.
6. **Сломанную историю** на локальной ветке можно исправить через `git reset --soft <hash>` + повторные коммиты. Если ветка не запушена — допустимо оставить as-is, перед PR squash или amend.

Связано: правило plan-driven dev (Refs trailer обязателен и в спасательных коммитах).

**Статус 2026-10-03:** хук `session-log` снят с pre-commit (Task 1.1 плана commit-mechanism, слияние `8b0eeac41`). Журнал пишет и коммитит `/core:team:wrap-up` (шаг 7, один явный путь). Урок остаётся в силе для любого хука, который стейджит общий файл; в ветках со старым `main` хук ещё работает.
