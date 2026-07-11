# C6 — Дизайн единого pipeline-движка (generic ↔ chain_module ↔ домен ↔ SystemBlueprint)

- **Slug задачи:** C6 (D4+D2), план [`2026-07-06_constructor-master/plan.md`](plan.md) строка 273
- **Дата:** 2026-07-11
- **Статус:** дизайн (владелец решил — «дизайн сначала», реализация (b)-(e) отдельными задачами)
- **Решение владельца (decision-log Ф5-добор, 2026-07-10):** D4 «единый pipeline (дизайн сначала)» + D2 «chain → пул worker_module» — [`plan.md:264`](plan.md). Это ОТМЕНЯЕТ более раннюю рекомендацию анти-карго-культ «ждать 2-го потребителя» из [`docs/audits/2026-07-10_module-responsibility-duplication-map.md:82`](../../docs/audits/2026-07-10_module-responsibility-duplication-map.md) — владелец явно попросил дизайн, зная о риске.
- **Пересечения:** app_module 5.11-5.13 (В2, «рыба») — НЕ блокирует C6, но порядок важен (см. §5); Ф7 hot-path (G-задачи) — hot-path НЕ вскрывается здесь, только домен верхнего уровня.
- **Рычаги ревью:** NEW-C6a ([`plans/current-path/plan.md:52,100`](../current-path/plan.md)) — `ProcessConfig.extras` + вынос `frame_trace` из `__init_subclass__`; находки A3/C-6 ([`plans/current-path/review-2026-07-11.md:34,63`](../current-path/review-2026-07-11.md)).

---

## 1. Текущее устройство (факты, file:line)

### 1.1. Кто сегодня реально исполняет pipeline

`GenericProcess` — **сам себя объявляет deprecated** в докстринге:

> «DEPRECATED: Используйте ProcessModule напрямую с config.plugins. ProcessModule теперь нативно поддерживает плагины через PluginOrchestrator. GenericProcess добавляет только app-specific data pipeline (DataReceiver, PipelineExecutor, SourceProducer) — **это не часть фреймворка, а логика Inspector vision приложения**.»
> — [`generic_process.py:1-9`](../../multiprocess_framework/modules/process_module/generic/generic_process.py#L1-L9)

Это не моя интерпретация — это факт, зафиксированный в самом коде: авторы уже понимали, что data pipeline — домен, а не механизм. `_init_data_pipeline()` ([`generic_process.py:43-183`](../../multiprocess_framework/modules/process_module/generic/generic_process.py#L43-L183)) собирает вручную:

- `FrameShmMiddleware` (SHM claim-check, реально живёт в `router_module`, здесь только wiring — L43-83)
- `PluginRunner` — единый шов вызова `process()`/`produce()` (создаётся один раз на процесс, L87)
- `DataReceiver` + `InspectorManager`/`JoinInspectorManager` (L93-109) — только если есть processing-плагины
- `PipelineExecutor` (L111-124) — исполняет processing-цепочку как воркер `WorkerManager` (LOOP)
- `SourceProducer` на каждый source-плагин (L156-182) — тоже LOOP-воркер
- `_build_inspector()` ([L217-248](../../multiprocess_framework/modules/process_module/generic/generic_process.py#L217-L248)) выбирает `InspectorManager` (fan-in по count, режим `fanin`) или `JoinInspectorManager` (join по `seq_id`+`data_type`, режим `join`) — **обе стратегии — vision-inspection словарь** (`camera_id`, `region_name`, `total_regions`).

`PipelineExecutor._execute_chain()` ([`pipeline_executor.py:176-216`](../../multiprocess_framework/modules/process_module/generic/pipeline_executor.py#L176-L216)) — плоский **последовательный** проход по `list[ProcessModulePlugin]` с:
- circuit breaker (Q7): `max_consecutive_fails`/`auto_reset_sec`/`_bypassed` — состояние per-plugin, живёт МЕЖДУ вызовами `run_loop()` (across many batches), это НЕ разовая политика одного исполнения
- error policy: pass-through + `item["inspection_status"] = "not_inspected"` (не break, а тег + продолжение — принципиально отличается от chain_module)
- routing: `item["target"]` override → `chain_targets` (Q1)

`SourceProducer.run_loop()` ([`source_producer.py:92-186`](../../multiprocess_framework/modules/process_module/generic/source_producer.py#L92-L186)) — produce-loop с честным health/breaker (Task 2.2) и smart-sleep до `target_fps`.

**Вывод:** «живой пайплайн» — это `PipelineExecutor` + `SourceProducer` + `DataReceiver`, каждый работает как LOOP-воркер поверх `queue.Queue` (`chain_queue`), обрабатывая **батчи `list[dict]`**, а не одиночные кадры.

### 1.2. Где домен (что не механизм)

| Артефакт | Файл | Домен-вокабуляр |
|---|---|---|
| `InspectorManager` | [`inspector_manager.py:1-137`](../../multiprocess_framework/modules/process_module/generic/inspector_manager.py) | `camera_id`, `seq_id`, `region_name`, `total_regions` — region fan-in объектива инспекции |
| `JoinInspectorManager` | [`join_inspector_manager.py:1-40+`](../../multiprocess_framework/modules/process_module/generic/join_inspector_manager.py) | `data_type` (`"frame"`/`"overlay"`), left-join семантика оверлея поверх кадра |
| `frame_trace` | [`frame_trace.py:1-259`](../../multiprocess_framework/modules/process_module/generic/frame_trace.py) | сам механизм (спаны `transport`/`process`/`merge`) — engine-уровня; НО `merge_trace`/`record_merge`/`fork_trace` used ТОЛЬКО доменными fan-in/fan-out плагинами (`region_name`, `branches`, `chosen` — vision-словарь) |
| `INSPECTOR_FRAME_TRACE` env | [`frame_trace.py:54`](../../multiprocess_framework/modules/process_module/generic/frame_trace.py#L54) | брендинг в имени флага (не в семантике — это единственный env этой задачи; `INSPECTOR_HEALTH_*` в `health/state.py:52-57` — вне скоупа C6, см. NEW-9) |
| `ProcessConfig.inspector`/`chain_targets`/`source_target_fps`/`io_peek` | [`blueprint.py:113-131`](../../multiprocess_framework/modules/process_module/generic/blueprint.py#L113-L131) | типизированные поля SchemaBase framework-класса под доменные концепты pipeline |

Использование `frame_trace` ВНЕ `process_module` подтверждает, что доменный слой уже частично живёт в `Plugins/` (framework только даёт примитив):
- [`Plugins/processing/stitcher/plugin.py:16,76,91`](../../Plugins/processing/stitcher/plugin.py) — `merge_trace`/`record_merge` (fan-in склейка регионов)
- [`Plugins/processing/region_split/plugin.py:12,82,103`](../../Plugins/processing/region_split/plugin.py) — `fork_trace` (fan-out разрезание кадра на регионы)

Домен УЖЕ течёт правильным путём (Plugins импортирует framework — разрешено ADR-120/правило 9 CLAUDE.md); проблема НЕ в направлении импорта, а в том, что framework-слой (`process_module/generic/`) содержит vision-специфичные структуры данных (region/join fan-in), которые architecture-10-of-10 относит к уровню 2 «Платформа» / уровню 3 «Приложение», а не к уровню 1 «Механизмы, НИЧЕГО доменного» ([`architecture-10-of-10.md:26-33`](../current-path/architecture-10-of-10.md#L26-L33)).

### 1.3. `__init_subclass__` тянет домен в базу плагина (C-6)

```python
# multiprocess_framework/modules/process_module/plugins/base.py:245-257
def __init_subclass__(cls, **kwargs) -> None:
    super().__init_subclass__(**kwargs)
    from ..generic import frame_trace          # ← база плагина импортирует generic
    for _method in ("process", "produce"):
        fn = cls.__dict__.get(_method)
        if callable(fn) and not getattr(fn, "_traced", False):
            setattr(cls, _method, frame_trace.traced(fn))
```

**Каждый** подкласс `ProcessModulePlugin` (то есть буквально каждый плагин любого будущего приложения) на этапе объявления класса тянет `process_module.generic.frame_trace`. Это создаёт жёсткую связь база-плагина→inspection-домен ещё ДО того, как плагин выбрал категорию. `frame_trace.traced` дешёвый (bool-чек при выключенном флаге, [`frame_trace.py:245-246`](../../multiprocess_framework/modules/process_module/generic/frame_trace.py#L245-L246)) — накладные расходы не проблема, проблема архитектурная (домен в фундаменте).

`_trace_node` выставляется в [`plugin_orchestrator.py:131`](../../multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py#L131) (`plugin._trace_node = self._services.name`) — **уже** внутри `generic/`, то есть оркестратор — легитимное место для доменной инструментовки, в отличие от `plugins/base.py`.

### 1.4. `SystemBlueprint` живёт не там (D4/A3)

`SystemBlueprint`/`ProcessConfig`/`Wire` ([`blueprint.py:34-337`](../../multiprocess_framework/modules/process_module/generic/blueprint.py#L34-L337)) — чертёж **ВСЕЙ системы** (много процессов + wires между ними), но физически лежит в `process_module/generic/` — модуле ОДНОГО процесса. Систему собирает `process_manager_module` (L9, «оркестратор системы»), и он **уже сегодня** реализует эту зависимость напрямую:

```python
# process_manager_module/process/process_manager_process.py:835-840
from multiprocess_framework.modules.process_module.generic.blueprint import (
    SystemBlueprint,
)
...
topology = SystemBlueprint.model_validate(desired_blueprint or {})
```

Это ФАКТИЧЕСКАЯ реверс-связь L9→L8 «внутрь чужого модуля» — она уже отмечена в аудите: «PM импортит внутренности process_module (`health.schema`, `generic.blueprint`) — общие контракты в чужом модуле» ([`docs/audits/2026-07-10_module-responsibility-duplication-map.md:33-35`](../../docs/audits/2026-07-10_module-responsibility-duplication-map.md#L33-L35)). Других потребителей `SystemBlueprint`/`ProcessConfig`/`Wire` (grep `generic.blueprint` / `generic import.*blueprint`):
- `process_manager_module/tests/conftest.py`, `process_manager_module/tests/test_apply_topology_integration.py`
- `multiprocess_prototype/frontend/widgets/topology/presenter.py:11`
- `multiprocess_prototype/backend/assembly/assembler.py:31`
- `multiprocess_prototype/generic_process_app.py`, `multiprocess_prototype/frontend/app.py`, тесты (`frontend/tests/test_gui_process.py`, `pipeline/tests/test_io_roundtrip.py`, `backend/topology/tests/test_base_merge.py`, `backend/assembly/tests/test_assembler.py`)

Итого ~9 живых импортёров — не «единичный слепок», перенос требует мех. правки импортов, не только логики.

### 1.5. `chain_module` — 0 живых потребителей, другая модель данных

`chain_module` ([2735 LOC]): `ChainRunnable`/`DagRunnable`/`ParallelChainRunnable` + `ChainThreadPool` + `WorkerPoolDispatcher`. Контракт исполнителей:

```python
# chain_module/core/chain.py:20-24, interfaces.py:56-62
def execute(self, frame: np.ndarray, metadata: dict | None = None) -> ChainResult: ...
```

— **один кадр (`np.ndarray`) на вызов**, результат — `ChainResult` (dataclass: `frame`, `detections`, `masks`, `contours`, `processing_time`, `skipped_nodes`, `failed`, `fail_level` — [`result.py:13-26`](../../multiprocess_framework/modules/chain_module/core/result.py#L13-L26)). Шаг — `RunnableStep(node, operation, on_error)`, `operation: IExecutionStep` с `.execute(data, context) -> data` ([`interfaces.py:44-49`](../../multiprocess_framework/modules/chain_module/interfaces.py#L44-L49)) — сигнатура протокола формально `Any`, НЕ жёстко привязана к `ndarray`, но:
- `ChainThreadPool.submit_bundle()` жёстко вызывает `frame.copy()` для thread-safety ([`thread_pool/pool.py:65`](../../multiprocess_framework/modules/chain_module/thread_pool/pool.py#L65)) — предполагает `.copy()`-семантику ndarray, не протестировано на `list[dict]`.
- `apply_on_error_policy` ([`error_policy.py:15-63`](../../multiprocess_framework/modules/chain_module/core/error_policy.py#L15-L63)) знает только `skip`/`fail_region`/`fail_camera` — **нет** концепции circuit breaker (consecutive-fails/bypass/auto-reset), которая в `PipelineExecutor` — межбатчевое состояние per-plugin (живёт дольше одного `execute()`).
- `DagRunnable` работает через `port_data: dict[node_id, dict[port_name, value]]` — граф ВНУТРИ одного процесса; в generic сегодня ветвление реализовано ТОЛЬКО между процессами (через IPC + `Wire`), никакой intra-process DAG-топологии плагинов в `ProcessConfig.plugins` (плоский `list[dict]`) нет.

**`chain_module` использует СВОЙ поток-пул** ([`thread_pool/pool.py:14-33`](../../multiprocess_framework/modules/chain_module/thread_pool/pool.py#L14-L33), `ThreadPoolExecutor(max_workers=...)`), полностью отдельный от `worker_module` (D2 в аудите, [`docs/audits/...:85`](../../docs/audits/2026-07-10_module-responsibility-duplication-map.md#L85)). `WorkerPoolDispatcher` ([`worker_pool/dispatcher.py:1-70`](../../multiprocess_framework/modules/chain_module/worker_pool/dispatcher.py)) — это ДРУГОЙ пул: round-robin по CROSS-PROCESS worker-процессам (IPC+SHM), не путать с `ChainThreadPool` (in-process потоки для параллельных бандлов).

### 1.6. `worker_module` — не пул задач, а реестр именованных потоков

```python
# worker_module/lifecycle/worker_lifecycle.py:53-90 (create_worker/start_worker)
thread = threading.Thread(name=..., target=self._worker_wrapper, args=(worker_name, target, stop_event, pause_event), daemon=True)
```

`WorkerManager.create_worker(worker_name, target, config, auto_start)` создаёт **один именованный `threading.Thread`** на воркер, с двумя режимами ([`worker_module/types/types.py:89-118`](../../multiprocess_framework/modules/worker_module/types/types.py#L89-L118)):
- `ExecutionMode.LOOP` — бесконечный цикл (типичный кейс — `PipelineExecutor.run`/`SourceProducer.run_loop`)
- `ExecutionMode.TASK` — разовое исполнение, статус `COMPLETED`

**Нет** `submit()`/`Future`-API — это НЕ `ThreadPoolExecutor`-замена «из коробки». D2 («chain должен использовать worker_module под капотом») требует НОВОГО примитива поверх `worker_module` (см. §5, шаг (e)), не тривиальной замены импорта.

---

## 2. Целевые границы (generic-движок ↔ chain_module ↔ домен ↔ SystemBlueprint)

Проецируем на 4-уровневую модель `architecture-10-of-10.md` §1 ([строки 22-44](../current-path/architecture-10-of-10.md#L22-L44)): уровень 1 «Механизмы» (framework/modules, НИЧЕГО доменного) / уровень 2 «Платформа» (Plugins/Services/recipe) / уровень 3 «Приложение».

```
┌─────────────────────────────────────────────────────────────────┐
│ Уровень 3 — Приложение (multiprocess_prototype)                 │
│   рецепты, register-схемы vision-домена                         │
└─────────────────────────────────────────────────────────────────┘
                              │ конфигурирует
┌─────────────────────────────────────────────────────────────────┐
│ Уровень 2 — Платформа (Plugins/)                                 │
│   InspectorManager / JoinInspectorManager  ← домен fan-in/join   │
│   merge_trace / record_merge / fork_trace  ← домен trace-vocab   │
│   stitcher / region_split (уже здесь)                            │
└─────────────────────────────────────────────────────────────────┘
                              │ реализует контракт ProcessModulePlugin
┌─────────────────────────────────────────────────────────────────┐
│ Уровень 1 — Механизмы (framework/modules/)                       │
│                                                                    │
│  process_module/generic/  «pipeline-движок» (осталось после C6):  │
│    - PipelineExecutor   (sequential/DAG runner ПОВЕРХ chain_module)│
│    - SourceProducer     (produce-loop, health-интеграция)         │
│    - DataReceiver       (IPC → items, вызывает InspectorManager   │
│                           через DI, сам его не знает)              │
│    - PluginRunner       (единый шов process()/produce())          │
│    - frame_trace (transport/process спаны — ТОЛЬКО инструмент)    │
│                                                                    │
│  chain_module/  «исполнитель шага» (ядро C6d):                    │
│    - ChainRunnable/DagRunnable/ParallelChainRunnable               │
│    - через пул worker_module (C6e), не свой ThreadPoolExecutor    │
│                                                                    │
│  process_manager_module/  «топология системы» (C6c):              │
│    - SystemBlueprint/ProcessConfig/Wire (переехал из generic/)    │
│    - ProcessConfig.extras: dict  ← opaque домен-bag (C6-рычаг 1)  │
└─────────────────────────────────────────────────────────────────┘
```

**Правило владения после C6:**

| Что | Дом ДО | Дом ПОСЛЕ | Задача |
|---|---|---|---|
| `InspectorManager`/`JoinInspectorManager` | `process_module/generic/` | `Plugins/` (общий утилити-модуль, напр. `Plugins/_shared/fanin/`) | (b) |
| `merge_trace`/`record_merge`/`fork_trace` (домен-вокабуляр trace) | `process_module/generic/frame_trace.py` | остаются в `frame_trace.py` (см. рычаг 4, §4) — вокабуляр общий для transport+merge, разделять физически рискованно при 0 др. потребителей | (b), решение — НЕ разделять сейчас |
| `SystemBlueprint`/`ProcessConfig`/`Wire` | `process_module/generic/blueprint.py` | `process_manager_module/topology/blueprint.py` (новый) | (c) |
| Исполнение processing-цепочки | `PipelineExecutor._execute_chain` (свой sequential loop) | `PipelineExecutor` строит `list[RunnableStep]` из плагинов, делегирует проход `ChainRunnable.execute()` | (d) |
| Пул параллельных бандлов | `ChainThreadPool` (свой `ThreadPoolExecutor`) | новый примитив `WorkerPoolExecutor` НАД `worker_module` (N персистентных LOOP-воркеров + internal queue) | (e) |
| `frame_trace.traced` на каждый плагин | `plugins/base.py.__init_subclass__` (импорт `..generic`) | `PluginOrchestrator.boot()` (уже трогает `_trace_node`, [`plugin_orchestrator.py:131`](../../multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py#L131)) | рычаг 4 (§4) |

---

## 3. Рычаг 1 — `ProcessConfig.extras: dict` (domain-opaque)

**Проблема:** `ProcessConfig` — framework-класс (живёт сегодня в `process_module/generic/blueprint.py`, после (c) — в `process_manager_module`), но несёт 4 типизированных доменных поля ([`blueprint.py:113-131`](../../multiprocess_framework/modules/process_module/generic/blueprint.py#L113-L131)):

```python
chain_targets: Annotated[list[str], FieldMeta(...)] = []
source_target_fps: Annotated[float, FieldMeta(...)] = 25.0
inspector: Annotated[dict[str, Any], FieldMeta(...)] = {}
io_peek: Annotated[dict[str, Any], FieldMeta(...)] = {}
```

Это связывает перенос `SystemBlueprint` в `process_manager_module` (шаг c) с переносом домена (шаг b): `process_manager_module` после (c) обязан «знать» имена `inspector`/`chain_targets` — то есть шаг (c) НЕ может произойти независимо от (b). Рычаг снимает эту связку.

### Решение

Добавить **аддитивно** (без удаления типизированных полей — back-compat):

```python
@register_schema("ProcessConfigV1")
class ProcessConfig(SchemaBase):
    ...
    extras: Annotated[
        dict[str, Any],
        FieldMeta("Extras", info="Domain-opaque bag: pipeline-специфичные ключи (inspector/chain_targets/io_peek/...), которые framework не обязан знать по имени. Зеркалит формат app.yaml/manifest 'version + extras' (5.11/4.4)."),
    ] = {}
```

`as_generic_config()` ([`blueprint.py:133-171`](../../multiprocess_framework/modules/process_module/generic/blueprint.py#L133-L171)) читает **typed-поле, если непусто, иначе `extras[key]`** — приоритет typed сохраняет 100% обратную совместимость со старыми рецептами (никто их не мигрирует силой):

```python
def as_generic_config(self) -> GenericProcessConfig:
    ...
    chain_targets = self.chain_targets or self.extras.get("chain_targets", [])
    source_fps = self.source_target_fps if self.source_target_fps != 25.0 else self.extras.get("source_target_fps", 25.0)
    inspector = self.inspector or self.extras.get("inspector", {})
    io_peek = self.io_peek or self.extras.get("io_peek", {})
    if chain_targets: base_kwargs["chain_targets"] = chain_targets
    ...
```

**Почему это развязывает (b)/(c):**
- `process_manager_module` (после c) владеет `ProcessConfig`/`SystemBlueprint`, но методы `check()`/`build_configs()` НЕ обязаны знать про `inspector`/`chain_targets` по имени — `check()` работает с портами плагинов через `PluginRegistry`/`Port` (уже domain-agnostic, см. [`blueprint.py:224-322`](../../multiprocess_framework/modules/process_module/generic/blueprint.py#L224-L322)), а `as_generic_config()` может остаться единственным местом, знающим 4 legacy-имени — либо тоже уехать в domain-специфичный build-hook (см. риск ниже).
- Новые доменные ключи (например будущий `roi_selector` конфиг) добавляются в `extras` БЕЗ правки `ProcessConfig` — framework-схема стабильна.
- Совпадает с манифестным форматом `version + extras`, уже принятым для `app.yaml`/plugin-манифеста (4.4)/`service.yaml` — [`architecture-10-of-10.md:107`](../current-path/architecture-10-of-10.md#L107): «Манифестная плоскость — один формат... все несут `version + extras`».

**Что НЕ делаем сейчас:** не удаляем 4 typed-поля (это сломало бы ~9 живых импортёров и все существующие рецепты в один присест — избыточный риск для дизайн-задачи). Удаление — отдельная задача ПОСЛЕ того, как (b) фактически перенесёт логику, читающую эти поля, в `Plugins/` (тогда typed-поля станут явно мёртвыми, можно удалить per-item через G0/G4-паттерн, ПРИНЦИП №1 плана).

**Тест:** property-тест round-trip `ProcessConfig(chain_targets=[...]).as_generic_config().chain_targets == [...]` (typed-путь) + `ProcessConfig(extras={"chain_targets": [...]}).as_generic_config().chain_targets == [...]` (extras-путь) + приоритет typed>extras при обоих заданных.

---

## 4. Рычаг 2 — вынос `frame_trace` из `__init_subclass__` базы плагина (C-6)

### Варианты

**Вариант A (рекомендован) — перенести установку хука в `PluginOrchestrator.boot()`.**

`plugins/base.py` теряет `from ..generic import frame_trace` полностью. Вместо class-level авто-обёртки в `__init_subclass__`, `PluginOrchestrator` (который уже физически в `generic/`, уже трогает `plugin._trace_node` на [`plugin_orchestrator.py:131`](../../multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py#L131)) во время `boot()` оборачивает `process`/`produce` **инстанса** (не класса):

```python
# plugin_orchestrator.py, рядом с установкой _trace_node
from . import frame_trace
if not getattr(type(plugin).process, "_traced", False):
    # instance-level bind невозможен для bound-method переопределения класса —
    # оборачиваем на уровне класса ОДИН раз (idempotent, тот же паттерн, что и раньше)
    setattr(type(plugin), "process", frame_trace.traced(type(plugin).__dict__.get("process") or type(plugin).process))
```

Плюсы: `plugins/base.py` — чистая механика (state machine, PluginContext, порты), НЕ знает про `generic`. `frame_trace` остаётся ЕДИНСТВЕННЫМ местом обёртки — просто вызывается позже (на `boot()`, не на `class`-объявлении), что даже точнее по времени (плагин может быть импортирован, но никогда не забучен — тогда обёртка сейчас ставится зря).

Минус: обёртка происходит на **первом инстансе** класса, а не на объявлении — если два процесса поднимают один и тот же класс плагина, `setattr(type(plugin), ...)` мутирует класс дважды (idempotent-guard `_traced` уже защищает — не проблема, `frame_trace.traced` ставит `wrapper._traced = True` на функцию, [`frame_trace.py:258`](../../multiprocess_framework/modules/process_module/generic/frame_trace.py#L258)).

**Вариант B — opt-in hook, регистрируемый лениво.**

`ProcessModulePlugin` получает пустой class-level реестр `_subclass_hooks: ClassVar[list[Callable]] = []` и публичный `ProcessModulePlugin.register_subclass_hook(fn)`. `__init_subclass__` вызывает хуки из реестра, НЕ импортируя `generic` напрямую. `generic/__init__.py` (или модуль `plugin_orchestrator`) при импорте регистрирует `frame_trace.traced`-обёртку как хук.

Плюсы: `__init_subclass__` остаётся на этапе объявления класса (совпадает с текущим поведением 1-в-1, нулевой риск регресса поведения/тестов). Минус: требует, чтобы `generic/__init__.py` был импортирован ДО объявления любого плагина (порядок импортов) — сегодня это де-факто гарантировано (плагины импортируются через `PluginRegistry.discover()` ПОСЛЕ бута процесса, `generic` уже импортирован раньше), но это неявная инвариант, которую легко сломать в будущем (например тест плагина без загрузки всего процесса).

**Вариант C — свернуть в no-op-safe заглушку в `plugins/base.py`.**

Оставить `__init_subclass__` пустым по умолчанию, `frame_trace`-обёртка — только если `generic` уже импортирован (`sys.modules` guard). Минус: неявная магия, хуже читается, не рекомендуется.

### Рекомендация

**Вариант A** — минимальный диф, ноль новых абстракций, естественный дом (`PluginOrchestrator` уже владеет lifecycle-моментом `boot()` и уже трогает trace-related атрибут). Вариант B — запасной, если характеризационные тесты покажут, что порядок `class`-time vs `boot()`-time важен (например тесты объявляют плагин-класс и сразу проверяют `cls.process._traced` БЕЗ инстанцирования/boot — тогда переход на инстанс-время сломает ожидание). **Проверить это ПЕРВЫМ шагом реализации** — grep тестов на `.process._traced` / `.produce._traced` до выбора.

**Долгосрочная сходимость (не C6, зафиксировать как направление):** `frame_trace`'s process/transport-спаны концептуально пересекаются с G.6 trace-id (Ф7, «главный разрыв наблюдаемости», [`review-2026-07-11.md:85`](../current-path/review-2026-07-11.md#L85)) — вынесенный первым шагом Ф7 ([`plans/current-path/plan.md:72`](../current-path/plan.md#L72)). Когда Ф7 дойдёт до G.6, стоит решить: `frame_trace` эволюционирует в общий trace-id механизм (переезжает в `chain_module/metrics/` рядом с уже существующим `LatencyTracker`, [`chain_module/metrics/latency.py:39`](../../multiprocess_framework/modules/chain_module/metrics/latency.py#L39)) или остаётся отдельным item-level инструментом. **Не решаем сейчас** — это открытый вопрос Ф7, не C6 (см. §7).

---

## 5. Пошаговый план реализации (b) → (e)

Общий гейт для КАЖДОГО шага: `python scripts/validate.py` зелёный, `pytest` framework+prototype 0 красных (характеризационные тесты — ДО правки, без изменения ожиданий, по паттерну F.1-F.7), `sentrux check_rules` 0 нарушений (проверка на новые reverse-import).

### Порядок относительно 5.11-5.13 (В2) и Ф7

- **(b)/(c) МОГУТ идти ДО 5.11-5.13** — они не блокируют «рыбу»: 5.11 (`assemble_launcher`/`ManifestStore`) не зависит от того, где физически лежит `InspectorManager` или `SystemBlueprint`, только от их публичного API (который не меняется).
- **(d)/(e) РЕКОМЕНДУЕТСЯ ПОСЛЕ 5.11-5.13**: 5.13 вводит `minimal_app` в CI как «ранний детектор Inspector-допущений» ([`plans/current-path/plan.md:60`](../current-path/plan.md#L60)) — если `minimal_app` не использует ветвление/параллелизм (вероятно, headless-only простой pipeline), он даёт дешёвый регресс-сигнал ДО того, как chain_module станет ядром generic. Менять исполнитель pipeline ДО того, как есть второй живой смок (minimal_app) — повышает риск: единственный regression-detector — hikvision/phone_sketch рецепты, оба сложные.
- **Hot-path (Ф7) НЕ трогаем**: (d)/(e) касаются ТОЛЬКО processing-цепочки одного процесса (`PipelineExecutor`) — SHM/seqlock/`Message(**...)`-конструирование per-frame (инвариант 1, [`architecture-10-of-10.md:176`](../current-path/architecture-10-of-10.md#L176)) не меняются; `chain_targets`-роутинг и `_send_results` остаются в `PipelineExecutor` (IPC send не переезжает в chain_module).

### (b) Домен `InspectorManager`/`frame_trace`-вокабуляр/`INSPECTOR_*` → Plugins

**Скоуп:**
1. `InspectorManager` + `JoinInspectorManager` → новый модуль `Plugins/_shared/fanin/` (или аналог — конкретное имя решить по конвенции D9 «дом плагина», C7). Публичный контракт (`on_item`, `check_timeouts`, `pending_count`, `_on_ready` callback) НЕ меняется — DI, `DataReceiver` продолжает получать готовый инстанс через конструктор, НЕ импортирует конкретный класс напрямую (уже так: `DataReceiver.__init__(inspector_manager: InspectorManager, ...)` — заменить тип-хинт на `Protocol` с методами `on_item`/`check_timeouts`).
2. `GenericProcess._build_inspector()` ([`generic_process.py:217-248`](../../multiprocess_framework/modules/process_module/generic/generic_process.py#L217-L248)) — фабрика выбора `fanin`/`join` — переезжает вместе с классами (домен решает, ЧТО инстанцировать; `generic/` только принимает готовый объект через `extras["inspector"]` + DI-хук).
3. `frame_trace.py` — **НЕ разделяем** физически (см. §4 долгосрочная сходимость): `stamp_send`/`record_transport`/`record_process`/`traced` — используются `PipelineExecutor`/`SourceProducer`/`DataReceiver` (engine), `merge_trace`/`record_merge`/`fork_trace` — только доменными плагинами (`stitcher`/`region_split`, уже в Plugins). Один физический модуль, два логических потребителя — приемлемо (единый вокабуляр спанов, разделение сейчас = преждевременная абстракция при отсутствии второго потребителя chain-специфичного trace).
4. `INSPECTOR_FRAME_TRACE` env — остаётся как есть (сам флаг — не домен инспекции по сути, а generic on/off трассировки; переименование в `MPF_FRAME_TRACE`/алиас — задача NEW-9 (В6, packaging), НЕ C6).

**Характеризационные тесты ДО разреза:** существующие тесты `InspectorManager`/`JoinInspectorManager` (юнит, без правки ожиданий) + smoke двух живых рецептов (`phone_sketch`, `hikvision_letter_robot`) — оба используют fan-in (`region_split`+`stitcher`), это РЕАЛЬНАЯ регрессионная защита.

**Acceptance:** `grep "InspectorManager\|JoinInspectorManager" multiprocess_framework/modules/process_module/generic/*.py` = 0 (кроме DI-Protocol, если такой заведён); `process_module/generic/__init__.py` больше НЕ экспортирует `InspectorManager` напрямую (back-compat: временный ре-экспорт-шим на 1 цикл, если внешние импортёры есть — проверить grep ДО удаления).

### (c) `SystemBlueprint` → `process_manager_module`

**Предусловие:** рычаг 1 (§3) закрыт — `ProcessConfig.extras` существует.

**Скоуп:**
1. Физически перенести `blueprint.py` (382 LOC минус то, что осталось доменным) → `process_manager_module/topology/blueprint.py` (новый подпакет; альтернатива — плоский файл `process_manager_module/blueprint.py`, решить по конвенции модуля — обычно подпакет, т.к. `check()`/`describe()`/helpers — 200+ LOC).
2. Импорты внутри перенесённого файла: `..plugins.port` (`Port`, `are_ports_compatible`, `validate_chain`) и `..plugins.registry` (`PluginRegistry`) → меняются на `...process_module.plugins.port`/`...process_module.plugins.registry` (framework-internal cross-module импорт — РАЗРЕШЁН, framework не импортирует Services/Plugins/prototype, а process_manager_module↔process_module — оба framework, симметрично текущему де-факто состоянию). `GenericProcessConfig`/`PluginConfig` — аналогично, импорт из `...process_module.generic.generic_process_config` (эти классы ОСТАЮТСЯ в process_module — per-process конфиг, не системная топология).
3. Back-compat шим: `process_module/generic/blueprint.py` (или `__init__.py`) на переходный период ре-экспортирует `from ...process_manager_module.topology.blueprint import SystemBlueprint, ProcessConfig, Wire` — снимает необходимость править ~9 импортёров одним коммитом; правка call sites (prototype/frontend/presenter.py:11, backend/assembly/assembler.py:31, тесты) — отдельный follow-up коммит(ы), может идти параллельно.
4. `process_manager_process.py:835-840` — убрать `from multiprocess_framework...generic.blueprint import SystemBlueprint`, заменить на прямой импорт из нового дома (это и была причина переноса — снять реверс-паттерн «PM лезет во внутренности process_module»).

**Характеризационные тесты:** `process_manager_module/tests/test_apply_topology_integration.py`, `process_manager_module/tests/conftest.py` — зелёные БЕЗ правки ожиданий (только импорт-путь, если шим не используется).

**Риск-анализ ребра импорта:** после (c) `process_manager_module` (L9) владеет `SystemBlueprint`, но `SystemBlueprint.as_generic_config()`/`build_configs()` по-прежнему возвращает `GenericProcessConfig` (process_module, L8) — то есть `process_manager_module` ИМПОРТИРУЕТ `process_module` (L9→L8, framework-internal, разрешено, это НЕ реверс относительно правила №9 CLAUDE.md, которое запрещает framework→Services/Plugins/prototype, а НЕ framework-внутренние связи между L8/L9). Единственный реальный реверс, который снимается — было «process_manager лезет в generic-ПАКЕТ (внутренности одного процесса) за системным артефактом», станет «process_manager владеет системным артефактом локально, обращается к per-process конфигу через публичный `generic_process_config` (уже сегодня публичный API модуля, экспортируется в `generic/__init__.py`)».

**Acceptance:** sentrux `check_rules` 0 нарушений (новых циклов/реверсов); `grep "generic.blueprint" -r` вне шима = 0 (после follow-up фазы правки call sites).

### (d) generic-механика на runnables `chain_module`

**Предусловие:** (b) закрыт (домен не путается под ногами при переносе исполнителя) — НЕ жёсткая зависимость от (c).

**Ключевой архитектурный факт (§1.5):** `chain_module`-исполнители работают с ОДНИМ `frame: np.ndarray`, `PipelineExecutor` — с `items: list[dict]` (батчи). Это НЕ шаблонное натягивание импорта — нужен адаптер.

**Инкремент 1 (в скоупе C6, низкий риск) — `ChainRunnable` как sequential-движок вместо `_execute_chain`:**

1. Обобщить типизацию `chain_module`: `ChainRunnable.execute(frame: np.ndarray, ...)` → `execute(payload: Any, ...)` (только type hints — тело уже duck-typed, `operation.execute(current_frame, context)` не делает ничего ndarray-специфичного). `ChainResult.frame: np.ndarray` → `frame: Any`. Формально расширяет контракт, обратной совместимости не ломает (текущие потребители chain_module — 0 живых, тесты — единственные потребители, их пройти без правки ожиданий).
2. Новый адаптер `PluginOperationStep` (дом — `process_module/generic/`, т.к. это МОСТ движка к chain, не домен) — реализует `IExecutionStep`: `execute(items: list[dict], context: ChainContext) -> list[dict]` делегирует в `PluginRunner.call_process(plugin, items)` (**обязательно через раннер, НЕ напрямую `plugin.process()`** — иначе io-debug/port-validation хуки из [`plugin_runner.py:92-110`](../../multiprocess_framework/modules/process_module/generic/plugin_runner.py#L92-L110) молча отключатся для chain-исполняемых плагинов — это конкретный риск, не гипотетический, `PluginRunner` — «единственная точка в data-плоскости» по докстрингу).
3. `PipelineExecutor._execute_chain()` — переписывается на: (а) отфильтровать `bypassed` плагины (circuit breaker — состояние ВНЕ `ChainRunnable`, живёт в `PipelineExecutor` как раньше, между вызовами `execute()`); (б) построить `list[RunnableStep]` из оставшихся плагинов (`on_error="skip"` — ближайший аналог текущего pass-through-с-тегом поведения, НО chain's `skip`-политика не тегирует `item["inspection_status"]` — нужен ЛИБО кастомный `on_error` режим в `apply_on_error_policy` (`"tag_and_continue"`), ЛИБО `PluginOperationStep.execute()` сам ловит исключение и тегирует ДО того, как отдать `apply_on_error_policy` решать (тогда `on_error` всегда `"skip"`, а bypass/counter — как раньше, вне chain). **Рекомендация: второй вариант** — `apply_on_error_policy` не трогаем (0 изменений в chain_module/core/error_policy.py), вся текущая семантика (тег + fails-counter + bypass) остаётся в адаптере/`PipelineExecutor`, `ChainRunnable` используется ТОЛЬКО как «пройти список шагов последовательно, дать each свою error_policy=skip» — минимальный, безопасный срез ответственности.
4. `SourceProducer` — **НЕ трогаем** в (d): она не «цепочка» (один плагин, produce-loop с health/breaker) — chain_module ей не нужен, интеграция была бы генерализацией без потребителя.

**Инкремент 2 (ВНЕ скоупа C6, зафиксировать как будущую задачу) — `DagRunnable`/`ParallelChainRunnable` для intra-process ветвления:**

Сегодня `ProcessConfig.plugins` — плоский список, ветвление реализуется ТОЛЬКО между процессами через `Wire` (IPC). `DagRunnable`/`ParallelChainRunnable` дают intra-process DAG/параллелизм — но это НОВАЯ возможность, которой ни один живой рецепт не пользуется (anti-cargo-cult, `analysis.md §9` принцип «генерализация только при втором потребителе», подтверждённый в [`architecture-10-of-10.md:193`](../current-path/architecture-10-of-10.md#L193)). Использовать их — потребует РАСШИРЕНИЯ схемы `ProcessConfig` (граф плагинов вместо списка) — отдельная, более крупная задача, инициируется ТОЛЬКО когда появится конкретный рецепт, которому нужно intra-process ветвление (например: один кадр параллельно в 2 детектора внутри процесса, join результатов до отправки). До этого момента `DagRunnable`/`ParallelChainRunnable` — доступны, протестированы, НЕ подключены к generic (chain «перестаёт дремать» за счёт `ChainRunnable`, что удовлетворяет acceptance C6 «живой пайплайн через chain»; DAG/parallel — «доступны», НЕ «обязательно используются» — это буквально формулировка acceptance в [`plan.md:273`](plan.md#L273): «DAG/parallel доступны»).

**Характеризационные тесты:** сравнить `PipelineExecutor` до/после байт-в-байт по поведению (circuit breaker включается на N-м фейле, auto-reset по таймауту, routing per-item `target`, `inspection_status="not_inspected"` при ошибке) — существующий юнит-сьют `pipeline_executor` тестов (если есть) + новый тест «`ChainRunnable`-based `_execute_chain` даёт идентичный результат старому list-loop на одинаковых входах» (property-тест или таблица кейсов).

**Acceptance:** framework+prototype regression 0 красных; FPS/latency обоих рецептов ≥ baseline (Ф0 baseline.md) — `ChainRunnable.execute()` добавляет один слой вызова (`ChainContext` создаётся на КАЖДЫЙ батч — новый dataclass alloc per batch, не per item — стоимость нужно измерить, не hot-path per-frame, но частый путь; если регресс FPS замечен — это blocker, откат к прямому list-loop).

### (e) chain использует пул `worker_module`

**Предусловие:** (d) закрыт — иначе нечего пулить (без chain_module-ядра в generic, `ChainThreadPool` не вызывается вообще, задача бессмысленна раньше).

**Ключевой факт (§1.6):** `worker_module` не даёт `submit()`/`Future` API — нужен новый примитив.

**Дизайн `WorkerPoolExecutor` (новый, дом — либо `worker_module` как opt-in расширение, либо `chain_module/thread_pool/` как обёртка, ИСПОЛЬЗУЮЩАЯ `worker_module` внутри — рекомендация: второе, чтобы не расширять контракт `IWorkerManager` ради узкого кейса одного потребителя):**

1. При инициализации создаётся `N` персистентных LOOP-воркеров через `WorkerManager.create_worker(f"chain_pool_{i}", target=self._pool_loop, config={"execution_mode": "loop", ...})` — каждый крутит `while not stop_event: task = self._in_queue.get(timeout=...); ...; self._out_queue.put(...)`.
2. `submit_bundle(steps, frame, context)` — кладёт задачи в `self._in_queue` (`queue.Queue`), возвращает handle (не `concurrent.futures.Future` — `threading.Event`-based, как `PendingTask` в `WorkerPoolDispatcher` уже делает, [`worker_pool/dispatcher.py:27-32`](../../multiprocess_framework/modules/chain_module/worker_pool/dispatcher.py#L27-L32) — паттерн уже есть в chain_module, переиспользуем).
3. `collect_results(handles, steps, timeout)` — ждёт `Event`, читает результат — интерфейсно СОВМЕСТИМО с текущим `ChainThreadPool.submit_bundle`/`collect_results` (тот же вызывающий код в `ParallelChainRunnable` не меняется — только реализация пула).
4. `resize()` — для `worker_module` это `stop_worker` N старых + `create_worker` N новых (нет hot-resize `ThreadPoolExecutor`-стиля «изменить `max_workers` без пересоздания живых потоков») — приемлемая деградация, `resize()` — не hot-path операция.

**Почему не менять `IWorkerManager` напрямую:** единственный потребитель `submit()`-паттерна сегодня — `ChainThreadPool` (0 живых потребителей ДО (d), 1 живой ПОСЛЕ). Расширять публичный контракт 24-модульного `worker_module` (используемого ВЕЗДЕ — LOOP-воркеры почти в каждом процессе) ради одного потребителя — риск для стабильного API. Обёртка-адаптер локальна к `chain_module`, использует ТОЛЬКО существующий публичный `IWorkerManager` (create_worker/stop_worker), не требует правки `worker_module`.

**Характеризационные тесты:** существующие `test_thread_pool.py` (134 LOC) — заменить бэкенд, ожидания (submit→collect→timeout→cancel) должны остаться зелёными БЕЗ правки (контрактный тест на публичный API `ChainThreadPool`, не на реализацию).

**Acceptance:** `grep ThreadPoolExecutor multiprocess_framework/modules/chain_module/` = 0 (пул физически исчез, реализация — через `worker_module`); regression 0 красных; sentrux `check_rules` 0 нарушений (D2 закрыт).

---

## 6. Риски / откаты / анти-карго-культ

| Риск | Митигация |
|---|---|
| (c) ломает ~9 живых импортёров `SystemBlueprint` одним коммитом | back-compat шим-реэкспорт на переходный период; правка call sites — отдельные follow-up коммиты |
| (d) `ChainRunnable`-адаптер вызывает `plugin.process()` напрямую, минуя `PluginRunner` → io-debug/port-validation молча отключаются | контракт-тест «io-debug hook срабатывает на chain-исполняемом плагине» (регресс на `IoPeekPublisher`) |
| (d) circuit breaker / auto-reset семантика теряется при переходе на `apply_on_error_policy` | НЕ трогать `error_policy.py`; вся breaker-логика остаётся в `PipelineExecutor`/адаптере, chain используется ТОЛЬКО для последовательного прохода (см. §5(d) инкремент 1 п.3) |
| (d) `ChainContext`-аллокация на батч роняет FPS | измерить на обоих живых рецептах ДО мержа; откат — прямой list-loop, если регресс > baseline-порога |
| (e) `WorkerPoolExecutor` меняет latency параллельных бандлов (persistent LOOP + queue.get(timeout) vs `ThreadPoolExecutor.submit` — разная задержка планирования) | `step_timeout`-контракт (`ChainThreadPool.step_timeout`) должен покрыть worst-case queue latency; замер до/после |
| Обе задачи (b)+(c) вместе — большой diff, сложно ревьюить | выполнять КАК ОТДЕЛЬНЫЕ задачи/PR (как и написано в плане: «(a) дизайн→(b)→(c)→(d)→(e)»), каждая со своим гейтом regression-зелёный |
| DAG/parallel генерализация без потребителя (анти-карго-культ) | **осознанно НЕ делаем** в C6 — только доступность примитива (инкремент 2 §5d — вне скоупа, будущая задача при 2-м потребителе) |
| `frame_trace` разделение домен/механизм создаёт лишний модуль ради 0 выгоды | **осознанно НЕ делаем** — один физический файл, два логических клиента, задокументировано в §5(b).3 |
| Переименование `INSPECTOR_FRAME_TRACE` в рамках C6 (scope creep в packaging NEW-9) | **осознанно НЕ делаем** — оставляем как есть, ссылка на NEW-9 |
| Расширение `IWorkerManager` контракта ради (e) | **осознанно НЕ делаем** — локальный адаптер поверх публичного API, не трогаем 24-модульный контракт |

**Что НЕ делаем (сводка анти-карго-культ):**
- Не разделяем `frame_trace.py` на domain/engine файлы.
- Не вводим граф-топологию в `ProcessConfig.plugins` (DAG/Parallel — доступны, не обязательны).
- Не трогаем hot-path (SHM/seqlock/per-frame `Message` конструирование) — вне скоупа C6, строго Ф7.
- Не удаляем 4 typed-поля `ProcessConfig` сейчас — только добавляем `extras` рядом (Принцип №1 плана: ничего не удаляется без per-item одобрения владельца через G0/G4).
- Не расширяем `IWorkerManager`/`IWorkerLifecycle` контракт ради одного потребителя (e).
- Не переименовываем `INSPECTOR_*` env в рамках C6 (это NEW-9, В6).

---

## 7. Открытые вопросы владельцу

1. **Судьба `InspectorManager`/`JoinInspectorManager` — Plugins или Services?** Дизайн рекомендует `Plugins/_shared/` (переиспользуемый общий код домена, не привязанный к конкретному плагину, но и не отдельный сервис с lifecycle/IService — это чистые классы без процесса/соединения). Альтернатива — `Services/` если в будущем понадобится shared state между несколькими процессами (сегодня не нужно — буфер живёт внутри ОДНОГО процесса). **Рекомендация: Plugins/_shared/, пересмотреть если появится cross-process потребность.**

2. **Вариант A vs B для рычага 4 (§4)** — перенос установки `frame_trace.traced` в `PluginOrchestrator.boot()` (инстанс-время) vs opt-in hook-реестр (class-время, как сейчас). Зависит от того, есть ли тесты, полагающиеся на `cls.process._traced` СРАЗУ после объявления класса, без бута. **Нужна проверка перед стартом (b)/(d)-исполнения** — предлагаю поручить разведку исполнителю задачи, не блокировать дизайн-гейт этим.

3. **Имя нового подпакета в `process_manager_module` для `blueprint.py`** — `topology/blueprint.py` (предложено) vs плоский `blueprint.py` в корне модуля vs слияние с существующим топология-related кодом PM (`FullReplacePlanner` и т.п., если такой каталог уже есть — не проверялось в рамках этого дизайна, уточнить при исполнении (c)).

4. **Судьба typed-полей `ProcessConfig` (`chain_targets`/`source_target_fps`/`inspector`/`io_peek`) после (b) их закрывает** — удалять сразу после того, как логика переехала в Plugins и extras стал единственным путём записи, или держать typed-поля неопределённо долго как «удобный short-hand» для самых частых ключей (снижает boilerplate в рецептах: `chain_targets: [...]` короче `extras: {chain_targets: [...]}`)? **Рекомендация: держать typed-поля как UX-shorthand — они уже generic по имени (`chain_targets`/`source_target_fps` не vision-специфичны, это routing/FPS-параметры pipeline вообще), удалять стоит только `inspector`/`io_peek` (явно доменные) после (b).** Финальное решение — за владельцем при исполнении (b).

5. **Приоритет (d)/(e) относительно В2 (5.11-5.13)** — дизайн рекомендует ПОСЛЕ (см. §5 «Порядок»), но decision-log владельца поставил C6 сразу после C3 в очереди В1 ([`plans/current-path/plan.md:51`](../current-path/plan.md#L51): «C1→C2→C3→C6→C7→C8»), ДО В2. **Уточнить: (b)/(c) исполняются в очереди В1 как написано; (d)/(e) — сдвинуть в В2/после 5.13, или исполнять всё C6 целиком в В1 несмотря на повышенный риск без `minimal_app`-регресс-сигнала?** Рекомендация дизайна: сдвинуть (d)/(e), (a)+(b)+(c) — не блокируются.
