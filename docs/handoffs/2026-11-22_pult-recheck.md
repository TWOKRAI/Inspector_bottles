# Handoff — полоса Пульт, повтор приёмки при `run_gate: true` (2026-11-22, сессия inspector-bottles-24)

**Состояние:** стенд снят, `stand.lock` удалён, порты свободны. Итог — `docs/reports/2026-11-22_pult_recheck-run-gate.md`; слепой отчёт tester — `…_pult_recheck_tester.md`; предсказания лида до окна — `…_pult_recheck_predictions.md`. Код не менялся.

**Заявка на слияние в main:** ветка `docs/pult-recheck-run-gate` (от `main` `15858154e`, один коммит, worktree `../Inspector_bottles--lane-pult-recheck`), только документы: три отчёта + 3 строки `plans/queue/defects.md` (C-103/104/105). Тема слияния — типа `feat`, не `merge(...)`; перед слиянием `python scripts/plans_progress/plans_progress.py --sync-order` не нужен (ORDER не тронут).

**Решения владельца (не мои):** C-103 — что мерим, ленту (критерий ≤ 1 с выполнен по прямому `belt.status`) или публикацию метрики сима (период публикации); C-104 — монитор по `layout.robot_io` и/или громкий лог (Р2); C-105 — `gui terminated` 5/5, нужен `investigator` (полоса Ф); русские подписи значений мониторов — код после 1.0.

**Не сделано:** кнопки GUI «Домой»/«ОСТАНОВИТЬ»/ленты в `ready`; «✕» ветка «Yes»; «Домой» при диске в полёте n=1; `run_alpha.py` с `--autostart`; β (после R4).

**agentId:** tester стенда 22.11 `a2f6c74bc16288802` (sonnet, ~220k токенов; при ~400k — свежий с файлом отчёта), haiku-опись `ad39cdbc085f1e51f`.
