# Архитектурные советы: конструктор 2026 (framework + prototype)

> Синтез multi-agent анализа 2026-07-04 (10 read-only ридеров: 8 подсистем + адвокат дьявола +
> сверка с ландшафтом 2025–2026). Каждое утверждение проверено ридером по живому коду с file:line.
> Контекст: продолжение [master-rework-roadmap](../../plans/master-rework-roadmap.md) и
> [review-and-constructor-plan](../../plans/2026-07-03_review-and-constructor-plan.md) (волны A–G).
> Здесь — то, чего в волнах НЕТ или что их усиливает.

---

## 0. Вердикт

Ядро уже на уровне индустрии 2026, местами выше среднего OSS:

- **Claim Check кадров через SHM** = loaned messages ROS2/iceoryx — совпали с индустрией самостоятельно;
- **Транзакционный hot-swap** (snapshot → apply → teardown_partial → rollback + debounce) — редкость даже в зрелых системах;
- **ProcessTreeGuard** (Job Object / setsid+killpg + pid_registry с реапом сирот) — сильнее большинства Python-оркестраторов;
- **Lifecycle плагинов** (IDLE→READY→RUNNING→PAUSED→STOPPED) = ROS2 managed nodes; **типизированные порты** с MIME-иерархией = GStreamer caps;
- **Гигиена слоёв**: 0 import-циклов, DSM above_diagonal=0, sentrux-enforcement, ADR-культура.

Отставание — НЕ в ядре, а в трёх слоях: **метаданные** (версии, контракты, QoS — всё на конвенциях),
**супервизия** (флагманская RestartPolicy выключена TODO-шкой), **фокус** (~9k LOC мёртвых подсистем
внутри framework размывают то, что реально является конструктором).

---

## 1. Пять сквозных тем (нашли ≥2 независимых ридера)

### Тема 1 — Hot-path: один вскрыш, три фикса (в волну G)

Волна G и так вскрывает кадровый hot-path (S4 kind-каналы). Три находки требуют делать это ОДНИМ заходом:

1. **Torn-frame по конструкции** 🔴. `FrameShmMiddleware.strip_and_write` пишет round-robin `% coll`
   без генераций/секлока (`frame_shm_middleware.py:179-183`); формат буфера не содержит seq-слова.
   Медленный читатель молча получает рваный кадр. Готовый `RingBufferWriter/Reader` с seq-трекингом
   (`buffers/ring_buffer.py`) экспортирован, но 0 прод-потребителей. **Фикс:** generation-счётчик в
   header слота (seqlock: writer инкрементит до/после записи, reader сверяет после копии → drop + метрика).
   Закрывает половину HP-5. Без этого `copy=False` (zero-copy) небезопасен в принципе.
2. **S4 kind-каналы проводить как QoS-профили, а не имена типов.** Сейчас ТРИ расходящиеся политики
   переполнения: `QueueRegistry.remove_old_if_full` молча выкидывает СТАРОЕ (включая команды из
   system-очереди — `process.stop` может быть тихо вытеснен бурстом, без лога!); `AsyncSender` дропает
   НОВОЕ с warning; `DataReceiver` блокируется и не дропает никогда. **Фикс:** kind несёт профиль
   `{reliability, history_depth, drop_policy, deadline_ms}` (словарь ROS2 QoS): system = reliable/never-drop,
   data = keep_last+drop-oldest со счётчиком. Счётчики drop/depth → heartbeat → state-дерево → вкладка Pipeline.
3. **Двойная Pydantic-конверсия на каждый кадр**: `RouterManager.receive(return_messages=True)` делает
   полный `Message.from_dict` (validate), `DataReceiver` тут же конвертит обратно `to_dict()`. **Фикс:**
   data-plane потребителям `return_messages=False` (plain dict насквозь). Туда же copy-elision:
   `restore_frame(copy=False)` для read-only потребителей + pass-through SHM-ref на транзитных хопах
   (сейчас ~4 memcpy × 6 МБ на кадр 1080p на цепочке из 3 процессов) — строго ПОСЛЕ seqlock.

### Тема 2 — Супервизия: флагман выключен (крупнейший разрыв заявка↔код)

Роадмап §1.1 записывает «RestartPolicy/auto_restart» в «80% изоляции даром» — по коду это спящая фича:

- `RestartPolicy.enabled=False` с TODO (`restart_policy.py:24`), прототип её нигде не включает →
  **авто-рестарт в живом приложении не работает вообще**;
- политика одна на всех (камере нужен агрессивный restart, sql-writer — transient); счётчик рестартов
  никогда не сбрасывается (`reset_restart_count` — 0 вызовов) → 3 краша за месяц = FAILED навсегда;
- `_try_auto_restart` делает `time.sleep(backoff)` ВНУТРИ monitoring-loop → на время рестарта одного
  процесса монитор слеп для всех;
- **рестарт не перепрошивает потребителей**: соседи держат stale-копию routing_map → peer→peer трафик
  к перезапущенному процессу молча теряется (docstring `process.relay` сам это признаёт).

**Пакет «Supervisor v2» (framework, M):** per-process restart-секция в ProcessConfig + окно стабильности
(Erlang max_restarts/max_seconds) + рестарт по deadline вместо sleep + **routing-epoch** (PM инкрементит
epoch в PSR при create/restart, рассылает `routing.refresh`; закрывает и HP-5-вопрос — делать ДО волны G)
+ readiness «medium» (self-reported ready из `process_runner` уже наполовину есть) + `depends_on` в blueprint
+ одна pytest-фикстура fault-injection (kill -9 → сосед жив, статус деградации виден) — превращает критерий
§1.1 из ручного qt-smoke в автоматический тест.

### Тема 3 — Контракты вместо конвенций (метаданные)

Один и тот же анти-паттерн в четырёх местах: механизм есть, контракта нет.

| Где | Факт | Фикс |
|---|---|---|
| IPC-сообщения | `Message` = union 9 типов, `extra="allow"`; `Message.create(schema=...)` — 0 прод-вызовов; опечатка в ключе = тихий сбой в другом процессе | Реестр `command/data_type → схема` как receive-middleware (режим warn→strict, off на data-plane до волны G) |
| Payload конвейера | items = свободные dict, join держится на строках `data_type`, контракт выхода плагина не проверяется никем | Хук-валидатор в PluginRunner: сверка фактических ключей item с Port-декларацией, dev-mode флаг |
| Плагины | Версий нет ВООБЩЕ (0 упоминаний); переименовал поле регистра → старый рецепт молча теряет значение; identity размазана по 4 местам | Манифест плагина = данные (version, api_version, requires); рецепт хранит name+version; boot логирует mismatch |
| Схемы/рецепты | `RecipeMeta.version=3` никем не читается; V1/V2/V3-суффиксы — конвенция; ломающее изменение схемы не ловится ничем | Движок миграций dict-документов (`@migration("recipe", from_=2, to=3)`) — SC-12 or-цепочки становятся migration-шагом и удаляются; schema-manifest дамп в docs/contracts/ + CI-gate на дрифт |

Плюс два подтверждённых **бага** рядом: (а) multi-register контракт — ложь: `plugin_orchestrator.py:247-255`
перезаписывает `schemas[plugin.name]` для каждого reg_cls — при len>1 выживает последний, остальные молча
теряются; (б) ошибки discovery на DEBUG — плагин с опечаткой просто исчезает из каталога. Оба — S-фиксы.

### Тема 4 — `ctx.health`: примитив «contain→report→degrade» ДО волны C

Волна C собирается чинить ~30 сайтов `except Exception: return []` руками. Два ридера независимо:
дать примитив фреймворка **до** этого — `ctx.health.report_error(exc, throttle_s=5)` = троттлированный лог
+ инкремент счётчика circuit breaker (сейчас breaker слеп к ошибкам, проглоченным внутри produce!)
+ публикация `processes.{p}.plugins.{name}.status='error'` в state-дерево. Волна C сжимается до одной
строки на call-site и перестаёт дрейфовать. Заодно: PluginContext сегодня отдаёт только log_info/log_error —
добавить warning/debug/record_metric; и закрыть мета-дыру — `ObservableMixin._call_manager` глушит все
исключения `except Exception: pass` (тот же M-err-анти-паттерн в ядре observability).

### Тема 5 — Фокус: конструктор из 8 модулей, а не 22

Адвокат дьявола, проверено grep'ом (и это НЕ покрыто kill-list K1–K12):

- **chain_module** (1661 LOC + 77 тестов): полный DAG-движок, 0 потребителей — реальный конвейер это
  `pipeline_executor.py`. Доки (`CONSTRUCTOR_BLUEPRINT.md:28`) продают мёртвый движок. → заморозить
  (frozen/experimental) ЛИБО осознанно сделать in-process DAG-движком PipelineExecutor (даёт ветвление
  1→N без налога отдельного процесса) — но не оставлять как есть;
- **dispatch_module** (3447 LOC): PATTERN/FALLBACK/CHAIN + ScenarioBuilder — все реальные потребители
  используют EXACT_MATCH; dict-lookup завёрнут в 3.4k LOC;
- **data_schema_module**: ~2118 LOC мёртвых подсистем (dna_factory, version_manager, storage_manager,
  visualizer/doc-generator) — ноль потребителей даже внутри framework;
- **console_module** (1675 LOC, «God Mode») — 0 использований;
- **frontend_module флагман мёртв в собственном продукте**: FrontendManager не инстанцируется,
  WidgetRegistry/WidgetDescriptor/LayoutComposer — 0 использований; биндинг-стеков ТРИ;
- **7+ реактивных механизмов**: Qt-сигналы, EventBus, StateStore-подписки, Registers-observers,
  Router-каналы, Config.subscribe, ActionBus. Одно редактирование поля GUI проходит 4 шины; 5 двунаправленных
  адаптеров с anti-loop синком RegistersManager⇄StateStore («**»-подписка на всё дерево!) — merge, не bridge:
  StateStore = истина, RegistersManager = view-model;
- доки расходятся в базовой цифре модулей (20 vs 21 vs 22) — поверхность не помещается даже в свои доки.

**Действия:** ярусы `core-8 / optional / frozen` в MODULES_STATUS; kill-list дополнить K13–K16
(~4.5k LOC, owner-decides per-item); gate «биндинг-систем ≤2» в acceptance E4; один стандарт логирования
(сейчас stdlib/ObservableMixin/loguru в одном прототипе).

---

## 2. Приоритеты для ФРЕЙМВОРКА

| Приор | Что | Усилие | Зачем |
|---|---|---|---|
| P0 | `ctx.health.report_error` + типизация PluginContext (requires-декларация) | S/M | Сжимает волну C в one-liner'ы; DX плагинописателя |
| P0 | Фикс multi-register overwrite + boot-проверка дубликата plugin_name (Н-7+) | S | Подтверждённая потеря данных на конвенции |
| P0 | Supervisor v2: per-process policy, окно, deadline-рестарт, routing-epoch, fault-injection фикстура | M | Флагманская фича сейчас мертва; routing-epoch нужен ДО волны G (HP-5) |
| P1 | Волна G расширенная: seqlock + QoS-профили kind + снятие двойной конверсии + copy-elision | M | Hot-path вскрывается ОДИН раз |
| P1 | Реестр контрактов сообщений (warn→strict) + payload-валидатор PluginRunner (dev-mode) | M | Опечатка = ошибка на границе, не тихий сбой |
| P1 | Ревизии state-дерева + resync (watch-from-revision, etcd-паттерн) | M | Потерянная дельта ≠ вечное расхождение кэша; фундамент undo/аудита |
| P1 | Ярусы core/optional/frozen + заморозка chain_module + K13–K16 в kill-list | S | Порог входа 22 → 8 концепций |
| P2 | Манифест плагина (version/api_version) + entry-points discovery (~50 строк) | M | Рецепты переживают эволюцию; pip-дистрибуция плагинов |
| P2 | JSONL-sink + OTel-совместимые ID в frame_trace/LogRecord (экспортёр потом) | S | Корреляция лог↔кадр↔процесс; Grafana бесплатно потом |
| P2 | Health-схема как контракт (пути дерева типизированы; breaker/restart публикуются) | M | GUI впервые видит деградацию плагина; убирает магические строки |
| P2 | Движок миграций версионированных dict-документов | M | Рецепты, пресеты, layout'ы любого будущего приложения |
| P2 | DeltaJournal (append-only журнал дельт + replay) | M | Post-mortem «почему пропустили дефект» — прямая ценность домена |
| P3 | TabSpec/TabRegistry во framework (расходится с планом «later» — механизм УЖЕ app-agnostic, app-specific только константа TAB_ORDER) | S | Без него «второе приложение декларативно» невозможно |
| P3 | IncrementalPlanner + replicas:N + команда scale | L | Правка одного узла ≠ рестарт всех камер; эластичность |
| P3 | Transport-conformance suite для IMessageChannel + запрет pickle-only полей | S | Дверь к multi-node остаётся открытой И проверяемой |
| P4 | GuiBootstrap (зеркало E3 для GUI: staged-pipeline вместо 875 LOC run_gui) | L | Composition root второго приложения = манифест ~100 строк |
| P4 | RemoteEventBridge (typed events между процессами поверх event_module) | M | Факты перестают моделироваться как state-пути |
| P4 | Inference-сервис: dynamic batching + GPU-ресурсы в blueprint (Triton-паттерн) | L | 3-5× throughput ML на том же GPU; после замера (product>engine) |

## 3. Приоритеты для ПРОТОТИПА

1. **Включить RestartPolicy** после Supervisor v2 — прототип сегодня живёт без авто-рестарта вообще.
2. **E4 расширенный**: в диспозицию ВСЕ ЧЕТЫРЕ механизма «схема→виджет» (не только diff двух по плану) —
   legacy factory / binding-aware (прод-мёртв, form_ctx=None везде) / params_form (0 потребителей) /
   WidgetRegistry (0 потребителей). Выход: ОДИН механизм; gate «биндинг-систем ≤2».
3. **join/inspector-конфиг выводить из wires при assembly** — костыль `_hoist_inspector_from_metadata`
   уже дал баг «join молча деградирует в fanin»; wires = единственный источник истины.
4. **RuntimeDeps → двухслойный контракт** (FrameworkRuntime + app-extras) — сейчас закрытый frozen dataclass
   с двумя `Any`, непереносим.
5. **Авто-подписка bind()** (StateProxy.ensure_subscription c refcount) — убирает класс ошибок «панель
   мертва, забыли wildcard в GuiProcess» (4 подряд комментария-инцидента в process.py).
6. **Прогнать Delta целиком до GUI** (сейчас delta_sink сплющивает в {path,value} — теряются delete/MISSING,
   transaction_id → layout-дёрганье) + один glob-матчер вместо трёх копий.
7. **Батчинг телеметрии**: `proxy.merge` одним сообщением вместо 3W+2 отдельных set (усиление E6).
8. **Один стандарт логирования** прототипа.

## 4. Чего НЕ делать (карго-культ 2026)

- **Не тащить кластер/брокер/DDS**: транспорт-нейтральная граница (conformance suite) — да; свой mesh — нет.
  Сетевой канал (Zenoh/NATS за IMessageChannel) — только при реальном втором боксе.
- **Не CRDT/полный event-sourcing**: журнал дельт + revision покрывает 80% ценности.
- **Не in-process магия hot-reload плагинов**: честная единица hot-swap = перезапуск процесса с тем же
  blueprint (ROS2/GStreamer тоже так); но починить identity-check reload и видимость failed-list — надо.
- **Не переписывать CRM-стек логирования на OTel SDK**: только семантические конвенции полей + JSONL-sink;
  экспортёр — тонкий адаптер потом.
- **Не строить autoscale до замера**: сначала replicas + ручной scale; реакция на глубину очереди — вторым этапом.
- **Не iceoryx2/Arrow как зависимость**: брать идею (seqlock), не биндинги.

## 5. Встройка в волны A–G

| Волна | Чем усилить |
|---|---|
| **C** (swallow) | СНАЧАЛА `ctx.health.report_error` (P0), потом 30 call-sites одной строкой |
| **D** (device_hub) | + wire-статусы first-class (publish `system.wires.*`, re-issue wire.configure при рестарте — сейчас после рестарта камеры её wire мёртв молча) |
| **E** (carve) | E3 + SpawnBackend Protocol (задел multi-node без постройки); E4 в расширенном охвате (4 механизма); E6 + merge-батчинг телеметрии |
| **F** (god-split) | без изменений — план уже хирургический |
| **G** (hot-path) | seqlock + QoS-профили + снятие двойной конверсии + copy-elision + trace_id — один вскрыш вместо пяти; routing-epoch сделать ДО |
| **Новая H** (фокус) | ярусы core/optional/frozen, K13–K16, merge Registers⇄StateStore, решение судьбы chain_module/config_module |

---

*Полные результаты ридеров (52 рекомендации, strengths/weaknesses по подсистемам):
журнал workflow `wf_ec3fc2e3-24e`. Дайджест хранился в scratchpad сессии.*
