# Анализ архитектуры «Конструктор 2026» — все находки и замечания

> Снимок: **2026-07-06**. Ветка: `fix/topology-switch-hardening` (20 коммитов впереди main, 0 позади).
> Метод: 3 Explore-агента (runtime-ядро / прототип+backend_ctl / дайджест планов) + Plan-агент (дизайн) +
> MCP (sentrux, codegraph, qex, serena, graphify). Каждое утверждение проверено по живому коду с file:line.
> План исполнения — рядом: [`plan.md`](plan.md).

---

## 1. Вердикт одной строкой

Ядро фреймворка — уровня индустрии 2026 (Claim-Check кадров через SHM = loaned messages ROS2; транзакционный hot-swap с rollback; ProcessTreeGuard; lifecycle плагинов = ROS2 managed nodes; типизированные порты = GStreamer caps; 0 import-циклов, DSM above_diagonal=0). Отставание НЕ в ядре, а в трёх слоях: **метаданные** (версии/контракты/QoS — всё на конвенциях), **супервизия** (флагманский авто-рестарт выключен, routing-epoch отсутствует), **фокус** (~9k LOC мёртвых подсистем размывают конструктор из ~8 реальных модулей на 22 заявленных).

## 2. Свежие метрики (sentrux, 2026-07-06)

| Метрика | Значение | Комментарий |
|---|---|---|
| Quality signal | **7174** | рост: 7031 (18.06) → 7173 (03.07) → 7174 |
| Modularity | raw 0.3478 / **5652** | bottleneck №1; 1600 из 2687 рёбер межмодульные |
| Acyclicity | 0 циклов / 10000 | идеально, держать |
| Depth | 5 / 6154 | **FAIL** правила `min_depth 0.65` (единственное нарушение из 9 проверенных) |
| Redundancy | 0.0987 / 9013 | хорошо |
| Тесты | framework 3395 + prototype 2819 passed | **3 pre-existing красных**: `test_observability_hot_reload` ×2, `test_assembler::test_custom_log_dir_parity` |
| Test coverage ratio | 723/2809 файлов | 786 тест-файлов |

## 3. Что УЖЕ сделано (не переделывать! — защита от stale-канона)

| Что | Доказательство |
|---|---|
| Волна A (гигиена: хвосты backup, .tmp_factcheck, битый test_plugin_chain) | коммит 82d1f517 |
| Волна B (утечки/teardown: dispose презентера+инспектора+таба, owner-teardown GuiStateBindings, `remove_state_listener`, снятие K1 `_legacy_action_bus`) | 4f5ad74c, 1b0e3d5d, 341b05f9, 8b7d10a0 |
| topology-switch-hardening 7/7: rollback тем же 5-фазным конвейером, `stop_many` ensure-stopped + подтверждение смерти, нет «призраков» конфигов, `unregister_process` (ADR-SRM-009), readiness-барьер death-watch + карта `ready` (settle 0.5с), монитор: синхронная пауза + рестарт через IPC `process.restart` вне потока монитора (`_pending_restarts`, БЕЗ sleep) | 9a9224f4…d835fb33 |
| transport-router-hub P0-P2 + **P3.1 FrameChannel** (два FrameShmMiddleware слиты) + **P4.4 command-bus** (kind-router по type, CommandManager — владелец команд, транспортный авто-reply по request_id — S5 auto-reply ≈ ноль кода) | план TRH, ADR-COMM-005 |
| observability-control-plane ПОЛНОСТЬЮ (reconfigure CRM, sink-реестр, hot-reload ConfigFileWatcher). НО: IPC-команды `config.reload`/`logger.sink.enable` — только design (ADR-CRM-006), НЕ реализованы | архив плана |
| recipe-orchestrator-unify Phase 1-4 (одна дорога топологии: boot = switch через BlueprintAssembler + TopologyManager) | план |
| backend_ctl P0-P2 (SocketChannel в router PM, driver, introspect.*) | архив 2026-05-31_backend-control-mcp |
| comm-system §11 quick-wins — ВСЕ 24 закрыты | CSA §12 трекинг |

## 4. Подтверждённые проблемы runtime (проверено по коду 06.07.2026)

| № | Проблема | Факт / file:line |
|---|---|---|
| R1 | **Авто-рестарт мёртв в prod**: `RestartPolicy.enabled=False` с TODO; прототип нигде не включает; `reset_restart_count` — 0 вызовов. Механика после hardening корректна, но путь не активирован | `process_manager_module/core/restart_policy.py:24`, `monitor/process_monitor.py:639` |
| R2 | **routing-epoch ОТСУТСТВУЕТ**: рестарт/switch не обновляет routing_map соседей; `process.relay` — частичный обход; прямой peer→peer send после switch **молча теряется** (`put_nowait→True` в мёртвую очередь) | `process/process_manager_process.py:1069-1089`, docstring :801-820 |
| R3 | **Torn-frame по конструкции**: round-robin `% coll` без seqlock/генераций; 7 `[TRACE]`-логов в `on_receive` hot-path; `RingBufferWriter` с seq-трекингом экспортирован — 0 прод-потребителей; **ДВЕ стратегии записи в одном классе** (`strip_and_write` round-robin + `on_send` find_free_index) = 2 точки правки для seqlock | `router_module/middleware/frame_shm_middleware.py:180-181` |
| R4 | **Три политики переполнения**: `QueueRegistry.remove_old_if_full` МОЛЧА дропает СТАРОЕ **включая system-очередь с командами** (`process.stop` может быть тихо вытеснен бурстом!); AsyncSender дропает новое с warning (PriorityQueue 512); DataReceiver блокируется | `shared_resources_module/queues/core/manager.py:266-271` (вызов :156); `router_module/core/_sender.py:60,141-147`; `process_module/generic/data_receiver.py:82-113` |
| R5 | **Двойная Pydantic-конверсия на кадр**: `receive(return_messages=True)` → `Message.from_dict`, DataReceiver тут же `.to_dict()` | `router_manager.py:542,600,607`; `data_receiver.py:148-149` |
| R6 | **Multi-register overwrite** (потеря данных): `schemas[plugin.name]` перезаписывается в цикле `reg_cls` — при >1 регистра выживает последний; `plugin_name` всегда перекрывает классовый `name`, контракт-теста нет (Н-7) | `process_module/generic/plugin_orchestrator.py:249-251, :201-205` |
| R7 | Discovery: `except Exception → logger.debug` — плагин с опечаткой **молча исчезает** из каталога | `process_module/plugins/registry.py:173-179` |
| R8 | `ObservableMixin._call_manager`: `except Exception: pass` — мета-дыра в ядре observability | `base_manager/mixins/observable_mixin.py:321-328` |
| R9 | **Message без контракта**: union 9 типов, `extra="allow"`, `Message.create(schema=)` — 0 прод-вызовов, валидации на receive НЕТ. Опечатка в ключе = тихий сбой в другом процессе | `message_module/core/message.py:52,133-173` |
| R10 | Readiness: death-watch есть (ok); **self-reported ready из process_runner НЕТ** (runner ставит только error при init-fail) | `runner/process_runner.py:177-189` |
| R11 | **StateStore без ревизий**: watch-from-revision нет; delta_sink на GUI-миле сплющивает `{path,value}` — теряет delete/MISSING/transaction_id (IPC-путь DeltaDispatcher шлёт полный `to_dict()` — ок) | `frontend/process.py:125`; `state_store_module/manager/delta_dispatcher.py:118` |
| R12 | `PluginContext` — только `log_info/log_error`; **`ctx.health` НЕТ** | `process_module/plugins/base.py:100-103` |
| R13 | **Circuit breaker слеп**: только в PipelineExecutor и только на ПРОБРОШЕННОЕ исключение; `produce()` вообще без breaker (лог + `items=[]` — swallowed-ошибка полностью невидима) | `pipeline_executor.py:197-214`; `source_producer.py:101-103` |
| R14 | `broken_wires` захардкожен 0 с TODO — health-метрика всегда зелёная | `monitor/process_monitor.py:294-295` |
| R15 | Волна C не сделана: ~30 сайтов `except Exception: return []` в Plugins/sources и hot-path (камера умирает молча → чёрный экран) | `Plugins/sources/camera_service/plugin.py:153-155`, `capture/plugin.py:152` |
| R16 | Волна D не сделана: device_hub — 10 мест плагин читает приватные `_manager._entries/_drivers` без лока | `Plugins/hub/device_hub/plugin.py:210,223,275,287,335,446,451,452,900,903` |

## 5. Composition root — цена второго приложения (главный анти-декларативный узел)

Рецепт уже декларирует **~95% приложения**: processes/plugins по FQN (словарь: 51 плагин Plugins/ + 5 Service-embedded = 56, авто-discovery), точные wires по портам, displays, devices, и даже декларативный пульт (`control_panel` ~40 контролов). Но второе приложение = форк кода:

1. **`frontend/app.py::run_gui` — 610 строк, 31 императивный шаг** ручной проводки (auth→services→registers→topology→bindings→app_services→tabs), не генерируется из конфига (`app.py:55-666`)
2. `_ORCHESTRATOR_CLASS_PATH` хардкод (`backend/launch.py:32`)
3. **SystemBuilder в app-слое**; универсальный шов = `SystemLauncher(...)+add_process` (`launch.py:374-394`); **характеризационного теста `build()` НЕТ** — долг
4. `TAB_ORDER` — 7 табов захардкожены (`tab_factory.py:54-97`); `RuntimeDeps` — frozen 11 полей + 2 `Any`
5. **Формат рецепта — костыли**: дубли `displays` (bindings в blueprint + definitions top-level) и `gui_positions` ×2; `unwrap_recipe` or-цепочки (`launch.py:58-89`); `_hoist_inspector_from_metadata` (:40-55) — уже дал баг «join молча деградирует в fanin»; 3 формата (v3/v2/legacy), READ-разбор в 3 сайтах (`pipeline/presenter.py:1225,1652`; `recipes/presenter.py:394`)
6. Prototype-швы разбора формата размазаны: `inject_recipe_devices`, извлечение display_definitions в `orchestrator.apply_topology`

## 6. backend_ctl — состояние и дыры (основной инструмент отладки владельца)

**Есть** (P0-P2 DONE): `SocketChannel 127.0.0.1:8765` как канал RouterManager в PM + `SocketBridgeAdapter` (форвардит ЛЮБОЕ router-сообщение через `router.request` → произвольная команда достижима); `BackendDriver` (request / send_command / system_command / introspect_handlers / introspect_registers / introspect_status / set_register); включение `BACKEND_CTL=1` или `system.yaml`; headless-подъём через `main.bootstrap()`; киллер-фича — диагноз «нет worker-side приёмника» за секунды. Слой корректно оформлен в `.sentrux/rules.toml` (тулинг: backend_ctl → app, обратное запрещено boundaries).

**Дыры**:
1. **Нет стриминга**: `driver._dispatch` ДРОПАЕТ любое сообщение без `request_id` (`driver.py:167-169`) → `state.subscribe` бесполезен (push-дельты физически не принимаются), нет tail логов, нет live-мониторинга (только поллинг `state.get`)
2. Готовые на бэкенде `introspect.router_stats`/`introspect.queues` (P1.5a) и `worker.*`/`wire.*` — не обёрнуты методами driver
3. **MCP-обёртка (P3) не сделана** — каждый вызов агента = Bash+Python-сниппет
4. verify-probe write→readback→diff (P1.5c) и record/replay (P4) — не сделаны
5. Один read-поток на соединение → in-flight запросы сериализуются
6. IPC `config.reload`/`logger.sink.enable` спроектированы (ADR-CRM-006), но не реализованы — hot-управление observability из driver невозможно

## 7. Мёртвый вес и дубли механизмов

> **ПРИНЦИП ВЛАДЕЛЬЦА: ничего не удаляется и не замораживается без явного per-item одобрения.**
> Таблица ниже — кандидаты на РЕШЕНИЕ владельца (gate G0 плана), не на действие.

| Кандидат | Объём | Факт |
|---|---|---|
| `chain_module` | 1661 LOC + 77 тестов | полный DAG-движок, **0 потребителей** (реальный конвейер — `pipeline_executor.py`); доки продают как флагман |
| `dispatch_module` | 3447 LOC | PATTERN/FALLBACK/CHAIN/ScenarioBuilder — реально используется только EXACT_MATCH |
| `data_schema_module` | ~2118 LOC мёртвых | dna_factory, version_manager, storage_manager, visualizer — 0 потребителей |
| `console_module` | 1675 LOC | «God Mode», 0 использований |
| `frontend_module` флагман | — | FrontendManager не инстанцируется, WidgetRegistry/LayoutComposer — 0 использований |
| `Services/Operation_crop` | 858 LOC | K9, dead |
| K3-K8 (topology_bridge мёртвые ветки, CommandPanel, editor-виджет…) | ~1000 LOC | per-item таблица в master-rework-roadmap §6 |
| **Дубли механизмов** | — | 7 реактивных механизмов (Qt-сигналы, EventBus, StateStore-подписки, Registers-observers, Router-каналы, Config.subscribe, ActionBus); **4 механизма «схема→виджет»** (legacy factory / binding-aware — прод-мёртв form_ctx=None / params_form — 0 потребителей / WidgetRegistry — 0); RegistersManager⇄StateStore «**»-подписка с анти-луп адаптерами; 3 стандарта логирования; доки расходятся 20/21/22 модуля |

## 8. Ландшафт планов (что живо, что осталось)

- **Governing до этого плана**: `2026-07-03_review-and-constructor-plan.md` (волны A-G; A+B DONE) + `master-rework-roadmap.md` (W-решётка, синтез 18.06) + `2026-07-03_god-split-design.md` (волна F — дизайн ГОТОВ, не начат)
- **Незатрёкенный аудит**: `docs/audits/2026-07-04_arch-advice-constructor-2026.md` — 52 рекомендации P0-P4, ни один план не ссылался (QUEUE.md фиксирует это как дыру). Данный план закрывает triage
- **Осталось по волнам**: C (error-swallow, ~30 сайтов), D (device_hub гонки), E (carve: E1 resolver, E2 qt_event_bus, E3 шов SystemBuilder, E4 forms→1, E6 telemetry helper), F (god-split: presenter 1828 / factory 1191 / inspector_panel 1152), G (hot-path: kind-каналы проводка ~15 строк за gates)
- **recipe-orchestrator Phase 5**: carve RecipeManager/Assembler/Planner во framework; **блокер**: `RecipeManager.duplicate()` (manager.py:204-215) импортирует `multiprocess_prototype.recipes.yaml_io` (reverse-import) + знает v3/legacy формат
- **pipeline-live-control Этап 3**: `stop_worker/start_worker(address)` + IPC-контракт (можно сейчас); drain→detach→stop (Task 3.3 — ждёт паритета FrameChannel)
- **p4.4.4 lifecycle-feedback**: BLOCKED (ctx для вложенных process.command), опционально
- **telemetry Option D**: DEFERRED за STOP-gate (2-й реактивный потребитель ИЛИ замер боли двойного glob)
- **ULTRACODE_BACKLOG**: фактически пуст (источники закрыты) — кандидат в архив (решение владельца)
- **Hardware-gated** (вне скоупа): letter-robot-cycle (ждёт калибровку px→мм), device-tree Фаза E (hikvision master-detail — KEYSTONE), калибровки, draw-mode (freeze)
- **Пересечения** (одна работа под 3 именами): kind-каналы = TRH P3 = CSA §12 P1 = волна G; carve = Phase 5 + CSA §15 + волна E; undo/ActionBus — РЕШЕНО framework-first (2026-06-18), не трогать

## 9. Чего НЕ делать (анти-карго-культ, аудит §4)

Кластер/брокер/DDS; CRDT/полный event-sourcing; in-process hot-reload плагинов (честная единица = перезапуск процесса); переписывание CRM на OTel SDK (только семантические поля + JSONL-sink); autoscale до замера; iceoryx2/Arrow биндинги (брать идею seqlock, не зависимость).
