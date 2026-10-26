# Task 1.9b — PM на ExecutorManager, стоп не глохнет (L-9)

**Суть.** Жизненный цикл PM переведён на последовательный KeyedExecutor `pm-lifecycle` через ExecutorManager. У стопа один владелец (D4). T-команды (`process.relay`, `telemetry.broadcast`) идут через один FIFO с квотой `_T_CAP`: лишние T получают отказ `executor_busy`, при этом L-команда никогда не отказывается из-за ждущих T (I5). ADR-PMM-039.
**Итог.** Код, тесты H1–H12 и ADR готовы. Ревью задачи (Sonnet) и ревью ветки (Opus р.2) — APPROVED. Вердикт CTO по L/T исполнен (вариант (д)). Гейт CTO на `d23dc31ab` — MERGE WITH CONDITIONS (только документы, исполнены). CTO воспроизвёл I5: 64 relay + `process.stop` → `success: True`.
**Проверка.**
- `process_manager_module/tests` — 0 failed; D1 краснеет при откате. Инъекции — по прогнозу, расхождение И12 → H7 0/5 разобрано (`plans/lifecycle-stop-ownership/tasks/T1.9b_tests.md`).
- Стенд L-9: R2-A и R2-B — PASS. R2-C в тихом окне — PASS: `pm_exit` на ветке 0,985 / 1,273 / 1,547 с, на main 0,953 / 1,485 / 1,578 с; на обоих деревьях 10 из 10 < 2,0 с.
- Перед merge, после rebase на f8f399576:
  - backend tests — 239 passed;
  - framework suite — 2 failed / 12218 passed за 21 мин 25 с. Оба красных — флейки вне ветки: C-50 и новый C-52;
  - `validate.py` — 1 FAIL: старая копия тега урока C-42, унаследованная от main до `6c0be425d`; на main тег уже исправлен.
**Проблемы → решение.**
- Сторож `test_module_tiers` не принимал юнит стенда, лежащий в `docs/reports`. Решение: каталог стенда вписан в `_RUNNERLESS_BY_DECISION` с причиной.
- Агент записал вывод pytest в исходник стенда. Решение: файл восстановлен из HEAD.
- Агент запустил второй heavy-процесс внутри окна. Решение: прогоны стенда больше не отдаю агентам, запускаю сам.
- R2-C под чужой нагрузкой дал 8 из 10. Решение: повтор в тихом окне.
**Агенты.** 9; таблица agentId — в handoff `docs/handoffs/2026-10-26_lane-F-1.9b-merged.md`.
**Открыто.**
- `rolled_back: True` при системном стопе.
- `_wait_processes_ready` (A2).
- Лавина T под потоком broadcast.
- Число `_T_CAP` — владелец решит после задачи про ёмкость.
- C-48, C-52.
- Наблюдение C-23(а) на стенде не проведено.
**Дальше.** C-35, C-36, C-41, C-46, C-48.
**Подробно.** Ревью — `docs/reviews/`; стенд — `docs/reports/2026-10-26_lifecycle-stop-ownership_1.9b-stand/`; карта — `docs/maps/pm-lifecycle-commands.md`.
