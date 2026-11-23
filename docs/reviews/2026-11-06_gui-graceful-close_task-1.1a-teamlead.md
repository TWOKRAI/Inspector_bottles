# Task 1.1a — отчёт teamlead (GREEN)

STATUS: DONE_WITH_CONCERNS

## Итог

- `ProcessModule._own_work_late(work)` — новый защищённый крюк корня (база пустая). Вызов в шаге 6a после `workers`, до `plugins-stop`.
- PM: в `_own_work_late` переехала только область `children`; `summary` остался в `_own_work`.
- Порядок закрытия `work` PM: `plugins-stop → children → workers → observability_watcher → recipe_watcher → state_store → summary`.
- Бюджет НЕ менялся (решение лида по ESCALATION). Ограничение записано в ADR-PMM-040 «Известное ограничение» и закреплено тестом `xfail(strict=True)`.
- Хазард-тест переименован в `test_app_watchers_and_state_store_close_after_children_end_before_summary`, ожидание журнала новое. Докстринг модуля тестов поправлен (строка о порядке).
- ADR-PMM-040 добавлен. В ADR-PMM-036 пункт о порядке получил ссылку «заменён ADR-PMM-040». `python -m scripts.sync` переписал строку индекса `multiprocess_framework/DECISIONS.md` (001…040).

## Доказательства

Путь импорта (cwd = корень worktree):
`PYTHONPATH=$PWD $MAIN/.venv/bin/python -c "import multiprocess_framework as m; print(m.__file__)"` →
`/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/op-1.1a/multiprocess_framework/__init__.py`

| Проверка | Команда (через `machine_gate.sh … operator-1.1a-teamlead`) | Результат |
|---|---|---|
| Слепой набор + hazards + golden | medium, `pytest test_pm_responsive_during_children_stop.py test_process_root_pm_hazards.py process_module/tests/test_process_root_acceptance.py` | `40 passed` (до xfail-теста); после него — `40 passed, 1 xfailed` |
| Каталог PM + golden | medium, `pytest process_manager_module/tests process_module/tests/test_process_root_acceptance.py` | `6 failed, 1551 passed, 1 skipped, 1 xfailed in 408.60s` |
| Baseline `main` 315fdbf51 (отдельный detached worktree) | light, `pytest process_manager_module/tests/test_cv_threads.py` | `6 failed, 9 passed`: те же 6 `test_cv_threads.py::*`, красные и до правки, не чинились |
| Стабильность слепого набора | light, 3 раза подряд | `8 passed` ×3 (9,92 / 9,83 / 9,91 с), флака нет |
| PM test 1, числа | light, проба повторяет сценарий теста 1, 3 раза | ответов 12/12, 12/12, 12/12; max латентность 0,013 / 0,013 / 0,014 с (≤ 0,3); ответ на `system.shutdown` раньше смерти ребёнка на 3,02 с |
| xfail-тест закреплён по делу | light, `--runxfail` | падает ровно на `assert 'proc/ProcessManager/work/workers' not in (…children/processes', …workers')`; без флага — XFAIL ×3 |
| ruff | `ruff check -q` (3 файла) | rc=0 |

Тесты 3 и 6 зелёные по делу: I4b и I6b ниже показывают, что их содержательные assert'ы ловят поломку.

## Инъекции (оба набора: слепой + `test_process_root_pm_hazards.py` + golden; патч, прогон, откат; `RESTORED_OK` — cmp с бэкапом)

| № | Патч | Предсказано красным | Получено красным | Расхождение |
|---|---|---|---|---|
| I1 | `children` обратно в `_own_work` | PM 1, 2, 3, 6, hazards-тест | PM 1, 2, 3, 6, **7**, hazards-тест, xfail-тест (XPASS strict) | PM 7 предсказан зелёным, получен красным: литерал PM 7 `[children.join_end, workers.stop_all, state_store, summary]` пинит и «дети раньше воркеров», а не только место `summary`. XPASS xfail-теста ожидаем: в старом порядке воркеры закрывались первыми |
| I2 | крюк после `plugins-stop` | только PM 4 | только PM 4 | нет |
| I3 | `summary` в `_own_work_late` | PM 7, hazards-тест | PM 7, hazards-тест | нет |
| I4a | убрать `should_reject=_pm_stopping` | НЕ инъекция; PM 3, 8 зелёные | 40 passed — PM 3 зелёный | нет. Чтение: `keyed_executor.py` `request_stop` ставит `_closed`; `submit` при `_closed` отвечает `SYSTEM_STOPPING`; `_ChildrenStop.request_stop` (фаза 1) СНАЧАЛА гасит исполнитель (`_stop_lifecycle_executor`) — в фазе детей отказ даёт закрытый исполнитель |
| I4b | `_spawn_refused_after_system_stop` → `False` | PM 8 | PM 8 | нет |
| I5 | `children` с `budget_s=pm_total_s` | PM 5 | PM 5 + `test_pm_root_budget_is_pm_total_plus_infra` | лишний красный в авторском наборе: он пинит срок области `children` — ожидаемо |
| I6 | снять страж `_group is not None` в `_ChildrenStop._start` | PM 6 | `test_monitor_paused_before_first_stop_event_with_infra_deadline`; **PM 6 зелёный** | находка: второй `system.shutdown` только взводит события (`_cmd_system_shutdown`), повторного `request_stop` группы на этом пути нет. Защиту даёт структура, а не этот страж. Доп. I6b (страж снят + второй `system.shutdown` явно зовёт `_children_stop.request_stop()`) → PM 6 красный, плюс тот же hazards-тест: у PM 6 есть зубы |

## Гипотеза `process.relay` (класс T) — не подтверждена чтением

`_cmd_process_relay` → `send_message` → `send_to_process` → `router.send` (синхронно) → `_deliver_by_targets` → `qr.send_to_queue(process, qtype, ticket)` без `timeout` (`router_module/core/router_manager.py:792,794`) → `timeout: float = 0.0` → `queue.put_nowait(message)` (`shared_resources_module/queues/core/manager.py:274,305-308`). Блокирующего `put` на этом пути нет. Чтение, не замер: блокировку внутри `mp.Queue.put_nowait` (внутренний lock, feeder-поток) при мёртвом читателе не проверял.

## Бюджет хвоста (ESCALATION → решение лида: не менять)

Проба (scratchpad, не в ветке), G = 1,0, ребёнок игнорирует сигнал и `terminate`, `kill()` в ≈ 2,02 с, ребёнок умирает через N с после `kill()`: N = 0,5 и 0,9 → `()`; N = 0,98 → `('proc/ProcessManager/work/workers',)`; N = 1,5 → `children/processes` + `workers`. Ребёнок, умирающий на `terminate` (тест 5), оставляет хвосту время: G = 1,0 → корень закрыт за 1,137 с, G = 5,0 → 5,057 с, survivors `()`. Механизм тестера (тест 5 краснеет, когда хвост без времени) повторён инъекцией I5: PM 5 красный.

## Текст для `docs/claude/OPEN_QUESTIONS.md` (вписывает лид)

```
## 2026-11-06 — хвост `work` PM без своей доли бюджета после Task 1.1a (ADR-PMM-040)

- **Вход:** корень PM, G = `pm_graceful_s` = 1,0. Ребёнок игнорирует сигнал стопа и `terminate()`; `kill()` уходит в ≈ 2,02 с; ребёнок умирает через N с после `kill()`.
- **Выход (проба teamlead 1.1a, Darwin):** N = 0,5 и 0,9 → `survivors=()`; N = 0,98 → `('proc/ProcessManager/work/workers',)`; N = 1,5 (не умер за окно) → `('proc/ProcessManager/work/children/processes', 'proc/ProcessManager/work/workers')`.
- **Причина:** область `children` (`process_manager_process.py`, `_own_work_late`: `work.child("children", budget_s=pm_graceful_s, kill_reserve_s=KILL_RESERVE_S)`) вправе занять весь сегмент `work` = `pm_total_s = G + TERMINATE_GRACE_S + KILL_CONFIRM_S` (`_root_budget`, ADR-PMM-036 О6). После переноса детей раньше `workers` хвосту (`_WorkersStop.join_until`, `process_module/lifecycle/process_lifecycle.py`) остаётся ≈ 0 с; `stop_all_workers(timeout=0)` не успевает остановить `message_processor`.
- **Страж:** `process_manager_module/tests/test_process_root_pm_hazards.py::test_workers_not_survivor_when_child_outlives_kill_window` (`xfail(strict=True)`).
- **Направление:** доля хвоста в бюджете `work` PM (`_root_budget` + константа в `core/stop_budget.py`) при согласовании с `PM_TEARDOWN_MARGIN_S` = 1,5 (при G ≥ 5 корень уже берёт +1,0 из него) и литералами `modules/tests/test_manager_shutdown_1_2b_2_acceptance.py:405,482` (3.2 / 8.0), `test_process_root_pm_hazards.py::test_pm_root_budget_is_pm_total_plus_infra`. Либо срок `children` = `work_deadline - tail`, без смены окон ADR-PMM-031. Владелец — полоса Ф.
```

## Файлы (staged, без коммита)

- `multiprocess_framework/modules/process_module/core/process_module.py`
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py`
- `multiprocess_framework/modules/process_manager_module/tests/test_process_root_pm_hazards.py`
- `multiprocess_framework/modules/process_manager_module/DECISIONS.md`
- `multiprocess_framework/DECISIONS.md` (вывод `scripts.sync`)
- Черновик коммита (не staged): `docs/reviews/2026-11-06_gui-graceful-close_task-1.1a-teamlead.commitmsg.txt`

## What I interpreted rather than followed

- xfail-тест закрепляет случай N = 1,5 (ребёнок не умирает за окно kill), а не N ≈ 0,98, как просил лид. Окно N ≈ 0,98 узкое, около 0,05–0,1 с между 0,9 (зелёный) и 0,98 (красный), и зависит от тайминга — это флак. При N = 1,5 дети детерминированно занимают весь `work`. Тест проверяет то же ограничение: «`workers` в выживших». Фикстура `pm_rig` — локальная обёртка над `_blind.Rig` (слепой файл не правился). Импорт фикстуры напрямую давал ruff F811.
- I6 как в таблице не нашёл стража на пути второго `system.shutdown`. Поставил I6b, чтобы проверить зубы PM 6.
- В ADR-PMM-036 добавил одну ссылку «заменён ADR-PMM-040» (тот же файл из FILES).
- Тип коммита — `feat(pm)`: меняется наблюдаемое поведение. Лид может сменить на `fix`.

## What I left open / unreliable

- Windows-харнесс и стенд (heavy) не запускались: ≥ 1 ответ `drv.supervision_status()` во время `system.shutdown`, 10/10 ≤ 2,07 с, граф с зависшим ребёнком — не проверены.
- Латентности (≤ 0,014 с) замерены на Darwin на фейковых детях. Под нагрузкой Windows число не проверено.
- Гипотеза `process.relay` закрыта только чтением.
- Поиск в памяти выполнен ПОСЛЕ первой правки (нарушение порядка §8).
- G4 lifecycle-guards: в отчёте pytest есть потоки без scope path (`QueueFeederThread`, `Thread-5/6/7`) от слепого набора. С baseline не сравнивал: G3 = 0, G4 — та же картина, что описал тестер.
- Docs-проход (README `process_module`, докстринг `orchestrator.py`, `process_module/DECISIONS.md` о контракте `_own_work_late`) не делал: он за tech-writer.

memory hits: `search.py PM children stop close order --module process_manager_module` -> project_graceful_stop_debt.md, feedback_order_has_two_implementations.md, feedback_unblocking_signal_at_the_moment_of_fact.md, project_industrial_standards_packml.md, project_switch_routing_stale.md — по сути задачи не применимы.
