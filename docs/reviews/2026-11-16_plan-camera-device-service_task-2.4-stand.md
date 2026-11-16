# Стенд camera_device_demo — приёмка 9 задачи 2.4b (живая правка через register)

Дата: 2026-11-16. Дерево: `.claude/worktrees/cam-w3` (HEAD e925ddb85 = main с 2.3a/2.3b/2.4a/2.4b). Исполнитель: диагност (код не правил, ничего не коммитил).

## Что запускал

Окно у гейта: `machine_gate.sh request inspector-bottles-20 stand 20 ...` -> `machine_gate: no machine.lock`, rc=2 (координатора нет, окно не нужно; `stand.lock` тоже нет). Перед стартом порты 8765/8766 были свободны, чужих python-процессов приложения не было. `release` в конце тоже rc=2 (нечего освобождать).

Бэкенд (scratchpad `.../scratchpad/stand/`):

```
BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=$S/logs MULTIPROCESS_LOG_DIR=$S/logs \
INSPECTOR_PID_FILE=$S/app.pid PYTHONPATH=<cam-w3> \
/Users/twokrai/Project_code/Inspector_bottles/.venv/bin/python multiprocess_prototype/run.py camera_device_demo
```

Порт backend_ctl: УНИКАЛЬНЫЙ порт не задавал. MCP-сервер backend-ctl уже запущен сессией с портом по умолчанию 8765 (env `BACKEND_CTL_PORT` у него не выставлен), поэтому и бэкенд сидел на 8765 (свободен). Свой `INSPECTOR_PID_FILE` и `INSPECTOR_LOG_DIR` использованы; pid-файл: 72559 (лаунчер), 72561/72562/72563 (дети; cam_fake = 72563). Топология: gui (Headless), devices, cam_fake.

Дальше: MCP `capabilities`, `watch_like_gui`, `state_get_subtree`, `introspect_registers`, `log_tail DEBUG cam_fake`, `set_register_verified`, `await_condition`, `system_command process.pause/resume`, `system_shutdown`.

## Таблица чисел

### 1. Старт

| Что | Значение |
|---|---|
| Процессы | cam_fake, devices, gui подняты, `get_status cam_fake`: status=running, pid 72563, воркеры `camera_device_0_owner`, `..._watchdog`, `source_producer_camera_device` running |
| `state.plugins.camera_device.state` | `grabbing`, `device_held=true`, device FAKE-0001, profile `run` |
| capabilities фейка | `live_write, node_describe, read_back, restart_regrab, software_trigger` |
| fps | 25.0 (source producer: effective_hz 25.0, cycle_duration_ms 40.3, pacer_late 0) |
| frames (публикуются раз в 5 с, тик телеметрии) | 225 -> 350 -> 475 -> 600 -> 725 -> 850 -> 975 -> 1100 -> 1225: ровно +125 за 5 с = 25 fps |
| params на старте | `{exposure_time: 10000.0}` (план run: при `take_device` 22:22:42,015 `apply field=exposure_time ... verified=True`) |
| Старт в логе | `session state=idle->opening` 22:22:42,014; `opening->grabbing` 22:22:42,015; `take_device ok=True` |

### 2. Живая правка exposure_time = 900 (ГЛАВНАЯ ПРОВЕРКА)

Ответ `set_register_verified cam_fake camera_device exposure_time 900` дословно (главное):

```
{"success": true, "verified": true, "found": true, "process": "cam_fake", "register": "camera_device", "field": "exposure_time", "expected": 900, "actual": 900.0, "known_registers": ["camera_device"], "ack": {... "sender": "cam_fake", ... "success": true, "result": {"success": true, "register": "camera_device", "field": "exposure_time", "value": 900}, ... "receive_time": 1794856982.163305}}
```

Цепочка по логам cam_fake (метки epoch, секунды):

| Событие | Время | Дельта от предыдущего |
|---|---|---|
| `PluginOrchestrator[cam_fake]: register_update camera_device.exposure_time = 900` (вход `_on_register_update`) | 1794856982.1522 | - |
| ack set_register_verified получен драйвером | 1794856982.1633 | +11 мс |
| `apply field=exposure_time binding=ExposureTime value_written=900.0 value_read=900.0 rc=None ms=0 verified=True` (ProfileRunner, поток-владелец) | 1794856982.1731 | +21 мс от register_update |
| `apply field=exposure_time policy=live ms=0` (`DeviceSession._drain` -> `_log_apply`, ветка live) | 1794856982.1734 | +0,2 мс |
| `plugins.camera_device.ts` в дереве = момент публикации | 1794856982.1733 | - |

Время от `register_update` до `params.exposure_time == 900.0` в дереве: около 21 мс (по меткам логов/ts; ms внутри apply = 0). От ack драйвера до дерева: около 10 мс. Дерево: `await_condition metric_threshold path=...params.exposure_time op<=900.5` вернул `matched, value 900.0, elapsed_sec 0.0, source read-model`; `state_get_subtree` сразу после: `params: {exposure_time: 900.0}`, `params_status.exposure_time: {verified: true, rc: null}`, `param_errors: {}`, `last_error: null`. Дельта в потоке `state.changed`: revision 299 `params.exposure_time 10000.0 -> 900.0`, source `cam_fake`.

Регистр в дереве процесса (`introspect_registers cam_fake`): `exposure_time` = 900 (verify-probe `actual: 900.0`).

Перезахват/open: НЕТ. Политика поля `live` + capability `live_write` -> `_drain` пошёл в ветку `live` (`apply_plan` без остановки). В логе нет ни одной строки `session state=...` после старта (нет opening/перехода состояния), нет `policy=restart`. Кадры не прервались: frames 475 (tick 22:23:01,7) -> 600 (22:23:06,7), +125 за 5 с, fps 25.0 до и после правки; `state` всё время `grabbing`.

Порядок самих замеров: `await_condition` вызывал после `set` (MCP выполнил вызовы последовательно), поэтому `elapsed_sec 0.0` не является замером задержки; задержка взята из меток логов (строки выше).

### 3. Правка другого поля (restart-политика)

`trigger_period_ms` имеет `apply="restart"`, но `enabled_if={"trigger_managed":[True],"trigger_source":["SelfTrigger"]}`.

| Шаг | Вход | Наблюдаемое (лог 22:23:..) | Перезахват |
|---|---|---|---|
| a | `trigger_period_ms=100` при `trigger_managed=false` | 22:23:30,604 `CameraDevicePlugin: apply field=trigger_period_ms skip=нет шага`; затем `register_update ... = 100`. Дерево params не изменилось (`{exposure_time: 900.0}`) | нет (шаг skip: прибор не тронут) |
| b | `trigger_managed=true` | 22:23:36,527 `register_update`; apply не вызван (поле без FieldMeta.apply, `config`/нет политики) | нет |
| c | `trigger_mode=On` | 22:23:36,660 `apply field=trigger_mode ... verified=True` и в том же пакете `trigger_source ... value_written='Line0'` (потомок включился); `policy=restart ms=0` x2 | `_regrab` один на пакет (restart_regrab: stop_grabbing, запись шагов, start_grabbing); `open` НЕ вызывался |
| d | `trigger_source=SelfTrigger` | 22:23:36,775 `apply field=trigger_source ... 'SelfTrigger'` + `apply field=trigger_period_ms ... value_written=100` (потомок включился со значением из шага a); `policy=restart ms=0` x2 | один regrab |
| e | `trigger_period_ms=200` | 22:23:36,909 `apply ... value_written=200 verified=True`; `policy=restart ms=0` | один regrab |
| f | `trigger_period_ms=300` | 22:24:55,903 аналогично | один regrab |

Итоговое дерево после f: `params: {exposure_time: 900.0, trigger_mode: "On", trigger_source: "SelfTrigger", trigger_period_ms: 300}`, `params_status` у всех `verified: true`, `param_errors: {}`. Кадры шли непрерывно (fps 25, frames растут +125/5 с) и после regrab: у фейка нет реальных задержек (ms=0 в логе, секунда не разрешается до мс).

Метрика `regrab_ms`: в логах НЕ НАБЛЮДАЕТСЯ. Имена метрик во всех снимках `metrics snapshot` (раз в 10 с, `cam_fake/performance.log`) за прогон: `apply`, `get_frame_ms`, служебные `command_manager.*`, `dispatcher.*`. `regrab_ms` и `open_ms` отсутствуют, хотя `open` был (старт 22:22:42) и `_regrab` исполнялся 4 раза (по строкам `policy=restart`). `apply` (тот же `_on_timing`, соседняя ветка) попал в снимок. Значение `regrab_ms` поэтому ЧИСЛОМ не получено. Причину не установил (см. ниже «открытое»). Проверено: `telemetry_snapshot` по `regrab_ms`/`open_ms`/`get_frame_ms` дают `count 0` (этот инструмент видит только дерево состояния, а не statistics), так что за источник принят performance.log.

### 4. Пауза

`system_command {cmd: process.pause, process_name: cam_fake}` -> `success: true`. После паузы:

| Что | Значение |
|---|---|
| `processes.cam_fake.state.status` | `running` (не `paused`) |
| `plugins.camera_device.state` | `grabbing`; `params` без изменений |
| frames | 4103 (в момент 22:25:29) -> 4353 (22:26:12): продолжает расти; `source_producer` `cycles` 4221 -> растёт, effective_hz 25.01 |
| Живая правка во время паузы `exposure_time=1200` | `verified: true, actual 1200.0`; в дереве `params.exposure_time: 1200.0`, `ts` = 1794857129.3746 (ack 129.3639): +11 мс |

То есть `process.pause` на этом процессе в стенде не наблюдаемо остановил ни продюсер, ни дерево; проверить поведение `_sync_events` в паузе (требование Р6 про «окна produce нет в паузе») этим способом нельзя. `process.resume` -> `success: true`. Затем `system_shutdown` (graceful).

Дерево params после остановки системы получить нельзя (после `system_shutdown` бэкенда нет); последнее состояние перед остановкой: `params: {exposure_time: 1200.0, trigger_mode: On, trigger_source: SelfTrigger, trigger_period_ms: 300}`.

### 5. Остановка

`system_shutdown`: `accepted: true, mode: graceful, elapsed_s: 0.679, pm_gone: true, outcomes: {cam_fake: exited, devices: exited, gui: exited}, unconfirmed: [], timed_out: false`. После: pid 72559/72561/72562/72563 завершены, порт 8765 не слушает, чужих процессов не трогал. `git status --short` в дереве чист (`app.state.yaml` рядом с рецептом перезаписан запуском; в статусе не виден).

## Логи

Каталог: `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/422fbc6b-1296-4c1b-8072-6402b3628f21/scratchpad/stand/logs/` (+ `run.out`).

- `errors.log`, `critical.log`, `warnings.log` (корневые) и `launcher/errors.log`: 0 байт. ERROR/CRITICAL за прогон: ноль. В `cam_fake/*.log`: ни одной строки ERROR, нет `Traceback`, нет «колбэк ... завершился исключением» (`DeviceSession._notify`), нет `health.report_error` из `_on_field_update`/`camera_device.live_apply`.
- WARNING от camera_device (один, ожидаемый, на старте): `device_select=first: прибор выбирается первым из перечисленных; задайте serial`.
- Прочие WARNING (к задаче отношения не имеют): ограничение частоты метрик fps/latency_ms тиком 5.0 с (heartbeat, три процесса); `DeviceHubPlugin: реестр устройств ожидается в .../cam-w3/data/devices.yaml, но данные найдены по прежнему пути .../.claude/worktrees/data/devices.yaml`; миграция auto_vacuum documents.db; на остановке «приёмники не приняли ни одной записи за прогон» (idle_sinks) у logger/error launcher/PM/devices.
- Строки пути записи (дословно, cam_fake/messages.log): `#47 22:23:02,152 register_update camera_device.exposure_time = 900`, `#48 22:23:02,173 apply field=exposure_time binding=ExposureTime value_written=900.0 value_read=900.0 rc=None code= ms=0 verified=True`, `#49 22:23:02,173 apply field=exposure_time policy=live ms=0`. (Время в логе локальное, UTC+... = epoch 1794856982.)

## Вывод

Приёмка 9: ПРИНЯТА по главному пункту. Живой путь `_message_processing_loop` -> `PluginOrchestrator register_update` -> `_on_register_update` / подписка `_on_field_update` -> `session.apply` -> поток-владелец -> `ProfileRunner.apply_plan` -> публикация в дерево отработал на реальном процессе cam_fake (драйвер fake): `exposure_time=900` дошёл в дерево за ~21 мс от `register_update` (~10 мс от ack), без перезахвата и без остановки кадров (live-ветка, `live_write`), ошибок и WARNING от camera_device нет. Дефекта framework в колбэке на живом пути НЕ обнаружено. Побочно подтверждено живьём: restart-политика даёт один `_regrab` на пакет без `open` (capability `restart_regrab`), потомок по `enabled_if` включается вместе с родителем, skip-случай не трогает прибор.

Две находки, не относящиеся к главной проверке (не чинил):
1. `regrab_ms` (и `open_ms`) не появляются в statistics-снимках процесса при том, что `regrab` и `open` реально исполнялись, а соседние `apply` и `get_frame_ms` появляются. Либо метрика не доходит до агрегатора, либо снимок её не выводит. Критерий «замер regrab_ms» из задания по стенду не закрыт числом.
2. `process.pause cam_fake` -> `success: true`, но `status` остаётся `running`, продюсер и публикация frames не останавливаются.

## Что я оставил открытым / ненадёжно

- Порт backend_ctl 8765 (по умолчанию), не уникальный: MCP-сервер запущен без `BACKEND_CTL_PORT`, перенаправить его на другой порт из этой сессии нельзя. Порт был свободен, чужих сессий на нём не видел.
- Задержку «set -> дерево» получил по меткам логов (`register_update` 982.1522, apply 982.1731, ts дерева 982.1733) и по ack драйвера (982.1633), а не отдельным вызовом `await_condition` в параллели: MCP исполнил вызовы последовательно (`elapsed_sec 0.0`). Грубость: метка ack идёт от другого процесса, часы общие (одна машина).
- `regrab_ms`: причина отсутствия не установлена (гипотезы не проверял: поток-владелец против плагинного потока, гейт политик метрик, окно снимка). Нужна отдельная проверка (например `introspect_observability` либо прогон с логом из `PluginContext._stats_call`). Не исключено, что дело в самом стенде, а не в коде.
- `open_ms` на старте отсутствует тоже (первый снимок появился уже после `open`; не проверял, что именно в нём было).
- Пауза: `process.pause` не дала наблюдаемой паузы, поэтому поведение живой правки В ПАУЗЕ процесса (нет окна `produce`) не проверено; правка при «паузе» прошла как обычно.
- Фейк не имеет задержек (ms=0 везде): время перезахвата на реальном приборе стенд не измеряет.
- Состояние `trigger_managed=true`, `trigger_mode=On`, `trigger_source=SelfTrigger` я менял на живом процессе; в рецепт/app.state не писал, дерево после остановки не сохраняется.
- Запуск `run.py` перезаписывает `multiprocess_prototype/app.state.yaml` (строка «активный рецепт записан в состояние»); `git status` после стенда чист, но файл стоит проверить при коммите.
- Предупреждение `DeviceHubPlugin` про `data/devices.yaml` (путь данных относительно worktree) не связано с камерой.

## Дополнение лида К: `regrab_ms` и `open_ms` закрыты числом (диагностика, 2026-11-16)

Находка «метрик нет» оказалась ошибкой чтения, не дефектом кода: метрики лежат в `observability.db` (`kind='stats'`), а строка `performance.log` режется до 2048 байт (`log_stats_channel.py:76-111`, хвост окна «опущено N из M метрик»). По БД: `regrab_ms` count 4 (по числу перезахватов), 0.00053–0.00111 с; `open_ms` count 1, 2.7e-06 с (фейк, секунды). Подробности и воспроизведение: `…task-2.4-metrics-diagnosis.md`. Приёмка 9 принята полностью, кроме проверки «в паузе»: `process.pause` статус не меняет (не исследовалось).
