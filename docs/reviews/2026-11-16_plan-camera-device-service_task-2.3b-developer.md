# Task 2.3b — developer: наблюдаемость базы плагина камеры

Ветка `feat/camera-device-w3` (HEAD 28720c500), worktree `cam-w3`. Не закоммичено.
Import path: `/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/cam-w3/multiprocess_framework/__init__.py`.

## Файлы
- `Services/camera_device/plugin_base.py` (+184/-6)
- `Services/camera_device/tests/test_plugin_observability.py` (новый, 6 тестов)

## Результаты (команды через gate, python главного .venv, PYTHONPATH=worktree)
- `pytest Services/camera_device/tests/test_plugin_observability.py` x3: 6 passed каждый раз. До правки src: 6 failed.
- `pytest Services/camera_device/tests` (medium): 192 passed, 10 skipped (186 + 6 новых).
- `pytest multiprocess_framework/modules/tests/test_one_connector_per_point.py`: 19 passed (AST-страж «один разъём на точку» видит Services).
- `ruff check Services/camera_device`, `ruff format --check` на двух файлах: чисто.
- Замер теста 1 (scratchpad measure.py): merge = 2 за 2 с, `publish_metric("frames")` max = 156 при 162 вызовах; замеры: open_ms 1, get_frame_ms 1, apply 1.

## Break-injection (по одной мутации, откат cp, `diff -q` подтвердил откат)
- M1 `merge` на каждый кадр: красный `merge 141 раз за 2 с` (тест 1).
- M2 инцидент busy через `ctx.log_error` вместо `health.report_error`: красный `report_error: 0 раз` (тесты busy и «настоящие объекты»).
- M3 (сверх брифа) убран дедуп `state != previous`: красный `report_error: 18 раз`.

## Дизайн, как исполнено
- Уровни: `declare_metric` x6 в `configure`; `frames` — на каждый учтённый кадр (как в 2.3a) и на тике; `fps`, `errors`, `dropped`, `pending`, `param_errors_count` — окном `_TICK_S=1.0 с` из `produce()`.
- События: `_sync_events()` из `_on_state` и из тика; перечитывает свойства сеанса, один `merge` отличий в `processes.<p>.state.plugins.<name>`, ушедшие ключи словарей — `state_proxy.delete`.
- Инциденты: переход в busy/not_found/error -> `report_error` + `health.degraded`; новый ключ `param_errors` -> `report_error`; `on_stall` -> `report_error` + `flight_dump("owner_stall", call=, seconds=)`.
- Замеры: `open` -> `record_timing("open_ms")`, `apply` -> `record_timing("apply")` (секунды), `get_frame` копится под замком и пишется одной записью `get_frame_ms` (среднее за окно).
- Мост `camera_device.session` -> `ctx.log_*` (`_SessionLogBridge`), ставится в `_ensure_session`, снимается в `shutdown`.
- TRAPS: `_dropped` подключён к уровню `dropped`; причина сбоя `create_port` теперь с traceback в `ctx.log_error` (для не-ValueError).

## Что я трактовал, а не исполнял
1. «publish_metric по тику framework»: хука тика у плагина нет, окно считает сам плагин в `produce()`. `frames` оставлен per-frame: окно 1 с не даёт `frames >= 90` в конце 2 с.
2. `frames >= 90` при `frame_period_s=0.02` недостижимо на macOS: замер 84 кадра за 2 с (фейк ставит срок от «сейчас» после сна). Тест 1 берёт `frame_period_s=0.012` (получается ~78 кадров/с).
3. `profile` из состояния: opening/grabbing -> "run", stopping/closed -> "rest", иначе None. Такой формулы в брифе нет.
4. `pending` = 1, если слот кадра занят, иначе 0. `dropped` = только битые item (перезапись слота не считается: у 6.1 выход 1 при `dropped > 0`).
5. Выход из отказа (busy -> closed) вызывает `health.set_status("ok")`, иначе `degraded` залипает. В брифе не было.
6. `params_meta` из tasks/2.3b.md не публикуется (в брифе его нет; источник данных — решение 2.3c).

## Что осталось открытым / ненадёжно
- Имя `open_ms`/`get_frame_ms` при значении в секундах (контракт `record_timing`): имя врёт про единицу. Решение лида, не менял; рекомендую `open`/`get_frame` или перевод в мс.
- Отказ reopen при rest (`run_rest` -> False) виден только в метрике `errors` и WARNING-строке через мост: `last_error` не пишется, `param_errors` пуст, состояние не отказное. Инцидента `report_error` на него нет (в `session.py` хука нет). Одиночные ошибки кадра (<3) тоже без инцидента.
- `last_error` не сбрасывается на `start()` (как и сказано в брифе, не чинил): после успешного захвата в дереве остаётся старая ошибка.
- Мост логгера: логгер `camera_device.session` общий на процесс, при двух плагинах камеры в одном процессе каждая строка уйдёт в оба журнала. Уровень логгера ставится в INFO, только если он NOTSET.
- Среднее `get_frame_ms` за окно скрывает выбросы (зависание ловит сторож); max/гистограмма не писались.
- README: запись про липкий `_item_error` и дедуп журнала (TRAPS) не сделана, README вне FILES.
- Проверка на стенде (6.1: `state_get`, `telemetry_snapshot`) не выполнялась; настоящий `StateProxy` в тестах не использовался (фейк), настоящие только `HealthState` и `PluginLevels`.
- Тесты на ~2 с реального времени и таймерах ОС: порог `frames` проверен 4 запусками (6 passed), запас по кадрам двукратный.
