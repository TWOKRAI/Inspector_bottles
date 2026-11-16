# Services/camera_device — Статус

Дата: 2026-11-15 · ветка `feat/camera-device-w2-core` (HEAD `1f7ab44f0`)

## Текущее состояние

Волна W2 (ядро) собрана: порт и фейк, план записи профиля, сеанс с потоком-владельцем, профили run/rest с проверкой чтением
и сквозной срез «фейк -> сеанс -> item -> дерево» на плагине-заготовке. Драйверов, реестра драйверов и публикации телеметрии нет.
`Services/camera_device/tests`: 143 passed, 10 skipped (9 — `CAMERA_HARDWARE=1` не задан; 1 — фейк объявляет `software_trigger`, проверять нечего).

## Что сделано

| Task | Что | Файлы | Тесты (passed) |
|---|---|---|---|
| 1.5 | порт, контрактный набор, фейк | `interface.py`, `testing/fake_port.py`, `tests/port_contract.py` | 68 (+10 skipped) вместе с опциями фейка 2.1/2.2 (`test_fake_port_*`, `test_port_contract`) |
| 1.6 | план записи профиля | `params.py` | 17 (`test_params*`) |
| 1.8 | срез «фейк -> поток -> item -> дерево» | `plugin_base.py`, `plugin.py`, `registers_base.py` | 6 (`test_slice_plugin`) |
| 2.1 | сеанс `DeviceSession`: поток-владелец, переходы, дедлайн `start`, сторож | `session.py` | 27 (`test_session_lifecycle*`) |
| 2.2 | профили run/rest, проверка чтением, допуск по `vtype` | `profiles.py` | 25 (`test_session_profiles*`) |

Сумма 68 + 17 + 6 + 27 + 25 = 143 (каждая группа прогнана отдельно 2026-11-15). Прежние записи: ADR-CAM-001…004 (Task 0.1),
boundary «ядро -> вендор» (`.sentrux/rules.toml`), записи узлов `testing/recordings/mvcr_ID3013.json` (Task 6.2, 2026-10-19)
и `mvs_MV-CS020-10GC.json` (Task 0.5, 2026-10-27).

## Чего ещё нет

- 2.3a: общий register (`device_select`, `timeout_ms`, `watchdog_s`, ...), команды Р7 (`list_devices`, `read_params`, `apply_params`, ...), `commands.py`;
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
- Автопереподключения нет: из `busy`/`not_found`/`error` повторный `start()` при живом владельце возвращает `False`; нужен `stop()`.
- Плагин принимает только 8-битные одноканальные кадры (`ponytail:` в `_build_item`); `create_port` знает только `"fake"`.

## Не проверено

- Запрет «ядро -> вендор» не ловит `from Services.hikvision_camera.sdk import structures` (один замер, Task 0.1).
- Перезахват `stop -> план -> start_grabbing` в том же handle у `mvcr` — шлюз Task 6.4.
- Строки G6 R1 для потоков сеанса (`session.py`): запрос записи в `ALLOWLIST` — решение владельца ожидается; investigator проверяет `KeyedExecutor`.
