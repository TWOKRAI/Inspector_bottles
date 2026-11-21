# Handoff полосы Н (observability-signal-contracts) — после стадии 0 Task 0.1–0.3

Сессия inspector-bottles-19, ветка `refactor/observability-signal-contracts` (worktree `../Inspector_bottles--lane-N`), коммит `dc6919c35`. Отчёт — `docs/reports/2026-11-21_observability-signal-contracts_0.1-0.3-stage0.md`.

Дальше (после слова координатора inspector-bottles-2b про слот писателя; слот занят К, Р2, Д2):
1. Teamlead (Opus) по 0.1 и 0.2: INTERFACE с телами функций и README; developer (Sonnet) по 0.3. Unit-тесты автор пишет ДО INTERFACE.
2. Слепой tester один раз на механизм, worktree на коммите после INTERFACE, запретные файлы — в TRAPS задач; тесты красные `4 failed, 4 passed` и т.д. (см. REDS).
3. GREEN функций, затем break-injection по таблицам инъекций (предсказания записаны до прогона), reviewer sonnet стадии 5; heavy — только в окне через `machine_gate.sh`.
4. Затем 0.4–0.13 по плану. Субагентам: не коммитить, не пушить.

Открыто для владельца/координатора: вето на поправки № 2, 3, 7 (литералы целей 1, 2, 10); бюджет размера Task (`amend` отказывает, `contract.lock` не обновлён). Основное дерево лежит на `main`; коммиты полосы — только в worktree ветки.
