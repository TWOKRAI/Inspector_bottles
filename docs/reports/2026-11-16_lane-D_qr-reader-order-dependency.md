# Полоса D: три красных `test_qr_reader_sdk*` в общем прогоне — причина и правка

Дата: 2026-11-16. Ветка `fix/validate-red-memory-tags` (worktree `laneD-validate`). Коммит не делался.

## Итог

Причина найдена и устранена. Красные: `test_qr_reader_sdk_demo.py::test_blueprint_проходит_check_загрузчика`,
`test_qr_reader_sdk_dual_demo.py::test_blueprint_проходит_check_загрузчика[qr_reader_sdk_dual_demo]` и
`[qr_reader_sdk_dual_selftrigger]`. Загрязнитель — тест
`multiprocess_prototype/frontend/forms/tests/test_catalog_kind_roundtrip.py::test_resolve_kind_stable_across_json_roundtrip_for_all_register_fields`.
Он откатывал реестр плагинов в `finally: PluginRegistry.restore(snapshot)`. Правка: откат убран (одна тестовая
функция, код framework не менялся).

## Механизм

1. `@register_plugin` срабатывает один раз — при первом `import` модуля `plugin.py`. `PluginRegistry.discover()` зовёт
   `importlib.import_module`; для модуля, уже лежащего в `sys.modules`, повторный вызов ничего не исполняет и
   ничего не регистрирует (`multiprocess_framework/modules/process_module/plugins/registry.py`, метод `discover`).
2. Загрязнитель берёт `snapshot()` (реестр пуст, если он первый в процессе, кто импортирует плагины), затем зовёт
   `discover(Plugins/ + Services/)` — это ПЕРВЫЙ импорт всех `plugin.py`, включая `Services/code_reader/plugin/sdk_plugin.py`.
   В `finally` он делает `restore(snapshot)` и стирает все только что рождённые регистрации. Модули остаются в
   `sys.modules`.
3. Жертва зовёт `discover(...)` — модули закешированы, реестр остаётся пустым. Страж жертвы
   `PluginRegistry.get("code_reader_sdk") is not None` падает: «реестр не знает code_reader_sdk».
4. В изоляции жертва зелёная: она сама первая импортирует плагины.

Гипотеза из брифа («другой тест очищает реестр») подтвердилась, уточнение: не `clear()`, а `restore()` к снимку,
взятому до первого импорта. Docstring загрязнителя сам предупреждал про `clear()`, но про `restore()` — нет.
Тот же класс описан в памяти: `.claude/memory/feedback_global_rollback_breaks_import_time_state.md` (состояние,
созданное импортом, монотонно; откатывать его нельзя).

## Воспроизведение (красное до правки)

Гейт: `machine_gate.sh heavy|light D`. Общий прогон нужной комбинации каталогов я не воспроизвёл (см. «Открытое»);
красное получено бисекцией: 87 файлов-кандидатов (ссылаются на `PluginRegistry`, `discover(`, `load_recipe`, сборку
блюпринта), каждый в свежем процессе вместе с двумя файлами-жертвами. Красной оказалась ровно одна пара:

```
test_catalog_kind_roundtrip.py => FAILED test_qr_reader_sdk_demo.py::test_blueprint_проходит_check_загрузчика
                                  FAILED test_qr_reader_sdk_dual_demo.py::test_blueprint_проходит_check_загрузчика ...
```

Пара с трассой состояния реестра (временный плагин pytest в scratchpad, в дерево не попал):

```
pytest test_catalog_kind_roundtrip.py test_qr_reader_sdk_demo.py test_qr_reader_sdk_dual_demo.py
  3 failed, 18 passed  (E AssertionError: реестр не знает code_reader_sdk ... get('code_reader_sdk') is None)
трасса после загрязнителя: len=0 has_sdk=False sdk_module_imported=True
```

`sdk_module_imported=True` при `len=0` — прямое доказательство механизма.

## Правка

Файл: `multiprocess_prototype/frontend/forms/tests/test_catalog_kind_roundtrip.py`. Убраны `snapshot = PluginRegistry.snapshot()`,
`try:` и `finally: PluginRegistry.restore(snapshot)`; тело теста сдвинуто на один уровень, проверки не менялись
(снимок полей `catalog_register_fields.txt`, ноль расхождений kind — те же). Docstring переписан под фактическую
причину. Выбор: не откатывать, потому что `discover()` только добавляет, а импортные регистрации монотонны.
Альтернативу «глобальная страховка в корневом conftest» не брал: память предупреждает (замер +29 падений на main).

## Зелёное после правки

Та же пара (`light D`): `21 passed`; трасса: `len=66 has_sdk=True sdk_module_imported=True`.
`ruff check` и `ruff format --check` по файлу — чисто.
Каталоги загрязнителя и жертвы целиком: `multiprocess_prototype/frontend/forms` + `multiprocess_prototype/recipes`
(`heavy D`): `319 passed, 5 skipped`.
Сверка набора падений на `multiprocess_prototype` целиком (`heavy D`): до правки `6 failed, 4557 passed, 32 skipped`,
после — `6 failed, 4557 passed, 32 skipped`; списки FAILED совпадают построчно (`diff` пуст). Новых красных нет.

## Что осталось открытым / ненадёжно

1. **Точная команда «общего прогона» из W2-отчёта мне неизвестна.** Отчёт называет «ядро + forms + recipes + device_hub» и
   «в том же сочетании каталогов». Я воспроизвёл красное парой «загрязнитель + жертва», не полным сочетанием. Что на
   том сочетании красное ушло, не доказано; доказано: механизм, красная пара и зелёная пара.
2. Корневой `pytest` (testpaths) и `pytest multiprocess_prototype` у меня давали ЗЕЛЁНЫЕ QR-тесты и до правки: к
   `frontend/forms` и `recipes` реестр уже наполнен адаптерами/backend-тестами, и снимок загрязнителя содержит sdk.
   Красное появляется лишь когда загрязнитель — ПЕРВЫЙ импортёр плагинов в процессе. Так что красное зависит от
   того, какие каталоги идут раньше; на других сочетаниях его не видно.
3. Класс остаётся хрупким: любой тест, который сам вызывает `discover()` под откатом `restore()`/`clear()`, воспроизводит
   дефект. Я проверил по `git grep` все фикстуры с `PluginRegistry.clear()` — они берут снимок и восстанавливают, но
   если внутри теста впервые импортируется новый `plugin.py`, они стирают его регистрацию так же. Системное
   решение (framework): `discover()` не умеет вернуть регистрацию уже импортированного модуля после `clear()`.
   Не делал: это решение по контракту реестра (вопрос владельцу/teamlead), а не правка в 5 строк.
4. Страховочный побочный эффект правки: загрязнитель теперь оставляет в реестре весь каталог Plugins+Services. Тесты,
   предполагающие пустой/малый реестр, защищены собственными фикстурами `snapshot/clear/restore`; полная сверка наборов
   падений на `multiprocess_prototype` до/после совпала (6 = 6, те же имена). Сравнение сделано на одном
   сочетании каталогов, где QR-красных и до правки не было, — это проверка «ничего не сломал», не повтор красного.
5. Попутные красные, не относящиеся к задаче и не тронутые: `multiprocess_prototype/domain/tests/test_entities_roundtrip.py::
   TestExtrasShorthandDriftGuard::test_every_pick_key_reaches_framework_from_domain`; в `multiprocess_prototype`:
   `backend/state/tests/test_integration.py::TestGenericProcessApp::test_shutdown_cleans_proxy`,
   `frontend/tests/test_app_foundation_names.py::test_boot_foundation_names_from_real_manifest`,
   `frontend/tests/test_gui_process.py::...test_bridge_created_in_init_application_threads`,
   `frontend/tests/test_headless_process.py::...test_drain_worker_is_created_and_started`,
   `frontend/widgets/tabs/processes/tests/test_system_dashboard.py::TestRefresh::test_refresh_pulls_ring_history_into_series`;
   `process_manager_module/tests/test_unapplied_metadata_check.py::test_m10_recipe_set_is_the_known_22` (23 рецепта вместо 22).
   Что из этого красное и на чистом `main`, не проверял (все по `multiprocess_prototype` я видел на ветке; ветка = main + два docs-коммита).
6. Корневой `Services/otel_export/tests` не собирается в этом venv (нет `opentelemetry`): `pytest` без аргументов даёт
   ошибку сбора. Среда, не код.
7. `scripts/machine_gate_tests` внутри окна `heavy` зависает на `test_gate_medium[G4]` (вложенный гейт); из набора я его
   исключал. Среда/гейт, не мой предмет.
