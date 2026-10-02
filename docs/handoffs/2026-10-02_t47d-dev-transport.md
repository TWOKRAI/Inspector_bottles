# Handoff dev-transport: трек 4.7d (transport-single-policy)

Ветка `feat/t47d`, worktree `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles--team-t47d`.
План: `plans/transport-single-policy/task-4.7.md`, раздел 4.7d. Состояние на SHA 751bbe24d (+ этот файл).

## 1. Сделано

- **4.7d-1** — `c008d5973` (после rebase; до него `65424a7a5`) и `9d58ffddc` (гард дрейфа extras-shorthand).
  Ключ рецепта `overflow: latest|every` (extras-only, `GenericProcessConfig.build()` пишет его только при `every`),
  чистый модуль `router_module/middleware/not_inspected_marker.py` (`build_marker`, `is_marker`), `DataReceiver` и
  `PipelineExecutor` принимают kwarg `overflow` и отдают read-only property. Поведения под `every` нет.
- **4.7d-4** — `751bbe24d`. `RobotControlPlugin`: `accepts_markers = True`, регистр `not_inspected_action reject|pass`,
  ветка маркера первой в `process` (`_process_marker`), счётчик `total_not_inspected`. Лид убил 13 из 13 инъекций,
  ревью идёт отдельно, код не менять.

## 2. Чего нет в docs/maps/transport.md

- Ключ `overflow` и ему подобные доезжают до процесса только по цепочке: рецепт `extras` -> `blueprint.as_generic_config`
  (`_pick`) -> `GenericProcessConfig.build()` -> `proc_dict["config"]` -> `GenericProcess._init_data_pipeline`. Любое звено,
  не названное поимённо, молча теряет ключ. Плоский `overflow: every` у процесса сворачивается в `metadata` и нем;
  поэтому такие ключи вписаны в `_FLAT_FORM_NOT_ACCEPTED` в `multiprocess_prototype/domain/tests/test_entities_roundtrip.py`.
  Новый extras-only ключ = правка и там, и в ожидаемом наборе `test_extras_only_pick_keys_are_named`.
- Ошибка pydantic-`Literal` не несёт имя процесса, поэтому в `as_generic_config` проверка явная и стоит ДО конструктора.
- `GenericProcessConfig.build()` обязан вычищать ключи со значением по умолчанию (golden-снапшоты
  `multiprocess_prototype/backend/tests/test_build_characterization.py`), иначе снапшоты меняются.
- Счётчики `RobotControlPlugin` живут в `configure()`, а не в `__init__`; сброс и `get_stats` правятся отдельно.
- Маркер не должен трогать `_rejecting`, `_total_rejected`, `_total_inspected` и вердикт-документы в ЛЮБОМ режиме
  (даже при `enabled=False`, где обычный item фронт сбрасывает).
- Хуки коммита: `ruff-format` переформатирует ВЕСЬ тронутый файл (так раздулся `registers.py`) и роняет первый коммит —
  надо снова сделать `git add` и повторить коммит. Хук `append session log` сам кладёт `docs/sessions/<дата>.md` в
  коммит. Предупреждения "LF will be replaced by CRLF" безвредны.
- Гейт SubagentStop печатает "pytest cannot be imported": у дефолтного `python` в worktree нет pytest. Это среда, не
  красные тесты; прогон через `$PY` общего venv зелёный. `uv sync` в worktree брифом запрещён.
- Известные красные не наши: `test_socket_channel_hol_*` x3 в `router_module/tests` (проверено 2026-10-02).

## 3. Тестовые швы, которые я переиспользовал

- `_wired_process(app_cfg)` из `process_module/tests/test_t47d1_overflow_wiring.py` — настоящий `_init_data_pipeline` на
  заглушке процесса (`object.__new__`), с настоящими `DataReceiver` и `PipelineExecutor`; для авторских тестов 4.7d-1.
- `_plugin()`, `_marker()`, `_defect_item()` из `Plugins/control/robot_control/tests/test_t47d4_marker_policy.py` —
  авторские тесты 4.7d-4 импортируют их оттуда; переименование там сломает `test_t47d4_author.py`.
- Любой вызов, способный блокироваться (`reject_delay_ms`, исполнитель в потоке), гонять в daemon-потоке с `join`-дедлайном.

## 4. Следующий шаг: 4.7d-2

Валидация портов в `plugin_runner` по плану (раздел 4.7d-2, там же minors ревью 4.7d-1): коллекция-маркер обходит
звенья без `accepts_markers` и доходит до звена с `accepts_markers = True`. Слепые RED-тесты `test_t47d2_*` (32 шт.)
будут в ветке; код под них писать без правки тестов. Ссылка на 4.7d-4: strict-xfail
`test_marker_collection_skips_blob_detector_and_reaches_robot_control` в `test_t47d4_marker_policy.py` после 4.7d-2
должен стать XPASS (strict -> упадёт): сообщить лиду, чтобы снял маркер xfail. Вне зоны: `FrameShmMiddleware` и
`router_manager` (4.7d-3), README/STATUS/ADR (4.7d-5).

## 5. Команды (из корня worktree)

    PY="D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python.exe"
    PYTHONPATH="$PWD" "$PY" -c "import multiprocess_framework; print(multiprocess_framework.__file__)"   # внутри worktree
    PYTHONPATH="$PWD" "$PY" -m pytest <файлы> -q --tb=short -p no:cacheprovider
    PYTHONPATH="$PWD" "$PY" -m pytest multiprocess_framework/modules/process_module/tests multiprocess_framework/modules/process_manager_module/tests multiprocess_framework/modules/router_module/tests -q --tb=line -p no:cacheprovider   # ~4 мин, ждать 3 известных красных
    PYTHONPATH="$PWD" "$PY" -m pytest Plugins/control/robot_control/tests multiprocess_prototype/domain/tests/test_entities_roundtrip.py multiprocess_prototype/backend/tests/test_build_characterization.py -q -p no:cacheprovider
    "$PY" -m ruff check -q <пути>; "$PY" -m ruff format --check <пути>
