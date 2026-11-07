# Handoff 2026-11-07 (2) · полоса «Оператор» · gui-graceful-close · 1.2a влита → дальше 1.2

**Состояние:** Task 1.2a ВЛИТА в `main` (`7465a5d4e`, merge-коммит; код итерации 2 — `38333f9fc`, отчёты и находка F1 — `7294a6e39`). Раньше в тот же заход влита малая правка `5db2a4d51` (G6 R6, `deleteLater` в `close_coordinator.py`). Влито: 1.1a, 1.1, 1.2a. **Следующая задача — Task 1.2** (бриф `plans/2026-10-20_gui-graceful-close/tasks/1.2.md`, решение CTO вариант A, ADR-PMM-042). Сначала сверить якоря по новому `main` и пройти стадию 0 (reviewer, sonnet, синхронно); потом 1.3; 1.4 разблокирован с стороны Р2 (T5.3e.5 влит `9eb384633`), но сверить, нет ли других условий в плане.

**Что сделано в этом заходе (цифры):**
- Три правки ревью 1.2a: `done` при `stopped or _killed` в `_ChildrenStop.join_until`; `initiator` только из конверта (`_EnvelopeSender(str)`, обрезка 64); `rejected`/`error` от `handle_state_set` → WARNING, ключ не помечается.
- Тесты: два файла `test_supervision_status_system_stop*.py` — 42 passed (зелёные у меня и у ревьюера). Новые H11–H13. Break-injection исполнителя 4 из 4 «ожидали = получили», ревьюер воспроизвёл 7 инъекций, все предсказаны.
- 24 соседних файла PM, каждый своим процессом: все зелёные при свободных семафорах. Один файл (`test_lifecycle_fifo_hazards`, порог 200 мс) один раз упал под нагрузкой и прошёл повторно (13 passed). Шесть красных `test_cv_threads.py` — на чистом `main` тоже (чужое).
- Проба Mac (`probe_slow.py` с чтением `r["result"]["system_stop"]`, 3 прогона): `answers_after` = 69 в каждом (порог ≥ 20), `initiator == "backend_ctl"`, `did_not_stop` = 0, shutdown 4,37 с, фаза в ответах `children`.
- `validate.py` на слиянии: 2 ошибки, обе про память (`docs/claude/memory`: теги и индекс BY-MODULE) — есть и на чистом `main`, не наши. G6 зелёный.

**Открыто / ненадёжно:**
- heavy на Windows для 1.1a, 1.1, 1.2a — PENDING (у владельца Windows нет).
- F1 (minor, в `docs/claude/OPEN_QUESTIONS.md`): `join_until` при `_group is None` выходит раньше проверки `_killed` → `done` не ставится при сбое реестра. Сделать в Task 1.2 (тот же `_ChildrenStop`) или отдельным коммитом. F2–F4 (minor): не охраняются статус `error`, пустой sender, запасной `done` в `close()`; докстринг слепого теста (:670) устарел; H13 считает только число WARNING.
- H11 идёт на Rig с двойником ребёнка, не на реальном процессе ОС; `_EnvelopeSender` — метка внутри PM, при межпроцессном пути потеряется (`initiator` станет `unknown`, безопасный отказ); подделка sender в самом конверте дочерним процессом не проверялась.
- macOS: каталог PM одним процессом pytest даёт ложный ENOSPC (лимит POSIX-семафоров `kern.posix.sem.max` = 10000; в этот заход семафоры исчерпывали и чужие прогоны — heavy сессии `-93`). Гонять по файлу и повторять, когда машина свободна. Кандидат в память-урок (в канон `docs/claude/memory/` не писал).
- Живой путь GUI `router.request`, замер базы «окно скрыто» и зонд `probe_gui_close_order_live.py` — как в прошлом handoff, не закрыты.
- Две ошибки `validate.py` по памяти (чужие файлы) — координатору, если не занесены.

**Worktree и ветки:** `op-merge` убран. `feat/gui-close-1.2a` влита; worktree `op-1.2a`, `op-1.2a-tester`, `op-1.1`, `op-1.1-tester`, `op-1.1a` — убирать только по слову владельца (в `op-1.2a` лежат untracked `*.commitmsg.txt`, не коммитить). Корневой checkout стоит на `main`, в нём чужая правка `docs/reports/2026-10-26_stage0-eval.md` — не трогать.

**agentId (роль → что делал):** teamlead 1.2a r2 `a86a4e982a5d44003`; reviewer ст. 5 1.2a итерация 2 `affa7f766764b0a16`. Старые (из прошлого handoff) в новой сессии недоступны.

**Уроки:** при ENOSPC на macOS сначала проверять `kern.posix.sem.max` и чужие прогоны, а не диск; обёртка `python -I -c` убирает каталог пробы из `sys.path` — кладите нужные пути в `PYTHONPATH`; слияние при `main`, стоящем в корневом checkout: merge в отдельном detached worktree, `validate.py`, затем `git merge --ff-only` в корне.
