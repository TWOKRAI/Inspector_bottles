# chain_module — Архитектурные решения

## ADR-CM-001: Protocol-based decoupling от доменных типов

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

## ADR-CM-002: ChainContext перемещён во фреймворк

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

## ADR-CM-003: builder.py остаётся в прототипе

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

## ADR-CM-004: autofill.py остаётся в прототипе

**Статус:** Принято (2026-05-01)

**Контекст:**
`autofill_inputs()` вызывает `ProcessingNode.model_copy()` — Pydantic v2 API.
Это domain-specific (зависит от конкретной схемы `ProcessingNode`).

**Решение:**
`autofill.py` остаётся в `services/processor/chain/autofill.py`.
Обобщённый `autofill` для фреймворка не нужен на данном этапе.

---

## ADR-CM-005: DagRunnable содержит _execute_dag_default

**Статус:** Принято (2026-05-01)

**Контекст:**
В прототипе `execute_dag_default` жил в `operations/base.py` и импортировался в `dag_runnable.py`.
После переноса создаётся обратная зависимость (fw ← prototype).

**Решение:**
`_execute_dag_default()` переносится в `chain_module/core/dag.py`.
В прототипе `operations/base.py` функция может быть удалена или оставлена как re-export.
