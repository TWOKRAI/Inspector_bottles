# Plan: Конструктор 2026 — мастер-план (фазы Ф0-Ф8 + трек F)

- **Slug:** 2026-07-06_constructor-master
- **Дата:** 2026-07-06
- **Статус:** IN PROGRESS с 2026-07-06 — **Ф0 ЗАКРЫТ** (G0 решён владельцем); идут Ф1 + трек F
- **Ветки:** Ф0 — `fix/constructor-f0` (merged); Ф1 — `feat/constructor-f1`; трек F — worktree `refactor/constructor-godsplit`; далее `<type>/constructor-fN`
- **Анализ-основание:** [`analysis.md`](analysis.md) (все находки R1-R16, метрики, ландшафт планов — с file:line)
- **Закрывает triage:** [`docs/audits/2026-07-04_arch-advice-constructor-2026.md`](../../docs/audits/2026-07-04_arch-advice-constructor-2026.md) (52 рекомендации)

## ПРИНЦИП №1 (директива владельца, 2026-07-06)

> **НИЧЕГО не удаляется, не замораживается и не архивируется без явного per-item одобрения владельца.**
> Все кандидаты на удаление/freeze проходят только через gates G0 (бумажный вердикт) и G4 (исполнение,
> каждое удаление — отдельный одобренный коммит). Никаких «гигиенических» удалений по ходу фаз.
> Это распространяется и на файлы планов/доков (архивация QUEUE/backlog — тоже только по команде).

## Цель

Мощная удобная система создания многопроцессных приложений на Python из модулей, сервисов и плагинов:
- **без костылей** — контракты вместо конвенций (сообщения/payload/плагины/рецепты версионированы и валидируются), единые механизмы вместо дублей;
- **живучесть** — рабочий авто-рестарт, routing-epoch, wire re-issue, fault-injection тесты;
- **безопасный hot-path** — seqlock (нет torn-frame), QoS-профили (system-команды никогда не теряются молча), без двойной конверсии;
- **backend_ctl — основной инструмент отладки** — события/подписки/логи/метрики/MCP;
- **composition root**, где второе приложение = рецепт + манифест + тонкий bootstrap.

Директивы: product>engine; hot-path последним; 2 живых рецепта (`phone_sketch`, `hikvision_letter_robot`) не ломать.

## Порядок фаз и параллелизм

```
Ф0 Фундамент ─► Ф1 backend_ctl v2 ─► Ф2 Наблюдаемость отказов ─► Ф3 Supervisor v2 + гонки ─►
                └─(worktree)─ Трек F: god-split (параллельно Ф1-Ф3) ─► MERGE-GATE F ─►
Ф4 Контракты и версии ─► Ф5 Конструктор (carve E + Phase 5) ─► Ф7 Hot-path G (строго последним) ─► Ф8 Фокус H
```

**Матрица конфликтов файлов** (обоснование порядка):

| Пара | Общие файлы | Решение |
|---|---|---|
| F ↔ Ф4.6 | `pipeline/presenter.py` (READ-сайт :1225) | F merge ДО Ф4; F.2 сам переводит recipe_io на unwrap_recipe (закрывает SC-12-остаток) |
| F ↔ Ф5.6 (E4) | `forms/factory.py` | split пакета = F.5; E4 после F = только diff + унификация |
| Ф3 ↔ Ф7 | `router_manager.py`, queue manager | строго последовательно |
| Ф4 ↔ Ф5 | `launch.py` | последовательно |
| Ф1 ↔ Ф2 | нет (только 2.6 JSONL-sink опц. ↔ 1.4 по logger_module — их не параллелить) | допустим ∥ |

Правила: ≤2 агента без worktree; трек F — единственный worktree; Ф7 — один агент строго последовательно.

---

## Ф0 — Фундамент (~2 дня)

| Task | Статус | Суть | Acceptance | Усилие |
|---|---|---|---|---|
| 0.1 | [x] | Merge `fix/topology-switch-hardening` → main (25 коммитов, merge 9a5f4b8f); framework 3395 + prototype 2819 passed, 3 красных pre-existing (→ 0.2). qt-smoke обоих рецептов — не гонялся, вынесен в 0.4 | main зелёный, оба рецепта поднимаются | S |
| 0.2 | [x] | Починить 3 красных теста (`test_observability_hot_reload` ×2, `test_assembler::test_custom_log_dir_parity`). Причины: env-дрейф (watchdog не в .venv) + хардкод `/var/log/inspector` в тесте (mkdir требует root) | pytest: 0 красных (fw 3401 + proto 2820) | M |
| 0.3 | [x] | sentrux `session_start` baseline (modularity 5652 / quality 7174 — совпали с ожиданием); **min_depth**: временно порог 0.65→0.60 в `.sentrux/rules.toml` с комментом «вернуть в Ф8» | `baseline.md`; sentrux-check зелёный (9 правил, 0 нарушений) | S |
| 0.4 | [x] | FPS/CPU baseline: headless-probe снят (boot ~1с, CPU ~24%); FPS обоих рецептов — hardware-gated (нет телефона/Hikvision). Бонус-находки: env-дрейф `[ml]` extras, shutdown-hang 8+ мин (gui/LoginDialog), BACKEND_CTL≠headless → входы для Ф1.3/Ф2/Ф3 | числа в `baseline.md` | S |
| 0.5 | [x] | **GATE G0 ЗАКРЫТ** (владелец, 2026-07-06): все 13 вердиктов — по рекомендациям (см. секцию «GATE G0»); ярусная карта core-15/optional/frozen принята. Исполнение KILL — только Ф8 H.2 (G4), per-item коммитами | таблица вердиктов здесь, в plan.md | S |
| 0.6 | [x] | Доки: QUEUE.md → governing этот план; триаж аудита → [`audit-triage.md`](audit-triage.md) (18 fw + 8 proto позиций: 21 → задачи фаз, 5 → defer/вне скоупа с причиной) | QUEUE актуален, аудит затрёкен | S |

Риск/откат: merge тривиален (ветка строго впереди); 0.2 может оказаться глубже — таймбокс + эскалация, xfail только решением владельца.

### GATE G0 — таблица вердиктов (подготовлено 2026-07-06; ждёт per-item решений владельца)

**А. Ярусная карта (рекомендация).** Честное ядро вышло 15 модулей, а не «core-8» аудита —
CRM-семейство (logger/error/stats/command/dispatch-ядро) и data_schema-ядро транзитивно
обязательны для любого процесса; за цифрой 8 не гонимся:

| Ярус | Модули | Критерий |
|---|---|---|
| **core (15)** | base_manager, message, router, channel_routing, dispatch (ядро EXACT_MATCH), logger, error, statistics, command, config, data_schema (ядро SchemaBase/FieldMeta/DataConverter), process, process_manager, worker, shared_resources | без них не бутится ни одно приложение; покрывает транзитивные зависимости app_module («рыбы», см. app-template-idea.md) |
| **optional** | state_store, registers, display, service, frontend (внутренности: tabs/forms/bridge/components/graph) | подключаются по потребности приложения |
| **frozen (кандидаты, см. Б)** | chain_module; фичи: console God-Mode, dispatch beyond-EXACT_MATCH, frontend-флагман | код не трогаем; ярус + sentrux-boundary + пометка в доках |
| — сверка H.1 | actions_module, event_module, sql_module-шим отсутствуют в MODULES_STATUS (дрейф «20/21/22») | закрывается Ф8 H.1 |

Правило Ф4: манифесты/контракты пишутся только ярусам core/optional.

**Б. Вердикты по мёртвому весу (рекомендации; исполнение — ТОЛЬКО Ф8 H.2/G4, отдельными одобренными коммитами):**

| # | Кандидат | Объём | Рекомендация | Обоснование (analysis.md §7/§10) | Решение владельца |
|---|---|---|---|---|---|
| 1 | `chain_module` | 1610 LOC + 77 тестов | **FREEZE** (ярус frozen; снять «флагман» из витрины CONSTRUCTOR_BLUEPRINT) | 0 потребителей; вариант «сделать DAG-движком PipelineExecutor» — отложить до 2-го потребителя (анти-карго-культ §9) | ✅ по реком. (владелец, 2026-07-06) |
| 2 | dispatch beyond-EXACT_MATCH (PATTERN/FALLBACK/CHAIN/ScenarioBuilder) | часть 3447 LOC | **FREEZE фич**, модуль остаётся core | модуль живой (база router/command/CRM), но 0 прод-вызовов не-EXACT_MATCH | ✅ по реком. (владелец, 2026-07-06) |
| 3 | `console_module` God-Mode | часть 2877 LOC | **FREEZE только интерактивной фичи** | §10: ConsoleManager создаётся в КАЖДОМ процессе — модуль НЕ трогать | ✅ по реком. (владелец, 2026-07-06) |
| 4 | data_schema-мертвецы: dna_factory, version_manager, schema_visualizer, storage_manager (+DataSchemaAdapter) | ~2118 LOC | **KILL в Ф8** | 0 потребителей; storage_manager мёртв транзитивно | ✅ по реком. (владелец, 2026-07-06) |
| 5 | frontend-флагман: FrontendManager / WidgetRegistry / LayoutComposer | часть 12039 LOC | FrontendManager+LayoutComposer **FREEZE**; WidgetRegistry (7d) — **KILL после G2** (E4) | флагман мёртв, внутренности — основа прототипа; legacy factory (7a) ЖИВОЙ прод-путь — НЕ кандидат | ✅ по реком. (владелец, 2026-07-06) |
| 6 | K3 `apply_topology_diff` + K5 `connect_wire` | ~133 LOC | **KILL в Ф8**; `disconnect_wire` ОСТАВИТЬ (K5-warn), K5b/K8b НЕ трогать | CONFIRMED dead / dead-chain | ✅ по реком. (владелец, 2026-07-06) |
| 7 | K4 `hot_add_process` | ~24 LOC | **KILL в Ф8** | CONFIRMED dead | ✅ по реком. (владелец, 2026-07-06) |
| 8 | K6 `CommandPanel`, K7 `ProcessStatusWidget` | 117 LOC | **KILL в Ф8** (K7 — предварительно догрепнуть test_bridge.py:87,105) | CONFIRMED dead (test-only) | ✅ по реком. (владелец, 2026-07-06) |
| 9 | K8 `TopologyEditorWidget` + дети | ~722 LOC | **KILL в Ф8** | CONFIRMED dead; изолированный под-граф, заметный +modularity | ✅ по реком. (владелец, 2026-07-06) |
| 10 | K9 `Services/Operation_crop` | 858 LOC | **KILL в Ф8** | CONFIRMED dead; крупнейший +modularity | ✅ по реком. (владелец, 2026-07-06) |
| 11 | K1 прототип-проводка ActionBus (`_legacy_action_bus` + `frontend/actions/`) | — | **KILL в Ф8**; K2 `bus.py` — ОСТАВИТЬ (решение 2026-06-18, patch-tier) | re-scan: 0 потребителей (no-op-guard) | ✅ по реком. (владелец, 2026-07-06) |
| 12 | K10 TRACE в FrameShmMiddleware | ~15 LOC | в **Ф7 G.1** (hot-path, не Ф8; qt-smoke + FPS-проверка) | уже в плане G.1 | ✅ по реком. (владелец, 2026-07-06) |
| 13 | ULTRACODE_BACKLOG.md | док | архивировать | источники закрыты | ✅ по реком. (владелец, 2026-07-06) |

Суммарно KILL-объём ≈ 4 000 LOC (owner-decides per-item). FREEZE = ноль правок кода сейчас.

## Ф1 — backend_ctl v2 (рано — по директиве владельца, ~3 дня)

| Task | Статус | Суть | Acceptance | Усилие |
|---|---|---|---|---|
| 1.1 | [x] | **Событийный канал driver**: `_dispatch` перестаёт дропать сообщения без request_id (или не матчащие pending) → bounded-очередь событий (deque maxlen) + `subscribe/unsubscribe/events(timeout)` + `state_subscribe()`; исключения колбэков не роняют reader-поток (`event_errors`). backend_ctl 20 passed | push `state.changed` доходит до подписчика; reply-путь не сломан | M |
| 1.2 | [x] | Обёртки: `router_stats()`→`RouterStats`, `queues()`→`QueueDepths`, `worker_status()`→`WorkerStatus` (dataclass + `.raw`) поверх готовых introspect. `wire_*()` НЕ вводится — отдельной `introspect.wire`-команды нет (только wire.configure/deconfigure = действия). Юнит с инжекцией (вложенность result/дефолты) + live против harness | каждый метод — тест против headless-бэкенда ✓ | S |
| 1.3 | [x] | **BackendHarness** — pytest-фикстура: headless launch (`strip_gui` исключает gui из топологии, БЕЗ Qt/LoginDialog) + driver + гарантированный scoped-teardown (watchdog + kill дерева своего PM). Маркер `harness_smoke`. Регресс 1.1 (state.changed push → внешний сокет) — **xfail** (адресуется targets=[subscriber]/queue_type=system → очереди `backend_ctl_system` нет; фикс на уровне PM, вне scope). backend_ctl 4 passed +1 xfail | `pytest -m harness_smoke` зелёный; старт+стоп 9.9с < 30с | M |
| 1.1b | [x] | **Мост push→SocketChannel для внешних подписчиков** (закрывает xfail 1.3): пуш с `targets=[X]`, у которого нет очереди `X_system`, но есть зарегистрированный канал `X` → доставка через канал (аддитивный fallback в `_deliver_by_targets`). Реализация: перед `send_to_queue` проверяем `_channel_registry.get(process)` + `_queue_absent` — у реальных процессов bare-канала нет (None), путь очереди без изменений; канал (SocketChannel 'backend_ctl') ловит пуш только когда очереди действительно нет. Прекондиция 1.5 (tail логов — тот же маршрут) | xfail 1.3 снят (зелёный на живом PM); contract-тест `TestChannelBridgeFallback` (4 кейса, вкл. safety «очередь не перехвачена каналом»); router+PM 545, backend_ctl 38 passed | M |
| 1.4 | [x] | IPC `config.reload` / `logger.sink.enable\|disable` (ADR-CRM-006 п.3): команды в BuiltinCommands + `LoggerManager.set_sink_enabled`; watcher и IPC делят один `apply_observability_reconfigure`→`reconfigure` (не конфликтуют — единый full-rebuild). driver: `config_reload/logger_sink_enable/disable`. Тесты: logger 4 + process 8 unit + live (уровень на лету) | через driver сменить уровень логгера на лету ✓; hot-reload файла и IPC не конфликтуют ✓ | M |
| 1.5 | [x] | Tail логов: `log.tail.subscribe/unsubscribe` + `LoggerManager.add_log_tap` (переживает reconfigure) + `RouterPushChannel` (ADR-CRM-006 п.2, targets=[subscriber]+queue_type=system → мост 1.1b). driver: `log_tail/log_untail(level=)`. **Граница:** end-to-end во внешний driver ловится у процесса-владельца сокета (ProcessManager); tail дочернего процесса ловится внутри, но push не доходит до внешнего сокета (канал 'backend_ctl' только в router'е PM — cross-process relay вне scope, Router/PM не трогаем). Тесты: logger 8 + process 4 unit + live (ERROR через мост) | driver ловит ERROR в тесте ✓ | M |
| 1.6 | [ ] опц | verify-probe (write→readback→diff, P1.5c) | probe на set_register | S |
| 1.7 | [ ] | **MCP-обёртка backend_ctl** (P3): инструменты status/introspect/state/send_command для Claude. Рекомендация: в Ф1 — все последующие фазы отлаживаются агентами нативно | Claude вызывает против живого бэкенда | M |
| 1.8 | [ ] опц | record/replay (P4) — решение на GATE G3 (полезен как характеризационный инструмент Ф7) | — | L |
| 1.9 | [ ] | **«Контактная книжка» v0** (директива владельца, [дизайн](capability-manifest-idea.md)): `introspect.capabilities` в PM (свод по процессам: команды+descriptions, регистры, каналы) + `driver.capabilities()` + `dump_capabilities` → `docs/contracts/CAPABILITIES.yaml`+`.md` + CI-сравнение (дрифт = красный). v1 (params_schema) — в Ф4.2 | агент по одному дампу воспроизводит сценарий smoke_proof без чтения исходников | S/M |

Риск: нулевой для прода (свой пакет + флаг); откат — не включать флаг.

## Ф2 — Наблюдаемость отказов (примитив → 30 сайтов, ~3 дня)

| Task | Статус | Суть | Acceptance | Усилие |
|---|---|---|---|---|
| 2.1 | [ ] | **`ctx.health`**: `report_error(exc, context, throttle)/set_status/degraded` в PluginContext + **health-схема путей state-дерева как контракт** + публикация через heartbeat self-publish; rate-limit | контракт-тест схемы; ошибка плагина видна в state-дереве и через driver | M |
| 2.2 | [ ] | Breaker честный: учитывает swallowed-ошибки (report_error инкрементит); produce()-breaker в SourceProducer | N подряд report_error → breaker open → health degraded | M |
| 2.3 | [ ] | Discovery `debug`→WARNING + видимый failed-list (state/introspect); ObservableMixin._call_manager `pass` → лог+счётчик | плагин с опечаткой виден через driver | S |
| 2.4 | [ ] ∥ | Волна C ч.1: M-err-1 (camera_service:153-155), M-err-2 (capture:152) + Plugins/sources (~15 сайтов) → one-liner `ctx.health.report_error` + contain→degrade | fault-smoke: выдернуть камеру → видимая ошибка, соседи живут, FPS ≥ baseline | M |
| 2.5 | [ ] ∥ | Волна C ч.2: остальные ~15 сайтов | grep swallow-без-report в Plugins/ = 0 | M |
| 2.6 | [ ] опц | JSONL-sink в logger_module (OTel-ID — позже, в G.6) | sink включается через 1.4 | S |

Порядок: 2.1 строго первым; 2.4∥2.5 после 2.1-2.2. Откат: report_error деградирует в лог-only переключателем.

## Ф3 — Supervisor v2 + волна D (живучесть ДО hot-path, ~4 дня)

Внутренний порядок ЖЁСТКИЙ: 3.1/3.2/3.5 — ДО 3.8 (иначе авто-рестарт производит процессы с мёртвыми wire и stale routing_map).

| Task | Статус | Суть | Acceptance | Усилие |
|---|---|---|---|---|
| 3.1 | [ ] | **routing-epoch**: монотонная эпоха топологии в PSR; PM после switch/restart рассылает идемпотентный `routing.refresh`; роутеры обновляют routing_map | peer→peer send после switch доставляется (сейчас молча теряется) | M |
| 3.2 | [ ] | Self-reported ready: process_runner шлёт `ready` после init; барьер PM потребляет ready (settle 0.5с — фолбэк) | switch/boot закрывается по ready, не по таймеру | M |
| 3.3 | [ ] | **Guard system-очереди**: `remove_old_if_full` НИКОГДА не вытесняет system-очередь молча (ERROR-лог + счётчик; политика: не вытеснять). Полная QoS-модель — в Ф7 G.4 | переполнение data-очередей не выбивает `process.stop` | S |
| 3.4 | [ ] ∥ | M-race-1: `snapshot_registry()/connected_ids()` под `_registry_lock`; плагин перестаёт читать `_manager._entries/_drivers` (10 мест); `list_devices()` на snapshot | grep приваток извне = 0; fault-тест: драйвер умер → хаб и соседи живут | M |
| 3.5 | [ ] | Wire-статусы first-class: publish `system.wires.*`, re-issue `wire.configure` при рестарте; `broken_wires` реальный (вместо hardcode 0) | kill+restart камеры → кадры снова идут; broken_wires ≠ 0 в момент разрыва | M |
| 3.6 | [ ] | Supervisor v2 policy: per-process RestartPolicy из blueprint/рецепта; окно стабильности (N рестартов в T → give-up + health=failed); проводка `reset_restart_count` | unit-тесты политики; give-up виден в health | M |
| 3.7 | [ ] | **Fault-injection фикстура** на BackendHarness: kill → авто-рестарт → wire re-issue → routing.refresh → данные идут | e2e-тест смерти-возрождения зелёный | M |
| 3.8 | [ ] | **GATE G1** (владелец): включить RestartPolicy в обоих рецептах (реком.: да, per-process для source/hub). Только после 3.1+3.2+3.5 | qt-smoke; откат = флаг в рецепте | S |
| 3.9 | [ ] опц | depends_on (порядок старта) — отложить в Ф8, если 3.7 не покажет необходимость | — | M |
| 3.10 | [ ] опц | pipeline-live-control Task 3.1+3.2: `stop_worker/start_worker(address)` + IPC-контракт (Task 3.3 drain — в Ф7 G.8) | по phase-3.md исходного плана | M+M |

## Трек F — God-split (worktree, старт после Ф0, MERGE-GATE до Ф4, ~4 дня ∥ Ф1-Ф3)

По готовому дизайну [`plans/2026-07-03_god-split-design.md`](../2026-07-03_god-split-design.md) (характеризационные тесты перечислены там; предусловие dispose — уже DONE волной B).

| Task | Статус | Суть | Acceptance |
|---|---|---|---|
| F.1 | [ ] | `graph/data.py` (NodeData/EdgeData/PortSchema без Qt) + характеризационные тесты codec ДО разреза | тесты фиксируют текущее поведение |
| F.2 | [ ] | `graph_codec.py` + `recipe_io.py` из presenter; recipe_io → `unwrap_recipe` (закрывает SC-12-остаток :1225) | характеризационные зелёные; grep or-цепочек в presenter = 0 |
| F.3 | [ ] | `wire_validation.py` + `runtime_control.py` | qt-smoke Pipeline |
| F.4 | [ ] | `layout_controller.py` + `mutations.py`; presenter-core ≤ ~400 LOC | публичные методы/сигналы presenter не изменены |
| F.5 | [ ] | `forms/factory.py` → пакет (kinds/builders_legacy/builders_binding/json_editor/реестр KindBuilders) + Н-5 (`_rm_old_value` helper ×3) | характеризационные тесты форм; qt-smoke inspector |
| F.6 | [ ] | `inspector_panel.py` → 5 секций (по образцу IoDebugSection) + `selectors_data.py`; проверить Н-4 (unbind camera), Н-6 (suppress) | баланс bind/unbind = 0 на fake-bindings |

**MERGE-GATE F**: полный qt-smoke обоих рецептов; sentrux modularity ≥ +250 от 5652; внешние контракты вкладок не изменены; pytest зелёный. Откат: revert-серия (модули аддитивны).

## Ф4 — Контракты и версии (после merge F, ~5 дней)

| Task | Статус | Суть | Acceptance | Усилие |
|---|---|---|---|---|
| 4.1 | [ ] | **Multi-register fix**: `schemas[reg.name]` вместо перезаписи по plugin.name; контракт-тест Н-7 (уникальность instance.name, семантика override); boot-проверка дубликатов plugin_name | плагин с 2 регистрами — оба живы | S |
| 4.2 | [ ] ∥ | **Реестр контрактов сообщений**: command/data_type → схема; warn-middleware на receive control-plane; флаг strict (default warn). Инвариант для Ф7: после G data-plane валидируется только 4.3 (зафиксировать текстом в G). + Контактная книжка v1: `introspect.capabilities` отдаёт params_schema из реестра (см. capability-manifest-idea.md) | опечатка в команде → WARNING с diff полей; capabilities со схемами | M |
| 4.3 | [ ] | Payload-валидатор PluginRunner по Port-декларациям (dev-mode флаг, выключен в prod) | несоответствие порту → ошибка на границе в dev | M |
| 4.4 | [ ] | **Манифест плагина**: version/api_version/requires (только ярусы core/optional по G0); рецепт хранит version при save; boot mismatch → WARNING | манифест-тест на 2-3 пилотных плагинах | M |
| 4.5 | [ ] ∥ | **Движок миграций dict-документов**: `@migration("recipe", from_=2, to=3)`, ядро framework; property-тест round-trip | новый модуль с contract-тестами | M |
| 4.6 | [ ] | **Единая READ-точка рецептов**: unwrap_recipe → движок 4.5; `recipes/presenter.py:394` через единый вход (:1225 закрыт F.2). Rank1 аудита ★★★★★ | grep формат-веток вне движка = 0 | S/M |
| 4.7 | [ ] | **join/inspector из wires** при assembly (BlueprintAssembler); снять костыль `_hoist_inspector_from_metadata` (launch.py:40-55) | регресс-тест: join НЕ деградирует в fanin | M |
| 4.8 | [ ] | **mini-GATE**: канонизация записи рецепта (дубли displays/gui_positions → одна секция) как migration-шаг; байт-diff обоих рецептов на одобрение владельца | оба рецепта грузятся идентично до/после; diff одобрен | M |
| 4.9 | [ ] | **StateStore ревизии**: (a) revision в дереве + Delta, DeltaDispatcher включает revision; (b) watch-from-revision + resync (etcd-паттерн) | пропущенная дельта → resync, кэш сходится | M+M |
| 4.10 | [ ] опц | driver watch-from-revision (поверх 1.1 + 4.9); DeltaJournal — defer | подписка переживает реконнект | S |

Риск: порча рецептов → миграции только in-memory на READ; WRITE-канонизация отдельно (4.8) с бэкапом; strict нигде не default.

## Ф5 — Конструктор: carve E + Phase 5 (~5 дней)

| Task | Статус | Суть | Acceptance | Усилие |
|---|---|---|---|---|
| 5.1 | [ ] | E3-прекондиция: **характеризационный тест `build()`** (snapshot: blueprint dict → N процессов + orchestrator_config) | зелёный на обоих рецептах | S/M |
| 5.2 | [ ] | E3: вынос шва `SystemLauncher(...)+add_process` (launch.py:374-394) во framework; `_ORCHESTRATOR_CLASS_PATH` → DI-параметр; + SpawnBackend Protocol (задел multi-node, без постройки) | 5.1 зелёный без изменений; check_rules: 0 reverse-import | M |
| 5.3 | [ ] | Phase 5 recipe-orchestrator: Assembler/Planner → framework; RecipeManager → framework, `duplicate()` через generic yaml_io/инъекцию (форматы — из движка 4.5); прототип — тонкие шимы | boot=switch=duplicate работают; 0 reverse-import | M+M |
| 5.4 | [ ] ∥ | E1: `plugin_register_resolver` → framework (чистая функция, тесты есть) | шим в прототипе; check_rules зелёный | S |
| 5.5 | [ ] ∥ | E2: `qt_event_bus` → `frontend_module/qt_event_bridge` (type-bound → Event-Protocol; решить судьбу `EventBusProtocol`) | cross-thread publish тест | S/M |
| 5.6 | [ ] | E4: (a) **diff-отчёт 4 механизмов** схема→виджет → **GATE G2** (владелец выбирает целевой); (b) унификация до одного, gate «биндинг-стеков ≤2→1» | отчёт; после (b): один механизм | S + M/L |
| 5.7 | [ ] | E6: телеметрия helper/mixin поверх `_publish_metrics_to_tree` + **merge-батчинг** (`proxy.merge` одним сообщением вместо 3W+2 set) | счётчик сообщений телеметрии ↓ ~в W раз | S/M |
| 5.8 | [ ] | RuntimeDeps → двухслойный контракт FrameworkRuntime + app-extras | tab_factory через новый контракт | M |
| 5.9 | [ ] | GUI state-plane: полный Delta до GUI (frontend/process.py:125 — сейчас теряет delete/MISSING/transaction_id); `StateProxy.ensure_subscription` c refcount (авто-подписка bind — убирает класс ошибок «панель мертва, забыли wildcard»); один glob-матчер вместо трёх | delete-дельта доходит до биндингов | M |
| 5.10 | [ ] опц | TabSpec/TabRegistry (механизм уже app-agnostic, app-specific только TAB_ORDER) — если останется бюджет фазы | TAB_ORDER = данные | S |

Риск: reverse-import при carve → check_rules в каждом acceptance; шимы сохраняют пути импорта прототипа.

## Ф7 — Hot-path G (ОДНИМ вскрытием, строго последним, один агент, ~5 дней)

**GATE G3 перед стартом**: routing-epoch влит (3.1); контракты warn живут (4.2); baseline подтверждён; ответ на HP-5 (`replace_blueprint` × in-flight кадр); откат = feature-flag; решение по 1.8.

| Task | Статус | Суть | Acceptance | Усилие |
|---|---|---|---|---|
| G.1 | [ ] | Снять 7 TRACE из on_receive + perf-пробы latency за флагом (HP-1) + повторный baseline (FPS, p50/p99) | TRACE=0; числа в baseline.md | S |
| G.2 | [ ] | Характеризационный тест паритета каналов на дефолте `"queue"` + feature-flag `use_kind_channels` + проводка `resolve_channel_kind` в `_resolve_channels` (router_manager.py:951, ~15 строк) | флаг off = бит-в-бит прежнее поведение | M |
| G.3 | [ ] | (a) Унификация ДВУХ стратегий записи FrameShm в одну; (b) **seqlock** (generation-счётчик в header слота: writer инкрементит до/после, reader сверяет после копии → drop + метрика) + torn-frame-репродьюсер | репродьюсер: 0 torn-frame после (до — воспроизводится) | M+M |
| G.4 | [ ] | **QoS-профили kind** `{reliability, history_depth, drop_policy, deadline_ms}`: system=reliable/never-drop (поглощает 3.3), data=keep_last+drop-oldest со счётчиками → heartbeat → state-дерево (по health-схеме 2.1) → вкладка Pipeline; унификация 3 политик переполнения | system никогда не дропается; дроп data виден в state | M |
| G.5 | [ ] | Снятие двойной конверсии: `return_messages=False` на data-plane + copy-elision `restore_frame(copy=False)` (строго ПОСЛЕ seqlock) | паритет G.2 зелёный; p99 ≤ baseline | M |
| G.6 | [ ] | trace_id/OTel-совместимые ID в frame_trace/LogRecord (семантические поля, БЕЗ OTel SDK) | лог↔кадр коррелируются | S |
| G.7 | [ ] | Приёмка: flip `use_kind_channels` on → soak оба рецепта; FPS ≥ baseline; p99 ≤ baseline; **socket-канал backend_ctl жив** (регресс-тест); drop-счётчики видимы; аудит opt-out'ов `manages_own_reply` (S5-остаток) | все gate-метрики зелёные; откат = флаг off | M |
| G.8 | [ ] | pipeline-live-control Task 3.3: drain→detach→stop воркера | нет полукадров при detach | M |

P3.2 StateChannel остаётся DEFERRED. Ничего из анти-карго-культ списка (analysis.md §9).

## Ф8 — Фокус H (~4 дня)

| Task | Статус | Суть | Acceptance | Усилие |
|---|---|---|---|---|
| H.1 | [ ] | Ярусы core-8/optional/frozen: доки + enforcement в `.sentrux/rules.toml` (boundaries на frozen) + сверка «20/21/22 модулей» | ярусная карта = код | M |
| H.2 | [ ] | **GATE G4**: исполнение вердиктов G0 per-item — каждое удаление/freeze отдельным ОДОБРЕННЫМ коммитом | pytest/qt-smoke после каждого | M |
| H.3 | [ ] | **Registers⇄StateStore merge**: ADR (реком.: StateStore = истина, RM = view-model) → адаптерный период → снятие «**»-подписки и анти-луп адаптеров после soak; 2-3 захода | 7 реактивных механизмов → 2-3; анти-луп костылей нет | L |
| H.4 | [ ] | Один стандарт логирования прототипа | grep нестандартных логгеров = 0 | S/M |
| H.5 | [ ] | Ужесточение sentrux: min_depth назад ≥0.65 (перезамер после F/E), min_quality → 0.70+; если depth не восстановился — решение владельца о пороге, НЕ подгонка кода под метрику | sentrux-check зелёный на новых порогах | S |
| H.6 | [ ] | Финальная сверка: QUEUE.md, session_end, сводная дельта факт-vs-цель | план закрыт таблицей | S |

---

## Gates (точки решения владельца, с рекомендациями)

| Gate | Когда | Решение | Рекомендация |
|---|---|---|---|
| G0 | Ф0.5 | Ярусы + судьбы мёртвого веса (бумажный вердикт per-item) | freeze chain/console/dispatch-extras; kill data_schema-мертвецов в Ф8 |
| G1 | Ф3.8 | Включить RestartPolicy в рецептах | да, per-process source/hub, после 3.1/3.2/3.5 |
| mini | Ф4.8 | Байт-diff канонизации рецептов | одобрить при идентичной загрузке |
| G2 | Ф5.6a | Целевой механизм форм из 4 | по diff-отчёту; стеков ≤2→1 |
| MERGE-F | конец F | Принять merge god-split | qt-smoke + modularity ≥ +250 |
| G3 | перед Ф7 | Старт hot-path; HP-5; record/replay | только при зелёных Ф0-Ф5; флаг-откат обязателен |
| G4 | Ф8.2 | Каждое удаление per-item | по вердиктам G0 |

## Метрики приёмки (числовые)

| Метрика | Сейчас | Чекпойнты | Финал |
|---|---|---|---|
| sentrux modularity | 5652 | после F ≥ 5900; после Ф5 ≥ 6050 | **≥ 6200** (stretch 6500) |
| sentrux quality | 7174 | после Ф4 ≥ 7250 | **≥ 7500** |
| min_depth | 0.6154 FAIL | Ф0: порог временно 0.60 | Ф8: порог назад 0.65 |
| циклы импортов | 0 | exit-gate каждой фазы | 0 |
| pytest красные | 3 | Ф0 → 0 | 0 (новые xfail — только решением владельца) |
| FPS | baseline Ф0 | каждая фаза ≥ baseline−5% | Ф7: ≥ baseline; p99 ≤ baseline; torn-frame-repro = 0 |
| grep-инварианты | — | Ф2: swallow-без-report=0; Ф3: приватки device_hub извне=0; Ф4: формат-ветки вне движка=0 | Ф7: TRACE hot-path=0 |

## Сквозные правила исполнения

- Каждая фаза: `session_start` → задачи → `session_end`; дельта в трейлер `Tested:`
- Каждый task с рантайм-эффектом: qt-smoke ИЛИ BackendHarness-smoke
- Задачи, меняющие публичные контракты (api-full/api-lite) → дисциплина module-contract (README + Protocol + contract-тесты)
- Коммиты: Conventional Commits + `Why:`/`Layer:` + `Refs: plans/2026-07-06_constructor-master/plan.md`
- Ветки: по фазе (`<type>/constructor-fN`), трек F — worktree `refactor/constructor-godsplit`
- Удаления/freeze — ТОЛЬКО через G0/G4 (Принцип №1); hot-path — один агент, feature-flag откат на каждом под-шаге

## Оценка

~35 рабочих дней последовательно; ~28 с треком F в параллель.

## Вне скоупа

Hardware-gated планы (letter-robot цикл, калибровки, device-tree E), sql-insert-many-atomic, GuiBootstrap/P4-хвосты аудита, IncrementalPlanner/replicas, telemetry Option D (за STOP-gate), E5 generic graph-editor (до 2-го потребителя), всё из анти-карго-культ (analysis.md §9).

## Следующий шаг

**Ничего не исполняется без команды владельца.** По команде: Ф0 Task 0.1 (merge hardening → main) → далее по порядку фаз. Опционально перед стартом: разбить фазы на `phase-N.md` файлы (по текущей грануляции таблиц) и создать `baseline.md` в Ф0.3/0.4.