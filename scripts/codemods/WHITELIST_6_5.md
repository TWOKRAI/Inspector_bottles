# Ф6.5 — что кодмод НЕ трогает во фреймворке, и почему

Список для владельца **до** кодмода 6.2 (условие приёмки 6.5: «whitelist с
обоснованием у КАЖДОЙ строки, иначе он станет свалкой»).

Проверено не рассуждением о слоях, а **пробой**: в каждый файл фреймворка с
голым `logging.getLogger(__name__)` временно вставлялся импорт вида и правился
вызов, после чего модуль импортировался в свежем интерпретаторе; правка
откатывалась. Скрипт пробы — `probe_cycles.py` (одноразовый, в scratchpad
сессии; воспроизводится за минуту).

**Итог пробы: 30 файлов фреймворка, из них 26 чистых, 4 в whitelist, 1 требует
ручной правки.**

## Whitelist — 4 файла

| Файл | Причина | Чем доказана |
|------|---------|--------------|
| [`base_manager/mixins/observable_mixin.py`](../../multiprocess_framework/modules/base_manager/mixins/observable_mixin.py) | `_note_manager_call_failure` пишет **мимо отказавшего менеджера**: сообщить о поломке логгера через логгер нельзя | Проба: `ImportError: cannot import name 'ObservableMixin' from partially initialized module` — цикл, а не стилистика |
| [`data_schema_module/registry/discovery.py`](../../multiprocess_framework/modules/data_schema_module/registry/discovery.py) | Ниже слоя логгера: `logger_module` импортирует `data_schema_module` | Проба: `ImportError: cannot import name 'SchemaBase' from partially initialized module` |
| [`data_schema_module/registry/process_registry.py`](../../multiprocess_framework/modules/data_schema_module/registry/process_registry.py) | То же | Проба: та же ошибка |
| [`modules/_fallback.py`](../../multiprocess_framework/modules/_fallback.py) | **Сам аварийный выход**. `FallbackLogger` переведён на вид (`get_std_logger(self._name, fallback_name=self._name)`), а вот `emergency_log` держит голый `logging.getLogger(name)` **намеренно и обязательно**: это последний рубеж, когда штатный маршрут сломан, и страж 6.3 требует, чтобы это нарушение в файле жило (протухшая строка whitelist = красный). *(Поправка ревью 2026-08-03: прежняя редакция утверждала «голого getLogger в нём нет» — это было неверно про файл целиком.)* | Чтением + стражем: `test_std_logger_guard.py::test_whitelist_entry_is_not_stale` |

**Что в whitelist НЕ попало, вопреки ожиданию плана.**
`config_module/core/config.py` проба прошла **чисто** — `logger_module` его не
импортирует, «ниже слоя логгера» для этого файла оказалось предположением, а не
фактом. Мигрируется на общих основаниях.

`channel_routing_manager._fallback_logger` из формулировки плана не существует
как отдельный логгер: `_fallback_log` делегирует в `_fallback.emergency_log`,
голого `getLogger` в `channel_routing_module` нет. Мигрировать нечего.

## Требует ручной правки — 1 файл фреймворка + 2 прототипа

Правило `std-logger-import` вставляет импорт рядом с **модульным**
`import logging`. Там, где `import logging` лежит внутри функции или под
алиасом, импорта вида не появится, а вызов уже будет переписан — то есть
`NameError` в рантайме, невидимый в диффе.

| Файл | Что не так | Что сделать руками |
|------|-----------|--------------------|
| [`process_module/plugins/registry.py:177`](../../multiprocess_framework/modules/process_module/plugins/registry.py#L177) | `import logging` **внутри метода**, модульного нет | Добавить импорт вида на уровень модуля |
| [`multiprocess_prototype/domain/__init__.py:145,154`](../../multiprocess_prototype/domain/__init__.py#L145) | Алиасы `_log` / `_logging` внутри `try` на импорте | Переписать обе точки руками |
| [`multiprocess_prototype/frontend/app.py:640`](../../multiprocess_prototype/frontend/app.py#L640) | Алиас `_logging` | То же |

Приёмка 6.2 (`grep getLogger(__name__)` = 0 вне whitelist) эти три файла
поймает — но только если её считать **после** ручных правок, а не до.

## Мигрируются штатно — 26 файлов фреймворка

`actions_module` (3), `config_module` (1), `event_module` (1),
`frontend_module` (16), `process_module/plugins/manifest.py` (1),
`recipe/recipe_engine.py` (1), `shared_resources_module` (2 —
`buffers/cleanup.py` и уже переведённый `queues/core/manager.py`),
`state_store_module/persistence/persistence_manager.py` (1).

Все 26 импортировались чисто с подставленным видом.

**Оговорка о силе доказательства.** Проба показывает отсутствие цикла при
**прямом** импорте модуля — самый жёсткий одиночный порядок, но не все
возможные. Окончательный ответ даёт live smoke двух стендов после 6.2, как и
записано в приёмке («ревью — запуском, не чтением диффа»).
