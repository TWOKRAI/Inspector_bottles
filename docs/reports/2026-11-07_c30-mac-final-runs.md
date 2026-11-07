# C-30 · финальные прогоны на Mac · 2026-11-07

Сессия inspector-bottles-c7. Ветка `fix/recipe-save-noise`, HEAD на момент прогонов `f5fa8c237` (merge main `cca8fe148`); чистый main — worktree `lane-d-c30-main` на `cca8fe148`. Интерпретатор `/Users/twokrai/Project_code/Inspector_bottles/.venv/bin/python` 3.12.13, PySide6 6.10.3, `QT_QPA_PLATFORM=offscreen`. Прогоны — через `machine_gate.sh heavy` (machine.lock на Mac нет → `stand.lock`; окон `request` не выдаётся: «no machine.lock»), последовательно, один за другим. Скрипты и логи: scratchpad сессии `…/scratchpad/suites/`.

## Время и счёт (время — по строке итога pytest, не по обёртке)

| Прогон | Время | failed | passed | skipped | errors |
|---|---|---|---|---|---|
| framework, ветка | 22 мин 24 с | 92 | 12631 | 48 | 1 |
| framework, чистый main | 21 мин 47 с | 90 | 12527 | 48 | 4 |
| корневой, ветка | 43 мин 14 с | 567 | 17299 | 179 | 7 |
| корневой, чистый main | 45 мин 06 с | 567 | 17282 | 179 | 7 |

Оценки 57/26 мин были Windows; на Mac корневой — около 45 мин, framework — около 22 мин. Обёртка показала 7787 с для корневого main (против 2706 по pytest): лишнее — простой вне pytest (сон машины или ожидание), для времени Mac брать pytest-цифры.

## Разница красных ветка ↔ main (сравнение списков `FAILED`/`ERROR`)

- **Корневой suite: множества красных идентичны** (574 строки в обоих, общих 574). Ветка не добавила и не убрала ни одного красного. Ветка проходит на 17 тестов больше (новые тесты 1.4, 1.5, 1.16 и тест порядка).
- **framework:** 145 общих из 147/148. Расходятся три имени: `process_module/tests/test_pacing_hazards.py::test_idle_cycle_duration_measured_with_fine_clock` (красный на ветке в полном прогоне) и ошибки `test_t45b_process_fields.py::TestIntrospectQueuesCapacity` (в полном прогоне на main). Перепрогон по отдельности: `fine_clock` на ветке 1 passed / 1 failed / 1 passed, на main 1 failed / 1 failed / 1 passed — **плавающий тест**, зависит от тайминга Mac (не наш: `process_module` ветка не меняла). `t45b` падают одинаково на обоих деревьях.

## Что в красных (среда Mac, не C-30)

Группы красных корневого suite (ветка = main): `Services/layer_render` 227, `scripts/machine_gate_tests` 118, `scripts/atlas` 79, `Plugins/io` 46, `Services/otel_export` 39, `Services/dataset_gen` 26, `scripts/lifecycle_guards` 8, `Services/code_reader` 7, `Plugins/sim` 5, `Services/robot_comm` 4. Ошибки сбора: `recipe/tests/test_yaml_patch.py` (нет `hypothesis`), `multiprocess_prototype/adapters/tests/test_recipe_canonical.py`, `Services/otel_export/tests/test_f2_task24_*`, `Services/robot_comm/tests/test_*_acceptance.py`, `examples/minimal_app/tests/test_ci_smoke.py`. В логе framework есть `OSError(28, 'No space left on device')` при `create_queues()` (shared memory/семафоры macOS) — причина части красных `process_module`. **OSError(28) — не диск** (на Mac свободно 294 ГиБ; значения от координатора). Гипотеза, НЕ воспроизведена: лимиты SysV-разделяемой памяти macOS — `kern.sysv.shmmax=4194304`, `kern.sysv.shmall=1024` (≈ 4 МиБ на всю систему), а фреймворк берёт SHM для очередей; это объяснило бы массу красных `process_module`/`shared_resources` и часть 567 на чистом main. Системные настройки не менялись (`sysctl -w` требует sudo — решение владельца, агентам нельзя). Скипы: Windows-only (лок `msvcrt`, SharedMemory «unreliable on macOS» и др.) считать скипами, не зелёными. Сверка с `plans/queue/defects.md` не делалась: файл писали на Windows, критерий — чистый main на этом же Mac (идентичен).

## Живая проба `run.py` на Mac (light, 75 с, чистый main, offscreen)

Запускается: 6 процессов поднялись (ProcessManager, gui, devices, reader_1/2, draw_1/2), manifest/pipeline `qr_reader_sdk_dual_demo`, plugins 65. Но: GUI-процесс стартует **headless** («presentation: overlay не задан … HeadlessGuiProcess») — окна нет; `MvCodeReader SDK есть только под Windows` (ошибки плагина code_reader). Для M1/M2 нужен настоящий GUI с редактором и кликами Save — это требует оверлея `INSPECTOR_PRESENTATION` и автоматизации GUI (qt-mcp не подключился: CONNECTION_CLOSED), либо участия владельца с реальным экраном. Не запускалось: M1, M2, M3, M5, сценарии 1.15/1.16 вживую. **M3 и M5 — «ожидает камеры/стенда»**, зелёными не считаются; синтетикой не закрывались.

## Итог для merge

Код и документы ветки готовы: инъекции и ревью стадии 5 по каждой задаче, Opus-ревью ветки APPROVED (`docs/reviews/2026-11-07_c30-final-branch-review.md`, 2 minor закрыты `aaf5ec1b2`), красные = красные чистого main. Не закрыто: M1–M3 живьём, `backend_ctl` live-тест хаба, `test_yaml_patch.py`. Merge в main и push — по слову владельца.
