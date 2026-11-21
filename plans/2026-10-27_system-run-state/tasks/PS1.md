# Task PS1 — разбить `plan.md` под бюджет 32 КБ (бриф, ред. 1, ЧЕРНОВИК лида)

Основание: отчёт полосы Ф 2026-11-21 §4 («`plan.md` 35 КБ при бюджете 32 КБ, было 34 КБ до правки»). Мерка — `git cat-file -s <sha>:plans/2026-10-27_system-run-state/plan.md` (не `wc -c`): на `96fb1ea59` = 35 928 байт. Задача документная; не стартовала; нужна, чтобы шапка плана читалась целиком.

## Открыто для лида

| № | вопрос | замер | умолчание брифа |
|---|---|---|---|
| О1 | что выносить | по разделам (байты, awk по `## `): «Порядок выполнения» 15 706; «Решения (decisions log)» 6 562; «Решения владельца (В1–В8)» 2 436; «Вопросы CTO» 1 449; «В10» 1 218; «Вопрос владельцу (закрыт)» 1 064 | в новый `plans/2026-10-27_system-run-state/decisions.md` — три раздела решений и три вопроса (≈ 13,4 КБ); в `plan.md` — по абзацу-указателю на каждый |
| О2 | на что ссылаются из других файлов | `git grep -n "plan.md#" -- plans docs multiprocess_framework backend_ctl` | перед правкой — список якорей; якорь-заглушку оставить, если на него ссылаются |
| О3 | счётчики `plans_progress` | читает «Порядок выполнения» (задачи, шапки) — раздел НЕ трогаем | в `plan.md` остаётся целиком |

TASK: PS1 — вынести решения и закрытые вопросы из `plan.md` в `decisions.md` рядом; `plan.md` ≤ 32 000 байт   PLAN: plans/2026-10-27_system-run-state/plan.md
ROLE: docs-writer
CHAIN: лид полосы Ф -> you -> лид (проверка якорей, `scripts/plans_progress`, `validate.py`)

DESIGN (decided by the lead — you type it, you do not derive it):
  Раздел «Порядок выполнения» (строки ~64–155: Ф0…Ф3, статусы по git) остаётся в `plan.md` нетронутым — его читает `scripts/plans_progress/plans_progress.py`, счётчик «20 из 32» не должен измениться.
  В новый файл `decisions.md` переносятся БЕЗ изменения текста: «Решения владельца (В1–В8…)», «Вопрос владельцу (закрыт 2026-11-02)», «Вопрос владельцу В10…», «Вопросы CTO (Task 0.1)», «Решения (decisions log)». В `plan.md` на их месте остаётся один раздел «Решения и вопросы» со ссылкой и одной строкой на каждую группу (где открытое: В10 — одна строка с состоянием «открыт, блокирует п.6 Task 2.2»).
  Перед правкой: `git grep -n "plan.md#" -- plans docs multiprocess_framework backend_ctl scripts` и перечислить якоря, ведущие на переносимые разделы; такие ссылки обновить на `decisions.md#…` (файлы других планов не править — только перечислить лиду, раздел «Связи» плана это допускает).

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. plans/2026-10-27_system-run-state/plan.md — вынос разделов, указатели
  2. plans/2026-10-27_system-run-state/decisions.md — новый, перенесённые разделы

REDS: n/a — документы.

ACCEPTANCE:
- размер — `git cat-file -s :plans/2026-10-27_system-run-state/plan.md` после `git add` → число ≤ 32000
- счётчик плана — `python scripts/plans_progress/plans_progress.py` → тот же «влито/всего», что до правки (20/32 на `96fb1ea59`)
- структура — `python scripts/validate.py` → exit 0

TESTS: `python scripts/validate.py`; `python -m scripts.sync --check`.

OUT OF SCOPE: «Порядок выполнения» и шапки задач; `tasks/*.md`; другие планы; переписывание текста решений; правка `ORDER.md`.
TRAPS: «Решения (decisions log)» ссылаются друг на друга по номерам — не перенумеровывать; журнал решений владельца `plans/queue/decisions.md` — другой файл, не путать.
HANDOFF IN: none
