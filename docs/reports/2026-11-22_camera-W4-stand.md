# Живой стенд К4' (камера на ядре `camera_device`) — отчёт

Сессия гейта: `inspector-bottles-fd`. Дерево `Inspector_bottles--lane-K-w4`, ветка `feat/camera-w4`, HEAD `c5fa505f9`, `git status --short` до и после — пусто (отчёт не стейджен). macOS, MVS SDK нет.
Интерпретатор: `/Users/twokrai/Project_code/Inspector_bottles/.venv/bin/python`, `PYTHONPATH=$PWD`.
Импорт: `multiprocess_framework.__file__` = `/Users/twokrai/Project_code/Inspector_bottles--lane-K-w4/multiprocess_framework/__init__.py` (внутри worktree).
Окно: `machine.lock` на этой машине нет (`machine_gate.sh status` -> `machine.lock: none`), окно не нужно; команды стенда шли через `machine_gate.sh heavy inspector-bottles-fd <cmd>` (rc 0, проход); `release` -> rc 2 «no machine.lock» (держать нечего). `stand.lock` нет.
Порт backend_ctl: фактически 8765 (`system.yaml`, `lsof` показал LISTEN); 8775 из брифа не использовался. Оба порта свободны до и после.
Логи прогона: `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/7f540482-7c1b-4b52-9214-73fee5553042/scratchpad/stand_w4/` (скрипты `a*.py`, `b*.py`, выводы `A*.log`, `B*.log`, `A_backend.log`, `B_backend.log`, `*_samples.json`).

## Таблица: предсказано / наблюдено / совпало

| # | Предсказано | Наблюдено | Совпало |
|---|---|---|---|
| A1 ready | ≤ 15 с | `state=ready` с `since` на 3,64 с после запуска (`since` из `run_status` минус метка перед `run.py`); моё первое клиентское наблюдение — 11,74 с (драйвер стартовал поздно, не чистый замер) | да |
| A2 run_start | ответ, running | `run_start` 7 мс: `{"success": true, "state": "running"}`; `run_status` сразу `running` | да |
| A3 fps | 25 ± 3 в 3 окнах | `get_status.frames` опрос 50 мс: 25,08 / 25,05 / 24,99 fps (262, 261, 249 кадров за 10,45 / 10,42 / 9,97 с); дерево состояния по точкам смены (шаг 5 с): 25,14 / 24,89 / 24,96; `processes.cam_fake.state.fps` = 24,98, `plugins.camera_device.fps` = 25,0; `device_state` во всех пробах `grabbing`, `dropped` 0, `errors` 0, `last_error` пуст | да |
| A4 команды | 9 + `set_config` + `register_update` = 11 на `introspect.capabilities` | на `introspect.capabilities(cam_fake)` 60 команд всего. Относительно процесса-плагина `devices` у `cam_fake` ровно 9 лишних: `apply_params`, `describe_params`, `get_status`, `list_devices`, `read_params`, `release_device`, `reset_stats`, `take_device`, `trigger_software`. `set_config`, `register_update`, `set_enabled` есть у любого процесса с плагином (у `devices` тоже) | частично: 9 ядра подтверждено; «11» — не мера вывода (всего 60; общих плагинных 3, а не 2: ещё `set_enabled`) |
| A5 смена поля на ходу | запись принята, разрыв < 1,5 с или нет | `set_register_verified(cam_fake, camera_device, exposure_time, 12000.0)` при 10000: `verdict=confirmed`, `vacuous=false`, `pre=10000.0`, `post=12000.0`, возврат за 36 мс; повтор 12000 -> `vacuous` (72 мс); 12000 -> 8000 `confirmed` (61 мс). Опрос `get_status` каждые ~49 мс (2 клиента): рост `frames` виден в каждом опросе; максимальный интервал между наблюдениями роста 100 мс за всю пробу и ≤ 54-57 мс вокруг записей (период кадра 40 мс). Разрыва нет. `device_state` = `grabbing` всё время. В журнале `policy=live ms=0` (поле `exposure_time`: `apply="live"` в `registers_base.py:113`, capability `live_write`). Второй прогон (8000 -> 12000 -> 12000 -> 8000): те же вердикты, максимум 63 мс | да |
| A6 run_locked | отказ take/release в running | оба: `success=false`, `result={"status":"error","error":"running","message":"сначала ОСТАНОВИТЬ"}`, 22-23 мс; `get_status` после — `grabbing`, `device_held=True`, кадры идут | да |
| A7 остановка | все `exited`, ≤ 10 с, сирот 0, порт свободен | `system_shutdown()` 0,99 с: `{"accepted": true, "mode": "graceful", "elapsed_s": 0.99, "pm_gone": true, "outcomes": {"cam_fake": "exited", "devices": "exited", "gui": "exited"}, "unconfirmed": [], "timed_out": false}`; `ps` через 2 с — 0 процессов проекта; `lsof` 8765/8775 пусто | да |
| B take_device на hikvision | `status: error` с текстом про недоступность прибора/SDK; `camera_0` жив; соседи живы | рецепт `hikvision_inspect` поднялся (процессы `ProcessManager`, `devices`, `gui`, `camera_0`). `take_device` -> `success=false`, `{"status":"error","device_state":"error","error":"PortError kind=other: acquire: other"}`. Текст НЕ говорит про SDK: «acquire: other». Причина лежит только в INFO-строке лога `S.h.sdk.bindings: Платформа darwin — Hikvision SDK не поддерживается.` | частично: отказ есть, процессы живы, текст нечитаем (находка) |
| B readiness / run_start | отказ по readiness или без кадров | `run_status`: `not_ready`, `reasons=[{"node":"camera_0.hikvision","severity":"failure","reason":"ошибка камеры","source":"readiness"}]`; `run_start` 11 мс -> `success=false, error="not_ready"` с теми же `reasons`; `get_status`: `state=error`, `frames=0`, `last_error="PortError kind=other: acquire: other"` | да |
| B живость | нет crash-loop | `supervision_status` на +17 с и +40 с: все 4 процесса `running`, `restart_count=0`, pid не менялись (88089/88091/88092/88093) | да |
| C остановка после B | как A7 | `system_shutdown()` 0,44 с, `outcomes`: `camera_0`, `devices`, `gui` = `exited`; `release_device` на `camera_0` (без прибора) `ok`, `device_state=closed`; `ps` — 0; порты свободны | да |

## Дополнительные наблюдения (вне предсказаний)

1. **`frames` растёт только в `running`.** После `run_stop` (-> `ready` за 0,32 с) счётчик замёрз: `[8523 x6]` при `device_state=grabbing`; после `release_device` (`closed`) и `take_device` (`grabbing`) в `ready` — те же 8523 ещё 3 с; после `run_start` рост возобновился сразу (`8523, 8536, 8549, 8561, 8574, 8587` за 0,5 с-шаги, 25 fps). Счётчик считает `produce()` (`plugin_base.py:526-547`), источник процесса вне `running`, видимо, не опрашивается. Это не красное по механизму (кадры идут, когда система `running`), но «grabbing без кадров» в `ready` — штатно, и GUI-индикатор по `device_state` в `ready` будет «захват» без кадров. Лиду решить, ожидаемо ли.
2. `release_device` в `ready` переводит `run_status` в `not_ready` (процесс без прибора), `take_device` возвращает `ready` — readiness связан с `device_held` (лог `A6d_ready_frames.log`).
3. Метрика `frames` в дереве состояния публикуется тиком 5 с (+125 кадров на тик). Прямое `Δframes/Δt` по произвольным двум чтениям дерева даёт 35,7 fps (артефакт: первое чтение устарело); корректно — по точкам смены или через `get_status.frames` (вживую). Предупреждение для будущих замеров fps через `state_get`.
4. Поле с `apply="restart"` (`exposure_auto`, `registers_base.py:108-111`): `Off -> Once -> Off` через `set_register_verified`: оба `confirmed`, разрыва кадров нет (максимум 86 мс на t≈1,8 с, вне окон записи 3,0 и 4,6 с), `device_state` `grabbing`. Перезахват НЕ наблюдался, `params` плана не получил `exposure_auto`. Поведение `restart` этим не проверено (вероятно, поле не входит в план фейк-порта или применяется при следующем `take_device`) — фиксирую как есть, вывода нет.
5. В топологии рецепта `camera_device_demo` кроме `gui` и `cam_fake` есть процесс `devices` (DeviceHub); `devices.yaml` лежит по прежнему пути (WARNING `device_hub`: ожидается в worktree `data/`, найден в `/Users/twokrai/Project_code/data/`). К камере отношения не имеет.
6. Рецепт β `hikvision_letter_robot` НЕ поднимался (нужны робот 192.168.1.7:502 и камера). Пять рецептов К4' (`hikvision_inspect`, `hikvision_dual`, `camera_robot_calibration`, `dataset_circle_capture`, `hikvision_letter_robot`) — только `yaml.safe_load` + подсчёт процессов/плагинов (`B3_recipes_parse.log`: 2, 3, 7, 10, 11 процессов; везде `HikvisionCameraPlugin`). Это слабая проверка (не `SystemBlueprint.check`); реально поднимался только `hikvision_inspect`.

## Процессы до / после

- До A: `ps` по `multiprocess_prototype|run.py|camera_device|spawn_main|resource_tracker` — 0; порты 8765/8775 свободны.
- A в `running`: pid 79321 (gate bash) -> 79328 (run.py) -> 79332 (ProcessManager) и дети 79347 (`devices`), 79349 (`gui`), 79350 (`cam_fake`).
- После A и после B/C: 0 процессов, порты свободны (`A7_ps_after.log`, `C_ps_after.log`).

## Что осталось открытым / ненадёжно

- Реальный прибор: `mvs`-порт и перезахват `mvs` не проверены (SDK на macOS нет); вся часть A на фейк-порту, он по определению `live_write`.
- B проверена только до `acquire`-отказа порта; поведение вендорского плагина при реальном приборе, цвет кадра (BGR/дисплей) не проверены. Кадры дисплея не смотрелись (headless `HeadlessGuiProcess`): путь «кадр -> gui -> дисплей» подтверждён только счётчиком `frames` у источника.
- GUI-вкладка вживую не смотрелась (qt-mcp не подключён: `CONNECTION_CLOSED`).
- Поле `restart` (п. 4) не воспроизведено; разрыв на перезахвате остаётся неизмеренным.
- Текст ошибки порта без SDK («PortError kind=other: acquire: other») не называет причину — предложение: поднять «SDK недоступен» в `last_error` (решение лида, код не правился).
- A5: разрыв измерен через `get_status.frames` с шагом ~49 мс против периода кадра 40 мс: разрыв короче ~50 мс не виден; для «нет разрыва» этого достаточно, для «разрыв 0 мс» — нет.
- Побочные файлы: `multiprocess_prototype/app.state.yaml` (игнорируется git, `*.state.yaml`) теперь указывает на `recipes/hikvision_inspect.yaml` (`run.py <рецепт>` пишет активный рецепт); логи в `logs/prototype_2/` (игнорируются).
- Не повторялось: ни один прогон не падал; стоп-условия не сработали.
