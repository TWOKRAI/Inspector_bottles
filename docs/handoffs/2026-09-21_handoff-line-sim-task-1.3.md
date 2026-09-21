# Хендоф: line-sim Task 1.3 — стенд двух приложений (2026-09-21)

Дерево `.claude/worktrees/line-sim`, ветка `feat/line-sim`. `main` не тронут. qex в сессии был
недоступен (ollama down) — всё грепом и прогонами.

## Где остановились

- Хвосты 1.2 закрыты и закоммичены (`2b463ceb`): пара кадра одним полем, 3 сторожа
  `OPENCV_FFMPEG_CAPTURE_OPTIONS`, conftest-откат env. Ревью APPROVED (2 итерации).
- Коммит с этим хендофом: сим-рецепт `robot_main` → `127.0.0.1:5021` (был боевой
  `192.168.1.7:502`; upsert рецепта перезаписывает `data/devices.yaml`, живьём подтверждено
  `device_list` → `origin: recipe:letter_robot_sim`), тест + README; критерий живого стенда 1.2
  переоткрыт в плане; две записи в `OPEN_QUESTIONS.md` (SHM, TIME_WAIT).
- **Стенд остановлен, порты 8765/8766/5021/8091 свободны.**

## Шаги стенда — что уже снято (первый стенд, БЕЗ флага SHM — перемерить с флагом)

| Шаг | Итог | Числа |
|---|---|---|
| 1. наблюдаемость сима | зелёный | 4 ручки непусты; сумма дельт `sim_robot.writes` в `history_query` = 260 = `writes_seen` на момент снимка |
| 2. прототип → сим | зелёный | `robot_get_telemetry` живой (heartbeat, encoder); `robot_send_test_job{x:10,y:20}` → `queue_len 1`, `robot_read_echo` → `job_x 10.0, job_y 20.0`; записей за 5 с 14 против фоновых 10 |
| 3. отказ робота | НЕ снимался | `observability-closure` Task 4.4 не закрыта — спека велит пропустить и сказать |
| 4. fps `camera_0` | недействителен | 16.3 Гц — маска дефекта SHM (ниже) |

## Главная находка — дефект фреймворка, не сима

Без `FW_SHM_OWNER_INCARNATION=1` на POSIX все `GenericProcess` создают `/output_frames_0..2` и
угоняют имена друг у друга. Прототип ломает сам себя (4 писателя), сим — пятый. Замеры CTO
(`scratchpad/cto/`, протоколы трёх прогонов): OFF/OFF — дверь 8091 отдаёт (1,1,3) нули при hz
24.5; ON/ON — (480,640,3), 0 SHM-ошибок, camera_0 ≈ vision ≈ 24.5; сим ON / прототип OFF —
прототип теряет ровно треть при `router.errors=0`. Подробно — `OPEN_QUESTIONS.md`.

**Вердикт CTO:** флаг в обоих приложениях — легитимная конфигурация стенда (штатное средство,
не обход), при трёх условиях: флаг виден (README сима, шапка `letter_robot_sim.yaml`, отчёт),
заведена framework-задача, шаг 4 перемерен ведущим с проверкой кадра. Задать флаг из рецепта
нельзя — только env при запуске.

## Что сделать в новом чате (порядок)

1. **Стенд с флагом.** Оба запуска с `FW_SHM_OWNER_INCARNATION=1`:
   - сим: `FW_SHM_OWNER_INCARNATION=1 BACKEND_CTL=1 BACKEND_CTL_PORT=8766 MULTIPROCESS_LOG_DIR=<tmp> PYTHONPATH=$PWD .venv/bin/python apps/line_sim/run.py`
   - прототип: `FW_SHM_OWNER_INCARNATION=1 BACKEND_CTL=1 BACKEND_CTL_PORT=8765 MULTIPROCESS_LOG_DIR=<tmp> INSPECTOR_LOG_DIR=<tmp> PYTHONPATH=$PWD .venv/bin/python multiprocess_prototype/run.py letter_robot_sim --headless`
   - сим — ПЕРВЫМ и не раньше ~30 с после прошлого останова (TIME_WAIT на 5021, см. п. 5).
   - MCP `backend-ctl` смотрит на 8765; сим вести скриптом `BackendDriver(port=8766)`.
2. **Перемер шагов 1, 2, 4** с новым критерием кадра: на двери 40 кадров → `(480,640,3)`, `uint8`,
   mean_px > 0, соседние кадры различаются (движение CTO НЕ проверял); 0 строк
   `SHM fallback failed|frame не восстановлен` за 30 с в логах обоих; `line`/`maskview` hz ≈
   `camera_0`, `draw`/`recog` ≈ 2×; `lsof -p <pids> | grep PSXSHM` — ни одно имя у двух владельцев.
   Тем же критерием переснять Task 1.2 (критерий переоткрыт в плане).
3. **RSS на длинном прогоне** — на исправном стенде, ≥20 мин, раз в 30 с по дереву потомков двух
   корневых pid (не `pgrep multiprocessing` — цепляет чужое). Первый прогон (5 мин, сломанный стенд)
   для приёмки не годится.
4. **Строка про флаг** в `apps/line_sim/README.md` и шапке `letter_robot_sim.yaml`: «на POSIX без
   `FW_SHM_OWNER_INCARNATION=1` прототип теряет треть кадров и читает чужие сегменты; hz этого не
   показывает; дефект фреймворка, задача <slug>».
5. **Дефект TIME_WAIT** сим-робота (`Plugins/sim/robot_host/plugin.py:154-158`, `SO_REUSEADDR`) —
   отдельной маленькой задачей: tester до кода → фикс → инъекция. Без него шаг 3 после closure 4.4
   даст ложный красный.
6. **Отчёт** `docs/reviews/2026-09-21_line-sim-f1-stand.md`: input → observed по каждому шагу, шаг 3
   пропущен с причиной, находка SHM с числами CTO и своими.
7. **Ревью** `reviewer` синхронно (`run_in_background: false`), затем коммит, статус Task 1.3 в
   `plan.md` и `phase-1-vertical-slice.md`.
8. **Framework-задача** (флип дефолта флага + громкий ERROR при старте без флага на POSIX + уборка
   по префиксу для хеш-имён + счётчик отказов restore в `system_overview`) — отдельный план через
   `/dev:plan`, после ответа владельца на вопросы в `OPEN_QUESTIONS.md`. CTO: `cleanup_stale_shm`
   в `create_shm_block` НЕ трогать (на нём держится уборка после kill -9).

## Ловушки, на которые уже наступили

- `run.py <рецепт>` **переписывает `multiprocess_prototype/app.yaml`** (строка `pipeline:` и
  форматирование `base:`). После стенда в дереве остаётся изменённый `app.yaml` — не коммитить.
  На момент хендофа он изменён и в коммит не включён (откат `git checkout` в сессии не разрешили).
- `pytest … | tail` возвращает статус `tail` — exit code проверять через `${pipestatus[1]}`.
- В брифе CTO я передал со слов investigator «dualcam_* задают флаг» — неверно, флаг у них только
  в комментарии. Факты из отчётов субагентов перепроверять до передачи дальше.

## Открытые вопросы владельцу

См. `OPEN_QUESTIONS.md`, запись про SHM: (1) флип дефолта одного флага до soak отдельным планом?
(2) framework-задача блокирует Ф2 или параллельно?
