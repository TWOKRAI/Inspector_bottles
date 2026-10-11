# Rubric — ground truth per question

Built 2026-10-11 by four blind Opus judges from the code (file:line as of that date). Paths in q1/q2/q4/q8 are
relative to `multiprocess_framework/modules/` unless stated. "Core" facts = a complete answer needs them;
"extra" = a plus, not required. "Traps" = claims seen in earlier answers that are WRONG.

## q1 — RouterManager; Router channel vs process name
Core:
1. `RouterManager(ChannelRoutingManager)` — facade over AsyncSender/AsyncReceiver, `channel_dispatcher` (outgoing) and `event_dispatcher` (incoming); own dispatcher since F4.6 (`router_module/core/router_manager.py:123-124, 185-203`).
2. `send()` is synchronous → `_do_send`; only `send_async()` uses the AsyncSender PriorityQueue (`:515-530`).
3. `_do_send`: send-middleware → `_resolve_channels` → `channel.send()`; no channel → fallback `_deliver_by_targets` (`:532-580`).
4. `_resolve_channels` order: explicit `msg["channel"]` → `channel_dispatcher` by `command`/`type` (default EXACT_MATCH) → kind-channels `{process}_{kind}` under flag G.2 → `[]` (`:1998-2065`).
5. `_deliver_by_targets`: process names from `targets` go straight to `queue_registry.send_to_queue(process, qtype)`, no channel involved (`:624-802`).
6. Receive: recv-middleware → request/response by correlation_id → worker handler → `command` to CommandManager (auto-reply), the rest to `event_dispatcher` (`:1299-1474`).
7. Process name = `target` in `send_message`/`Message.targets`; `send_to_process` sets `targets=[target]` and calls `router_manager.send` (`process_communication.py:189-221`).
8. Router channel = key in the channel registry (`FieldRouting.channel`, `msg["channel"]`); need not equal the process name, e.g. field `draw` → channel `control_draw` → process `renderer` (`ROUTING_GLOSSARY.md`).
Traps: "send() goes through AsyncSender"; incoming goes to `message_dispatcher` (stale README name); "exact → pattern → broadcast" cascade (PATTERN frozen, default EXACT_MATCH); "every channel is a shared_resources queue" (SocketChannel exists); "transport inside one process".

## q2 — core tier modules
Core:
1. `multiprocess_framework/docs/MODULE_TIERS.md:51`: core 17, optional 10, frozen 0; total 27.
2. The 17: base_manager, message_module, channel_routing_module, logger_module, error_module, statistics_module, dispatch_module, command_module, router_module, config_module, data_schema_module, shared_resources_module, process_module, process_manager_module, worker_module, console_module, chain_module.
Extra: chain_module frozen→core needs owner reconfirmation (`:65`); frozen tier holds features only, not modules; contract test `modules/tests/test_module_tiers.py` checks map vs disk, not the number 17.
Traps: "the document was last updated 2026-07-26" (that is the header date; git edit 2026-10-05).

## q3 — StateStoreManager glob delivery
Paths relative to `multiprocess_framework/modules/state_store_module/`.
Core:
1. Mutations `handle_state_set/merge/delete` (`manager/state_store_manager.py:181/220/281`); middleware before/after (not for delete) → `dispatch_single`/`dispatch`; merge yields one delta per leaf with its own revision.
2. `SubscriptionManager.match` copies subscriptions under RLock, matches outside; skips `exclude_sources`; `_split_pattern` lru_cache(256); `*` = exactly one segment, `**` = zero or more, the rest literal and case-sensitive (`core/subscription_manager.py:49-341`).
3. Matching happens at mutation time, not at flush; per-subscriber dedup by delta index, order kept (`manager/delta_dispatcher.py:118-156`).
4. Deltas buffered per subscriber; keep-last coalescing forbidden (`:173-211`).
5. One `StateCoalesceFlusher` thread sends, tick 0.12 s; at 200 deltas it is woken early via `_wake`; the mutator never sends (`:35-39, 265-302`).
6. Envelope: `type=event`, `targets=[subscriber]`, `queue_type="state"`, `command=state.changed`, data `deltas`, `revision` (max), `first_revision` (min); sent via `router.send_async`; state queue is drop_oldest (`:339-393`).
7. Initial snapshot: `_replay_initial_state` replays the `static_prefix` subtree, leaves only, `source="__replay__"`, into the same buffer (`state_store_manager.py:430-533`).
Extra: client `StateProxy.on_state_changed` checks continuity by `first_revision`/`revision` and resyncs on a gap (`proxy/state_proxy.py:771-894`).
Traps: an `update` operation (it is `merge`); "stop_flusher always drains everything" (skipped if the thread hangs); middleware on delete.

## q4 — why only dict crosses processes; where it is checked
Core:
1. ADR-008 (`multiprocess_framework/DECISIONS.md:262-268`): Pydantic models do not always pickle for `multiprocessing.Queue`; dict always does.
2. `multiprocess_framework/docs/DESIGN_RULES.md` R-3 (`:49-58`, bans BaseModel/SchemaBase, lambdas, closures, unregistered classes) and R-11 (`:164-172`, spawn on ALL OSes since Atlas 0.8b); R-3 check = "`pickle.dumps(payload)` in a test" (`:290`); validate.py/sentrux check only structure/layers (`:309`).
3. `RouterManager._to_dict` (`router_module/core/router_manager.py:1929`) normalises the TOP level on send/send_async/request; nested payload is NOT checked.
4. Runtime spot checks: `app_module/builder.py:507` `_pickle_sanity` (pickle.dumps of build-time hook results before spawn); `ConfigStore.store` raises TypeError for non-dict (`shared_resources_module/config_store/config_store.py:34`).
5. No sentrux rule, no script check; tests: 74 `pickle.dumps` (87 with loads) in 37 files, framework only.
Extra: ADR-MSG-005 (`message_module/DECISIONS.md:65-73`): Message itself need not pickle, only `to_dict()` crosses.
Traps: "fails only on Windows" (spawn is on all OSes); "silent data corruption" (unsupported); `router_manager.py:832 isinstance(dict)` as a receive-side guard (it handles an evicted pool ticket).

## q5 — where ProcessManagerProcess is created; child start order
Paths relative to `multiprocess_framework/modules/` unless stated.
Core:
1. No direct `ProcessManagerProcess(...)` call. `SystemLauncher.run()/start()` → `_create_spawner` → `ProcessSpawner.launch_orchestrator` → `Process(target=run_process_function, args=(class_path, "ProcessManager", stop_event, bundle, system_stop_event)).start()` (`spawner.py:86-140`).
2. The instance is built in the child: `_load_process_class` → `process_class(name, shared_resources, config)` (`process_runner.py:315, 349`) → `initialize()` → `run()`.
3. Prototype substitutes `multiprocess_prototype.orchestrator.ProcessManagerProcessApp` (`multiprocess_prototype/launch.py:38`, via `assemble_launcher`), hierarchy ProcessManagerProcessApp → GenericProcessManagerApp → ProcessManagerProcess.
4. Main process: pid registry, processes config, SHM cleanup (by config names; prefix cleanup only under `FW_SHM_PREFIX_CLEANUP`, default False) → launch_orchestrator → join(0.5) loop on `system_stop_event`.
5. `PM.initialize`: self-registration, console/topology/state_store/commands → `_create_processes_from_config` (`process_manager_process.py:268`) → monitor → backend_ctl → barrier `_wait_boot_ready` (`:312`).
6. `_create_processes_from_config`: phase 1 `register_process` for all; phase 2 boot waves `_plan_boot_waves` (flag `FW_DEPENDS_ON_BOOT_ORDER` default True; Kahn topo-sort in `_compute_boot_waves` `:3452`); no `depends_on`/cycle/flag off → one flat wave in dict order; between waves `_wait_processes_ready` (timeout `boot_ready_timeout_s` 5.0, then WARNING and continue).
7. Per process: `create_and_register` → `register_priority` → `start` → `_mark_instance_started` → `apply_priority`; rollback on failure.
Extra: prototype recipes have no `depends_on` → in practice one flat wave.
Traps: "SHM cleanup removes orphans by prefix" (flag default False); "prototype substitutes GenericProcessManagerApp".

## q6 — note: run tests via scripts/run_framework_tests.py
Core:
1. The script runs `[sys.executable, "-m", "pytest", *argv]` with `cwd=multiprocess_framework/modules`, args passed through (`scripts/run_framework_tests.py:25-32`). Imports work from the root too (editable install) — "imports break from the root" is FALSE.
2. `multiprocess_framework/modules/pytest.ini` has 35 testpaths, `asyncio_mode = auto`, `qt_api = pyside6`, marker `legacy_gen1`.
3. Root `pyproject.toml` `[tool.pytest.ini_options]` lists only TWO framework paths (`modules/state_store_module/tests`, `modules/tests`) → 33 framework test dirs are not collected; the other root paths are Services, Plugins, scripts, backend_ctl, prototype, etc.
4. So a bare `pytest` from the root gives a different, smaller set → a false green.
Extra: there are 0 native async tests in the framework today, so the asyncio_mode argument is true as a mechanism but has no effect now; passing an explicit path inside `modules/` from the root picks up `modules/pytest.ini`.
Traps: "only state_store_module is listed"; "the rest is the prototype"; `qt_api` presented as a difference (it is in both).

## q7 — ChainRunnable vs DagRunnable
Paths relative to `multiprocess_framework/modules/chain_module/`.
Core:
1. `ChainRunnable(steps)`: sequential, output of step N is input of N+1; payload duck-typed (ndarray or list[dict]) (`core/chain.py:34-94`).
2. `DagRunnable(steps, topology, node_inputs)`: data via `port_data[node][port]`, the frame is a virtual source `"frame"."out"`; ops without `execute_dag` are called via `execute` wrapped as `{"out": …}` (`core/dag.py:31-155`).
3. Shared: ChainResult, ChainContext, `apply_on_error_policy` (skip / fail_region / fail_camera), side results, cross-process branch; NEITHER runs in parallel.
4. DAG pitfalls: skipped node → `port_data={}`, consumers get None; node without inputs gets the frame; node in topology without a step silently skipped; result from the LAST topology node, not a chosen sink.
5. DagRunnable does not sort; `is_nonlinear_graph` chooses, `topological_sort` sorts (`graph/topology.py:62-84`).
6. Production creates only ChainRunnable (`process_module/generic/pipeline_executor.py:116, 362`); DagRunnable has no non-test callers.
Extra: for real parallelism there is `ParallelChainRunnable` (`core/parallel.py:23`).
Traps: "Chain skips a failed step" (fail_* aborts the chain, `chain.py:84-86`); a "continue" policy (it is skip); "only detections go through port_data" (the input goes there).

## q8 — pickle risks in shared_resources_module
Paths relative to `multiprocess_framework/modules/`.
Core:
1. No explicit pickle.dumps/loads in the module's production code (tests only); pickle is implicit: spawn args and `mp.Queue` transport.
2. In production the SRM is NOT pickled into the child: `Process(args=(class_path, name, stop_event, bundle, system_stop_event))` (`process_manager_module/core/process_registry.py:253`); the child rebuilds SRM from a dict bundle (`process_manager_module/runner/bundle_builder.py:43-139`). SRM `__getstate__/__setstate__` is a dormant (test-only) path.
3. Silent loss: `mp.Queue.put` pickles in the feeder thread, so `send_to_queue` returns True (`shared_resources_module/queues/core/manager.py:306-309`); the PicklingError branch (`:350-371`) is unreachable on a real mp.Queue; no `_on_queue_feeder_error` override.
4. `ProcessData.custom` is pickled inside the bundle; a manual deny-list of keys guards mp.Event (`process_registry.py:187-196`); `ProcessData.__getstate__` has no filter, `to_dict` has one (`state/process_data.py:224-255`).
5. After unpickle state is a copy: RLock recreated; EventManager drops queue, subscribers, `_router_manager`, and `reinitialize()` does not restore the router; `emit_event` with `_event_queue=None` does NOT crash (guard `events/core/manager.py:155`).
6. SRM `__setstate__` skips `ObservableMixin.__setstate__` → `_registry` and `log_*` not restored; `_log_*` go silent, `srm.log_info` → AttributeError.
7. SHM write failure → frames fall back to pickle via pipe, with a counter AND a throttled WARNING (`router_module/middleware/frame_shm_middleware.py:716-726`).
Extra: security risk low (local channels).
Traps: "the SRM is pickled at spawn, so a deny-list bug breaks spawn of all children" (dormant path); "nobody notices the pickle fallback" (there is a WARNING); "AttributeError on None in emit_event"; `_log_*` resolved via `__getattr__→_noop` (they are class methods).
