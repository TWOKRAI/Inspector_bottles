# Карта подсистемы transport — для 4.7d (правило переполнения, маркер `not_inspected`)

Автор: `know-transport`. Базис кода: `49da43dc2` (HEAD ветки `feat/t47d` = `d4927f0c3`, отличается от базиса только docs; код в `multiprocess_framework/`, `Plugins/`, `Services/` не менялся с `23f872bce`, на котором сверена спека, — `git diff --stat` пуст). Ссылки `файл:строка` — по этому дереву. Счётчики вызывающих и тестов — грепом, тесты считаны по `def test_` (параметризация не раскрыта). Семантический поиск (qex) не использовался: Ollama недоступна.

Пути сокращены: `PM` = `multiprocess_framework/modules/process_module`, `RM` = `multiprocess_framework/modules/router_module`, `PMM` = `multiprocess_framework/modules/process_manager_module`.

## 0. Поток данных одного узла (кто в каком потоке)

| Поток | Что делает | Пишет |
|---|---|---|
| receiver (`DataReceiver.run_loop`, PM/generic/data_receiver.py:325) | receive → `restore_frame` → `_build_item` → collector → `on_items_ready` → `chain_queue` | единственный производитель `chain_queue` (коллектор и `check_timeouts` зовутся из этого же потока, :344, :396) |
| executor (`PipelineExecutor.run_loop`, pipeline_executor.py:160) | `chain_queue.get` → `_run_batch` → `_send_results` → router.send → middleware `strip_data_frame_on_send` (дверь) | `note_stale_drops`, дверные счётчики, release-тикеты |
| source producers (`SourceProducer`, generic_process.py:330) | `produce()` → send → та же дверь | выход источника не несёт `_shm_views`, дверью по входам не дропается |

Порядок «рождения» дропов по ходу кадра: restore (receiver) → bound (receiver) → pre-chain (executor) → post-chain (executor) → дверь (executor, router.send).
Конструкция data-плоскости: `generic_process.py:_init_data_pipeline` (:139). `FrameShmMiddleware` строится всегда, когда есть хоть один плагин (:222); `DataReceiver` и `PipelineExecutor` — только если есть processing-плагины (:262). У source-only процесса `receiver.overflow`/`executor.overflow` не существует.

## 1. `process_module/generic/data_receiver.py` (445 строк)

| Символ | Строка | Заметка |
|---|---|---|
| `_StampedBatch(list)`, слот `enq_ts` | :24, :31 | метка ставится в `on_items_ready` :297-298; исполнитель читает `getattr(items, "enq_ts")` (pipeline_executor.py:192). Маркер-коллекция, поставленная вне `on_items_ready`, метки не имеет (не ошибка: `queue_wait_ms` просто не обновится) |
| `__init__` | :47 | kwargs: `max_lag_items`, `inflight_budget`, `ipc_depth_fn`, `node_name`, `clock`. Сюда добавится `overflow="latest"` |
| `get_cycle_metrics` | :122-141 | база CycleMetricsRecorder + `transport_ms` (всегда) + `ipc_queue_depth` (если читали) + `transit_over_budget` (только при `inflight_budget>0`) + `perf_probes` (флаг). **`lag_dropped_total` в нём НЕТ** |
| `_bound_lag` | :199-257 | `chain.mutex` :238; `pending = chain.queue` (deque) :239; `frame_idx` :240; `excess` :241; `del pending[i]` с конца :243-244; `not_full.notify` :248; `put_nowait` :250; `queue.Full` → `False` :251-255 |
| `_is_frame_collection` | :259-262 | кадровая = хоть один item с `_shm_views` или `frame`. Маркер (без этих ключей) кадровой не считается |
| `_note_lag_drops` | :264-279 | `_lag_dropped_total += dropped` (число коллекций, не items); WARNING раз в 5 с |
| `lag_dropped_total` (property) | :281-284 | единственный выход счётчика; в `get_cycle_metrics` и в телеметрию не идёт |
| `on_items_ready` | :286-323 | `_StampedBatch` :297; bound :299; `put(timeout=lag_threshold)` :302; при shutdown `stop_event` → дроп (:315-318, вне формулы приёмки) |
| `run_loop` | :325-399 | `restore_frame` :376; `_is_shm_dropped` → `continue` :379-380 (ветка маркера 4.7d); `_note_transport` :383; `_build_item` :386; `collector.on_item` :396; `_cycle_metrics.record` :399 |
| `_is_shm_dropped` | :401-405 | читает `msg["data"][_shm_dropped]` |
| `_build_item` | :407-440 | `item = dict(msg["data"])` + `frame` из `msg` + msg-уровневые `camera_id, seq_id, total_regions, region_name, frame_id, timestamp, sender, data_type` **если ключа ещё нет в item** |

Вызывающие (грепом, не тесты): `run_loop` — worker target `generic_process.py:303`; `on_items_ready` — `collector._on_ready` `generic_process.py:281`; `_bound_lag` — только `on_items_ready:299`; `get_cycle_metrics` — `worker_module/core/worker_manager.py:329` через `target.__self__`, результат `status.update(cycle)` :334 (все ключи попадают в статус воркера).
Счётчики: `lag_dropped_total` (prop), `overload_events` (:443), `transit_over_budget`, `ipc_queue_depth`, `transport_ms`.
Тесты: `test_data_receiver.py` 10, `test_chain_lag_bound.py` 12, `test_t47c_bound_hazards.py` 5, `test_t47c_frame_aware_bound.py` 6, `test_frame_ref_atomic_item.py` 2, `test_claim_check_any_key_receive.py` 8, `test_t45d_transport_ms.py` 9, `test_cycle_metrics.py` 13 (все в `PM/tests/`); `Plugins/_shared/fanin/tests/test_t47a_join_views.py` 6.
Ловушки:
- Бюджет под mutex: замена `pending[i] = markers` допустима только внутри `with chain.mutex` (:238); длина очереди не меняется, поэтому `not_full.notify` для замены не нужен.
- `lag_dropped_items` считать `len(coll)` ДО замены/удаления; `lag_dropped_total` остаётся «коллекций» (:268).
- Ветка restore-дропа (:379): к этому моменту `_note_transport` ещё НЕ вызвана — `_t_sent_ns` лежит в `msg["data"]`, `_shm_refs` и `_shm_dropped` тоже. Метаданные маркера (`trace_id`, `capture_ts`, `frame_id`, `camera_id`) берутся из `msg["data"]`/`msg` как в `_build_item`.
- `_build_item` добавляет к item msg-уровневые ключи (`sender` ставит `process_communication.py:211` всегда) → пришедший по IPC маркер после `_build_item` НЕ равен «ровно ключам `build_marker`». `is_marker` надо проверять на `data` (до `_build_item`) или принять, что в item добавится `sender`.
- `run_loop` в ветке `continue` по `_shm_dropped` не вызывает `_cycle_metrics.record` (:399) — дропнутые сообщения в `effective_hz` не входят; при `every` маркер, отправленный `on_items_ready`, тоже не будет записан, если не добавить `record`.
- `test_cycle_metrics.py:210` фиксирует ТОЧНЫЙ набор ключей приёмника (`_RECEIVER_KEYS`, :28): при `max_lag_items=0` и `latest` новых ключей быть не должно (так и в спеке).

## 2. `process_module/generic/pipeline_executor.py` (484 строки)

| Символ | Строка | Заметка |
|---|---|---|
| `__init__` | :41 | kwargs: `plugins, chain_targets, shm_middleware, send_fn, max_consecutive_fails, auto_reset_sec, critical_plugins, node_name, plugin_runner`. Сюда `overflow="latest"` |
| breaker-состояние | :75-77 | `_consecutive_fails`, `_bypassed`, `_bypassed_since` |
| `_runnable_steps` (по шагу на плагин) | :83-95 | `PluginOperationStep(on_success=_on_plugin_success, on_fail=_on_plugin_fail)`, `on_error="skip"` :92 |
| `_suspect_step` | :99-103 | один `SuspectTagStep` на все позиции |
| `get_cycle_metrics` | :149-158 | база + `queue_wait_ms`. Счётчиков дропов нет |
| `run_loop` | :160-216 | `chain_queue.get(0.05)` :182; EMA `queue_wait_ms` по `enq_ts` :192-199; `_run_batch` внутри `log_correlation(items)` :212-213 |
| `_run_batch` | :218-280 | см. таблицу ниже |
| `_execute_chain` | :282-305 | перестраивает `_active_runnable` при `_steps_dirty` :301-303; `execute(items, None)` :304 |
| `_collect_view_tickets` | :307-322 | тикеты = ссылки из `item["_shm_views"]` входных items; пусто без middleware |
| `_attach_batch_views` | :324-340 | пишет в КАЖДЫЙ выход новый список views (свои + билеты батча) |
| `_frame_views_valid` | :342-347 | `all(shm.frame_view_valid(ref))`; первый же stale → reader +1 и стоп |
| `_accumulate_releases` / `_flush_releases` | :360, :377 | только при `loan_protocol_enabled` |
| `_build_active_steps` | :396-412 | критический bypassed → `SuspectTagStep` на его позиции |
| `_on_plugin_success` / `_on_plugin_fail` | :414, :418 | `consecutive_fails` :416, :425-426; bypass при `fails >= max_fails` :428-431 |
| `_send_results` | :437-467 | `item.pop("target")` :444; `data_type` для кадра :450-451; `frame_trace.stamp_send` :454; `item["_t_sent_ns"]` :457; **msg на каждый target с `"data": item` — один и тот же dict** :461-467 |

`_run_batch` по шагам (порядок несущий):

| # | Строки | Что |
|---|---|---|
| 1 | :230 | `view_tickets = _collect_view_tickets(items)` — ДО цепочки (плагин может заменить dict) |
| 2 | :240-245 | pre-chain: `view_tickets and not valid` → `note_stale_drops(len(items)-1)` если `len>1` :241-242; release :243; `record` :244; `return` :245. Единица — ВХОДНЫЕ items (reader +1 внутри `_frame_views_valid`) |
| 3 | :248 | `_execute_chain(items)` |
| 4 | :254 | `valid = _frame_views_valid(view_tickets)` — reader +1 при stale происходит ЗДЕСЬ |
| 5 | :255 | `_accumulate_releases` (в любом исходе) |
| 6 | :258-260 | `if not items: record; return` — пустой выход выходит ДО ветки по `valid` |
| 7 | :262-268 | `if not valid`: `note_stale_drops(len(items)-1)` (items = ВЫХОДЫ) :265-266; `return` |
| 8 | :273-274 | `_attach_batch_views` |
| 9 | :277 | `_send_results` |

Вызывающие: `_run_batch` — только `run_loop:213`; `PipelineExecutor(...)` — только `generic_process.py:284`; `note_stale_drops` — только :242, :266; `bind_queue/run` — `generic_process.py:309-312`.
Счётчики: `queue_wait_ms`; прочее в `shm`. Новые по спеке: `not_inspected_stale_exec` (при `every`), `not_inspected_handled` (всегда).
Тесты: `test_pipeline_executor.py` 10, `test_pipeline_executor_characterization.py` 14, `test_pipeline_chain_engine.py` 4, `test_g5c_executor_drop.py` 13, `test_t47c_gen_check_before_chain.py` 1, `test_frame_log_correlation.py` 12, `test_t45a_worker_fields.py` 16, `test_cycle_metrics.py` 13, `RM/tests/test_frame_ref_gen.py` 12, `RM/tests/test_t45c_transport_counters.py` 9 (используют `_run_batch`/`_send_results`: 4+3+5+1+1+1+1 файлов).
Ловушки:
- Менять существующий тест: `test_g5c_executor_drop.py:245 test_batch_drop_counts_one_per_output_item` фиксирует 1 вход → 3 выхода = `frame_stale_drops == 3`. После 4.7d-2 станет 1 — тест надо переписать намеренно (это спека, не регрессия).
- `test_cycle_metrics.py:164` фиксирует точный набор ключей исполнителя (`_EXECUTOR_KEYS`, :26): `not_inspected_handled` «всегда» ломает его — обновить тест.
- Общий `item`-dict при fan-out (:461-467): `_send_results` мутирует item (`pop target`, `_t_sent_ns`, штампы) — тот же объект идёт ко всем целям, потому маркер в двери меняется на месте.
- Под `FW_PORT_VALIDATE=1` (`plugin_runner.py:153-159`, `validate_items_against_ports` бросает `PortValidationError` при отсутствии обязательного порта, `process_module/plugins/port.py:187-192`) плагин с `accepts_markers=True` и обязательными портами `frame`/`detections` (как `robot_control`) на маркере упадёт в `except` шага → `on_fail` → `consecutive_fails` растёт. Для 4.7d-4 важно: или пропускать валидацию для маркера, или помечать порты optional. Решение — лиду.
- `ChainRunnable.execute` в `_execute_chain` проходит ВСЕ активные шаги; пропуск маркера обеспечивают сами шаги (спека 4.7d-2 п.5), а не `_execute_chain`.
- `_check_auto_reset` и release-флаш крутятся в том же потоке; маркер-ветка `_forward_markers` не должна пропускать `_accumulate_releases` (у маркера тикетов нет, no-op).

## 3. `plugin_operation_step.py` (120 строк) и breaker

| Символ | Строка | Заметка |
|---|---|---|
| `PipelineStepNode` | :36 | дескриптор для `RunnableStep` |
| `PluginOperationStep.execute` | :66-86 | `if not items: return items` :74; `runner.call_process` :77; `except` → `item["inspection_status"]="not_inspected"` на всех items :81-82, `on_fail` :83, `return items` :84; успех → `on_success` :85, `return outputs` :86 |
| `SuspectTagStep.execute` | :108-114 | `item["inspection_status"]="suspect"` :112-113; пустой батч не тегирует |
| breaker (`consecutive_fails`, `on_success`/`on_fail`) | живёт в executor :75-77, :414-431 | шаги только зовут колбэки; для маркер-коллекции колбэки НЕ звать |

Вызывающие: `PluginOperationStep(` — `pipeline_executor.py:86`; `SuspectTagStep()` — :101; других нет.
Единственные записи `inspection_status` вне тестов: `plugin_operation_step.py:82`, `:113` (остальные упоминания — комментарии/docstring). Читателей в коде нет.
Тесты: `test_plugin_levels_defect_quartet_hazards.py` 2, `test_pipeline_executor.py` (:159, :180, :200 читают тег), `test_pipeline_executor_characterization.py` (:190-222, :287-300).
Ловушки: `SuspectTagStep` пишет `suspect`, а не `not_inspected` (спека называет его в одном ряду с «сбоем плагина» — тег `not_inspected` ставит только `PluginOperationStep`). Тег `not_inspected` от сбоя плагина идёт у item с картинкой; `is_marker` различает это по `overflow_marker is True`. `accepts_markers` нигде в коде не объявлен (grep по репо пуст) — читать через `getattr(plugin, "accepts_markers", False)`; базовый класс `ProcessModulePlugin` (`PM/plugins/base.py:1251`) не в списке файлов спеки.

## 4. `generic_process.py` и `generic_process_config.py`

`_init_data_pipeline` (`generic_process.py:139-355`), чтение ключей из `app_cfg = self.get_config("config")` :141:

| Что строится | Строки | Откуда ключи |
|---|---|---|
| `max_lag_items` | :151 | `app_cfg["chain_max_lag_items"]` (дефолт 0) |
| `inflight_budget` | :153 | `app_cfg["inflight_budget"]` |
| `FrameShmMiddleware(memory_manager, owner=self.name, slot="output_frames", coll=frame_ring_depth, log_error, num_consumers)` | :222-229 | `frame_ring_depth` :207; `copy_out_targets` :215. Регистрация: `router.add_send_middleware(shm.strip_data_frame_on_send)` :235, `register_frame_middleware` :238 |
| `chain_queue = Queue(maxsize=queue_size)` | :259 | `queue_size` (64) |
| `DataReceiver(...)` | :266-279 | `max_lag_items`, `inflight_budget`, `ipc_depth_fn`, `node_name=self.name`; `collector._on_ready = receiver.on_items_ready` :281 |
| `PipelineExecutor(...)` | :284-297 | `max_fails`, `auto_reset`, `critical`; `node_name=self.name` |

Другие места, строящие `FrameShmMiddleware(`: `PM/commands/builtin_commands.py:3765` (wire.configure, путь `on_send`), `multiprocess_prototype/frontend/process.py:51` (GUI-приёмник). Новый kwarg `overflow` для них — дефолт `"latest"`.

`generic_process_config.py`: класс :65; `frame_ring_depth` :152; `chain_max_lag_items` :189-200; `build()` :284-304. `ProcessLaunchConfig.build` (`PM/configs/process_launch_config.py:147`) делает `model_dump()` — КАЖДОЕ typed-поле попадает в `proc_dict["config"]`. Поэтому «`overflow` только при `every`» требует явного `pop` при `latest` по образцу :298-303 (`inflight_budget`, `cv_threads`). `chain_max_lag_items` НЕ выпиливается (всегда в config, даже 0).

Путь `chain_max_lag_items` (прецедент для `overflow`): рецепт `extras` → `_pick` `blueprint.py:317` → `base_kwargs` только если truthy `:324-325` (`int()`) → typed-поле `GenericProcessConfig` → `build()` → `config["chain_max_lag_items"]` → `generic_process.py:151` → `DataReceiver(max_lag_items=)` :276. Дополнительно топология ПЕРЕПИСЫВАЕТ значение: `PMM/topology/blueprint.py:_apply_inflight_budgets` :577-621 (`cfg.chain_max_lag_items = …` :615) для каждого получателя за кольцом писателя (дефолт `min(2, B-1)`). Следствие: `lag_dropped_items` активен у многих процессов без ключа в рецепте.
Тесты конфигурации: `PM/tests/test_blueprint_extras.py` 22, `PMM/tests/test_t47c_blueprint_wiring.py` 10, `PMM/tests/test_cv_threads.py` 11, `PMM/tests/test_t47c_hazards.py` 11, `PM/tests/test_collector_legacy_alias.py` 20, `PM/tests/test_plugin_config_extra.py` 14, `PM/tests/test_protected_propagation.py` 4.

## 5. `process_manager_module/topology/blueprint.py`

| Символ | Строка | Заметка |
|---|---|---|
| `ProcessConfig` typed-поля | :80-209 | ТОЛЬКО `chain_targets`, `source_target_fps`, `collector`, `io_peek`, `telemetry` (+ `extras`, `metadata`, служебные). `frame_ring_depth`, `chain_max_lag_items`, `copy_out_targets`, `cv_threads`, `data_queue_maxsize` — typed-полей НЕТ, живут только в `extras` |
| `as_generic_config` | :245-347 | вызывается только `build_configs:573` (+тесты); у метода нет ни одного `raise` |
| `_pick(key, default)` | :281-291 | `key in model_fields_set` → `getattr(self,key)` (+ warning при конфликте с extras :285); иначе `extras.get(key, default)` |
| `chain_max_lag_items` pick/set | :317, :324-325 | |
| `build_configs` | :565-575 | `_apply_inflight_budgets` :574 |
| ошибки «с именем процесса» | `PMM/topology/inflight.py:51-54`, `:89-92`, `:98` | формат `процесс '{process}': …`, поднимаются из `_apply_inflight_budgets` :615-621, а не из `as_generic_config` |

Ловушка: ошибка «с именем процесса» для `overflow` в `as_generic_config` придётся писать явным `raise ValueError(f"ProcessConfig[{self.process_name}]: overflow … '{v}'")`. Если оставить проверку на `Literal` в `GenericProcessConfig`, получится `pydantic.ValidationError` (подкласс `ValueError`, проверено в этом окружении, pydantic 2.13.2) с именем поля и `input_value='sometimes'`, но БЕЗ имени процесса.

## 6. `router_module/middleware/frame_shm_middleware.py` (1329 строк) — основание 49da43dc2, изменится при слиянии 4.7b

Константы: `SHM_REFS_KEY` :61, `FRAME_KEY` :63, `SHM_VIEWS_KEY` :69, `SHM_DROPPED_KEY` :70 (там же, `CLAIM_CHECK_MIN_NBYTES` :55). `middleware/__init__.py` экспортирует только `FrameShmMiddleware`; модуля `not_inspected_marker.py` ещё нет.

| Символ | Строка | Заметка |
|---|---|---|
| `__init__` | :334-489 | `_owner` :351; `_coll` :357; `_last_loan_exhausted` :474; `_reader` :437-447. Сюда `overflow="latest"` |
| счётчики-состояния | :363 (`frame_boundary_crossings`), :365 (`frame_pickle_fallbacks`), :385 (`_restore_fail_count`), :389 (`_stale_unlinked_drops`), :394 (`_stale_batch_drops`) | plain int без lock; lock только для байтов (:369) |
| `frame_stale_drops` | :605-612 | `reader.stale_drops + _stale_unlinked_drops + _stale_batch_drops` |
| `note_stale_drops(n)` | :614-619 | `n<=0` — no-op |
| `frame_restore_failures` | :659-664 | `= _restore_fail_count` (сбой открытия/битая ссылка; stale и отвязанный сегмент сюда НЕ входят) |
| `frame_torn_reads` | :666-671 | `reader.torn_reads` (`shared_resources_module/memory/reader/shm_frame_reader.py:134`, только в `read_ref`) |
| `frame_view_valid` | :758-766 | → `reader.view_valid` (бьёт ТОЛЬКО `_stale_drops`, `shm_frame_reader.py:194`; torn там не считается) |
| `_inputs_still_valid` | :861-870 | цикл по `item["_shm_views"]`, стоп на первом stale → +1 на item |
| `restore_frame` | :955-984 | при провале ссылки `data["_shm_dropped"]=True` :981 |
| `_read_ref` | :986-1027 | `FileNotFoundError` → `_stale_unlinked_drops` :1004; иной сбой/битая ссылка → `_restore_fail_count` :1020 |
| `_restore_refs` | :1029-1063 | атомарно: стоп на первой `None`, снять восстановленное :1056-1058 |
| `_views_foreign_memory` | :1078-1090 | корень `.base` не ndarray = чужая память (4.7a) |
| `_copy_inline_views` | :1093-1109 | `True`, если что-то скопировано |
| `strip_and_write` | :1111-1178 | ранний выход по `_shm_dropped` :1145-1146; fan-out replay :1147-1150; `touched_foreign` :1154; запись :1156; `_last_loan_exhausted` :1160-1161; **единственное место, где ставится `_shm_dropped` на двери: :1171-1174** (`touched_foreign and not _inputs_still_valid`); `pop(SHM_VIEWS_KEY)` :1177 |
| `strip_data_frame_on_send` | :1188-1221 | guard `type=="data"` :1208; `strip_and_write(data)` :1212; loan-исчерпание → `None` :1215-1216; `_shm_dropped` → `None` :1219-1220 |
| `on_send` / `on_receive` | :1241, :1309 | wire.configure / GUI-путь; маркеры 4.7d их не касаются |

Вызывающие: `strip_data_frame_on_send` — только регистрация `generic_process.py:235` (router зовёт на каждый send, `router_manager.py:_do_send` :541-546; `None` → `middleware_dropped`); `note_stale_drops` — executor :242, :266; `restore_frame` — `data_receiver.py:376`; `frame_stale_drops/torn/restore_failures` — `router_manager.py:1787-1798` → `heartbeat/telemetry.py:258-295` (`state.shm.*`).
Тесты: `RM/tests/test_frame_shm_middleware.py` 38, `test_frame_ref_gen.py` 12, `test_frame_ref_hazards.py` 17, `test_g5d_loan.py` 22, `test_t47a_door_hazards.py` 10, `test_t47a_door_owndata.py` 10, `test_g5c_stale_recheck.py` 3, `test_t45c_transport_counters.py` 9, `test_claim_check_any_key.py` 12; `PM/tests/test_g5c_executor_drop.py` 13, `test_process_io_shm_contract.py` 6.
Ловушки:
- `door_drops` инкрементить на :1173 (первый раз), НЕ в `strip_data_frame_on_send`: он выполняется на каждую цель, а повтор fan-out выходит из `strip_and_write` на :1145.
- Замена содержимого `msg["data"]` на маркер обязана быть на месте в общем dict (`clear()+update()`), потому что `_send_results` создаёт msg на каждую цель с ОДНИМ объектом `item`. Перепривязка `msg["data"] = marker` ломает fan-out: вторая цель увидит исходный dict с `_shm_dropped` и родит второй маркер (или получит `None`).
- К моменту :1173 в кольцо уже могла быть записана ссылка (`_write_item_arrays` :1156): `item["_shm_refs"]` с собственными ссылками остаётся в item. Маркер её не несёт, слот брошен (при loan-протоколе его refcount никто не снимет — НЕ проверено, существует и сегодня для `latest`).
- Замена `data` стирает `_t_sent_ns` и frame-trace штампы — у получателя `transport_ms` для этого сообщения не снимется (мелочь).
- `_last_loan_exhausted` — разделяемый атрибут между потоками источника/исполнителя (:474, :1144); дропы по нему в формулу не входят (спека).
- Счётчики двери — plain int; единственный пишущий поток двери — executor (источник views не несёт), для `not_inspected_door` lock не нужен, но это допущение, не гарантия.

## 7. `Plugins/control/robot_control/plugin.py` (405 строк)

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
| 3 | `frame_stale_drops` = reader + отвязанные сегменты + `note_stale_drops` | CONFIRMED | `frame_shm_middleware.py:612` |
| 4 | Pre-chain считает входы `1 + note_stale_drops(len(items)-1)` | CONFIRMED (единица — items батча, не сообщения; склеенный join = 1) | `pipeline_executor.py:240-242` |
| 5 | Post-chain считает выходы, `pipeline_executor.py:262-267` | CONFIRMED, номера строк точны | :262-267 |
| 6 | Дверь считает выходы, по одному на item | CONFIRMED | `:861-870`, `:1171-1174` |
| 7 | Пост-проверка `valid` стоит ПОСЛЕ `if not items: return` (:258-260) | CHANGED (неточность): ВЫЧИСЛЕНИЕ `valid` — :254, ДО `if not items`; ПОСЛЕ стоит только ветка дропа `if not valid` :264. Reader +1 происходит на :254. Исправление 4.7d-2 = перенести ветку `if not valid` выше :258, а не «поставить проверку раньше» | :254, :258-260, :264-268 |
| 8 | «torn@exec» в коде нет, `_run_batch` видит только stale | CONFIRMED | `view_valid` бьёт лишь `_stale_drops` (`shm_frame_reader.py:194`); torn только в `read_ref` :134 |
| 9 | Torn возникает на restore и входит в `stale_restore` | CONFIRMED | `_read_ref` :1000-1027, `frame_torn_reads` :666 |
| 10 | Единица на restore — сообщение | CONFIRMED | `_restore_refs` стоп на первой :1055-1058 |
| 11 | `_build_item`: `trace_id`/`capture_ts` из `msg["data"]`, `frame_id`/`camera_id` из data, иначе из msg | CONFIRMED (оговорка: `_build_item` копирует ВСЁ из data и добавляет msg-ключи, в т.ч. `sender`) | `data_receiver.py:407-440` |
| 12 | `DataReceiver.get_cycle_metrics()` несёт `lag_dropped_total` («остаётся числом коллекций») | WRONG/CHANGED: `lag_dropped_total` — только property (:281), в `get_cycle_metrics` его нет и нигде вне класса не читается; тест на ключ `lag_dropped_total` в метриках получит `KeyError`. Спека перечисляет в метриках только `lag_dropped_items` | :122-141, :281 |
| 13 | 4.7d-1: `_pick("overflow")`, «typed-поле, заданное явно, перекрывает extras (как у остальных `_pick`)» | WRONG для `overflow`: у `ProcessConfig` нет typed-поля `overflow` и спека его не вводит; как `chain_max_lag_items`/`frame_ring_depth`, ключ только в extras → ветка «typed перекрывает» недостижима, критерий непроверяем без нового поля | `blueprint.py:80-209`, :281-291 |
| 14 | 4.7d-1: `ValueError` с именем процесса на `overflow: "sometimes"` | CHANGED: в `as_generic_config` нет raise-пути; имя процесса несут только ошибки `inflight.py` из `build_configs`. Нужен явный raise (см. §5) | `blueprint.py:245-347`, `inflight.py:54,89,98` |
| 15 | 4.7d-1: `build()` кладёт `overflow` только при `every`, golden не меняются | CONFIRMED как требование к коду: без `pop` typed-поле попадёт в `config` всегда (`model_dump`) | `process_launch_config.py:147`, образец `generic_process_config.py:298-303` |
| 16 | 4.7d-1: `receiver.overflow`, `executor.overflow`, `shm_middleware.overflow` на реальной сборке | CONFIRMED с условием: receiver/executor есть только при processing-плагинах; атрибут `shm_middleware` в `GenericProcess` не сохраняется (локальная переменная `shm_middleware`, :222) — проверка идёт через `router`/`_pipeline_executor._shm` | `generic_process.py:222`, :262, :266, :284 |
| 17 | 4.7d-2: `pending[i] = markers` под `chain.mutex`; метка `enq_ts` — момент замены | CONFIRMED выполнимо: `chain.queue` — deque, индексная запись возможна; `enq_ts` нужен `_StampedBatch` | `data_receiver.py:238-244`, :31 |
| 18 | 4.7d-2: `run_loop`, ветка `_is_shm_dropped` вместо `continue` | CONFIRMED точка вставки | `data_receiver.py:379-380` |
| 19 | 4.7d-3: повторный `send` fan-out видит уже маркер (замена на месте в общем `data`) | CONFIRMED механизм (общий item-dict), при условии замены in-place | `pipeline_executor.py:461-467`, `frame_shm_middleware.py:1145-1146` |
| 20 | Телеметрия: счётчики 4.7d читает стенд | НЕ ПРОВЕРЕНО до конца: `get_cycle_metrics` целиком попадает в статус воркера (`worker_manager.py:334`), но heartbeat-телеметрия пропускает только объявленные `declare_metric` ключи (`heartbeat/telemetry.py:63-69`, :160-176) — новые `not_inspected_*`/`lag_dropped_items` в дерево состояния сами не попадут |
| 21 | Существующие тесты, которые спека меняет | `test_g5c_executor_drop.py:245` (1→3 = 3 станет 1); `test_cycle_metrics.py:164` (`_EXECUTOR_KEYS` + `not_inspected_handled`) | см. §2 |

## 9. Что я оставляю открытым / считаю ненадёжным в карте

- Числа тестов — `grep -c "def test_"`, параметризованные и классовые кейсы не раскрыты; «используют `_run_batch`» — по вхождению слова в файл, не по числу вызовов.
- Утечка слота loan-протокола при дроп двери (§6) — гипотеза по чтению кода, не воспроизведена.
- Кто и как публикует новые счётчики на стенд (п.20 §8): по чтению; живую цепочку статус воркера → `introspect_*` я не гонял.
- Решения, не мои (-> лид): typed-поле `ProcessConfig.overflow` или extras-only (п.13); где поднимать `ValueError` (п.14); поведение `robot_control` на маркере при `enabled=False` и запись широкой записи для маркера; `FW_PORT_VALIDATE` для маркера (§2).
- Раздел §6 — основание `49da43dc2`, помечен «изменится при слиянии 4.7b» (4.7b правит `frame_shm_middleware.py`); номера строк после 4.7b пересверить.
