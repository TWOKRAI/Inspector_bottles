### Task 8.2 -- DAG-валидация + DagRunnable

**Уровень:** Senior+ (Opus, extended thinking)
**Исполнитель:** teamlead
**Цель:** Расширить `GraphRunnableBuilder` полноценной DAG-валидацией (ацикличность + совместимость типов портов) и создать `DagRunnable` для исполнения графов с ветвлениями и merge.

**Контекст:**
Текущий `GraphRunnableBuilder` уже выполняет topological sort (Kahn's algorithm) и обнаруживает циклы. Но: (1) не валидирует типы портов; (2) `ChainRunnable.execute()` передаёт один `current_frame` линейно -- не поддерживает ветвления (1->2) и merge (2->1). Для Phase 8 нужен `DagRunnable`, который маршрутизирует данные по портам между узлами.

**Файлы:**
- `multiprocess_prototype/services/processor/chain/builder.py` -- расширить валидацию
- `multiprocess_prototype/services/processor/chain/dag_runnable.py` -- **создать**: DagRunnable
- `multiprocess_prototype/services/processor/chain/runnable.py` -- добавить общий Protocol/ABC `IRunnableChain`
- `multiprocess_prototype/services/processor/operations/base.py` -- расширить `ProcessingOperation.execute()` для multi-port I/O
- `multiprocess_prototype/tests/unit/test_dag_runnable.py` -- **создать**
- `multiprocess_prototype/tests/unit/test_dag_validation.py` -- **создать**

**Шаги:**

1. **Определить Protocol `IRunnableChain`** в `runnable.py`:
   ```python
   class IRunnableChain(Protocol):
       def execute(self, frame: np.ndarray, metadata: dict | None = None) -> ChainResult: ...
   ```
   `ChainRunnable` и `DagRunnable` оба реализуют этот протокол. Существующий код, принимающий `ChainRunnable`, не ломается.

2. **Расширить `ProcessingOperation`** -- добавить альтернативный метод `execute_dag`:
   ```python
   def execute_dag(self, inputs: dict[str, Any], context: ChainContext) -> dict[str, Any]:
       """Исполнение в DAG-режиме: принимает именованные входы, возвращает именованные выходы.
       
       Default: оборачивает legacy execute() -- берёт inputs["in"], возвращает {"out": result}.
       Операции с нестандартными портами переопределяют этот метод.
       """
       frame = inputs.get("in")
       result = self.execute(frame, context)
       return {"out": result}
   ```
   Это обеспечивает обратную совместимость -- существующие операции работают без изменений.

3. **Расширить `GraphRunnableBuilder.build()`** -- добавить валидацию портов после topological sort:
   - Для каждой связи `(source_node, output_port) -> (target_node, input_port)`:
     - Проверить, что `output_port` существует в `catalog[source.operation_ref].output_ports`
     - Проверить, что `input_port` существует в `catalog[target.operation_ref].input_ports` (input_port берётся из позиции в `inputs` -- первый input -> первый input_port, или по имени)
     - Проверить совместимость типов через `are_ports_compatible()`
   - При несовместимости -- `ValueError` с описанием проблемной связи

4. **Расширить `NodeInput`** -- добавить `input_port: str = "in"` (в какой входной порт target-ноды подключается эта связь). **Внимание:** это поле нужно добавить в `processing_node.py`. Текущий `NodeInput` имеет `source` и `output_port`, но не `input_port` (на какой вход target подключается). Для линейных цепочек это не нужно (один вход), но для DAG -- обязательно.

5. **Создать `DagRunnable`** в `dag_runnable.py`:
   ```python
   class DagRunnable:
       """Исполнение DAG: маршрутизация данных по портам между узлами."""
       
       def __init__(self, steps: list[RunnableStep], topology: list[str]):
           # topology -- topological order node_ids
           # steps indexed by node_id
       
       def execute(self, frame: np.ndarray, metadata: dict | None = None) -> ChainResult:
           # 1. port_data: dict[str, dict[str, Any]] -- {node_id: {port_name: data}}
           # 2. Для "frame" source: port_data["frame"]["out"] = frame
           # 3. По topological order:
           #    a. Собрать inputs из port_data[inp.source][inp.output_port]
           #    b. Вызвать operation.execute_dag(inputs, context)
           #    c. Записать outputs в port_data[node_id]
           # 4. Собрать результат из последнего узла (или узлов без зависимых)
   ```

6. **Расширить `GraphRunnableBuilder.build()`** -- если граф нелинеен (есть ветвления), возвращать `DagRunnable`. Если линеен -- `ChainRunnable` (обратная совместимость).

7. **Определение нелинейности:**
   - Граф линеен, если каждая нода имеет <= 1 зависимой (dependents) и <= 1 зависимости (inputs)
   - Иначе -- DAG

8. **Тесты:**
   - Линейная цепочка A->B->C -- возвращает `ChainRunnable` (обратная совместимость)
   - DAG с ветвлением A->{B,C}->D -- возвращает `DagRunnable`, результат корректен
   - Цикл A->B->A -- `ValueError`
   - Несовместимые типы портов -- `ValueError`
   - Операция с `execute_dag` default -- работает через legacy `execute()`

**Критерии приёмки:**
- [ ] Линейные цепочки из Phase 5 продолжают работать без изменений (ChainRunnable)
- [ ] Ветвление 1->2: данные копируются в оба выхода
- [ ] Merge 2->1: DagRunnable собирает inputs из двух источников
- [ ] Несовместимые порты -> ValueError с описанием
- [ ] Цикл -> ValueError (уже работает, проверить)
- [ ] `NodeInput` получает `input_port: str = "in"` (обратная совместимость)
- [ ] `ProcessingOperation.execute_dag()` default оборачивает legacy execute()
- [ ] Все существующие тесты chain проходят
- [ ] `ruff check` + `ruff format` проходят

**Вне scope:**
- Параллельное исполнение внутри DagRunnable (ThreadPool) -- не в этой задаче, `ParallelChainRunnable` уже существует для линейных бандлов
- Визуальный UI (Task 8.3-8.6)
- Изменение YAML-каталога

**Edge cases:**
- Граф из одной ноды (без связей) -- работает как раньше
- Нода с `enabled=False` в середине DAG -- пропускается, зависимые получают данные от предыдущего уровня (или ошибку если нет альтернативного пути)
- `optional=True` input_port без подключения -- передаётся `None`
- "frame" как source -- внешний вход (кадр с камеры), не нода

**Зависимости:** Task 8.1 (Port schema, `are_ports_compatible`)
