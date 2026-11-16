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
