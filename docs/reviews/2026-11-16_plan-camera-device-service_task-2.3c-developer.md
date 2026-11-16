# Task 2.3c, developer: `commands.py`, `timeout_s`, `read_params`, `reset_stats`, `apply_params`

Дерево `cam-2-3c-dev`, ветка `feat/camera-2-3c`, база `b41f1575f`. Не коммитил (по брифу). Итерация 1 из 2.
Доказательство пути импорта (из того же cwd, что pytest): `multiprocess_framework/__init__.py` и `Services/camera_device/commands.py` лежат внутри дерева
`.claude/worktrees/cam-2-3c-dev`. memory hits: `search.py camera device plugin commands` -> ни одного релевантного урока (project_camera_settings_feature,
project_device_hub — другое).

## Что сделано (DESIGN / ACCEPTANCE)

- `commands.py` (новый, lite): `TakeDeviceArgs(timeout_s=5.0)`, `ReleaseDeviceArgs(timeout_s=2.0)` с `0 < timeout_s <= 30.0`, `ApplyParamsArgs(params)`
  с `extra="forbid"`; `__all__` из трёх имён; docstring Purpose / Public API / Stability. Контрактный тест — в слепом файле.
- `plugin_base.py`: проводка `timeout_s` в `cmd_take_device`/`cmd_release_device` (валидация первой; отказ -> `{"status": "error", "device_state", "error"}`,
  `start`/`stop` и создание сеанса не происходят); `_validation_text` (из `loc` и `msg`, `include_input=False`); словарь `commands` и docstring класса
  дополнены тремя строками; раздел «# Команды Р7» после `cmd_release_device` (место под readiness Ф ниже `cmd_get_status` не тронуто).
- `_stats_lock` (в `configure` рядом с `_timing_lock`): пара «`_frames += 1` + `reg.frames`» в `produce()`, `_dropped`/`_item_error` в `_drop_frame`,
  чтение счётчиков и сдвиг окна `_tick_t0`/`_tick_frames` в `_tick`, весь сброс. `publish_metric` и логи вне замка.
- `reset_stats`: `frames` (счётчик, поле, `publish_metric("frames", 0)` сразу), `dropped`, `_item_error`, `_tick_frames`, `_tick_t0 = now`; `errors` и
  `seq_id` не трогаются. INFO-лог без значений.
- `read_params`: снимок `session.params`/`session.param_errors`; сеанса нет -> оба пусты.
- `apply_params`: порядок (1) модель (2) `ctx.registers` (3) поле из `bindings()` по всему пакету (4) `readonly` по всему пакету (5) проба на
  `self._reg.model_copy(deep=True).apply_values(params)` -> запись по одному `set_field_value`; `session.apply` и порт не зовутся.
  Ответ `{"success": True, "applied", "on_device"}`; `on_device` = сеанс в `opening`/`grabbing` И есть поле с политикой `live`/`restart`.
  Отказ на фазе записи -> `{"success": False, "error", "applied": [...]}`. INFO-лог `apply_params fields=[...] ok=`, значений нет.
- README: раздел «Команды» (таблица форм ответа `status`/`success`; `read_params` — снимок; `reset_stats` — что сбрасывается и что нет; `apply_params` —
  `applied`/`on_device`, поля вне `bindings()`, флаги групп, остаточный отказ записи; строка про `set_config`); «Boundaries» + `pydantic`.
  `README` входит в FILES 2.3c; `DECISIONS.md` и `STATUS.md` не трогал.

## Прогоны (через `machine_gate.sh`, `PYTHONPATH=<дерево>`, `.venv/bin/python`)

| Команда | Итог |
|---|---|
| `test_plugin_commands.py` (слепой, до кода 38 красных) | 42 passed |
| `test_plugin_commands_hazards.py` (мой) | 18 passed |
| `Services/camera_device/tests` — прогон 1 / 2 / 3 | 321 passed, 10 skipped / 321 passed, 10 skipped / 321 passed, 10 skipped (флейков нет) |
| `Services/hikvision_camera/tests` | 287 passed, 15 skipped |
| `multiprocess_framework/modules/tests/test_one_connector_per_point.py` | 19 passed |
| `ruff check` и `ruff format --check` на `plugin_base.py`, `commands.py`, обоих тестовых файлах | чисто, 4 files already formatted |
| `git grep -nE "threading\.Thread|KeyedExecutor|ThreadPoolExecutor" -- plugin_base.py commands.py` | пусто, rc=1 |

## Красные слепые тесты, которые считаю ошибочными

Нет: после реализации все 42 зелёные, тест не правил. Замечание без красного: `test_страж_набор_команд...` проверяет `vars(CameraDevicePlugin)`; унаследованный
`cmd_set_config` в счёт 11 для 4.2a входит (ответ лида 3).

## Гарантии hazard-тестов -> мутация, которая ломает (прогноз; сам инъекции не делал)

Файл `test_plugin_commands_hazards.py` (18 тестов):

1. `test_reset_stats_ждёт_производителя_...` — убрать `with self._stats_lock` вокруг пары `+= 1` и `reg.frames` в `produce()` ИЛИ вокруг тела
   `cmd_reset_stats` -> красный (`resetter.is_alive()` ложно: сброс вернулся сразу; итог `inner.frames == 1`, счётчик 0).
2. `test_замок_статистики_охраняет_отброс_окно_и_сброс[drop_frame]` — убрать замок в `_drop_frame`. `[tick_window]` — убрать замок в `_tick`.
   `[reset_stats]` — убрать замок в `cmd_reset_stats`. Каждый параметр краснеет своей мутацией (работа не должна стоять на занятом замке).
   Слабость: `produce()` в этом тесте не проверяется (его `_tick` сам берёт замок, пара `+= 1`/поле изолирована только тестом 1).
3. `test_публикация_метрик_и_журнал_идут_вне_замка_статистики` — перенести `publish_metric("frames", ...)` в `produce()` / `cmd_reset_stats` внутрь замка,
   `ctx.log_error` из `_drop_frame` внутрь замка, или публикацию окна в `_tick` внутрь замка -> `held != []`.
4. `test_apply_params_пишет_поля_в_порядке_словаря` — сортировка/перестановка полей в цикле записи (`sorted(params)`, запись `bindings()` по порядку
   привязок) -> красный на втором пакете (обратный порядок).
5. `test_apply_params_отказ_пробы_не_пишет_ни_одного_поля[3 варианта]` — запись поле за полем без пробы (`set_field_value` в цикле до проверки) ->
   `seen != []` и `exposure_time == 900.0` на смешанных пакетах; проверка (3) только per-field после записи первого -> красный на `nope`.
6. `test_apply_params_успешная_проба_не_меняет_register_сама` — проба на оригинале (`self._reg.apply_values(params)` вместо копии) ->
   `exposure_time == 900.0` при отказе записи.
7. `test_apply_params_отказ_на_фазе_записи_называет_уже_записанные_поля` — убрать `applied` из ответа отказа или очищать список -> красный;
   откат уже записанных -> `reg.exposure_time == 10000.0` вместо 900.0.
8. `test_apply_params_проверки_идут_в_порядке_...` — перестановка любой пары проверок (registers после bindings, readonly после пробы, readonly
   по-полевой вместо фазы bindings) -> красный на своём шаге.
9. `test_apply_params_пустой_пакет_ничего_не_пишет` — запись заглушки для пустого пакета / `on_device` истинный -> красный.
10. `test_apply_params_на_прибор_ровно_одна_запись_и_один_apply_сеанса` — вызов `session.apply(...)` из команды вдобавок к `set_field_value` ->
    `applies` из двух элементов; прямая запись `self._reg.x = v` вместо `set_field_value` -> `writes` пуст (таймаут `_wait`); порт из потока команды
    (`session.call`/прямой `set_param`) -> `caller[0] in writer_threads`.
11. `test_apply_params_on_device_ложен_после_release_и_истинен_для_restart` — `on_device` без учёта `state` -> красный на втором ответе; без политики
    (`state` только) -> слепой `config`-тест; `restart` отброшен из `("live", "restart")` -> красный на первом ответе.
12. `test_take_device_отказ_валидации...` / `test_release_device_отказ_валидации...` — перенос валидации после `_ensure_session`/после `stop` ->
    `_session is not None` / `stops != []`; текст из `input` -> красный на литерале; без `device_state` в ответе -> красный.
13. `test_take_device_лишние_ключи_data_игнорируются` — `extra="forbid"` у `TakeDeviceArgs` -> красный.

Не покрыто своими тестами (покрыто слепым): сброс `_tick_frames` (`fps >= 0`), `seq_id`, `last_error`, `dropped` после битого кадра.

## Отклонения от текста задачи

- Нет существенных. Мелочи: проверки (3) и (4) выполняются фазами по всему пакету (так читается список «(3) … (4) …» в DESIGN); `_START_TIMEOUT_S` и
  `_STOP_TIMEOUT_S` в `plugin_base.py` остались определёнными, но обработчики их больше не читают (умолчания живут в `commands.py` и совпадают с ними:
  5.0 / 2.0). Не удалил, чтобы не трогать смежные ссылки; решить лиду (мёртвые константы или оставить как документацию).
- `_tick`: запись окна (`_tick_t0`, `_tick_frames`) теперь выполняется ДО публикаций метрик (раньше — после): иначе пара «чтение + запись» не помещалась бы
  в один короткий замок без `publish_metric` внутри. Побочный эффект: исключение в `publish_metric` больше не оставляет окно несдвинутым.

## Что я оставил открытым / ненадёжно

- Break-injection не делал (по брифу): таблица выше — прогноз по чтению, не по запуску. Все мои hazard-тесты зелёные с первого прогона; красными без
  замка/пробы они, по рассуждению, станут, но это не доказано запуском (тест 1 — единственный, где я прямо проследил расхождение `1 != 0` по коду).
- Гонка `publish_metric("frames", 0)` из `reset_stats` (вне замка) с `publish_metric("frames", N)` из `produce()`: возможен порядок «0, затем устаревшее
  N» в дереве до следующего кадра. Следствие требования «публикация вне замка»; в течение следующего кадра/окна дерево выравнивается. Не тестировал.
- Тест 2 (`[drop_frame]`, `[tick_window]`, `[reset_stats]`) держит `_stats_lock` и привязан к имени замка (его называет DESIGN); это проверка
  дисциплины замка, а не наблюдаемого итога. Наблюдаемая форма — только тест 1 (пара `frames`).
- `on_device=True` для `restart` проверен на `trigger_mode` при выключенном `trigger_managed`: план шага нет (skip), на приборе ничего не меняется; ответ
  зависит только от политики и состояния. Живое поведение restart на приборе (перезахват) не проверял.
- `apply_params` проба идёт на `deep` копии управляемого register'а: стоимость при большом register'е не замерял (камерный register — десятки полей).
- `data` не-словарь для `apply_params` (например `None`) даёт текст «Input should be a valid dictionary or instance of ApplyParamsArgs» — читаемо, но
  не пинал.
- `readiness` Ф и `list_devices` и др. команды 2.3d не добавлены (страж: словарь `commands` = три прежних + три новых).
- Файлы 2.3c не закоммичены: `commands.py`, `test_plugin_commands_hazards.py`, правки `plugin_base.py` и `README.md`, этот отчёт — в рабочем дереве.
