# Handoff dev-transport-2: 4.7d-2a / 4.7d-2b (transport-single-policy)

Ветка `feat/t47d`, worktree `D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles--team-t47d`. План: `plans/transport-single-policy/task-4.7.md`, раздел 4.7d.
Базовый хендофф (хуки, швы, команды): `docs/handoffs/2026-10-02_t47d-dev-transport.md`. Карта: `docs/maps/transport.md`.

## 1. Сделано

- 4.7d-2a — `849bc2ad1`: приёмник (`DataReceiver`) рождает маркеры lag / stale_restore, IPC-маркер идёт мимо коллектора; `meta_from_msg`.
- 4.7d-2b — `7ef022244`: исполнитель (`PipelineExecutor`) пропускает маркер-коллекцию, рождает `stale_exec`; шаги и `plugin_runner` пропускают маркер. Снят strict-xfail в `test_t47d4_marker_policy.py`.

## 2. Чего нет в базовом хендоффе и карте

- Детекция «коллекция из одних маркеров» живёт в ДВУХ местах: приёмник — приватный `DataReceiver._is_marker_collection` (в `data_receiver.py`);
  остальные — `plugin_runner.is_marker_collection` (импортируют `plugin_operation_step.py` и `pipeline_executor.py`). Различие: первый не проверяет тип коллекции.
  Дубль — долг (`not_inspected_marker.py` в FILES 2b не входил). Смешанная коллекция (маркер + обычный item) маркерной НЕ считается.
- Источник маркера везде `self._node` (атрибут `node_name`), не `_node_name`: в брифе было второе имя, в коде его нет.
- `PipelineExecutor._forward_markers(items, t_start)` — `t_start` нужен для `_cycle_metrics.record`. Считает `not_inspected_handled += len(items)`, зовёт `_execute_chain`, затем `_send_results`.
- `stale_markers` строятся в начале `_run_batch` (до `_collect_view_tickets` и до цепочки) и только при `overflow == "every"`: плагин может мутировать/заменить dict входа.
  Pre-chain stale -> `_forward_markers(stale_markers)` (цепочка идёт для плагинов с `accepts_markers`); post-chain stale -> `_send_results(stale_markers)` напрямую, мимо цепочки.
  Ветка `if not valid` стоит ВЫШЕ `if not items`; `note_stale_drops(n_in - 1)` — по входам.
- `test_g5c_executor_drop.py::test_batch_drop_counts_one_per_output_item` теперь пинит 1 (вход 1 -> выход 3) и его докстринг переписан: тест больше не охраняет `note_stale_drops(n_in-1)`, это делает только слепой `test_t47d2_executor.py`.
- Дверь (4.7d-3, `FrameShmMiddleware.strip_data_frame_on_send` / `router_manager`): я её НЕ читал и код не менял. Знаю только по карте §6 и по коммиту `560b03e7f` (слепые RED-тесты двери в `router_module/tests`, не мои). Всё про дверь проверять заново.
- Маркер из `_send_results` несёт служебные ключи `_t_sent_ns` и frame-trace штамп; `data_type` не ставится (кадра нет).
- Ревью-правки 2a/2b мне не передавались. Открытое по 2b: `build_marker` на каждый item каждого батча под every (не мерил), и post-chain маркер не проходит цепочку (спека так велит).

## 3. Радиус 2b (из корня worktree)

    PY="D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python.exe"; PT=multiprocess_framework/modules/process_module/tests
    PYTHONPATH="$PWD" "$PY" -m pytest $PT/test_pipeline_executor*.py $PT/test_pipeline_chain_engine.py $PT/test_g5c_executor_drop.py $PT/test_t47c_gen_check_before_chain.py $PT/test_frame_log_correlation.py $PT/test_t45a_worker_fields.py $PT/test_cycle_metrics.py $PT/test_plugin_levels_defect_quartet_hazards.py $PT/test_data_receiver.py $PT/test_chain_lag_bound.py multiprocess_framework/modules/process_module/plugins multiprocess_framework/modules/router_module/tests/test_frame_ref_gen.py multiprocess_framework/modules/router_module/tests/test_t45c_transport_counters.py -q --tb=short -p no:cacheprovider
    -> 208 passed, 1 xfailed (xfail не мой, источник не выяснял)
    PYTHONPATH="$PWD" "$PY" -m pytest Plugins/control/robot_control/tests -q -p no:cacheprovider   -> 91 passed
    PYTHONPATH="$PWD" "$PY" -m pytest $PT/test_t47d2_executor.py $PT/test_t47d2_receiver.py $PT/test_t47d2a_author.py $PT/test_t47d2b_author.py -q -p no:cacheprovider   -> 37 passed

(Список файлов `test_pipeline_executor*` я получал через `ls | grep`, не глобом; результат тот же набор.)
