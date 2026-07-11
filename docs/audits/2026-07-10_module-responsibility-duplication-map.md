# Карта ответственности модулей + реестр дублирования (2026-07-10)

- **Цель:** для КАЖДОГО модуля (framework + Services + Plugins) зафиксировать одну зону ответственности и найти **дублирование** — ради чистой архитектуры. Мёртвый/дремлющий код в фокус НЕ берём (владелец: freeze-over-kill, мог не успеть задействовать) — отмечаем лишь там, где это создаёт дубль ответственности.
- **Метод:** 9 Fable-агентов (read-only) + sentrux DSM (732 ребра, 0 циклов, чистое слоение) + codegraph/qex + прямая проверка кода. Ссылки файл:строка — в под-отчётах.
- **Связь:** дом движка миграций 4.5 — см. [`document-versioning-architecture.md`](../../plans/2026-07-06_constructor-master/document-versioning-architecture.md) (глубокий разбор «version ×3»).
- **Существующие docs, описывающие модули:** [`MODULES_OVERVIEW.md`](../../multiprocess_framework/docs/MODULES_OVERVIEW.md) («когда применять»), [`MODULE_CONTRACTS.md`](../../multiprocess_framework/docs/MODULE_CONTRACTS.md) («что обязано быть»), [`MODULES_RESPONSIBILITY_MAP.md`](../../multiprocess_framework/docs/MODULES_RESPONSIBILITY_MAP.md) («владеет / НЕ владеет» + путающие оси), `MODULES_STATUS.md`, per-module `README.md`. **Покрывают только 24 framework-модуля.** Services/Plugins — вне сетки (только `Services/STATUS.md`).

---

## 1. Ответственность framework-модулей (честная, 1 фраза)

Где реальность расходится с заявленным в docs — помечено ⚠️.

| Слой | Модуль | Владеет (по факту) | ⚠️ Расхождение с docs |
|---|---|---|---|
| L1 | `base_manager` | lifecycle менеджера + `ObservableMixin` (прокси лог/метрик/ошибок) | — |
| L1 | `data_schema_module` | **чертёж** данных: SchemaBase/FieldMeta/FieldRouting + реестр + сериализация | ⚠️ по факту 4 роли под крышей (+ storage/factory/versioning); «version» здесь = **история/откат** (VersionManager), не миграция формата |
| L2 | `dispatch_module` | примитив `ключ → handler` (4 стратегии) | — (подтв.) |
| L2 | `channel_routing_module` | база каналов/буферов (CRM) для logger/error/stats | ⚠️ + держит observability-стор/hub (660 LOC) → пересечение с осью «метрики» statistics_module |
| L3 | `message_module` | value object IPC (Message/MessageAdapter) | ⚠️ + fencing-token (Ф4.2) + реестр контрактов + middleware — это IPC-guard, не только «value object» |
| L3 | `router_module` | доставка сообщений **между процессами** | — (подтв.) |
| L4 | `logger_module` | логирование (scope-routing) | ⚠️ + app-протечка env `INSPECTOR_FRAME_TRACE` + pipeline-`frame_trace()` в generic-логгере; README врёт про наследование Error |
| L4 | `error_module` | ошибки с severity-routing | ⚠️ README: «наследник LoggerManager» — на деле **брат** через `LoggerCore` (после 5.14) |
| L4 | `statistics_module` | метрики/агрегация (counter/gauge/timing) | — (осью не владеют logger/error; но см. дубль D8) |
| L5 | `shared_resources_module` | **межпроцессные** ресурсы: очереди, SHM, EventManager, ConfigStore, PSR | — (подтв.) |
| L5 | `config_module` | runtime-доступ к конфигу (dot-path, env-fallback, subscribe) + слоистая сборка | ⚠️ скрытый от README слой `tools/` (loader/watcher/merge); «cross-process sync» = снапшот на spawn (живой синхронизации нет) |
| L5 | `state_store_module` | **глобальное реактивное дерево** (glob-подписки, дельты, IPC) | ⚠️ `recipes/RecipeEngine` несёт доменный `DEFAULT_CONFIG_PATHS` + одношаговые миграции формата |
| L6 | `event_module` | **in-proc** typed pub/sub «фактов» (по `type(event)`) | — (подтв., leaf) |
| L7 | `command_module` | реестр `имя команды → handler` (фасад над dispatch) | — (подтв.: `Dispatcher` из dispatch_module) |
| L7 | `actions_module` | building-blocks undo/redo (ActionBus PATCH / SnapshotHistory) | — (честно: прод-undo идёт мимо, см. дубль D7) |
| L7 | `worker_module` | потоки внутри процесса (LOOP/TASK) | — |
| L7 | `chain_module` | DAG/Chain/Parallel + worker-pool — **движок пайплайна** | ⚠️ **0 живых потребителей**; реальный пайплайн исполняет `process_module/generic` → дубль ответственности D4 |
| L8 | `process_module` | база дочернего процесса (собирает подсистемы) | ⚠️ `generic/` (~3k LOC) = **живой vision-inspection пайплайн** (InspectorManager/source_producer/pipeline_executor/frame_trace) + `SystemBlueprint` (топология ВСЕЙ системы) — домен и системный артефакт протекли вверх |
| L8 | `console_module` | терминальный I/O (passive/active/God) | ⚠️ `commands/` (588 LOC) — бизнес-хендлеры (`reg set` мутирует регистры), не «только транспорт» |
| L9 | `process_manager_module` | оркестратор системы (spawn/monitor/registry) | ⚠️ импортит внутренности process_module (`health.schema`, `generic.blueprint`) — общие контракты в чужом модуле |
| L10 | `service_module` | реестр long-running сервисов (lifecycle, без hot-reload) | — (подтв., чистый) |
| L10 | `display_module` | реестр SHM-каналов кадров (blueprint + YAML) | — (подтв.; README documents obsolete `bind_displays_to_blueprint`) |
| L11 | `registers_module` | runtime **экземпляров регистров** + fan-out полей | — (подтв.; `routing_map.py` не используется, но это дремлющее) |
| L12 | `frontend_module` | PySide6-конструктор: components/bridge/tabs-каркас/graph/forms/debug | ⚠️ ярлык «bridge» = 6% модуля; это **MVP GUI-фреймворк**; app-идентичность зашита (`prefs_store: _ORG="Inspector"`) |

**Метапоправка:** LOC в `MODULES_STATUS.md` раздуты тестами ×1.5–2 (process_module 11.8k prod / 8.3k тесты, не 20k; message 2k, dispatch 2.1k). Развести prod/test.

---

## 2. Services (13) — 3 кластера

| Кластер | Сервисы | Ответственность | Владелец связи |
|---|---|---|---|
| **Устройства** (чистая вертикаль) | `modbus` (транспорт) → `robot_comm`/`vfd_comm` (протокол-клиенты) → `device_hub` (реестр+lifecycle) + `hikvision_camera` | драйверы промышленного железа | процесс `devices` — единственный владелец соединений (ADR-DH-001) |
| **ML-конвейер** | `dataset_gen` → `ml_train` → `ml_inference` | данные → обучение → инференс (стык через ONNX+sidecar) | контракт формата модели |
| **Инфраструктура** | `sql`, `auth`, `control_panel`, `phone_gateway` | БД, RBAC, пульт оператора, телефон-источник | `@register_service` (IService) |
| **сирота** | `Region_processors` | конвертация цвет.пространства региона | **0 потребителей** — дремлющий, функция перекрыта processing-плагинами |

Границы ADR-120 держатся (0 reverse-import). Мягкое: прототип местами лезет мимо фасадов в `core/`/`storage/` сервисов (`model_picker.py:19`).

---

## 3. Plugins (~51 в 11 доменах) — единый контракт

**Модель:** плагин = подкласс `ProcessModulePlugin` (GStreamer-подобный lifecycle IDLE→READY→RUNNING⇄PAUSED→STOPPED), контракт портов `inputs`/`outputs` + `produce()`/`process(items)`, доступ к процессу через `PluginContext`, регистрация `@register_plugin` → `PluginRegistry.discover`. Данные текут list[dict]-items по внутрипроцессной цепочке, между процессами — SHM Claim Check.

| Домен | Ответственность | ~N |
|---|---|---|
| `sources` | генерация кадров (`produce()`) | 4 |
| `processing` | покадровые CV-преобразования и детекция | 29 |
| `render` | отрисовка результатов на кадре | 4 |
| `sinks` / `io` | вывод во внешние приёмники / персистентность (диск/БД/робот) | 1 / 6 |
| `hub` | always-on реестр устройств процесса `devices` | 1 |
| `control` / `filter` / `calibration` | решение по детекции / фильтр потока / калибровка | по 1 |
| `runtime` / `utility` | мета-плагины (цепочка/пул) / тестовые стенды | 2 / 1 |

Границы ADR-120 держатся (0 импортов прототипа; только framework + Services).

---

## 4. РЕЕСТР ДУБЛИРОВАНИЯ (главный результат)

Разделено: **D** = реальный дубль функции (кандидат на консолидацию) · **N** = параллельные механизмы by-design (НЕ трогать) · **V** = расщепление смысла «version».

### D — реальные дубли (кандидаты на консолидацию)

| # | Что дублируется | Где | Вердикт |
|---|---|---|---|
| **D1** | нормализатор config-shape (None\|dict\|Schema\|build()) — **×3** | CRM `normalize_config` / `LoggerCore._resolve_log_config` / `ErrorManager._normalize_error_config` | свести к базе CRM; наследники не переопределяют |
| **D2** | пул потоков — **×2** | `worker_module` vs `chain_module/thread_pool/pool.py` | chain должен использовать worker_module под капотом |
| **D3** | deep-merge словарей — **×3** | `data_schema.merge_with_defaults` / `config.tools.deep_merge` (самозван «канон») / `prototype._deep_merge` | один канонический merge на проект |
| **D4** | движок пайплайна — **×2** | `chain_module` (заявлен в docs, 0 живых) vs `process_module/generic` (живой pipeline_executor) | решить владельца: либо оживить chain как ядро generic, либо docs признают generic; выделить `generic/` в отдельный pipeline-модуль (заодно `SystemBlueprint`) |
| **D5** | определение версии рецепта «по форме» — **×3** | `RecipeEngine` (meta.version) / `recipe_io.py` (`"blueprint" in raw`) / `unwrap_recipe` | единый detect через движок миграций (задача 4.6) |
| **D6** | wiring миграций рецепта — **×3** + два одноимённых `v1_to_v2` | инъекция в RecipeEngine / wrapper-обход / standalone-скрипты; `backend/state/.../v1_to_v2` vs `recipes/migrations/format_v1_to_v2` | унифицировать через движок миграций (регистрация шагов по doc_type; → решение 2026-07-10: модуль `recipe`, см. §5) |
| **D7** | undo/redo — **×2** | `actions_module.ActionBus` (0 прод) vs domain `CommandDispatcherOrchestrator` | владелец решил **сохранить** actions_module (freeze); консолидация отложена |
| **D8** | tap/агрегация наблюдаемости | `channel_routing/observability/` (store+hub) vs ось «метрики» `statistics_module` | зафиксировать: hub = доставка, stats = агрегация; не сливать счётчики |
| **D9** | «где живёт плагин» — **×2 дома** | `Services/*/plugin/` (5 толстых) vs `Plugins/` (тонкие обёртки) | зафиксировать ADR-конвенцию «толстый-при-сервисе / тонкий-в-Plugins» |

### N — параллельно by-design (НЕ дубли, не трогать)

| # | Пара | Почему не дубль |
|---|---|---|
| N1 | `event_module.EventBus` (in-proc факт) vs `shared_resources.EventManager` (cross-proc) | разные оси; только **коллизия имён** «EventBus» — при чтении сверяться |
| N2 | `config_module` vs `state_store` (дерево+подписки) | граница = **жизненный цикл + транспорт** (config: до-spawn, редкий; state: runtime, IPC-дельты). NB: merge — это D3 |
| N3 | registers-observers vs state_store glob-подписки | мост by-design (`registers_adapter`), разный код |
| N4 | семейство реестров `Service`/`Display`/`Registers` | разные сущности; общий `IRegistry` не выделен — мелкий кандидат-рефактор |
| N5 | crop-семейство: `crop`/`roi_crop`/`center_crop`/`region_split` | различная семантика (задокументировано); таксономия разрослась, но функции разные |

### V — расщепление смысла «version» (крух задачи 4.5)

| Смысл | Дом сейчас | Дом целевой |
|---|---|---|
| **A. Миграция формата** (v2→v3) | размазано ×9 (D5/D6) | **`doc_migration_module`** (новый leaf) |
| **B. История/откат** содержимого | `data_schema/versioning` (дремлет) | там же (или заморозить) |
| **C. Манифест/совместимость** | плагины 4.4 (не построен) | `AppManifest.api_version` |

**Таксономия плагинов** (сопутствующее): 10 значений `category` против 3 задекларированных; домены `io`/`sinks`/`render` пересекаются по роли — канонизировать словарь (отдельный тикет).

---

## 5. Дом движка миграций (4.5) — вывод

> **⚠️ SUPERSEDED (решение владельца 2026-07-10, позже этого анализа):** движок миграций идёт в **модуль `recipe`**, НЕ в отдельный generic `doc_migration_module` — рецепт единственный реальный клиент (config без миграций, манифест 4.4 не построен), generic = YAGNI; раннер строится извлекаемым. См. decision-log Ф5-добора (D5/D6, задача C2) в [`plan.md`](../../plans/2026-07-06_constructor-master/plan.md). Ниже — исходная рекомендация, сохранена как анализ.

**Новый leaf-модуль `doc_migration_module`** (25-й). Обоснование — в [`document-versioning-architecture.md`](../../plans/2026-07-06_constructor-master/document-versioning-architecture.md) §4: клиенты во всех слоях (recipe/config/manifest), любой другой дом тянет баласт или усиливает расщепление «version». Разрешает D5/D6.

**Регистрация в docs при заведении:** запись в `MODULES_OVERVIEW.md` (L?, «когда применять») + `MODULE_CONTRACTS.md` (цель/контракт/инварианты) + `MODULES_RESPONSIBILITY_MAP.md` (владеет = «миграция формата dict-документов»; НЕ владеет = историей (B) и снапшотами) + `MODULES_STATUS.md` + own `README/interfaces/DECISIONS/tests`. Счётчик 24→25 в CLAUDE.md. `python -m scripts.sync` + `validate.py`.

---

## 6. Что поправить в существующих docs (дельта, не переписывать)

1. `MODULES_RESPONSIBILITY_MAP.md`: process_module — признать `generic/` inspection-пайплайном + владение `SystemBlueprint`; chain_module — пометить «0 живых потребителей, pipeline фактически в generic» (D4); channel_routing — добавить observability-стор; console — уточнить границу (588 LOC хендлеров); message — «+ IPC-guard».
2. `error_module`/`logger_module` README: ErrorManager — **брат** через LoggerCore, не наследник (после 5.14).
3. `MODULES_STATUS.md`: развести prod/test LOC.
4. Добавить в сетку docs **Services** и **Plugins** (сейчас их нет — только `Services/STATUS.md`).
5. Зафиксировать ADR-конвенцию «дом плагина» (D9) и канонический словарь category плагинов.
