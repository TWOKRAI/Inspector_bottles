# gui-graceful-close · Task 1.1a · ревью стадии 5 (reviewer, sonnet)

Вердикт: **APPROVED**. Ветка `feat/gui-close-1.1a`, HEAD на момент ревью `737904400`. Сжатая запись отчёта; полный текст — в переписке сессии (agentId `ae38001100c9107c5`).

## Воспроизведено

- Радиус (каталог `process_manager_module/tests` + `test_process_root_acceptance.py`): `6 failed, 1551 passed, 1 skipped, 1 xfailed`. Красные — только `test_cv_threads.py`; те же 6 тестов красные на чистом `315fdbf51` (`6 failed, 9 passed`). Golden порядка обычного процесса зелёный.
- Инъекции в копиях `git archive` (дерево не тронуто):

| № | Патч | Красные |
|---|---|---|
| I1 | `children` обратно в `_own_work` | PM1, PM2, PM3, PM6, PM7, hazards-тест порядка, xfail (XPASS strict); PM4/5/8 и golden зелёные |
| I2 | `_own_work_late` после `plugins-stop` | только PM4 |
| I3 | `summary` в `_own_work_late` | PM7 и hazards-тест |

  Расхождение с предсказанием одно: PM7 красный в I1 (его литерал держит и «дети раньше воркеров»). Не дефект.
- xfail-тест с `--runxfail` падает на целевом assert (`work/workers` в выживших), предусловие проходит.
- Бюджет (18 прогонов, живой PM, настоящая группа детей): ребёнок, умирающий на kill через N с. N ≤ 0,9 — выживших нет; N ≈ 0,95 — иногда `work/workers` (окно ~0,05–0,1 с, от G не зависит, зависит от тайминга); N ≥ 1,0 — выживает ребёнок, это было и до 1.1a. Во всех 18: `errors == []`, `shutdown() is True`, `summary` и `state_store.shutdown` по одному разу.
- `git grep "def _own_work_late"`: только `process_module.py:428` и `process_manager_process.py:3808` — утверждение ADR-PM-059 верно.
- Слои: новых импортов вверх нет. Код вне FILES не менялся.

## Замечания (минорные)

1. xfail без `raises=` — **исправлено** (`raises=AssertionError`), hazards-файл: `20 passed, 1 xfailed`.
2. hazards-файл импортирует `Rig` из слепого файла — вынос в общий `tests/_pm_rig.py` отдельной задачей.
3. PM6: assert `request_stop_calls == 1` вакуумен (на пути второго `system.shutdown` вызов невозможен), содержательные assert'ы работают. Слепой файл не правится автором; I6b зафиксирован в `tasks/1.1a.md`.

## Не проверено

- Heavy на Windows (harness 10/10, `supervision_status` во время стопа, граф с зависшим ребёнком) — за лидом.
- Код выхода PM при `workers` в survivors (`_hard_exit(76)` только через `run_process_function`) — гипотеза.
- Блокировка `_lock` при `force` в фазе 1 (≤ `infra_s` ≈ 1,0 с) — гипотеза, не воспроизведена.
- `process.relay` в умирающего ребёнка — только чтением, без замера `mp.Queue`.
- Инъекции I4b, I5, I6 не повторены; опора на отчёт teamlead.
