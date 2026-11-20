# Запрос на слияние: ветка feat/camera-4c (полоса К, Task 4c)

- Ветка: `feat/camera-4c` (worktree `Inspector_bottles--lane-K-4c`), основа `main` `ad3dc7b72`.
- HEAD кода и доков (последний коммит до этого файла): `aea78c313a0c21531140a1d0fd7b1da6f7f7b08c`. Итоговый HEAD ветки с этим файлом: `git rev-parse feat/camera-4c` (один коммит сверху).
- Содержит: текст задачи 4c (`plans/2026-10-18_camera-device-service/tasks/4c.md`), слепые тесты, ключ `run_locked_commands` в `camera_device_demo.yaml`, Б1 (`registers_module/core/manager.py:222`), Б2 (`Services/camera_device/plugin_base.py`), доки камеры (readiness, ADR-CAM-005), документ сухого прогона дня №1, отчёт `docs/reports/2026-11-20_camera-device-service_4c.md`.
- Ревью: Opus по ветке — APPROVED WITH CONDITIONS, условия закрыты в ветке; блокеров нет.
- Тесты на ветке: `Services/camera_device/tests` 462 passed / 10 skipped; `registers_module/tests` 113 passed; `multiprocess_prototype/recipes/tests` 214 passed / 5 skipped; `sentrux check .` 43 правила проходят. После слияния на `main` прогнать эти три каталога повторно: `main` ушёл вперёд, на новой основе не гонялось.
- Конфликты: возможны в `docs/claude/OPEN_QUESTIONS.md` (вставка после записи 2026-11-19 «Два остатка…»), `Services/camera_device/STATUS.md`; проверить `git merge-tree`.
- Слияние делает координатор: в `main` я не коммитил. Тема merge-коммита — `feat(...): merge ...` + `Why:`/`Layer:`/`Refs:` (хук режет `merge(...)`); сообщение — из файла.
- В моём дереве остаются ДВЕ чужие незастейдженные правки Д2 (`frontend_module/.../telemetry_chart.py`, `.../tests/test_telemetry_chart.py`): в ветку не попали (`git diff ad3dc7b72..feat/camera-4c --stat` их не содержит).
