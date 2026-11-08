# Handoff 2026-11-08 · полоса «Оператор» · gui-graceful-close · 1.2 влита → дальше 1.3

**Состояние:** Task 1.2 ВЛИТА в `main` (`68884237c`, ff после merge-коммитов `84d769ad7`, `441a33b8a`). Влито: 1.1a, 1.1, 1.2a, 1.2. **Следующая задача — Task 1.3** («волна последними», `plans/2026-10-20_gui-graceful-close/tasks/1.3.md`, Senior+, teamlead). Сначала сверить якоря по новому `main` (1.2 сдвинула `_ChildrenGroupStop`, `process_registry.py`, `process_manager_process.py`), пройти стадию 0 (reviewer, sonnet, синхронно); потом 1.4.

**Что сделано в этом заходе (цифры):**
- Ветка `feat/gui-close-1.2`: `7684e6472` стадия 0 (2 раунда, 19 расхождений с кодом исправлены в тексте), `2006db93a` слепые тесты (6 красных, break-injection тестера 11 мутаций), `2b3d6bbe3` реализация, `fda64c80a` правки ревью, `4c5f77116` доки, `287da9286` проба Mac.
- Реализация: `on_outcome` в `_confirm` (итог под локом, колбэки после лока, сначала метка читателя, потом итог), `_record_stop_outcome` с рангом `handed_over < survived < exited < terminated < killed` под листовым `_stop_outcome_lock`, `survived` после `kill()` и срока, `exited` умершему до стопа, `stop_deadline_at` (сигнал `stop_requested_wall` + окно `stop_window_s`, force — `min` с `system_stop.deadline_at`), `stop_wave="main"`, F1, ADR-PMM-042.
- Тесты: слепой набор 6 + авторский H1–H7 + страж `message_processor` — 14 passed; весь каталог PM по файлам зелёный, кроме 6 известных красных `test_cv_threads.py` (есть на чистом `main`). Инъекции I1–I13 «ожидал = получил»; I3b не краснил, закрыт тестом H5 (5/5 красный без лока); ревью нашло непокрытые инварианты `_confirm` → H6, H7.
- Ревью стадии 5 (reviewer sonnet): раунд 1 CHANGES REQUESTED (формулировка «остановлен» в ADR неверна для `survived`/`handed_over`; ранний `return` и порядок колбэков без тестов; предел «имя, а не воплощение»), раунд 2 APPROVED.
- Проба Mac (3 прогона, `docs/reports/2026-11-08_gui-graceful-close_1.2_mac-probe/`): (а) 65/65/64 ответов `exited` у соседа при живом медленном; (б)(в)(г) 0 нарушений.
- `validate.py` на слиянии: только 2 известные ошибки про память (чужие).

**Решения лида (не пересматривать без причины):** умершему до стопа ребёнку пишем `exited`; «остановлен» = `stop_outcome` ∈ {exited, terminated, killed}, `survived`/`handed_over` — НЕ остановлен (правило поправлено в ADR-042, `design.md:82,159`, `tasks/1.2.md`); F1 закрыт в 1.2; защиту по идентичности воплощения (`current is observed`) не делали — строка в ADR. Правки обвязки вне FILES: `_GroupProxy.__getattr__` в `test_pm_responsive_during_children_stop.py`, 2 ключа в `_PROCESS_KEYS` у стража 1.2a.

**Открыто / ненадёжно:**
- heavy на Windows для 1.1a, 1.1, 1.2a, 1.2 — PENDING (нужен стенд, у владельца Windows нет).
- Проба (д): итог последнего медленного ребёнка опросом не виден (очередь PM после закрытия корня не обслуживается, `done` в ответах не виден) — предел контракта записан в ADR-042, живым наблюдением не подтверждён.
- Устаревшая группа прежнего воплощения может записать итог под именем нового (ключ — имя); на `main` так же через цикл `_stop_many`; экспозиция низкая.
- Не воспроизведено: незапущенный ребёнок (`pid is None`) даст `exited` от корня.
- Живой путь GUI `router.request`, замер базы «окно скрыто», зонд `probe_gui_close_order_live.py` — как в прошлом handoff, не закрыты. F2–F4 (minor) в `docs/claude/OPEN_QUESTIONS.md` открыты.
- Две ошибки `validate.py` по памяти — координатору, если не занесены.
- Правило проекта: macOS-каталог PM одним pytest даёт ложный ENOSPC (`kern.posix.sem.max` = 10000) — гонять по файлу.

**Worktree и ветки:** `feat/gui-close-1.2` влита. Worktree `op-1.2`, `op-1.2-tester`, `op-merge` (ветка `docs/gui-close-1.2-done`), а также старые `op-1.2a`, `op-1.2a-tester`, `op-1.1`, `op-1.1-tester`, `op-1.1a` — убирать только по слову владельца. Корень на `main`, чужие правки (`docs/reports/2026-10-26_stage0-eval.md`, robot-файлы) не трогать. Мои команды `git checkout --`/`rm`/`rm -r` в корне система прав отклоняет — такое владелец делает сам.

**agentId (роль → что делал):** teamlead 1.2 `a2a68b0f2077b473e` (≈220k токенов — для 1.3 новый); reviewer ст. 5 1.2 `a644447e3b64dcb35`; reviewer ст. 0 1.2 `ab885e03f2a51416f`; tester 1.2 `afd1efff7349dca00`. Для 1.3 tester и reviewer — свежие.

**Уроки:** (1) в команде слияния не оставлять `cat >` без входа — вешает на ожидание stdin; (2) `main` в корне уходит вперёд за минуты: слияние в detached worktree, перед `--ff-only` подтянуть `main` (`git merge --no-ff main -F файл`), проверить `git merge-base --is-ancestor`; (3) `cd ../..` из вложенного worktree может выйти в другой репозиторий — команды git в цепочке с `&&` начинать с абсолютного `cd`; (4) lint-brief требует DESIGN многострочным и REDS ≤ 10 (страж — в тексте вне блока).
