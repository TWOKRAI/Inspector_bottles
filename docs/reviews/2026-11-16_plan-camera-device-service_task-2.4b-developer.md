# Task 2.4b — developer: подписка плагина на RegistersManager, политика apply

Дерево `cam-2-4b-dev` (ветка `feat/camera-2-4b`, HEAD d67e1617c). Не закоммичено.
Import path: `/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/cam-2-4b-dev/multiprocess_framework/__init__.py`.

## Что сделано
- `Services/camera_device/plugin_base.py`: `_subscribe_fields` (в `configure`), `_unsubscribe_fields` (в `shutdown` и перед повторной подпиской), `_apply_policy`, `_on_field_update`.
  - `ctx.registers is None` -> один `log_warning`, подписки нет.
  - Иначе `registers.subscribe(self.name, поле, cb)` на каждое поле `bindings()`; `cb = functools.partial(self._on_field_update, поле)` — свой объект на поле и на configure. Хранится `(менеджер, поле, колбэк)`: снимается на том менеджере, на котором подписались.
  - Колбэк: политика `FieldMeta.apply` (`None`/`config` -> ничего); сеанса нет -> ничего; шаг из `build_plan(type(reg), {**reg.model_dump(), поле: value}, {поле: binding})`; нет шага или `skip` -> `log_info "apply field= skip="`; иначе `session.apply([шаг], policy)`. Любое исключение (в том числе `ValueError` неизвестной policy) -> `ctx.health.report_error(..., context="camera_device.live_apply")`, колбэк не падает.
- `Services/camera_device/tests/test_live_apply_wiring.py` (новый, 7 тестов): настоящие `RegistersManager` и `PluginOrchestrator._on_register_update`.
- Не тронуты: `session.py`, `fake_port.py`, слепые тесты, README, `readiness`, `outputs`, `cmd_*`, хуки. Потоков и `merge` не добавлял.

## Числа (gate, python главного .venv, PYTHONPATH=дерево)
- `test_live_apply_plugin.py`: до правки 6 failed (по заданию лида); после 6 passed.
- `test_live_apply_wiring.py`: 7 passed.
- `test_plugin_base.py`: 23 passed; `test_slice_plugin.py`: 6 passed; `test_plugin_observability.py`: 18 passed.
- весь `Services/camera_device/tests` 3 прогона подряд: 245 passed, 10 skipped, 245 passed, 10 skipped, 245 passed, 10 skipped.
- `test_one_connector_per_point.py`: 19 passed.
- `ruff check Services/camera_device`: чисто; `ruff format --check` на двух файлах: чисто.

## Мутации на моём коде (одна за раз, откат cp, `diff -q` подтвердил). Прогон: plugin + wiring + test_plugin_base + test_slice_plugin
| мутация | красные |
|---|---|
| M1 подписка снята | 8: строки 1, 3, 6, 7 тестера и 3 wiring (прибор не тронут) |
| M2 restart пишется как live | 3: строка 2, строка 6, wiring «неизвестная policy» |
| M3 колбэк зовёт порт сам | 8: в том числе строка 6 («id потока») |
| M4 `unsubscribe` убран из `shutdown` | 1: wiring `после_shutdown_правка_не_доходит…`; строка 7 тестера зелёная (после shutdown `session.apply` и так не принимает правку в `closed`) |
| M5 проверка `registers is None` убрана | 21: строка 5, `test_plugin_base`, `test_slice_plugin` |
| M6 снятие прежних подписок при повторном configure убрано | 1: wiring `повторный_configure…` (счёт подписчиков 2 вместо 1) |

M6 сначала выживал: тест видел только итоговую запись (сеанс сливает двойные правки по полю). Закрыт проверкой числа подписчиков. Тест «после повторного configure и shutdown» поймал реальный дефект в моём коде: `configure` обнулял список подписок до их снятия (исправлено: список не обнуляется).

## Что трактовал, а не исполнял
1. Повторный `configure` без `shutdown`: подписки не просто хранятся, а снимаются перед новой подпиской (иначе колбэки накапливаются; дедуп `subscribe` по равенству на `partial` не срабатывает).
2. Исключение колбэка идёт в `health.report_error`, не в `log_error` (инцидент одной дверью). Отказ приёма правки сеансом (`busy`/`closed`) — не инцидент.
3. Значение для плана берётся как `{**reg.model_dump(), поле: value}`: не полагаюсь на то, что register уже обновлён к моменту колбэка.
4. Неизвестная policy: тест подменяет `plugin._apply_policy` (валидный `FieldMeta` такого значения не даёт).

## Что осталось открытым / ненадёжно
- Живой процесс (`_message_processing_loop`) и стенд `camera_device_demo` (строка 9) не проверялись: вызов `_on_register_update` в тестах идёт из отдельного потока вручную, не транспортом.
- Тест подписок читает приватный `RegistersManager._field_observers` (публичного счёта нет).
- Поля без привязки в `bindings()` (флаги `*_managed`, `trigger_managed` с apply `restart`) не подписаны: переключение группы триггера на лету прибор не трогает, значение войдёт в план следующего `take_device`.
- Правка, пришедшая пока сеанс в `stopping`/`closed`/отказе, молча не принимается (только INFO в логе сеанса); значение попадёт в план следующего `take_device`.
- Строка 7 слепого теста слабее своей формулировки (M4 её не краснит); сам тест не правился, добавлен wiring-тест.
- Колбэк берёт `session = self._session` без замка: гонка с `_ensure_session` возможна только до первого `take_device` (тогда значение войдёт в план).
- Мутации прогонял сам (не junior/haiku); прогноз лидера по M4 («красный двойных set_param») не подтвердился в таком виде: красный — другой тест.

## Раунд 1 ревью Opus 2.4a+2.4b (находки 1, 3, 5)

Не коммичено. Файлы: `plugin_base.py`, `tests/test_live_apply_wiring.py`. `session.py` не тронут.

Правки:
- Находка 1: `_on_timing` для `apply` и `regrab` зовёт `_sync_events()` из потока владельца, но только при `session.state == "grabbing"` (запись `run` при открытии покрывает `on_state(grabbing)`, лишних merge нет). Дерево обновляется без вызовов `produce()`.
- Находка 5: `regrab` -> `record_timing("regrab_ms", seconds)` (секунды, как `open_ms`).
- Находка 3: колбэк строит ПОЛНЫЙ план (все `bindings()`) со старым и с новым значением поля при прочих равных значениях register'а и берёт шаги, которые различаются: собственный шаг и шаги потомков (включая ставшие `skip` и впервые включённые); `skip -> skip` отбрасывается. Политика вызвавшего поля — для всего пакета. Пустой набор -> прибор не трогается, лог `apply field= skip=`.

Что трактовал, а не исполнял (находка 3): вместо «сравнить с последним применённым run» плагин хранит `_seen_values` (значения привязанных полей, из которых построен идущий run; задаются в `take_device` при принятом `set_cycle`, обновляются колбэком, под `_plan_lock`) и сравнивает два плана «до/после» для вызвавшего поля. Причина: сравнение с планом целиком протаскивало бы в пакет несвязанные правки полей с apply `None`/`config` (привязанное поле `camera_id` в слепом тесте дописало бы `ExposureTime` при следующей правке).

Числа (gate, python главного .venv, PYTHONPATH=дерево):
- `test_live_apply_wiring.py`: 13 passed (было 7), 5 прогонов подряд: 13 passed x5.
- весь `Services/camera_device/tests`, 3 прогона подряд: 256 passed, 10 skipped (было 245).
- `test_one_connector_per_point.py`: 19 passed; `ruff check Services/camera_device` и `ruff format --check` на двух файлах чисто.
- по ходу работы тест дерева был флаки (гонка: `on_state(grabbing)` может прийти после ответа `take_device`); исправлено ожиданием исходного значения, 12 прогонов подряд зелёные.

Мутации (одна за раз, откат cp, `diff -q`; прогон plugin + wiring + session + hazards):
| мутация | красные |
|---|---|
| N1 `_sync_events` убрана из `_on_timing` | wiring `дерево_обновляется…`, `test_live_apply_session::test_restart_без_restart_regrab…` |
| N2 `regrab_ms` не пишется | wiring `перезахват_пишет_regrab_ms…`, hazards `test_stop_в_окне_перезахвата…` |
| N3 план не пересчитывается (только собственный шаг, старое поведение) | wiring `смена_родителя_без_restart_regrab…`, `обратная_смена_родителя…`, hazards `test_stop_в_окне…` |
| N4 `skip -> skip` включается в пакет | wiring `правка_пропущенного_потомка…` |

Открыто: стенд (строка 9) не прогонялся. Тест на дерево идёт с `StateProxy` + `TreeStore` (router-двойник), не с живым процессом. `_seen_values` инициализируется после `set_cycle` без общего замка с колбэком: правка между построением плана и снимком значений теоретически теряется (окно микросекунд, при принятом `set_cycle` сеанс ещё не запущен). Если `set_cycle` отклонён (прибор держится), `_seen_values` не меняется: повторный `take_device` на идущем цикле правки не откатывает. Снятие `skip` с потомка при смене родителя на restart_regrab пишет потомка по порядку `_run`, проверено только на фейке (MVS без `restart_regrab` — весь run после reopen, проверено фейком без этой capability). Найденные ревью 2 и 4 (hazard-тест порядка, BaseException в `_execute`) — в `session.py`/тестах 2.4a, не мои.

## Раунд 2 ревью Opus: R2-1 (повтор того же значения после отказа записи)

Не коммичено. Файлы: `plugin_base.py`, `tests/test_live_apply_wiring.py`.

- Правка: `_changed_steps(..., retry)`; `retry = field in session.param_errors`. Собственный шаг поля пишется, если значение изменилось ИЛИ у поля есть отказ записи; повтор без отказа — по-прежнему 0 записей и 0 перезахватов.
- Тесты (2 новых, в файле 15): повтор 900.0 после сбоя подтверждения (`read_offset=5.0`, сбой снят) -> ровно один `set_param(ExposureTime, 900.0)`, `param_errors` без поля, `params["exposure_time"] == 900.0`; повтор того же значения без отказа (live и restart) -> журнал пуст, `stop_grabbing` нет.
- Инъекция: убрано условие retry -> красный только новый тест «после отказа записи» (в 4 файлах live_apply один ещё `test_stop_в_окне…`, см. ниже — это флаки). Обратная мутация (retry всегда) -> красный «без отказа». Откат cp, `diff -q` подтвердил.
- Прогон (gate): `Services/camera_device/tests` 261 passed, 10 skipped (x2: 261 passed, 10 skipped); `Services/hikvision_camera/tests` 287 passed, 15 skipped; `test_live_apply_wiring.py` 15 passed x3; ruff check и format --check чисто.

Открыто: `test_live_apply_hazards.py::test_stop_в_окне_перезахвата_…` (тест 2.4a, не мой файл) флаки на ЧИСТОМ коде: в 2 из 3 прогонов четырёх файлов live_apply красный, `rig.events` читается раньше, чем колбэк `on_state(stopping->closed)` добавил событие (тест ждёт `session.state == "closed"`, а колбэк идёт после установки состояния); в 5 из 5 отдельных прогонов файла и в полных прогонах каталога зелёный. Тест работает на `DeviceSession` без плагина, мои правки на него не влияют. Предлагаю лиду ждать `len(rig.events) == 4` в тесте. Остальное из прежних разделов в силе.
