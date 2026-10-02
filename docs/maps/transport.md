# Карта подсистемы transport — для 4.7d (правило переполнения, маркер `not_inspected`)

Автор: `know-transport`. Карта ОБНОВЛЕНА 2026-10-02 под HEAD `671660688` (ветка `feat/t47d`, перебазирована на main `d60bd59ad`: 4.7b влита; в ветке 4.7d-1 и 4.7d-4). Первоначальный базис был `49da43dc2`; номера строк §0-§6 пересчитаны под HEAD, §7-§8 частично (см. пометки). Тексты `49da43dc2`/`23f872bce` ниже — исторические. Ссылки `файл:строка` — по этому дереву. Счётчики вызывающих и тестов — грепом, тесты считаны по `def test_` (параметризация не раскрыта). Семантический поиск (qex) не использовался: Ollama недоступна.

Пути сокращены: `PM` = `multiprocess_framework/modules/process_module`, `RM` = `multiprocess_framework/modules/router_module`, `PMM` = `multiprocess_framework/modules/process_manager_module`.

## 0. Поток данных одного узла (кто в каком потоке)

| Поток | Что делает | Пишет |
|---|---|---|
| receiver (`DataReceiver.run_loop`, PM/generic/data_receiver.py:332) | receive → `restore_frame` → `_build_item` → collector → `on_items_ready` → `chain_queue` | единственный производитель `chain_queue` (коллектор и `check_timeouts` зовутся из этого же потока, :344, :396) |
| executor (`PipelineExecutor.run_loop`, pipeline_executor.py:167) | `chain_queue.get` → `_run_batch` → `_send_results` → router.send → middleware `strip_data_frame_on_send` (дверь) | `note_stale_drops`, дверные счётчики, release-тикеты |
| source producers (`SourceProducer`, generic_process.py:334) | `produce()` → send → та же дверь | выход источника не несёт `_shm_views`, дверью по входам не дропается |

Порядок «рождения» дропов по ходу кадра: restore (receiver) → bound (receiver) → pre-chain (executor) → post-chain (executor) → дверь (executor, router.send).
Конструкция data-плоскости: `generic_process.py:_init_data_pipeline` (:139). `FrameShmMiddleware` строится всегда, когда есть хоть один плагин (:222); `DataReceiver` и `PipelineExecutor` — только если есть processing-плагины (:262). У source-only процесса `receiver.overflow`/`executor.overflow` не существует.

### 0.1 Что поменялось в файлах §1-§3 с 49da43dc2 по HEAD 671660688

| Файл | Изменение | Источник |
|---|---|---|
| `data_receiver.py` | kwarg `overflow="latest"` в `__init__` :62, поле `_overflow` :93, read-only property `overflow` :125; поведения нет. Сдвиг строк +7 после :122 | 4.7d-1 |
| `pipeline_executor.py` | kwarg `overflow` :55, поле :64, property :139; поведения нет. Сдвиг: +2 для :63-135, +7 после :136 | 4.7d-1 |
| `plugin_operation_step.py`, `plugin_runner.py` | НЕ менялись (номера строк прежние; `FW_PORT_VALIDATE` :153-159 и `accepts_markers` по-прежнему НЕ читаются шагом: `getattr(plugin, "accepts_markers", False)` ещё не написан — это 4.7d-2) | - |
| `plugins/base.py` | +2 строки в docstring `process`: вход — read-only view, живёт только внутри `process()` (4.7b); `accepts_markers` в базе по-прежнему нет | 4.7b |
| `generic_process.py` | `overflow = app_cfg.get("overflow", "latest")` :153, передача в `DataReceiver` :281 и `PipelineExecutor` :300; в `FrameShmMiddleware` НЕ передаётся | 4.7d-1 |
| `generic_process_config.py` | поле `overflow: Literal["latest","every"]` :202-211; в `build()` `pop` при не-`every` :314-316 | 4.7d-1 |
| `blueprint.py` | `_pick("overflow")` :322 + явный `ValueError` с именем процесса :323-324, в kwargs только при `every` :325-326 | 4.7d-1 |
| executor-путь restore/stale | 4.7b не менял логику `_run_batch`; изменилось только то, что `_shm_views` теперь есть у КАЖДОГО item с кадром (раньше только при `FW_SHM_ZERO_COPY`), т.е. pre/post-проверки view выполняются всегда | 4.7b |
| `frame_saver` (Plugins/io) | копирует item при буферизации (`_owned`) — read-only view валиден только в `process()` | 4.7b |

## 1. `process_module/generic/data_receiver.py` (452 строки в HEAD)

| Символ | Строка | Заметка |
|---|---|---|
| `_StampedBatch(list)`, слот `enq_ts` | :24, :31 | метка ставится в `on_items_ready` :304-305; исполнитель читает `getattr(items, "enq_ts")` (pipeline_executor.py:199). Маркер-коллекция, поставленная вне `on_items_ready`, метки не имеет (не ошибка: `queue_wait_ms` просто не обновится) |
| `__init__` | :47 | kwargs: `max_lag_items`, `inflight_budget`, `ipc_depth_fn`, `node_name`, `clock`. Сюда добавится `overflow="latest"` |
| `get_cycle_metrics` | :129-148 | база CycleMetricsRecorder + `transport_ms` (всегда) + `ipc_queue_depth` (если читали) + `transit_over_budget` (только при `inflight_budget>0`) + `perf_probes` (флаг). **`lag_dropped_total` в нём НЕТ** |
| `_bound_lag` | :206-264 | `chain.mutex` :245; `pending = chain.queue` (deque) :246; `frame_idx` :247; `excess` :248; `del pending[i]` с конца :250-251; `not_full.notify` :255; `put_nowait` :257; `queue.Full` → `False` :258-262 |
| `_is_frame_collection` | :266-269 | кадровая = хоть один item с `_shm_views` или `frame`. Маркер (без этих ключей) кадровой не считается |
| `_note_lag_drops` | :271-286 | `_lag_dropped_total += dropped` (число коллекций, не items); WARNING раз в 5 с |
| `lag_dropped_total` (property) | :288-291 | единственный выход счётчика; в `get_cycle_metrics` и в телеметрию не идёт |
| `on_items_ready` | :293-330 | `_StampedBatch` :304; bound :306; `put(timeout=lag_threshold)` :309; при shutdown `stop_event` → дроп (:322-325, вне формулы приёмки) |
| `run_loop` | :332-406 | `restore_frame` :383; `_is_shm_dropped` → `continue` :386-387 (ветка маркера 4.7d); `_note_transport` :390; `_build_item` :393; `collector.on_item` :403; `_cycle_metrics.record` :406 |
| `_is_shm_dropped` | :408-412 | читает `msg["data"][_shm_dropped]` |
| `_build_item` | :414-447 | `item = dict(msg["data"])` + `frame` из `msg` + msg-уровневые `camera_id, seq_id, total_regions, region_name, frame_id, timestamp, sender, data_type` **если ключа ещё нет в item** |

Вызывающие (грепом, не тесты): `run_loop` — worker target `generic_process.py:307`; `on_items_ready` — `collector._on_ready` `generic_process.py:284`; `_bound_lag` — только `on_items_ready:306`; `get_cycle_metrics` — `worker_module/core/worker_manager.py:329` через `target.__self__`, результат `status.update(cycle)` :341 (все ключи попадают в статус воркера).
Счётчики: `lag_dropped_total` (prop), `overload_events` (:450), `transit_over_budget`, `ipc_queue_depth`, `transport_ms`.
Тесты: `test_data_receiver.py` 10, `test_chain_lag_bound.py` 12, `test_t47c_bound_hazards.py` 5, `test_t47c_frame_aware_bound.py` 6, `test_frame_ref_atomic_item.py` 2, `test_claim_check_any_key_receive.py` 8, `test_t45d_transport_ms.py` 9, `test_cycle_metrics.py` 13 (все в `PM/tests/`); `Plugins/_shared/fanin/tests/test_t47a_join_views.py` 6.
Ловушки:
- Бюджет под mutex: замена `pending[i] = markers` допустима только внутри `with chain.mutex` (:245); длина очереди не меняется, поэтому `not_full.notify` для замены не нужен.
- `lag_dropped_items` считать `len(coll)` ДО замены/удаления; `lag_dropped_total` остаётся «коллекций» (:275).
- Ветка restore-дропа (:386): к этому моменту `_note_transport` ещё НЕ вызвана — `_t_sent_ns` лежит в `msg["data"]`, `_shm_refs` и `_shm_dropped` тоже. Метаданные маркера (`trace_id`, `capture_ts`, `frame_id`, `camera_id`) берутся из `msg["data"]`/`msg` как в `_build_item`.
- `_build_item` добавляет к item msg-уровневые ключи (`sender` ставит `process_communication.py:211` всегда) → пришедший по IPC маркер после `_build_item` НЕ равен «ровно ключам `build_marker`». `is_marker` надо проверять на `data` (до `_build_item`) или принять, что в item добавится `sender`.
- `run_loop` в ветке `continue` по `_shm_dropped` не вызывает `_cycle_metrics.record` (:406) — дропнутые сообщения в `effective_hz` не входят; при `every` маркер, отправленный `on_items_ready`, тоже не будет записан, если не добавить `record`.
- `test_cycle_metrics.py:210` фиксирует ТОЧНЫЙ набор ключей приёмника (`_RECEIVER_KEYS`, :28): при `max_lag_items=0` и `latest` новых ключей быть не должно (так и в спеке).

## 2. `process_module/generic/pipeline_executor.py` (491 строка в HEAD)

| Символ | Строка | Заметка |
|---|---|---|
| `__init__` | :41 | kwargs: `plugins, chain_targets, shm_middleware, send_fn, max_consecutive_fails, auto_reset_sec, critical_plugins, node_name, plugin_runner`. Сюда `overflow="latest"` |
| breaker-состояние | :77-79 | `_consecutive_fails`, `_bypassed`, `_bypassed_since` |
| `_runnable_steps` (по шагу на плагин) | :85-97 | `PluginOperationStep(on_success=_on_plugin_success, on_fail=_on_plugin_fail)`, `on_error="skip"` :94 |
| `_suspect_step` | :101-105 | один `SuspectTagStep` на все позиции |
| `get_cycle_metrics` | :156-165 | база + `queue_wait_ms`. Счётчиков дропов нет |
| `run_loop` | :167-223 | `chain_queue.get(0.05)` :189; EMA `queue_wait_ms` по `enq_ts` :199-206; `_run_batch` внутри `log_correlation(items)` :219-220 |
| `_run_batch` | :225-287 | см. таблицу ниже |
| `_execute_chain` | :289-312 | перестраивает `_active_runnable` при `_steps_dirty` :308-310; `execute(items, None)` :311 |
| `_collect_view_tickets` | :314-329 | тикеты = ссылки из `item["_shm_views"]` входных items; пусто без middleware |
| `_attach_batch_views` | :331-347 | пишет в КАЖДЫЙ выход новый список views (свои + билеты батча) |
| `_frame_views_valid` | :349-354 | `all(shm.frame_view_valid(ref))`; первый же stale → reader +1 и стоп |
| `_accumulate_releases` / `_flush_releases` | :367, :384 | только при `loan_protocol_enabled` |
| `_build_active_steps` | :403-419 | критический bypassed → `SuspectTagStep` на его позиции |
| `_on_plugin_success` / `_on_plugin_fail` | :421, :425 | `consecutive_fails` :423, :432-433; bypass при `fails >= max_fails` :435-438 |
| `_send_results` | :444-474 | `item.pop("target")` :451; `data_type` для кадра :457-458; `frame_trace.stamp_send` :461; `item["_t_sent_ns"]` :464; **msg на каждый target с `"data": item` — один и тот же dict** :468-474 |

`_run_batch` по шагам (порядок несущий):

| # | Строки | Что |
|---|---|---|
| 1 | :237 | `view_tickets = _collect_view_tickets(items)` — ДО цепочки (плагин может заменить dict) |
| 2 | :247-252 | pre-chain: `view_tickets and not valid` → `note_stale_drops(len(items)-1)` если `len>1` :248-249; release :250; `record` :251; `return` :252. Единица — ВХОДНЫЕ items (reader +1 внутри `_frame_views_valid`) |
| 3 | :255 | `_execute_chain(items)` |
| 4 | :261 | `valid = _frame_views_valid(view_tickets)` — reader +1 при stale происходит ЗДЕСЬ |
| 5 | :262 | `_accumulate_releases` (в любом исходе) |
| 6 | :265-267 | `if not items: record; return` — пустой выход выходит ДО ветки по `valid` |
| 7 | :269-275 | `if not valid`: `note_stale_drops(len(items)-1)` (items = ВЫХОДЫ) :272-273; `return` |
| 8 | :280-281 | `_attach_batch_views` |
| 9 | :284 | `_send_results` |

Вызывающие: `_run_batch` — только `run_loop:220`; `PipelineExecutor(...)` — только `generic_process.py:287`; `note_stale_drops` — только :249, :273; `bind_queue/run` — `generic_process.py:313-316`.
Счётчики: `queue_wait_ms`; прочее в `shm`. Новые по спеке: `not_inspected_stale_exec` (при `every`), `not_inspected_handled` (всегда).
Тесты: `test_pipeline_executor.py` 10, `test_pipeline_executor_characterization.py` 14, `test_pipeline_chain_engine.py` 4, `test_g5c_executor_drop.py` 13, `test_t47c_gen_check_before_chain.py` 1, `test_frame_log_correlation.py` 12, `test_t45a_worker_fields.py` 16, `test_cycle_metrics.py` 13, `RM/tests/test_frame_ref_gen.py` 12, `RM/tests/test_t45c_transport_counters.py` 9 (используют `_run_batch`/`_send_results`: 4+3+5+1+1+1+1 файлов).
Ловушки:
- Менять существующий тест: `test_g5c_executor_drop.py:245 test_batch_drop_counts_one_per_output_item` фиксирует 1 вход → 3 выхода = `frame_stale_drops == 3`. После 4.7d-2 станет 1 — тест надо переписать намеренно (это спека, не регрессия).
- `test_cycle_metrics.py:164` фиксирует точный набор ключей исполнителя (`_EXECUTOR_KEYS`, :26): `not_inspected_handled` «всегда» ломает его — обновить тест.
- Общий `item`-dict при fan-out (:468-474): `_send_results` мутирует item (`pop target`, `_t_sent_ns`, штампы) — тот же объект идёт ко всем целям, потому маркер в двери меняется на месте.
- Под `FW_PORT_VALIDATE=1` (`plugin_runner.py:153-159`, `validate_items_against_ports` бросает `PortValidationError` при отсутствии обязательного порта, `process_module/plugins/port.py:187-192`) плагин с `accepts_markers=True` и обязательными портами `frame`/`detections` (как `robot_control`) на маркере упадёт в `except` шага → `on_fail` → `consecutive_fails` растёт. Для 4.7d-4 важно: или пропускать валидацию для маркера, или помечать порты optional. Решение — лиду.
- `ChainRunnable.execute` в `_execute_chain` проходит ВСЕ активные шаги; пропуск маркера обеспечивают сами шаги (спека 4.7d-2 п.5), а не `_execute_chain`.
- `_check_auto_reset` и release-флаш крутятся в том же потоке; маркер-ветка `_forward_markers` не должна пропускать `_accumulate_releases` (у маркера тикетов нет, no-op).

## 3. `plugin_operation_step.py` (120 строк) и breaker

| Символ | Строка | Заметка |
|---|---|---|
| `PipelineStepNode` | :36 | дескриптор для `RunnableStep` |
| `PluginOperationStep.execute` | :66-86 | `if not items: return items` :74; `runner.call_process` :77; `except` → `item["inspection_status"]="not_inspected"` на всех items :81-82, `on_fail` :83, `return items` :84; успех → `on_success` :85, `return outputs` :86 |
| `SuspectTagStep.execute` | :108-114 | `item["inspection_status"]="suspect"` :112-113; пустой батч не тегирует |
| breaker (`consecutive_fails`, `on_success`/`on_fail`) | живёт в executor :77-79, :421-438 | шаги только зовут колбэки; для маркер-коллекции колбэки НЕ звать |

Вызывающие: `PluginOperationStep(` — `pipeline_executor.py:88`; `SuspectTagStep()` — :103; других нет.
Единственные записи `inspection_status` вне тестов: `plugin_operation_step.py:82`, `:113` (остальные упоминания — комментарии/docstring). Читателей в коде нет.
Тесты: `test_plugin_levels_defect_quartet_hazards.py` 2, `test_pipeline_executor.py` (:159, :180, :200 читают тег), `test_pipeline_executor_characterization.py` (:190-222, :287-300).
Ловушки: `SuspectTagStep` пишет `suspect`, а не `not_inspected` (спека называет его в одном ряду с «сбоем плагина» — тег `not_inspected` ставит только `PluginOperationStep`). Тег `not_inspected` от сбоя плагина идёт у item с картинкой; `is_marker` различает это по `overflow_marker is True`. `accepts_markers` нигде в коде не объявлен (grep по репо пуст) — читать через `getattr(plugin, "accepts_markers", False)`; базовый класс `ProcessModulePlugin` (`PM/plugins/base.py:1251`) не в списке файлов спеки.

## 4. `generic_process.py` и `generic_process_config.py`

`_init_data_pipeline` (`generic_process.py:139-359`), чтение ключей из `app_cfg = self.get_config("config")` :141:

| Что строится | Строки | Откуда ключи |
|---|---|---|
| `max_lag_items` | :151 | `app_cfg["chain_max_lag_items"]` (дефолт 0) |
| `inflight_budget` | :155 | `app_cfg["inflight_budget"]` |
| `FrameShmMiddleware(memory_manager, owner=self.name, slot="output_frames", coll=frame_ring_depth, log_error, num_consumers)` | :224-231 | `frame_ring_depth` :209; `copy_out_targets` :217. Регистрация: `router.add_send_middleware(shm.strip_data_frame_on_send)` :237, `register_frame_middleware` :240 |
| `chain_queue = Queue(maxsize=queue_size)` | :261 | `queue_size` (64) |
| `DataReceiver(...)` | :268-282 | `max_lag_items`, `inflight_budget`, `ipc_depth_fn`, `node_name=self.name`; `collector._on_ready = receiver.on_items_ready` :284 |
| `PipelineExecutor(...)` | :287-301 | `max_fails`, `auto_reset`, `critical`; `node_name=self.name` |

Другие места, строящие `FrameShmMiddleware(`: `PM/commands/builtin_commands.py:3765` (wire.configure, путь `on_send`), `multiprocess_prototype/frontend/process.py:51` (GUI-приёмник). Новый kwarg `overflow` для них — дефолт `"latest"`.

`generic_process_config.py`: класс :65; `frame_ring_depth` :152; `chain_max_lag_items` :189-200; `build()` :294-314. `ProcessLaunchConfig.build` (`PM/configs/process_launch_config.py:147`) делает `model_dump()` — КАЖДОЕ typed-поле попадает в `proc_dict["config"]`. Поэтому «`overflow` только при `every`» требует явного `pop` при `latest` по образцу :308-313 (`inflight_budget`, `cv_threads`). `chain_max_lag_items` НЕ выпиливается (всегда в config, даже 0).

Путь `chain_max_lag_items` (прецедент для `overflow`): рецепт `extras` → `_pick` `blueprint.py:317` → `base_kwargs` только если truthy `:334-335` (`int()`) → typed-поле `GenericProcessConfig` → `build()` → `config["chain_max_lag_items"]` → `generic_process.py:151` → `DataReceiver(max_lag_items=)` :286. Дополнительно топология ПЕРЕПИСЫВАЕТ значение: `PMM/topology/blueprint.py:_apply_inflight_budgets` :587-631 (`cfg.chain_max_lag_items = …` :625) для каждого получателя за кольцом писателя (дефолт `min(2, B-1)`). Следствие: `lag_dropped_items` активен у многих процессов без ключа в рецепте.
Тесты конфигурации: `PM/tests/test_blueprint_extras.py` 22, `PMM/tests/test_t47c_blueprint_wiring.py` 10, `PMM/tests/test_cv_threads.py` 11, `PMM/tests/test_t47c_hazards.py` 11, `PM/tests/test_collector_legacy_alias.py` 20, `PM/tests/test_plugin_config_extra.py` 14, `PM/tests/test_protected_propagation.py` 4.

## 5. `process_manager_module/topology/blueprint.py`

| Символ | Строка | Заметка |
|---|---|---|
| `ProcessConfig` typed-поля | :80-209 | ТОЛЬКО `chain_targets`, `source_target_fps`, `collector`, `io_peek`, `telemetry` (+ `extras`, `metadata`, служебные). `frame_ring_depth`, `chain_max_lag_items`, `copy_out_targets`, `cv_threads`, `data_queue_maxsize` — typed-полей НЕТ, живут только в `extras` |
| `as_generic_config` | :245-354 | вызывается только `build_configs:580` (+тесты); в HEAD есть один `raise ValueError` для `overflow` :323-324 (4.7d-1) |
| `_pick(key, default)` | :281-291 | `key in model_fields_set` → `getattr(self,key)` (+ warning при конфликте с extras :285); иначе `extras.get(key, default)` |
| `chain_max_lag_items` pick/set | :317, :331-332 | |
| `build_configs` | :572-582 | `_apply_inflight_budgets` :581 |
| ошибки «с именем процесса» | `PMM/topology/inflight.py:51-54`, `:89-92`, `:98` | формат `процесс '{process}': …`, поднимаются из `_apply_inflight_budgets` :622-628, а не из `as_generic_config` |

Ловушка (СНЯТА в HEAD, 4.7d-1): `overflow` проверяется явно ДО `GenericProcessConfig` (`blueprint.py:322-324`), текст несёт имя процесса; `Literal` в `GenericProcessConfig` остаётся второй линией (pydantic `ValidationError` — подкласс `ValueError`, без имени процесса).

## 6. `router_module/middleware/frame_shm_middleware.py` (1300 строк) — основание HEAD 671660688 (после 4.7b, d60bd59ad)

Константы: `SHM_REFS_KEY` :59, `FRAME_KEY` :61, `SHM_VIEWS_KEY` :67, `SHM_DROPPED_KEY` :68; новый `_ref_key(ref)` :71 = `(owner, slot, idx)` (без owner — `(name,)`). `middleware/__init__.py` по-прежнему экспортирует только `FrameShmMiddleware`; рядом лежит `not_inspected_marker.py` (4.7d-1: `build_marker`, `is_marker`, `MARKER_REASONS`; импортов `process_module` в нём нет). Параметра `overflow` у `FrameShmMiddleware` ещё НЕТ (это 4.7d-3), `grep overflow` по файлу пуст.

**Что изменила 4.7b в этом файле (было -> стало):**
- Удалены флаги и kwargs `cache_shm_handles`, `owner_incarnation`, `handle_cache_cap`, `zero_copy`, константа `_HANDLE_CACHE_CAP`, поля `_zero_copy`, `_cache_shm_handles`, `_owner_incarnation`; `resolve` по `FW_SHM_ZERO_COPY/HANDLE_CACHE/OWNER_INCARNATION` -> `KeyError`. Конструктор теперь: `memory_manager, owner, slot, coll, log_error, loan_protocol, num_consumers, pool, reader` (:342). Reader строится `ShmFrameReader(log=...)` :416.
- `_read_ref` :956: `view = allow_view` (раньше `allow_view and self._zero_copy`) — конвейер (`restore_frame`) ВСЕГДА получает read-only view, у любого item с кадром есть `_shm_views`; `on_receive` (`allow_view=False`) получает копию. В reader уходит `key=_ref_key(ref)`.
- `frame_view_valid` :728-736 передаёт `key=_ref_key(ref)`; reader сверяет и имя сегмента под ключом (смена имени = realloc писателя -> drop).
- Логика дропов, дверь (`strip_and_write`, `strip_data_frame_on_send`, `_inputs_still_valid`) и счётчики не менялись — только сдвиг строк на -29...-31.
- Reader (`shared_resources_module/memory/reader/shm_frame_reader.py`): кэш всегда включён, ключ `(owner, slot, idx)`, новое имя под ключом отправляет старый handle в отставку; `view_valid` :195 (дроп `_stale_drops += 1` :210 на: gen<0, нет handle, имя в кэше != имени ссылки, поколение разошлось); `_read_at_generation` :122 (stale :124 до чтения, torn :130 после); новые `deferred_closes`, `close_errors`.
- Имя сегмента ВСЕГДА `{base}_{owner}_{pid}_{inc}_{idx}` (`memory/platform/shm.py`); при realloc ключа старый сегмент отвязывается сразу.

**C7 (realloc ключа, сообщение в полёте).** Писатель при росте кольца пересоздаёт сегмент под НОВЫМ именем, старый отвязан. Сообщение со старой ссылкой на стороне reader'а: `open` -> `FileNotFoundError` -> `_read_ref` :975 `_stale_unlinked_drops += 1` -> `None` -> `_restore_refs` снимает уже восстановленное, `restore_frame` ставит `_shm_dropped` :951 -> в приёмнике это ветка `_is_shm_dropped` (`data_receiver.py:386`) = маркер `stale_restore`. Счётчик: `frame_stale_drops` (слагаемое `_stale_unlinked_drops`, :581), НЕ `frame_restore_failures` и НЕ `torn`. Подтверждено тестом `RM/tests/test_claim_check_any_key.py::_realloc_scenario` (`stale_m1 == 1`, `got1 is None` для роста ЛЮБОГО ключа, коммит `9f6e989a3`). Если старое имя ещё открыто в кэше reader'а (view жив, сегмент отставлен), executor-сторона `view_valid` даёт `_stale_drops` (имя не совпало) — это pre-/post-chain stale, не restore. Развилку «какой из двух путей на каком окне» я не прогонял, только прочитал код.

| Символ | Строка | Заметка |
|---|---|---|
| `__init__` | :342-460 | `_owner` :355; `_coll` :361; счётчики :367 (`frame_boundary_crossings`), :369 (`frame_pickle_fallbacks`), :389 (`_restore_fail_count`), :393 (`_stale_unlinked_drops`), :398 (`_stale_batch_drops`); `_last_loan_exhausted` :443. Сюда `overflow="latest"` (4.7d-3) |
| `frame_stale_drops` | :575-581 | `reader.stale_drops + _stale_unlinked_drops + _stale_batch_drops` |
| `note_stale_drops(n)` | :583-588 | `n<=0` — no-op; plain int без lock |
| `frame_restore_failures` | :629-633 | `= _restore_fail_count` (сбой открытия/битая ссылка; stale и отвязанный сегмент сюда НЕ входят) |
| `frame_torn_reads` | :636-640 | `reader.torn_reads` (`shm_frame_reader.py:130`, только `read_ref`) |
| `frame_handle_cache_size` | :643-649 | проекция `reader.cache_size` |
| `frame_view_valid` | :728-736 | -> `reader.view_valid(..., key=_ref_key(ref))` (бьёт ТОЛЬКО `_stale_drops`, `shm_frame_reader.py:210`; torn там нет) |
| `_inputs_still_valid` | :831-840 | цикл по `item["_shm_views"]`, стоп на первом stale -> +1 на item |
| `restore_frame` | :925-954 | при провале ссылки `data["_shm_dropped"]=True` :951 |
| `_read_ref` | :956-998 | `FileNotFoundError` -> `_stale_unlinked_drops` :975; иной сбой/битая ссылка -> `_restore_fail_count` :991 |
| `_restore_refs` | :1000-1034 | атомарно: стоп на первой `None`, снять восстановленное :1027-1029 |
| `_views_foreign_memory` | :1049-1061 | корень `.base` не ndarray = чужая память (4.7a) |
| `_copy_inline_views` | :1064-1080 | `True`, если что-то скопировано |
| `strip_and_write` | :1082-1149 | ранний выход по `_shm_dropped` :1116-1117; fan-out replay :1118-1121; `has_views` :1123; `touched_foreign` :1125; запись :1127; loan-исчерпание :1131-1132; **единственное место `_shm_dropped` на двери: :1142-1145** (`touched_foreign and not _inputs_still_valid` :1143, метка :1144); `pop(SHM_VIEWS_KEY)` :1148 |
| `strip_data_frame_on_send` | :1159-1192 | guard `type=="data"` :1179; `strip_and_write(data)` :1183; loan-исчерпание -> `None` :1186-1187; `_shm_dropped` -> `None` :1190-1191 |
| `on_send` / `on_receive` | :1212, :1280 | wire.configure / GUI-путь; маркеры 4.7d их не касаются |

Вызывающие: `strip_data_frame_on_send` — только регистрация `generic_process.py:237` (router зовёт на каждый send, `router_manager.py:_do_send` :541-546; `None` -> `middleware_dropped`); `note_stale_drops` — executor :249, :273; `restore_frame` — `data_receiver.py:383`; `frame_stale_drops/torn/restore_failures` — `router_manager.py:1787-1798` -> `heartbeat/telemetry.py:258-295` (`state.shm.*`).
Тесты (4.7b правила около 20 файлов): `RM/tests/test_frame_shm_middleware.py` 38, `test_frame_ref_gen.py` 12, `test_frame_ref_hazards.py` 17, `test_g5d_loan.py` 22, `test_t47a_door_hazards.py` 10, `test_t47a_door_owndata.py` 10, `test_g5c_stale_recheck.py` 3, `test_t45c_transport_counters.py` 9, `test_claim_check_any_key.py` 12, новые `test_t47b2_ref_key_without_owner.py`, `test_t47d1_marker_contract.py`; `shared_resources_module/memory/tests/test_t47b2_hazards.py` (новый), `test_frame_reader.py`, `test_seqlock.py`; `PM/tests/test_g5c_executor_drop.py` 13, `test_process_io_shm_contract.py` 6.
Ловушки (для 4.7d-3):
- `door_drops` инкрементить на :1144 (первый раз), НЕ в `strip_data_frame_on_send`: он выполняется на каждую цель, а повтор fan-out выходит из `strip_and_write` на :1116.
- Замена содержимого `msg["data"]` на маркер обязана быть на месте в общем dict (`clear()+update()`): `_send_results` создаёт msg на каждую цель с ОДНИМ объектом `item` (`pipeline_executor.py:468-474`). Перепривязка `msg["data"] = marker` ломает fan-out: вторая цель увидит исходный dict с `_shm_dropped` и родит второй маркер (или получит `None`).
- К моменту :1144 в кольцо уже могла быть записана ссылка (`_write_item_arrays` :1127): `item["_shm_refs"]` с собственными ссылками остаётся в item; маркер её не несёт, слот брошен (при loan-протоколе refcount никто не снимет — НЕ проверено, существует и сегодня для `latest`).
- Замена `data` стирает `_t_sent_ns` и frame-trace штампы — у получателя `transport_ms` для этого сообщения не снимется (мелочь).
- После 4.7b у каждого item с кадром на входе есть `_shm_views` (view всегда); дверь проверяет входы только при `touched_foreign` (4.7a) — это не изменилось.
- `_last_loan_exhausted` — разделяемый атрибут между потоками источника/исполнителя (:443, :1115); дропы по нему в формулу не входят (спека).
- Счётчики двери — plain int; пишущий поток двери — executor (источник views не несёт); для `not_inspected_door` lock не нужен, но это допущение.

## 7. `Plugins/control/robot_control/plugin.py` (405 строк на 49da43dc2; таблица ниже — ДО 4.7d-4)

**Дельта HEAD 671660688 (4.7d-4 влита):** `accepts_markers = True` :68; импорт `is_marker` :47; `process` :136 — первая ветка `if is_marker(item): return self._process_marker(item)` :152, ДО `self._total_inspected += 1` (:155); `_process_marker`: `_total_not_inspected += 1`, при `enabled=False` -> `pass/disabled` + `origin`/`source`, иначе `action = _reg.not_inspected_action` (регистр, дефолт reject), задержка `reject_delay_ms` только для reject, `_write_unit_event(..., decisive=False)` пишется (текст «не проверен»), вердикт-документ и `_rejecting` не трогаются; `cmd_get_stats` несёт `total_not_inspected`. Вопросы лиду по этому файлу из первой версии карты сняты реализацией. Строки таблицы ниже — старые, перепроверять grep'ом.

| Символ | Строка | Заметка |
|---|---|---|
| `process` (`@for_each`) | :124-211 | `for_each` = `PM/plugins/base.py:44-67` (None → фильтр, dict → 1:1) |
| `self._total_inspected += 1` | :136 | ПЕРВАЯ строка тела, до проверки `enabled` |
| ветка `disabled` | :139-152 | `_rejecting=False` :143, `inspection_result={"action":"pass","reason":"disabled"}` :144-148, `_write_unit_event(..., decisive=False)` :152 |
| `detections = item.get("detections", [])` | :155 | item без детекций → `defects=[]` |
| reject-ветка | :168-179 | `_total_rejected += 1` :169; `front = not self._rejecting` :173; `_write_verdict` :175; `_rejecting=True` :176 |
| pass-ветка | :180-182 | `action="pass"`, `_rejecting=False` :182 |
| `inspection_result` | :187-194 | `{action, defect_count, total_inspected, total_rejected, reject_rate}` |
| `_write_unit_event` | :199 (def :252) | ОДНА широкая запись на единицу, и для pass тоже |
| `_dump_flight` | :207-208 (def :213) | на фронте |
| `_write_verdict` / `_verdicts_written` | :295 / :112, :339, сброс :384, `cmd_get_stats` :403 | |

Как item без детекций становится `pass`: :155 → :158 → :180-182. Для маркера сегодня: `total_inspected+1`, `pass`, `_rejecting=False` (сбросит фронт текущей отбраковки → следующий реальный брак выдаст повторный вердикт), широкая запись `inspection` с `decisive=False`.
`accepts_markers` в классе нет. Тесты: `Plugins/control/robot_control/tests/` — `test_plugin.py` 17, `test_verdict_documents.py` 20, `test_wide_event_emitter.py` 7, `test_flight_dump_emitter.py` 6, `test_verdict_real_wiring.py` 5, `test_trace_id_guard_usage.py` 6; `PM/tests/test_wide_event_acceptance.py` 30, `test_flight_recorder_acceptance.py` 23.
Ловушки для 4.7d-4: маркер-ветка должна стоять ДО :136 (иначе `total_inspected` вырастет) и решить, что делать при `enabled=False` (спека молчит: ветка :139 вернёт `pass/disabled` на маркер); спека не говорит, пишется ли широкая запись `_write_unit_event` для маркера (в спеке запрещены только вердикт-документ и `_rejecting`) — вопрос лиду.

## 8. Факты спеки 4.7d («Что код делает сегодня») — сверка

| # | Утверждение спеки | Вердикт | Опора |
|---|---|---|---|
| 1 | Нигде нет читателя `inspection_status`; тег ставят `PluginOperationStep` и `SuspectTagStep` | CONFIRMED (оговорка: `SuspectTagStep` пишет `"suspect"`, не `"not_inspected"`) | записи `plugin_operation_step.py:82`, `:113`; читателей вне тестов нет |
| 2 | `RobotControlPlugin.process` решает только по `item["detections"]`, без детекций → `pass` | CONFIRMED | `plugin.py:155`, `:158`, `:180-182` |
| 3 | `frame_stale_drops` = reader + отвязанные сегменты + `note_stale_drops` | CONFIRMED | `frame_shm_middleware.py:581` |
| 4 | Pre-chain считает входы `1 + note_stale_drops(len(items)-1)` | CONFIRMED (единица — items батча, не сообщения; склеенный join = 1) | `pipeline_executor.py:247-249` |
| 5 | Post-chain считает выходы, `pipeline_executor.py:262-267` | CONFIRMED на 49da43dc2; в HEAD те же строки = :269-274 | `pipeline_executor.py:269-274` |
| 6 | Дверь считает выходы, по одному на item | CONFIRMED | `:861-870`, `:1171-1174` |
| 7 | Пост-проверка `valid` стоит ПОСЛЕ `if not items: return` (:258-260 на 49da43dc2; в HEAD :265-267) | CHANGED (неточность): ВЫЧИСЛЕНИЕ `valid` — :261, ДО `if not items`; ПОСЛЕ стоит только ветка дропа `if not valid` :271. Reader +1 происходит на :261. Исправление 4.7d-2 = перенести ветку `if not valid` выше :265, а не «поставить проверку раньше» | :261, :258-260, :271-268 |
| 8 | «torn@exec» в коде нет, `_run_batch` видит только stale | CONFIRMED (HEAD) | `view_valid` бьёт лишь `_stale_drops` (`shm_frame_reader.py:210`); torn только в `read_ref` -> `_read_at_generation` :130 |
| 9 | Torn возникает на restore и входит в `stale_restore` | CONFIRMED | `_read_ref` :1000-1027, `frame_torn_reads` :666 |
| 10 | Единица на restore — сообщение | CONFIRMED | `_restore_refs` стоп на первой :1027-1029 (HEAD) |
| 11 | `_build_item`: `trace_id`/`capture_ts` из `msg["data"]`, `frame_id`/`camera_id` из data, иначе из msg | CONFIRMED (оговорка: `_build_item` копирует ВСЁ из data и добавляет msg-ключи, в т.ч. `sender`) | `data_receiver.py:414-447` |
| 12 | `DataReceiver.get_cycle_metrics()` несёт `lag_dropped_total` («остаётся числом коллекций») | WRONG на 49da43dc2 (спека с тех пор исправлена: «свойство `DataReceiver`, не ключ метрик»); в HEAD по-прежнему так: `lag_dropped_total` — только property (:288-291 в HEAD), в `get_cycle_metrics` его нет и нигде вне класса не читается; тест на ключ `lag_dropped_total` в метриках получит `KeyError`. Спека перечисляет в метриках только `lag_dropped_items` | :122-141, :281 |
| 13 | 4.7d-1: `_pick("overflow")`, «typed-поле, заданное явно, перекрывает extras (как у остальных `_pick`)» | ВСЁ ЕЩЁ ВЕРНО в HEAD для критерия: у `ProcessConfig` нет typed-поля `overflow` (реализация 4.7d-1 — extras-only, `blueprint.py:322`), ветка «typed перекрывает» для `overflow` недостижима; критерий «typed перекрывает» из спеки без typed-поля проверить нечем | `blueprint.py:80-209`, `:281-291`, `:322` |
| 14 | 4.7d-1: `ValueError` с именем процесса на `overflow: "sometimes"` | RESOLVED в HEAD: явный `raise ValueError(f"process {name!r}: overflow={v!r} — expected 'latest' or 'every'")` — несёт имя процесса, `overflow` и `'sometimes'` (repr) | `blueprint.py:322-324` |
| 15 | 4.7d-1: `build()` кладёт `overflow` только при `every`, golden не меняются | CONFIRMED и реализовано в HEAD: `pop` при не-`every` | `generic_process_config.py:314-316`, поле :202-211 |
| 16 | 4.7d-1: `receiver.overflow`, `executor.overflow`, `shm_middleware.overflow` на реальной сборке | В HEAD есть `DataReceiver.overflow` (:125), `PipelineExecutor.overflow` (:139); проводка `generic_process.py:153, :281, :300`. У `FrameShmMiddleware` свойства/kwarg `overflow` НЕТ (grep пуст; 4.7d-3). Атрибут `shm_middleware` в `GenericProcess` не сохраняется (локальная переменная, :224) — достать через `_pipeline_executor._shm` | `generic_process.py:224`, `:264-300` |
| 17 | 4.7d-2: `pending[i] = markers` под `chain.mutex`; метка `enq_ts` — момент замены | CONFIRMED выполнимо: `chain.queue` — deque, индексная запись возможна; `enq_ts` нужен `_StampedBatch` | `data_receiver.py:245-251`, :31 |
| 18 | 4.7d-2: `run_loop`, ветка `_is_shm_dropped` вместо `continue` | CONFIRMED точка вставки | `data_receiver.py:386-387` |
| 19 | 4.7d-3: повторный `send` fan-out видит уже маркер (замена на месте в общем `data`) | CONFIRMED механизм (общий item-dict), при условии замены in-place | `pipeline_executor.py:468-474`, `frame_shm_middleware.py:1116-1117` (HEAD) |
| 20 | Телеметрия: счётчики 4.7d читает стенд | НЕ ПРОВЕРЕНО до конца: `get_cycle_metrics` целиком попадает в статус воркера (`worker_manager.py:334`), но heartbeat-телеметрия пропускает только объявленные `declare_metric` ключи (`heartbeat/telemetry.py:63-69`, :160-176) — новые `not_inspected_*`/`lag_dropped_items` в дерево состояния сами не попадут |
| 21 | Существующие тесты, которые спека меняет | `test_g5c_executor_drop.py:245` (1→3 = 3 станет 1); `test_cycle_metrics.py:164` (`_EXECUTOR_KEYS` + `not_inspected_handled`) | см. §2 |

## 9. Что я оставляю открытым / считаю ненадёжным в карте

- Числа тестов — `grep -c "def test_"`, параметризованные и классовые кейсы не раскрыты; «используют `_run_batch`» — по вхождению слова в файл, не по числу вызовов.
- Утечка слота loan-протокола при дроп двери (§6) — гипотеза по чтению кода, не воспроизведена.
- Кто и как публикует новые счётчики на стенд (п.20 §8): по чтению; живую цепочку статус воркера → `introspect_*` я не гонял.
- Решения, не мои (-> лид): typed-поле `ProcessConfig.overflow` или extras-only (п.13); где поднимать `ValueError` (п.14); поведение `robot_control` на маркере при `enabled=False` и запись широкой записи для маркера; `FW_PORT_VALIDATE` для маркера (§2).
- Обновление 2026-10-02: §0-§6 пересчитаны под HEAD `671660688`; §7 — только дельта 4.7d-4 в шапке, строки таблицы старые; §8 — строки 5, 7, 8, 10, 12-16, 19 обновлены, остальное по 49da43dc2. Путь C7 (стале через `_stale_unlinked_drops`) выведен из чтения кода и коммита `9f6e989a3`, мной не прогонялся.
- Открыто для 4.7d-2: шаги спеки не говорят, что делать с `FW_PORT_VALIDATE=1` для маркера у плагина с `accepts_markers=True` (комментарий в `robot_control/plugin.py` отсылает к 4.7d-2, шаги 1-6 молчат); номера строк `:258-260` в тексте плана устарели (HEAD :265-267).
