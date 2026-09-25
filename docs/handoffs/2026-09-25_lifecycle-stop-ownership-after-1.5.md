# Handoff: lifecycle-stop-ownership после Task 1.5 (2026-09-25)

**План:** [`plans/lifecycle-stop-ownership.md`](../../plans/lifecycle-stop-ownership.md) · **main:** `2fd1a1f6` (merge Task 1.5)

## Сделано

- **Task 1.5 — DONE кроме Linux-пункта, слита в main** (`2fd1a1f6`, docs `3af662cc`). Механизм плана (prctl + труба)
  заменён решением владельца на POSIX-сторож `os.getppid()` первой строкой `run_process_function`, взводит только
  `ProcessRegistry._create_process` (`parent_pid=os.getpid()`), сам PM не сторожится. ADR-PMM-032. Причины замены —
  в плане, раздел Task 1.5.
- Живьём `inspection_full`, `kill -9` PM: main 6/6 сирот → ветка 0 за 0.96–0.99 с; стоп/рестарт без регрессии.
- Merge gate — CTO (Fable): ACCEPT_WITH_DEBT, долги D1–D5 в плане и `docs/reviews/2026-09-25_lifecycle-task-1.5-cto.md`.
- Сосед gui-service (`inspector-bottles-05`) получил SHA; бронь портов 8860–8910 снята обеими сторонами.

## Следующий шаг

**Task 1.6** — потери при стопе видны снаружи: итог отпуска очередей каждого ребёнка (`released` / `buffered_dropped`,
сегодня только строка `emergency_log` в stderr, `process_runner.py`, конец `run_process_function`) доезжает до PM,
PM пишет сводку стопа одной записью в `observability.db`. Level Middle+, assignee developer. Acceptance — в плане.
Порядок стадий как всегда: tester в worktree до кода → developer → инъекции ведущего → стенд → reviewer.
Перед стартом спросить соседа gui-service: 1.6 трогает `process_runner.py` и, вероятно, `process_manager_process.py`
(сосед готовит фикс потери ответа `system.shutdown` — роутер «синхронный самоответ», gui-service 1.3b; решение за CTO).

## Открыто

- **Linux для 1.5 (D1)** — отложен владельцем; как закрыть — `docs/claude/OPEN_QUESTIONS.md`, запись от 2026-09-25.
- D2 запас 0.25 с из 2.0 (флак на медленном CI → поднять приёмку/снизить grace, не опрос); D3 внуки ребёнка на
  `os._exit`; D4 код 75 = `EX_TEMPFAIL`; D5 `ResourceTracker called reentrantly` в тесте Task 1.3 — не сверено с main.
- Нестабильный `test_system_shutdown_children_exit_hook_in_system_stop_mode` (гонка `(system-wide)`): ветка 1/9, main 2/8 —
  не регрессия 1.5; причина — у соседа в разборе `system.shutdown`.
- Урок: живые замеры рестарта — по имени процесса, которое есть в рецепте (`inspection_full`: `processor`, не
  `preprocessor`; неверное имя даёт `success: false` за 0.02 с).
- Живые прогоны с `--backend-live`, иначе живые тесты молча `skipped`.

## Хвосты

Worktree не удалены, ждут решения владельца: `.claude/worktrees/lso-1.5-dev` (`fix/lifecycle-1.5`),
`lso-1.5-tester` (`test/lifecycle-1.5`), `lso-1.4-dev`, `lso-1.4-tester`, `lso-hotfix`.
Мои порты для живых прогонов — 9800–9899.
