# Хендофф лида lifecycle-owner-scope — Task 0.2 после правок ревью р1 (2026-10-05, пауза по слову владельца)

## Где
- Ветка `feat/lifecycle-owner-scope`, worktree `.claude/worktrees/lifecycle`. `main` влит (`9d8e5dfcc`, без конфликтов).
  В `main` ветка НЕ влита — только по слову владельца.
- venv основной, `PYTHONPATH=<worktree>`, pytest из `multiprocess_framework/modules`. Grep-инструмент не видит worktree — `git grep`.

## Сделано в этой сессии
- Ревью кода 0.2 р1 (reviewer `a51db4da46fc92690`): CHANGES REQUESTED, 3 major с воспроизведениями
  (скрипты `scratchpad/rev02/` сессии aab3cfb2): F1 вечная самоблокировка `unclosed_roots()` под финализатором gc;
  F2 взаимное ожидание и ложный выживший в `IHandle.close` из потока поддерева; F3 `__del__` ресурса под локом области.
  Находка 4 (один выживший в двух отчётах reporter'а) — без кода, записана в `task-0.2.md` для спека 1.2.
- Правки teamlead `a1882e8f4a10d6b8c`: `e75d19b81` RED, `324ad1170` фикс, `b7410e9f2` отчёт, `bf7b27d6e` тесты по инъекциям.
  `pytest base_manager` → 559 passed / 2 skipped.
- Инъекции ведущего: `docs/reviews/2026-10-05_task-0.2-fix-injections.md` — 6/6 совпали с предсказаниями
  (итерация 1 вскрыла вакуумный F1-тест — исправлен).

## Следующее
1. Ревью кода 0.2 р2 — тот же reviewer `a51db4da46fc92690` (повторный вызов по agentId), синхронно; дать ему SHA
   `bf7b27d6e` и отчёт инъекций. APPROVED → в `plan.md` Task 0.2 `[DONE 2026-10-?? — <sha>]` + галочки, коммит `docs(plans):`.
2. Task 0.3 `Subscribers` ∥ 0.4 `qt_lifetime` по конвенции: спек → reviewer MODE: plan → слепой tester в worktree на
   коммите спека → teamlead → инъекции ведущего → reviewer.

## Открыто / ненадёжно
- J5 ловится только белым ящиком (`root._close_entry_early` напрямую); через публичный API ветка недостижима.
- Тайминговые пороги F2 (≤ 0.1 с) и G3 (`sleep(0.3)`, `dt >= 0.2`) на загруженной машине не мерились.
- Ревьюер р1 не воспроизводил: гонку `child.close()` против close родителя, reporter для отказа `own` в гонке с концом close.
- В дереве не закоммичены файлы памяти teamlead (`.claude/agent-memory/teamlead/MEMORY.md` + новый
  `feedback_gc_finalizer_test_needs_gen0_pin.md`) — их судьбу решить при слиянии (в main их держит сессия-владелец памяти).
- Хук subagent-stop-gate в worktree пишет «pytest cannot be imported, run uv sync» — ложный: venv основной, `uv sync` запрещён.
