# Хендофф лида lifecycle-owner-scope — после Task 0.1 (2026-10-04)

## Где
- Ветка `feat/lifecycle-owner-scope`, worktree `.claude/worktrees/lifecycle`, HEAD после `eff573720`. В main не влито
  (main `14aa47ab6` содержит план, DESIGN и спек до `f189c122d`). Слияние — только по слову владельца.
- venv: основной `.venv`, `PYTHONPATH=<корень worktree>`; pytest из `multiprocess_framework/modules`.
- Grep-инструмент не видит `.claude/worktrees` — `git grep` / Read.

## Сделано
- Task 0.1 DONE (`b4f24c58a` + `dad6ef9c9`, закрытие `eff573720`): интерфейсы владения в `base_manager/interfaces.py`,
  ADR-BM-008. Тестер 97/97, автор 46, `base_manager` 305 passed / 2 skipped. Инъекции 19/19 —
  `docs/reviews/2026-10-04_task-0.1-injections.md`. Итог и список для следующих спеков — `task-0.1.md` (конец файла).
- DESIGN ред. 3.1 — вердикт CTO 2026-10-04: Q1 `join_until`, Q2 `open_scope` в пакете (класс `Scope` не
  экспортируется), Q3 сроки (`kill_reserve_s` у `child`, `min` для срока ребёнка, резерв сверху, `kill()` не блокирует,
  `budget_s`+`deadline` → `ValueError`).
- План `lifecycle-stop-ownership` разведён с этим (Task 3.1 сужена, хук и долги — в нашу 1.2, их Ф2 ⛔ наша Ф1).

## Следующее — Task 0.2 (`Scope`, `Handle`, `open_scope`, `unclosed_roots`, G1), Senior+
Конвенция: спек `task-0.2.md` из plan.md 0.2 + DESIGN ред. 3.1 + `task-0.1.md` «Для следующих спеков» → reviewer
(MODE: plan, синхронно) → слепой tester в worktree на коммите спека → teamlead → инъекции ведущего (предсказания до
прогона; скрипт-образец `scratchpad/inj01/run_matrix.py` сессии 08888c98 — шаблоны в CRLF!) → reviewer → статус.
Хук lint-brief требует форму `.claude/plugins/dev/templates/executor-brief.md` (DESIGN/FILES ≤ 6/REDS/REPORT).

## agentId (повторный вызов дешевле нового)
| Роль | agentId | Видел |
|---|---|---|
| reviewer (спек 0.1 р1–р2, код 0.1 р1–р2) | `a276dbabfbf92daf5` | спек и код 0.1 — для 0.2 код-ревью р1 НЕ годится (видел реализацию 0.1, но не 0.2 — годится как свежий к коду 0.2; решать по правилу «свежий к коду») |
| teamlead (автор 0.1) | `ad5b9e57846529217` | реализация 0.1 — кандидат «один разработчик на трек» для 0.2 |
| cto (вердикт Q1–Q3) | `a11737b757ac1e437` | DESIGN, спек 0.1, зонды `scratchpad/cto01/` |
| tester 0.1 (слепой) | `a4526c1c5961ad74e` | только спек 0.1 — можно повторно для нового механизма 0.2 |

## Открыто
- `ChildProcessStop.kill()` блокирующий по П1 против неблокирующего по Q3 — спек 1.1 (условие ревьюера: отсчёт
  эскалации от момента `kill()`).
- О-12 (транспорт 5.11 ⛔ Ж0; 5.8a/5.8b ⛔ наша 1.3) — решение владельца не принято.
- `lifecycle-stop-ownership.md` (54 КБ) и `ORDER.md` (41 КБ) выше бюджета doc-size-guard 32 КБ — не делились.
