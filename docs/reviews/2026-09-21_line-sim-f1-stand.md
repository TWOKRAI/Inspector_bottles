# Стенд line-sim Ф1 — Task 1.3: два приложения одновременно (2026-09-21)

Ветка `feat/line-sim`, дерево `.claude/worktrees/line-sim`, база `6e21843d`. macOS (darwin),
Python 3.12. Стенд вёл lead; скрипты замеров — в scratchpad сессии, команды и выводы ниже.

## Конфигурация

| | Команда (обе — с `FW_SHM_OWNER_INCARNATION=1`) | Корневой pid |
|---|---|---|
| сим | `FW_SHM_OWNER_INCARNATION=1 BACKEND_CTL=1 BACKEND_CTL_PORT=8766 MULTIPROCESS_LOG_DIR=<tmp> PYTHONPATH=$PWD .venv/bin/python apps/line_sim/run.py` | 90915 (3 процесса + PM) |
| прототип | `FW_SHM_OWNER_INCARNATION=1 BACKEND_CTL=1 BACKEND_CTL_PORT=8765 MULTIPROCESS_LOG_DIR=<tmp> INSPECTOR_LOG_DIR=<tmp> PYTHONPATH=$PWD .venv/bin/python multiprocess_prototype/run.py letter_robot_sim --headless` | 91118 (10 процессов + PM) |

Сим запущен первым, прототип после появления 8766/5021/8091.

**⚠ Флаг `FW_SHM_OWNER_INCARNATION=1` — условие стенда, а не обход** (вердикт CTO на A/B-прогонах
первого стенда, три условия выполнены: флаг назван в `apps/line_sim/README.md` и шапке
`letter_robot_sim.yaml`, задача записана в `docs/claude/OPEN_QUESTIONS.md`, шаг 4 перемерен ниже
с проверкой кадра). Без флага на POSIX все владельцы кадровых колец создают сегменты с голыми
именами `/output_frames_0..2` и перехватывают их друг у друга. Замеры CTO на первом стенде:
OFF/OFF — дверь 8091 отдаёт кадры формы `(1,1,3)`, mean_px 0.0 при hz 24.5 и `router.errors=0`;
ON/ON — `(480,640,3)`, 0 SHM-ошибок; сим ON / прототип OFF — прототип теряет ровно треть кадров
при `router.errors=0`. **`hz` этот дефект не показывает** — поэтому критерий кадра ниже снимается
по содержимому, а не по частоте.

## Шаг 1 — наблюдаемость сима (порт 8766) — ЗЕЛЁНЫЙ

| Ввод | Наблюдение |
|---|---|
| `system_overview` | 4 процесса (`ProcessManager`, `camera`, `mjpeg`, `robot`), все `running`, `router.errors=0`, `middleware_dropped=0`; hz `camera` 24.32, `mjpeg` 24.33 |
| `send_command(robot, introspect.observability)` | непусто: ключи `audit, counters, documents, effective, events, flight, history, layers, observation, process, provenance, stats`; `logger.messages_processed=410`, `errors_to_floor=0` |
| `history_query(kind="stats", process="robot")`, имя в `extra.metrics[].name` | строки с `sim_robot.writes` есть (тип `counter`, поле `count`); **сумма дельт = 1570 = `writes_seen` на момент предыдущего `sim_robot.status`**, текущее `writes_seen` 1615 |
| `observability_tail("robot")` + `events_page` | подписка `min_level=ERROR`, 2 тапа (`error`, `logger_error`); в событиях — `observability.record` от `robot` (снимок метрик, 6 имён) |

Инвариант спеки «записей в истории больше, чем `writes_seen`, не бывает» держится, причём с
равенством на момент синхронизации. Отставание истории от `writes_seen` — свойство плагина, а не
потеря: метрика переносится в plane stats дельтой только из `cmd_status` и `shutdown` (поток
`pymodbus` `record_metric` не зовёт — докстринг `Plugins/sim/robot_host/plugin.py`). Между
вызовами `status` история стоит.

## Шаг 2 — прототип → сим — ЗЕЛЁНЫЙ

| Ввод (порт 8765, процесс `devices`) | Наблюдение |
|---|---|
| `device_list` | `robot_main`: `tcp 127.0.0.1:5021 unit_id 2`, `origin: recipe:letter_robot_sim`; `vfd_belt`: мост через `robot_main` |
| `robot_get_telemetry{device_id: robot_main}` ×3 с паузой 3 с | `status ok`, heartbeat 20280 → 24910 → 25251 (растёт), `servo true`, `miss_count 0`, `encoder 141960` |
| `vfd_get_status{device_id: vfd_belt}` | `bridge_alive true`, `comm_errors 0`, `dcbus_v 540.0` |
| `health.status` | `status ok`, `errors 0`, `breaker closed` |
| `robot_send_test_job{x:10, y:20}` | `{status: ok, queue_len: 1}`; фон `writes_seen` сима — 10 записей за 5.02 с, за 5 с после задания — 13 |
| `robot_read_echo` | `job_x 10.0, job_y 20.0, px 10.0, py 20.0` — задание дошло до сим-робота |

Отдельной команды «online» у `devices` нет (`introspect_handlers`: `device_connect`,
`device_disconnect`, `health.*`, `introspect.status`, `vfd_get_status`); «online» подтверждён
живой телеметрией (растущий heartbeat) и `bridge_alive`.

## Шаг 3 — отказ робота — ПРОПУЩЕН

По спеке сценарий идёт после closure `observability-closure` Task 4.4, а она не закрыта. Снят не
был. Попутно устранён дефект, который дал бы здесь ложный красный: сим-робот не поднимался на
5021 около 30 с после останова (TIME_WAIT) — см. раздел «Дефект TIME_WAIT» ниже.

## Шаг 4 — цена: кадр и частоты прототипа — ЗЕЛЁНЫЙ (перемер с флагом)

| Ввод | Наблюдение |
|---|---|
| 40 кадров двери `http://127.0.0.1:8091/` (`cv2.VideoCapture`, FFMPEG) | ok 40/40, формы `{(480,640,3): 40}`, dtype `uint8`, mean_px 3.3 (чёрный фон + красный квадрат + часы), **соседние кадры различаются 39/39**, mean_abs_diff 0.53, min 0.36; последний кадр осмотрен глазами — таймштамп `12:13:46.488` |
| `system_overview` прототипа, 4 снимка через 10 с | `camera_0` 24.46–24.60; `vision` 24.25–24.89; `line` 24.46–24.69; `maskview` 24.41–24.70; `draw` 49.85–50.23; `recog` 49.27–50.81; `router.errors=0` и `middleware_dropped=0` у всех |
| `grep -E 'SHM fallback failed\|frame не восстановлен'` по логам и stdout обоих за те же 38 с | 0 → 0 строк |
| `lsof -p <все pid обоих деревьев>`, тип `PSXSHM` | общих имён между деревьями **нет**; голых `/output_frames_N` **нет**; каждый `output_fra_<hash>` держит ровно один pid; кольца `camera_0_f_<hash>` мапят читатели своего дерева (11 pid в прототипе, 4 в симе) |

fps `camera_0` = **24.5** при ориентире ≥ 20. `line`/`maskview` ≈ `camera_0`, `draw`/`recog` ≈ 2×,
как и должно быть при исправных кольцах. Задержка кадра не мерялась (Ф5).

Тот же критерий кадра закрывает переоткрытый критерий живого стенда Task 1.2.

## RSS на длинном прогоне

Исправный стенд (оба с флагом), 50 замеров раз в 30 с за **24.9 мин**, RSS по дереву потомков
двух корневых pid (`pgrep -P` рекурсивно, не `pgrep multiprocessing`).

| Дерево | Старт, МБ | Конец, МБ | Максимум, МБ | Δ второй половины, МБ |
|---|---|---|---|---|
| сим (4 pid) | 491 | 365 | 491 | −126.4 |
| прототип (13 pid) | 1967 | 1739 | 1975 | −235.5 |

Ни один pid не вырос (наибольшие «приросты» отрицательные: −2.3…−11.8 МБ). Падение RSS —
вероятно, компрессор памяти macOS (процессы в состоянии `SN`), это не освобождение памяти
приложением. Значит, замер отвечает только «монотонного роста нет», а не «утечки нет» — для
второго нужен `footprint`/`vmmap` или прогон на Linux. `SHM fallback failed|frame не
восстановлен` за весь прогон — 0 строк в логах обоих приложений.

Первый 5-минутный прогон на сломанном стенде (без флага) в приёмку не идёт.

## Дефект TIME_WAIT сим-робота — найден на первом стенде, исправлен здесь

**Симптом (CTO, первый стенд):** рестарт сима через 27 с после останова →
`sim_robot_host.start: [Errno 48] Address already in use`, порт никто не слушает, прототип получает
`Connection refused`.

**Причина:** пробный сокет `_probe_port_free` (`Plugins/sim/robot_host/plugin.py`) биндил порт без
`SO_REUSEADDR`, а серверная сторона прошлого запуска оставляла TIME_WAIT (macOS: `net.inet.tcp.msl
15000` → ≈ 30 с). Сам сервер pymodbus передаёт `reuse_address=True`
(`pymodbus/transport/transport.py:204`) и TIME_WAIT пережил бы. Фикс — `SO_REUSEADDR` на пробном
сокете **только на POSIX** (`os.name == "posix"`): на Windows эта опция разрешает bind поверх живого
слушателя, и проба перестала бы видеть ещё живой прошлый сим (замечание ревью; на Windows не
воспроизведено). Изначально фикс ставил опцию на всех ОС — ревью итерация 1.

Исполнитель не привлекался (одна строка, без нового механизма — solo-исключение конвенции, названо
здесь). Стадии 1, 3 и 5 выполнены.

**Стадия 1 — независимый tester**, worktree на `6e21843d` (до фикса), бриф — только критерии
приёмки; тесты автора запрещены. Файл `Plugins/sim/robot_host/tests/test_acceptance_time_wait.py`,
4 теста. До фикса: `1 failed, 3 passed` — красный ровно AC1
(`плагин не поднялся за 5с поверх TIME_WAIT, статус: {... 'state': 'error'}`), предусловие
(TIME_WAIT реален: plain bind → errno 48) зелёное. Полный отчёт —
[`2026-09-21_task-1.3-tw-tester.md`](2026-09-21_task-1.3-tw-tester.md).

**После фикса:** `Plugins/sim/robot_host/tests` — `8 passed`.

**Стадия 3 — инъекции** (против обоих наборов: tester + `test_hazards.py` автора Task 1.1),
прогноз записан до прогона:

| Инъекция | Прогноз | Факт |
|---|---|---|
| I1: убрать `setsockopt(SO_REUSEADDR)` | падает только AC1 | ✅ `test_plugin_survives_time_wait_and_reports_running` — 1 failed / 7 passed |
| I2: убрать пробный `bind` | падают тесты занятого порта | ✅ `test_plugin_reports_error_on_genuinely_busy_port` + `test_hazards.py::test_port_busy_reports_error_not_crash` — 2 failed |
| I3: `SO_REUSEPORT` вместо `SO_REUSEADDR` | падают тесты занятого порта (двойной bind) | ❌ 8 passed — **прогноз неверен** |
| I4 (после ревью): `os.name != "posix"` — опция не ставится на macOS | падает только AC1 | ✅ `test_plugin_survives_time_wait_and_reports_running` — 1 failed / 7 passed |

I3 — ошибка моей модели, а не дыра в тестах: на BSD/macOS двойной bind под `SO_REUSEPORT`
разрешён, только если флаг стоит у **обоих** сокетов; у чужого слушателя (и у asyncio-сервера
pymodbus, `reuse_port=None`) его нет, поэтому занятый порт по-прежнему даёт `EADDRINUSE`. В этой
постановке I3 — эквивалентная реализация. Ceiling: если когда-нибудь рядом окажется слушатель с
`SO_REUSEPORT`, проба `SO_REUSEPORT` его бы не заметила — `SO_REUSEADDR` выбран поэтому.

`test_plugin_start_does_not_raise_on_busy_port` под I2 зелёный — ожидаемо: без пробы исключение
всё равно не выходит наружу (поток pymodbus умирает молча), тест стережёт «не бросает», а не
«ловит занятость».

**Живой рестарт после фикса:** SIGINT сима в 12:42:32 → повторный запуск через ~5 с → 5021 в
`LISTEN` в 12:42:40, `sim_robot.status` → `running: true, state: running`, `writes_seen` 19 через
8 с; прототип переподключился сам — `robot_get_telemetry` → `status ok`, heartbeat 1848 (счётчик
нового сима). **Оговорка:** `netstat -an | grep 127.0.0.1.5021` сразу после останова TIME_WAIT
не показал, поэтому этот прогон не доказывает, что порт был в TIME_WAIT. Доказательство фикса —
тест tester с проверенным предусловием (plain bind → errno 48) и инъекция I1.

После останова стенда: `apps/line_sim/tests multiprocess_prototype/recipes/tests Plugins/sim` —
**109 passed, 5 skipped** (при поднятом стенде `test_f1_task11_acceptance.py` падал на `Errno 48`,
потому что сам поднимает сим на 5021/8766).

## Что осталось открытым и что ненадёжно в моей работе

- Шаг 3 не снят (ждёт closure 4.4).
- Кадровые кольца `camera_0_f_<hash>` в прототипе — два префикса, каждый мапят все 11 pid дерева;
  кто из них владелец, `lsof` не говорит. Критерий «ни одно имя у двух владельцев» проверен
  косвенно: имена с хешем инкарнации уникальны, `output_fra_*` — ровно один pid, пересечений между
  деревьями нет. Прямого перечня «создатель сегмента» не снимал.
- mean_px 3.3 — кадр в основном чёрный; «не пустой» подтверждён различием соседних кадров и
  осмотром, а не яркостью.
- RSS на macOS не отличает утечку от сжатия страниц — см. раздел RSS.
- Живой рестарт не подтвердил TIME_WAIT на порту (см. оговорку выше).
- `apps/line_sim/tests/test_f1_task11_acceptance.py` конфликтует с живым стендом по портам — при
  параллельной работе стенда и тестов даёт ложный красный.
- Дефект SHM фреймворка не исправлен — отдельный план после ответа владельца (`OPEN_QUESTIONS.md`).
