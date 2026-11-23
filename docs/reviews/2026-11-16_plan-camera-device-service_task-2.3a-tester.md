# Task 2.3a — слепой tester (RED), план camera-device-service

Файл: `Services/camera_device/tests/test_plugin_base.py` (единственный изменённый; не закоммичен).
Запуск: `multiprocess_framework.__file__` = `.../worktrees/cam-2-3a-tester/multiprocess_framework/__init__.py`;
`machine_gate.sh light inspector-bottles-20 <python> -m pytest Services/camera_device/tests/test_plugin_base.py` -> `16 failed, 7 passed`.

## Пункт ACCEPTANCE -> тест -> красный/зелёный -> причина

| Пункт | Тест (параметры) | До кода | Причина |
|---|---|---|---|
| 1 умолчание serial, пустое поле -> ValueError без значений | `test_идентичность_и_WARNING` (умолчание, serial/ip/url пусты; в соседние поля положены «канарейки») | 4 красных | `DID NOT RAISE ValueError`: `configure` не проверяет идентичность |
| 1 first -> WARNING; index без имени -> WARNING | то же (first, first+serial, index без имени) | 3 красных | `AssertionError: []`: строк `device_select=...` нет |
| 1 index с именем / serial задан молчат | то же (2 случая) | 2 зелёных | охрана от ложных WARNING/ValueError; пойманы мутацией M6 |
| 1 first берёт первый из двух приборов | `test_идентичность_доходит_до_сеанса[first]` | зелёный | сеанс с `ident=None` уже берёт первый перечисленный; это охрана от регрессии |
| 9 серийник NOPE -> error/not_found/без open | `...[serial_NOPE]` | красный | `'ok' == 'error'`: ident пока `None`, открылся FAKE-0001 |
| 9 серийник FAKE-0001 -> ok, open(serial,FAKE-0001) | `...[serial_FAKE]` | зелёный | пока ident `None`, но журнал тот же; ловится M7 |
| 2 watchdog_s <= timeout_ms/1000 | `test_watchdog_...` (0.25 и 0.75 при 750 мс — ValueError; 0.751 — take_device ok) | 2 красных, 1 зелёный | `DID NOT RAISE`; допустимый случай зелёный (поле игнорируется) |
| 3 item: 130 кадров, seq_id, frame_id, ts | `test_item_seq_id_растёт_...` | зелёный | регрессионная защита, как и ожидалось |
| 4 поля register, `FAKE_BINDINGS`, Р4 | `test_register_поля_умолчания_и_таблица_привязки_фейка` | красный | `_REQUIRED <= set(model_fields)` — нет `device_select`, `trigger_*` и др.; `fake_port.FAKE_BINDINGS` дал бы `AttributeError` (проверено отдельно по построению, маскируется первым assert) |
| 5 план run/rest (3 случая) | `test_план_run_и_rest_из_register` | 3 красных | журнал окна run пуст (`[] == [set_param ExposureTime ...]`) |
| 6 план при каждом старте | `test_план_строится_при_каждом_старте` | красный | `ValidationError: Object has no attribute 'exposure_time'` |
| 7 потоки + tables.py | `test_потоки_база_...` (subprocess `git grep`, `git diff`) | зелёный | регрессионная защита; ловится M4/M5 |
| 10 хуки базы | `test_хуки_базы_create_port_и_bindings_подкласса` | красный | `'open' in []`: хук `create_port()` не вызывается, берётся модульная функция |
| 11 Р4 check_bindings | хвост register-теста | красный | см. п.4 |
| 12 перехват WARNING | сборка в `_Built`: `services.log_warning` с `**kwargs` до `PluginContext(plugin_name=...)` | — | работает: `ctx.log_warning` приходит с `module=` и ловится |

## Break-injection зелёных до кода (копия `plugin_base.py` в scratchpad, откат `cp`, `git diff --stat` пуст)

- M1 `seq % 121` -> `assert 9 == 130`. M2 `ts = monotonic` -> `abs(ts - time.time()) < 1.0` красный. M3 `frame_id = seq + 1` -> `131 == 130`.
- M4 `threading.Thread(...)` в `plugin_base.py` -> `git grep` вернул 0 вместо 1. M5 дописанная строка в `tables.py` -> diff непуст.
- M6 безусловный `ctx.log_warning("device_select=first: x")` в `configure` -> красными стали `index_с_именем` и `serial_задан`.
- M7 `ident = FAKE-0002` в `_ensure_session` -> красными стали `first_`, `serial_FAKE` и допустимый случай watchdog.
- Первый прогон M6 попал в докстринг (первое вхождение строки) и ничего не ловил; повторён по `        ctx.declare_metric("frames")\n` — это учтено выше.

Ожидаемые журналы плана сверены (отдельный скрипт в scratchpad, без плагина) на существующем `DeviceSession` + фейке с планами по DESIGN: окна run/rest и `params` совпали с литералами теста.

## Что я трактовал, а не исполнял

- «Текст не содержит значения» для пустого `device_serial`: значения нет, проверка бессмысленна; проверил, что в текст не попадают значения ДРУГИХ полей идентичности («канарейки»). Для `watchdog_s` — что не попали `0.25`/`750`.
- `param_errors` включён в запрещённые поля register'а: так в DESIGN («НЕ в 2.3a») и в п.8 («без `param_errors`»); в п.4 перечислены только `restart_backoff_s` и `device_id`.
- `git diff main -- tables.py` заменён на `git diff $(git merge-base HEAD main) -- ...`: `main` ушёл вперёд от ветки задачи, прямой diff давал бы чужие правки.
- WARNING для `index`: ACCEPTANCE говорит «-> ctx.log_warning»; префикс `device_select=index` взят из текста DESIGN.
- В хук-тесте добавлено «`ExposureTime` записан по привязкам подкласса» (иначе проверка «нет TriggerMode» пуста, если план не пишет ничего).
- ≤ 9 функций: Р4 (`check_bindings`) и умолчания/`apply`/`ui_group`/`min=1` вложены в один register-тест; параметризация даёт 23 прогона из 9 функций.

## Пункты, которые нельзя написать однозначно

- п.1: «не содержит значения» при пустом поле (см. выше).
- п.8 (`test_slice_plugin.py` зелёный, снимок `catalog_register_fields.txt`) — не в FILES этого теста, не писал.

## Что осталось открытым / ненадёжно

- Ветки `ip`/`url`/`index` идентичности до сеанса не проверены (фейк перечисляет только `serial`, сеанс сравнивает `(kind, value)`): проверены лишь ошибки пустых полей и WARNING `index`.
- Ожидаемый порядок `get_param` сразу за `set_param` пары — свойство `ProfileRunner` (2.2), а не 2.3a; если 2.2 его сменит, тесты плана красные по чужой причине.
- Register-тест маскирует красные: первый упавший assert скрывает остальные (`FAKE_BINDINGS`, `check_bindings`); после GREEN их нужно перепроверить по отдельности.
- `rest`: после `release_device` проверяется только журнал; `params` после rest не проверяется (в ACCEPTANCE не заявлено).
- Hypothesis не использован: свойства «для всего класса входов» в контракте нет.
- Не проверено: `take_device` при `build_plan`/`set_profiles` с `ValueError` (хазард автора), два потока `take_device`.
