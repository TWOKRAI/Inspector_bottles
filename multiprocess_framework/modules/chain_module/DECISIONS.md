# chain_module — Архитектурные решения

## ADR-CHN-001: Protocol-based decoupling от доменных типов

**Статус:** Принято (2026-05-01)

**Контекст:**
`ChainRunnable`, `DagRunnable`, `ParallelChainRunnable` используют типы из прототипа:
`ProcessingNode` (регистры), `ChainContext`, `ProcessingOperation` (operations/base).
Перенос в фреймворк требует разорвать эти зависимости.

**Решение:**
Определить минимальные Protocol-интерфейсы в `interfaces.py`:
- `IStepNode` — вместо `ProcessingNode` (node_id, operation_ref, inputs)
- `INodeConnection` — вместо `NodeInput` (source, input_port, output_port)
- `IExecutionStep` — вместо `ProcessingOperation` (execute, configure)

Доменные классы прототипа реализуют эти протоколы структурно (без наследования).
`ChainContext` перемещён во фреймворк (`core/context.py`) — он не содержит доменной логики.

**Последствия:**
- chain_module не импортирует ничего из `multiprocess_prototype.*`
- Прототип re-экспортирует `ChainContext` из фреймворка
- Типы аннотированы как `Any` где нужна гибкость (RunnableStep.node, pool в parallel.py)

---

## ADR-CHN-002: ChainContext перемещён во фреймворк

**Статус:** Принято (2026-05-01)

**Контекст:**
`ChainContext` — простой dataclass (`camera_id`, `region_id`, `seq_id`, accumulators).
Не содержит доменной логики, но живёт в `services/processor/operations/base.py`.

**Решение:**
Переместить `ChainContext` в `chain_module/core/context.py`.
Прототип в `operations/base.py` делает re-export: `from multiprocess_framework.modules.chain_module import ChainContext`.

**Последствия:**
- `camera_id`/`region_id` — generic source/target identifiers, не domain-specific
- Все операции прототипа работают без изменений (re-export прозрачный)

---

## ADR-CHN-003: builder.py остаётся в прототипе

**Статус:** Принято (2026-05-01)

**Контекст:**
`GraphRunnableBuilder.build()` вызывает `load_operation_class(op_def.module_path)` и использует
`ProcessingOperationDef` из `registers.processor.catalog.schemas`. Это pure domain-код.

**Решение:**
`builder.py` остаётся в прототипе, использует graph-утилиты из фреймворка:
```python
from multiprocess_framework.modules.chain_module import topological_sort, is_nonlinear_graph, detect_parallel_bundles
```
Топологическая сортировка и анализ графа — в `chain_module/graph/`.

---

## ADR-CHN-004: autofill.py остаётся в прототипе

**Статус:** Принято (2026-05-01)

**Контекст:**
`autofill_inputs()` вызывает `ProcessingNode.model_copy()` — Pydantic v2 API.
Это domain-specific (зависит от конкретной схемы `ProcessingNode`).

**Решение:**
`autofill.py` остаётся в `services/processor/chain/autofill.py`.
Обобщённый `autofill` для фреймворка не нужен на данном этапе.

---

## ADR-CHN-005: DagRunnable содержит _execute_dag_default

**Статус:** Принято (2026-05-01)

**Контекст:**
В прототипе `execute_dag_default` жил в `operations/base.py` и импортировался в `dag_runnable.py`.
После переноса создаётся обратная зависимость (fw ← prototype).

**Решение:**
`_execute_dag_default()` переносится в `chain_module/core/dag.py`.
В прототипе `operations/base.py` функция может быть удалена или оставлена как re-export.

---

## ADR-CHN-006: Явный IRemoteExecutable + общая on_error политика

**Статус:** Принято (2026-05-07)

**Контекст:**
1. `_is_cross_process(step)` использовал duck-typing через `hasattr("execute_remote", "dispatcher")`,
   но сигнатура `execute_remote(frame, context, input_shm_name, input_shm_index)` была зафиксирована
   только в `core/chain.py` — без явного Protocol-контракта в `interfaces.py`.
2. `ParallelChainRunnable` **не проверял** `_is_cross_process(step)` — для cross-process шага
   падал на `step.operation.execute(frame, ctx)` с AttributeError. Реальная регрессия.
3. Логика on_error (skip / fail_region / fail_camera) дублировалась в 3 файлах:
   `core/chain.py`, `core/dag.py`, `core/parallel.py` — DRY-нарушение, расхождение формулировок.
4. `RunnableStep.node` и `RunnableStep.operation` были типизированы как `Any`,
   что отключало статическую проверку доступа к `node.node_id` / `node.operation_ref`.

**Решение:**
1. Добавить `IRemoteExecutable` Protocol в `interfaces.py` — явный контракт cross-process шага.
   `_is_cross_process` остаётся через `hasattr` (избегаем циклов импорта), но контракт публичный.
2. Добавить cross-process ветку в `ParallelChainRunnable._execute_remote` (синхронное исполнение
   через `execute_remote` — параллелизм через ThreadPool бессмыслен, dispatcher уже блокирует
   поток). Бандл разделяется на remote/local: cross-process идут синхронно, local — через пул.
3. Вынести on_error логику в `core/error_policy.apply_on_error_policy(step, exc, ctx, result)
   -> bool` (returns should_break). Все три исполнителя зовут эту функцию.
4. Заменить `Any` на `IStepNode` / `IExecutionStep` в `RunnableStep` —
   оба Protocol уже `@runtime_checkable`, поэтому duck-typing не ломается.

**Последствия:**
- Cross-process шаги работают одинаково во всех трёх исполнителях.
- Сообщения об ошибках унифицированы (формат `"Операция '...' (node=...) упала: ...  on_error=..."`).
- IDE и type-checker подсказывают атрибуты `node.node_id` / `operation.execute`.
- Прототип (`CrossProcessStep` в `services/processor/`) не требует изменений —
  Protocol совпадает с фактическим API.
- Поведенческий тест `test_parallel_runnable.py` фиксирует регрессию.

---

## ADR-CHN-007: ObservableMixin для долгоживущих сервисов модуля

**Статус:** Принято (2026-05-07)

**Контекст:**
До итерации 2026-05-07 только `ChainThreadPool` наследовался от
`BaseManager + ObservableMixin`. `WorkerPoolDispatcher` и `LatencyTracker`
принимали `logger=None` параметром и использовали приватный паттерн
`self._log._log_warning(msg)` (вызов приватных методов у переданного объекта).
Метрики были скрытыми атрибутами (`_drops_total`, `_dispatched_total`,
`_timeout_total` в Dispatcher) — недоступны через единый интерфейс.
Сами модуль `metrics` не публиковал ничего в `StatsManager`.

**Решение:**
Подключить `BaseManager + ObservableMixin` к **долгоживущим сервисам** chain_module:
1. `WorkerPoolDispatcher` принимает `logger`, `stats`, `errors` (всё опц.).
   Заменяет ручные строки лога на `self._log_*`. Публикует:
   - `worker_pool.dispatched` / `.timeouts` / `.drops` / `.late_responses` / `.errors` (counters)
   - `worker_pool.processing_time` (timing per success ответ)
   Реализует `initialize()`/`shutdown()` (последний отменяет все pending задачи).
2. `LatencyTracker` принимает `logger`, `stats`, `metric_name` (default `chain.latency_ms`).
   Каждый `record(e2e_ms)` пишется в `_record_timing`. `maybe_log()` дополнительно
   публикует snapshot p50/p95/p99 как метрики `<name>.p50/.p95/.p99`.

**Не подключаем:**
Исполнители (`ChainRunnable`, `DagRunnable`, `ParallelChainRunnable`) и data-классы
(`RunnableStep`, `ChainResult`, `ChainContext`) **остаются обычными классами**.
Причины:
- Исполнители создаются на каждый `RegisterRuntime.rebuild()` → registry с менеджерами
  на каждом билде = лишняя память.
- Логгер уже доступен в исполнителях через `ChainContext.logger` (передаётся один раз
  при создании контекста), `apply_on_error_policy` использует его.
- Data-классы не имеют поведения — Mixin им не нужен по определению.

**Последствия:**
- Все три параметра — keyword, со значением `None` по умолчанию → старые места
  создания (например `Plugins/services/processor_service/plugin.py`)
  работают без изменений.
- `StatsManager.percentiles("chain.latency_ms")` — теперь основной источник истины
  для p50/p95/p99 latency (не парсинг лога). GUI / Inspector могут читать оттуда.
- `ErrorManager.track_error()` доступен, но пока не вызывается из chain_module
  (резерв на будущее — добавить в `apply_on_error_policy` опционально).
- Все тесты (фреймворк 67/67 + прототип test_worker_pool_dispatcher 14/14) проходят
  без модификации.

---

## ADR-CHN-008: Публичный IChainLogger Protocol для исполнителей

**Статус:** Принято (2026-05-07)

**Контекст:**
- `ChainContext.logger` был типизирован `Any` — у внешнего объекта вызывались
  псевдо-приватные методы `log._log_warning(msg)` / `log._log_error(msg)` в
  `core/error_policy.py`. Имена с `_` в `IObservableMixin` маркируют их как
  «семейные» методы для наследников `BaseManager` — вызов из чужого модуля
  нарушает эту конвенцию.
- В коде прототипа `ChainContext(logger=...)` сейчас не передаётся (ветка
  `if log is not None: ...` всегда уходит в no-op), но контракт всё равно
  должен быть зафиксирован — иначе любая попытка передать настоящий
  логгер натолкнётся на стилистическую регрессию.

**Решение:**
1. `IChainLogger` — узкий `runtime_checkable` Protocol в
   `chain_module/interfaces.py` с тремя публичными методами:
   `log_info`, `log_warning`, `log_error`. `log_debug` / `log_critical`
   не включены — внешним потребителям chain_module они не нужны.
2. `ChainContext.logger: IChainLogger | None` (вместо `Any`).
3. `core/error_policy.py` зовёт `log.log_warning` / `log.log_error`.
4. `ObservableMixin` получает публичные алиасы `log_debug/info/warning/error/critical`
   как методы класса — тонкие обёртки над `_log_*`. Это автоматически делает
   любого наследника `BaseManager + ObservableMixin` совместимым с
   `IChainLogger` через duck-typing.

**Не делаем:**
- ❌ Переименование `_log_*` → `log_*` внутри менеджеров. Это отдельный
  рефакторинг ~21 модуля без архитектурной пользы. `_log_*` остаются
  каноничным внутренним путём.
- ❌ `@abstractmethod` на публичные `log_*` в `IObservableMixin` ABC —
  заставило бы все standalone-фейки в тестах реализовать их. Контракт
  фиксируется в `ObservableMixin` и `IChainLogger`.

**Последствия:**
- Внешний код может передавать в `ChainContext` любой объект с тремя
  методами (упрощает тесты — не нужен `Mock(spec=...)` с приватными
  атрибутами).
- `isinstance(LoggerManager_instance, IChainLogger)` → `True` (smoke-тест).
- `auto_proxy=True` режим продолжает работать без изменений: динамические
  замыкания в `__dict__` имеют приоритет в lookup, методы класса остаются
  как fallback для `auto_proxy=False`.

---

## ADR-CHN-009: Пул параллельных бандлов на worker_module (C6e), а не свой ThreadPoolExecutor

**Статус:** Принято (2026-07-13)

**Контекст:**
- `ChainThreadPool` держал собственный `concurrent.futures.ThreadPoolExecutor` —
  второй, дублирующий механизм потоков в фреймворке (D2 аудита
  2026-07-10_module-responsibility-duplication-map): рядом с `worker_module`
  (`WorkerManager` — реестр именованных `threading.Thread` с LOOP/TASK-режимами),
  который уже несёт почти все потоки процессов.
- Дизайн C6 (`plans/2026-07-06_constructor-master/c6-pipeline-engine-design.md`
  §5(e)) требует: chain-параллелизм исполняется через пул `worker_module`, свой
  поток-пул физически исчезает (`grep ThreadPoolExecutor chain_module/ = 0`).
- `worker_module` НЕ даёт `submit()`/`Future`-API — это не drop-in замена
  `ThreadPoolExecutor`. Нужен новый примитив поверх публичного контракта.

**Решение:**
1. Новый `WorkerPoolExecutor` (`thread_pool/worker_pool_executor.py`): N
   персистентных LOOP-воркеров через `WorkerManager.create_worker("chain_pool_i",
   …)`, общая `queue.Queue`, handle `_PoolTask` — Event-based (паттерн
   `PendingTask` из `worker_pool/dispatcher.py`) с `result(timeout)`,
   интерфейсно совместимым с `Future.result(timeout)`.
2. `ChainThreadPool` — тонкий фасад-наследник `WorkerPoolExecutor`: публичное имя
   и контракт (`submit_bundle`/`collect_results`/`resize`/`step_timeout`/
   `max_workers`) не изменились. `ParallelChainRunnable` и `test_thread_pool.py`
   (контрактный тест) работают без правок.
3. `resize()` = `remove_worker` N старых + `create_worker` N новых.
   `remove_worker` (не `stop_worker`) — снимает имя с учёта в реестре, иначе
   `chain_pool_i` осталось бы занятым STOPPED-воркером и пересоздание
   коллизировало бы. resize не hot-path — деградация приемлема.
4. Пул создаётся в `__init__` (как прежний executor — готов сразу), собственный
   `WorkerManager` локален экземпляру; опционально инжектится извне (тесты).

**Отвергнуто:**
- ❌ Расширять `IWorkerManager` методом `submit()`/`Future`. Единственный
  потребитель submit-паттерна — chain-пул. Расширять публичный контракт
  worker_module (LOOP-воркеры почти в каждом процессе) ради одного узкого кейса —
  риск для стабильного API. Обёртка-адаптер локальна к chain_module.

**Последствия:**
- Свой поток-пул из stdlib исчез (D2 закрыт); один механизм потоков в фреймворке.
- Worst-case latency очереди покрывается контрактом `step_timeout`; замер
  submit→collect на 640×480×3-бандле из 3 шагов ≈ 714 µs (доминирует `frame.copy`,
  накладные пула планирования пренебрежимы: idle-воркер в `queue.get` забирает
  задачу сразу, poll 0.05с ограничивает только отзывчивость к `stop_event`).
- `ChainThreadPool` без живых рантайм-потребителей до подключения
  `ParallelChainRunnable` в generic (C6d инкремент 2, вне скоупа) — тесты
  единственный потребитель.
