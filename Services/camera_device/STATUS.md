# Services/camera_device — Статус

Дата: 2026-11-20 · ветка `feat/camera-4c` (от `main` `ad3dc7b72`)

## Текущее состояние

Волна W2 (ядро) собрана: порт и фейк, план записи профиля, сеанс с потоком-владельцем, профили run/rest с проверкой чтением
и сквозной срез «фейк -> сеанс -> item -> дерево» на плагине-заготовке. Драйверов, реестра драйверов и публикации телеметрии нет.
`Services/camera_device/tests`: 462 passed, 10 skipped (1 прогон на ветке `feat/camera-4c`, 2026-11-20; на коммите слепых тестов `7135ef6d9` (main + 13 слепых) — 456 passed + 4 красных теста части Б, 10 skipped; на самом `main` до 4c — 443 (462 минус 19 новых тестов 4c, вычитанием, без прогона)) (9 skipped — `CAMERA_HARDWARE=1` не задан; 1 — фейк объявляет `software_trigger`, проверять нечего). Прежнее число 371 (3 прогона, 2026-11-19) было до readiness 2.2c.

## Что сделано

| Task | Что | Файлы | Тесты (passed) |
|---|---|---|---|
| 1.5 | порт, контрактный набор, фейк | `interface.py`, `testing/fake_port.py`, `tests/port_contract.py` | 68 (+10 skipped) вместе с опциями фейка 2.1/2.2 (`test_fake_port_*`, `test_port_contract`) |
| 1.6 | план записи профиля | `params.py` | 17 (`test_params*`) |
| 1.8 | срез «фейк -> поток -> item -> дерево» | `plugin_base.py`, `plugin.py`, `registers_base.py` | 6 (`test_slice_plugin`) |
| 2.1 | сеанс `DeviceSession`: поток-владелец, переходы, дедлайн `start`, сторож | `session.py` | 27 (`test_session_lifecycle*`) |
| 2.2 | профили run/rest, проверка чтением, допуск по `vtype` | `profiles.py` | 25 (`test_session_profiles*`) |
| 2.3c | команды Р7 без порта: `commands.py` (модели аргументов), `timeout_s` у `take_device`/`release_device`, `read_params`, `reset_stats`, `apply_params` | `commands.py`, `plugin_base.py` | 50 тестов (`test_plugin_commands*`: 33 + 17, по числу `def test_`, не прогон) |
| 2.3d | команды Р7 с портом: `_ensure_port`, `list_devices` (путь по `device_held`), `describe_params`, `trigger_software`, сторож `call`, замок `refs` фейка | `plugin_base.py`, `session.py`, `testing/fake_port.py` | 44 теста (`test_plugin_device_commands*`: 30 слепых + 14 автора, по числу `def test_`; каталог целиком 371 passed, 10 skipped, 3 прогона; плюс тесты сторожа в `test_live_apply_hazards.py`) |
| 2.2c | readiness: Task 2.2c в main, `test_readiness.py`; хук `readiness(ctx)` по состоянию сеанса (README «Готовность», ADR-CAM-005) | `plugin_base.py` | `tests/test_readiness.py` (26 `def test_`, часть параметризована); каталог целиком: 462 passed, 10 skipped (прогон 2026-11-20) |
| 4c | ключ `run_locked_commands: [release_device, take_device]` в `camera_device_demo.yaml` (README «Запрет команд в `running`»); Б2: `bindings()` в `cmd_apply_params` под `try` | `plugin_base.py`, рецепт | 13 слепых (`test_run_locked_commands_camera`) + 2 hazard (`_hazards`) + 4 (`test_apply_params_bindings_refused`) + 3 теста рецепта |

Сумма 68 + 17 + 6 + 27 + 25 = 143 (каждая группа прогнана отдельно 2026-11-15). Прежние записи: ADR-CAM-001…004 (Task 0.1), ADR-CAM-005 (readiness камеры, Task 2.2c),
boundary «ядро -> вендор» (`.sentrux/rules.toml`), записи узлов `testing/recordings/mvcr_ID3013.json` (Task 6.2, 2026-10-19)
и `mvs_MV-CS020-10GC.json` (Task 0.5, 2026-10-27).

## Чего ещё нет

- 2.3a: общий register (`device_select`, `timeout_ms`, `watchdog_s`, ...);
  запись `run`/`rest` плагином (`build_plan` из register'а и `BINDINGS` -> `DeviceSession(run=, rest=)`) — пункт амендмента 4.
- 2.3b: публикация `device_held`, `last_error`, `params`, `params_status`, `param_errors` и замеров в дерево состояния.
- 2.4: живая правка (`subscribe` -> очередь владельца, политика `apply`) и почтовый ящик владельца в `session.py`.
- Реестр драйверов `drivers/__init__.py`, драйверы `mvcr`, `mvs`, `opencv` (фазы 3–5); тесты на приборе.

## Известные ограничения

- Метрики `on_timing` не подключены: плагин создаёт сеанс без `on_timing` (`plugin_base.py`, `_ensure_session`), замеры `open`/`stop_grabbing`/`get_frame`/`apply` никуда не уходят.
- `on_state` приходит не по порядку: его зовёт поток, сменивший состояние (вызывающий или владелец); истина — `session.state`, плагин перечитывает его (`_on_state`).
- `session.py` — 448 строк против ≈200 в плане Task 2.1 (в том числе докстринг модуля, сторож и откат `start`); `watchdog.py` не выделялся.
- Запись `run`/`rest` плагином — в 2.3a: плагин создаёт `DeviceSession` без `run`/`rest`, поэтому на стенде `camera_device_demo` `params` пуст, `set_param`/`get_param` не вызываются.
- Логгер сеанса `camera_device.session` — стандартный `logging`, вне файлов framework-логов (по сведениям ревью волны; в коде не перепроверялось).
- Переподключение и потеря по тишине выключены по умолчанию (ADR-CAM-008). При `reconnect: false` из `busy`/`not_found`/`error` повторный `start()` при живом владельце возвращает `False`; нужен `stop()`.
- Плагин принимает кадры `mono8`, `rgb8`, `bgr8`, `bayer_*8`: цветные отдаёт как BGR (дебайер — `cv2` в ядре, ветка `bayer_*` в `_frame_array`,
  4.2a, коммит `6de54a088`); `bayer_*10/12` и `mono16` отбрасываются (`dropped`). Дебайер проверен на синтетической мозаике, на приборе не проверен.
  `create_port` знает только `"fake"`.

## Не проверено

- Запрет «ядро -> вендор» не ловит `from Services.hikvision_camera.sdk import structures` (один замер, Task 0.1).
- Перезахват `stop -> план -> start_grabbing` в том же handle у `mvcr` — шлюз Task 6.4.
- `MV_CC_EnumDevices` при открытом handle на MVS (0.5/6.2): касается межпроцессного `list_devices` (`hikvision_dual`); внутри процесса при захвате перечисляет владелец.
- Блокировка приёма команд процесса до `_CALL_TIMEOUT_S` + `watchdog_s` (около 7 с) командами с `session.call` — вывод по чтению, в живом процессе не измерялась.
- Гонка `start()` из другого потока против `acquire` в `list_devices` без владельца: по чтению недостижима (ревью Opus), не воспроизведена, замка нет.
- Строки G6 R1 для потоков сеанса (`session.py`): запрос записи в `ALLOWLIST` — решение владельца ожидается; investigator проверяет `KeyedExecutor`.
