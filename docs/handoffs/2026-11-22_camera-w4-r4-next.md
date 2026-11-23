# Handoff: полоса К, W4 готов к слиянию, дальше R4 (2026-11-22)

Для следующей сессии полосы К. Прочитать сначала: `docs/handoffs/2026-11-22_camera-W4-merge-request.md`, `docs/reports/2026-11-22_camera-device-service_W4.md`, `docs/handoffs/2026-11-20_camera-w4-r4-owner-questions.md` (ответы владельца по R4), `docs/handoffs/2026-11-22_R2-merge-request.md` и `2026-11-20_R2-recipe-diff-reconnect.md`.

## Состояние
- Ветка `feat/camera-w4`, дерево `Inspector_bottles--lane-K-w4`: К4' = `a4e1b325d` поверх `main` `d221d9a9c`, плюс docs-коммит заявки/отчёта/handoff. Opus-ревью: APPROVED (раунд 2).
- **Слияние не выполнено и не запрошено словом координатора** (`inspector-bottles-30`): заявка файлом, merge делает лид по слову координатора. День №1 закреплён на `../Inspector_bottles--day1` (`d221d9a9c`); старый путь на `main` до слияния не ломать.
- Заявка не покрывает живой стенд (железа нет); координатору задан вопрос, нужен ли стенд на `driver: fake` до слияния.

## Следующий шаг: R4 (только после слияния К4' в main), три коммита в порядке
1. β `hikvision_letter_robot.yaml`: `max_reconnect_attempts: 0` у `robot_main` и `vfd_belt` (дифф Р2) + снять две записи `.devices[0|1].params.max_reconnect_attempts` и комментарий в `_EXPECTED_DIFFS` (`test_letter_robot_sim_diff.py`); ключ `readiness` в узле камеры (2.2c: камера в `stopping` при `auto_start`); golden β пересобрать (`UPDATE_BUILD_SNAPSHOTS=1 ... test_build_characterization.py`), дифф просмотреть.
2. `use_linear: false` + `first_y: -440.0` (как в `letter_robot_sim.yaml:316`; сверить `last_y` и ячейки слова); в рецепте строка-комментарий: без F7 (`config/calibration/cam0.yaml`, гомография) β при `false` даёт отказ или нули — ожидаемо; то же в коммите и отчёте.
3. Драйвер `delta_universal3` → `delta_v2` на `192.168.1.7:502` — ПОСЛЕДНИМ и отдельным коммитом (откат одним коммитом); v2 на роботе не проверен (T0.3/T4.0 на визите).
Границы: не трогать `pult` (Пульт), `Plugins/hub/device_hub` (Р2), PM/spawner/state_store (Ф); слово β влито Пультом (`40bcd743d`).

## Уроки сессии
- `protect-branch` читает ветку основного дерева: коммит из worktree — только как `cd <worktree> && git commit -F <файл>` (команда не должна начинаться с `git commit`), сообщение — файлом (`Write`), не heredoc.
- На macOS `sed -i` требует аргумент суффикса — править файлы `Edit`-ом.
- Список ожидаемых расхождений `_EXPECTED_DIFFS` сравнивается как отсортированный список строк: запись ставить в строковом порядке.
- Голое `Off`/`On` в YAML 1.1 = bool: значения enum-полей рецепта — в кавычках.
- `lint-brief` отклоняет бриф без `DESIGN` ≥ 3 строк, `FILES`, `REPORT`; слепому tester, раннеру тестов и подобным — строка `BRIEF-OVERRIDE: <причина>`.
- Агент, ожидающий разрешения на Bash, стоит, пока владелец не ответит в интерфейсе; сообщение ему не помогает.

## agentId (для re-summon; Opus-ревьюер раунда 1–2 — `a1319dc72a49e87f0`, developer 4.3 — `adca9a9f9b3279eec`, 4.4 — `ad3550b794c9e2ec9`)
Полная таблица — в отчёте W4.
