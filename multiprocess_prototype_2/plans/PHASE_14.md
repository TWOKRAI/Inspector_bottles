# Plan: Phase 14 — Schema Ports + Inspector + Safe FW Extraction

**Дата:** 2026-05-09
**Статус:** DONE
**Ветка:** refactor/t1.1-plugin-composition

---

## Обзор

Phase 13 завершена: Pipeline Editor работает полностью, 181 тест зелёный.

Phase 14 делает две вещи:

**Wave 1 — Фичи** (улучшают прототип без риска регрессий):
- Task 14.1 — Schema-Driven Ports: NodeItem рисует реальные N портов из `PluginEntry.inputs/outputs`, wire validation использует `are_ports_compatible()` из FW port module.
- Task 14.2 — Inspector + CardsFieldFactory: `NodeInspectorPanel` показывает типизированные виджеты из `FieldInfo` вместо `QLineEdit`, изменения идут через `ActionBus`.

**Wave 2 — Безопасная экстракция** (pure Python или уже спроектированные handlers, 0 поведенческих изменений):
- Task 14.3 — dag_utils + layout → FW: чистый Python без зависимостей (~280 LOC), re-exports в прототипе.
- Task 14.4 — Actions handlers → FW: `TopologyMutationHandler` и `NodeMoveHandler` уже используют `TYPE_CHECKING` импорты из FW actions/schemas — перенос в `frontend_module/actions/handlers/`, re-exports в прототипе.

**Отложено до Phase 16 (второй consumer):**
- GraphModel base class
- PortItem/TempWireItem в FW
- BasePalette/GenericDropTarget в FW

---

## Текущее состояние (важно знать)

- `frontend_module/actions/` уже содержит `bus.py`, `schemas.py`, `builder.py` — Task 14.4 добавляет `handlers/`
- `PluginEntry.inputs` / `.outputs` → `list[Port]`, где `Port.name` и `Port.dtype` — реальные типы (`image/bgr`, `image/gray`, `any`)
- `are_ports_compatible(output, input_port)` уже реализована в `process_module/plugins/port.py`
- `NodeItem` сейчас создаёт ровно 1 input + 1 output порт — `PortItem("input", f"{node_id}.input", category)`
- `validate_port_compatibility()` в `dag_utils.py` — заглушка: `return source_type == "output" and target_type == "input"`
- `NodeInspectorPanel` — `QLineEdit` для всех полей, уже имеет `field_changed Signal(str, str, object)`, `update_field()` с signal suppression
- `CardsFieldFactory` находится в `multiprocess_prototype_2/frontend/forms/factory.py`, принимает `FieldInfo`
- `topology_mutation_handler.py` использует `TYPE_CHECKING` импорты из `multiprocess_framework.modules.frontend_module.actions.schemas`
- `node_move_handler.py` использует `TYPE_CHECKING` импорты из `multiprocess_framework.modules.frontend_module.actions.schemas`

---

## Порядок выполнения

```
Wave 1 (независимы, параллельно):
  Task 14.1 — Schema-Driven Ports   [Middle+, Developer]
  Task 14.2 — Inspector + CFF       [Middle+, Developer]

Wave 2 (независимы друг от друга, Wave 1 не блокирует Wave 2):
  Task 14.3 — dag_utils + layout → FW   [Middle, Developer]
  Task 14.4 — Actions handlers → FW     [Middle, Developer]
```

---

## Tasks

---

### Task 14.1 — Schema-Driven Ports

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Status:** [DONE]
**Goal:** `NodeItem` рисует N портов из реальных `PluginEntry.inputs/outputs`, а wire validation проверяет совместимость типов через `are_ports_compatible()`.

**Контекст:**
Сейчас `NodeItem.__init__()` создаёт ровно один `PortItem("input", ...)` и один `PortItem("output", ...)` — это заглушки. Реальные плагины (например `color_mask`) имеют `inputs = [Port(name="frame", dtype="image/bgr")]` и `outputs = [Port(name="mask", dtype="image/gray")]`. `validate_port_compatibility()` в `dag_utils.py` — строчная заглушка. `are_ports_compatible()` в `process_module/plugins/port.py` уже реализована полноценно с wildcard/shape логикой.

`PipelinePresenter.add_process_from_plugin()` уже получает `registry.get(plugin_name)` — здесь можно достать `entry.inputs/outputs`.

Новый `PortSchema` нужен только как простой dataclass-мост между presenter и NodeItem — он не должен дублировать `Port`.

**Файлы:**

Создать:
- `multiprocess_prototype_2/frontend/widgets/tabs/pipeline/graph/port_schema.py` — `PortSchema` dataclass (мост presenter→NodeItem)

Изменить:
- `multiprocess_prototype_2/frontend/widgets/tabs/pipeline/graph/node_item.py` — принять `port_schemas: list[PortSchema] | None`, создать N портов
- `multiprocess_prototype_2/frontend/widgets/tabs/pipeline/presenter.py` — передавать `port_schemas` при создании ноды
- `multiprocess_prototype_2/frontend/widgets/tabs/pipeline/dag_utils.py` — расширить `validate_port_compatibility()` для dtype-совместимости
- `multiprocess_prototype_2/frontend/widgets/tabs/pipeline/model.py` — расширить `add_wire()` для type-aware валидации

Тесты (расширить / создать):
- `multiprocess_prototype_2/frontend/widgets/tabs/pipeline/tests/test_dag_utils.py` — тесты `validate_port_compatibility()`
- `multiprocess_prototype_2/frontend/widgets/tabs/pipeline/tests/test_model.py` — тесты type-check в `add_wire()`
- `multiprocess_prototype_2/frontend/widgets/tabs/pipeline/tests/test_ports.py` — тесты NodeItem с port_schemas

**Шаги:**

1. Создать `port_schema.py`:
   ```
   @dataclass
   class PortSchema:
       name: str        # "frame", "mask"
       direction: str   # "input" | "output"
       dtype: str       # "image/bgr", "any" (из Port.dtype)
       optional: bool = False
   ```
   Это thin-wrapper — не копирует Port целиком, берёт только нужные поля для визуализации.

2. Изменить `NodeItem.__init__()`:
   - Добавить параметр `port_schemas: list[PortSchema] | None = None`
   - Если `port_schemas` передан: создать `PortItem` для каждого entry, разделить inputs и outputs
   - Расположить input-порты равномерно по левому краю, output-порты — по правому краю
   - Если `port_schemas is None`: backward compat — создать один input + один output как раньше
   - Обновить `input_port` / `output_port` properties: для обратной совместимости вернуть первый соответствующий порт
   - Добавить `input_ports: list[PortItem]` и `output_ports: list[PortItem]` properties (все порты)
   - Tooltip для каждого `PortItem`: `f"{schema.name}: {schema.dtype}"`

3. Расширить `validate_port_compatibility(src_dtype: str, tgt_dtype: str) -> bool` в `dag_utils.py`:
   - Переименовать параметры с `source_type/target_type` на `src_dtype/tgt_dtype` — signature меняется, нужен backward compat alias
   - Логика: `"any"` совместим с любым; wildcard `"image/*"` принимает `"image/bgr"`, `"image/gray"`; иначе точное совпадение
   - **Не** импортировать `are_ports_compatible` из FW — реализовать упрощённую версию inline (без shape-проверки)
   - Старую заглушку-реализацию удалить
   - Добавить `get_port_tooltip(dtype: str) -> str` — человекочитаемое описание типа

4. Расширить `PipelineModel.add_wire(source, target, src_dtype="any", tgt_dtype="any")`:
   - Новые опциональные параметры `src_dtype: str = "any"`, `tgt_dtype: str = "any"`
   - Вызвать `validate_port_compatibility(src_dtype, tgt_dtype)` перед cycle detection
   - При несовместимости: `raise ValueError(f"Несовместимые типы портов: {src_dtype} → {tgt_dtype}")`
   - Хранить dtype в wire dict: `{"source": "...", "target": "...", "src_dtype": "any", "tgt_dtype": "any"}`
   - Если `src_dtype == "any"` — пропустить type check (backward compat)

5. В `PipelinePresenter.add_process_from_plugin()`:
   - После получения `entry = registry.get(plugin_name)`: собрать `port_schemas = [PortSchema(p.name, "input", p.dtype, p.optional) for p in entry.inputs] + [PortSchema(p.name, "output", p.dtype, p.optional) for p in entry.outputs]`
   - Если `entry is None` или `entry.inputs == [] and entry.outputs == []`: `port_schemas = None` (backward compat)
   - Передать `port_schemas` в `NodeData` (расширить `NodeData` полем `port_schemas: list | None = None`) или передать напрямую в `GraphScene.add_node()`

6. В `PipelinePresenter.add_wire()`:
   - Извлечь dtype из endpoint-строк через `_scene` (получить `PortItem.dtype` по endpoint имени)
   - Fallback: если dtype неизвестен → `"any"` (backward compat)
   - Передать `src_dtype`, `tgt_dtype` в `self._model.add_wire()`

7. Написать тесты:
   - `test_dag_utils.py`: `validate_port_compatibility("image/bgr", "image/bgr")` → True; `("image/bgr", "image/gray")` → False; `("any", "image/bgr")` → True; `("image/*", "image/bgr")` → True; `("image/bgr", "image/*")` → True
   - `test_model.py`: `add_wire` с совместимыми dtype → OK; с несовместимыми → ValueError; с `any` → OK
   - `test_ports.py`: `NodeItem(data, port_schemas=[...])` создаёт правильное число PortItem; без port_schemas → 1 input + 1 output

**Acceptance criteria:**
- [ ] `PortSchema` dataclass определён в `pipeline/graph/port_schema.py` с полями `name`, `direction`, `dtype`, `optional`
- [ ] `NodeItem` принимает `port_schemas`, рисует N input-портов слева и M output-портов справа
- [ ] `NodeItem` без `port_schemas` (None): backward compat — 1 input + 1 output, все существующие тесты проходят
- [ ] `validate_port_compatibility("image/bgr", "image/bgr")` → True; `("image/bgr", "image/gray")` → False; `("any", X)` → True; `("image/*", "image/bgr")` → True
- [ ] `PipelineModel.add_wire()` с несовместимыми dtype бросает `ValueError`
- [ ] `PipelinePresenter` передаёт `port_schemas` из PluginRegistry при добавлении ноды
- [ ] Graceful fallback: если PluginRegistry недоступен или плагин без портов → `port_schemas = None`, нода с 1+1 портами
- [ ] Все 181 существующих тестов pipeline проходят без изменений
- [ ] Новые тесты: ≥10 (validate_port_compatibility: 5+, add_wire type check: 3+, NodeItem ports: 2+)

**Out of scope:**
- Изменение формата topology YAML (dtype в wire — только in-memory)
- UI-диалог просмотра типов (только tooltip при наведении)
- Интеграция с `are_ports_compatible()` из FW (отдельная зависимость, достаточно inline-логики)
- Перенос `PortItem` в FW

**Edge cases:**
- Плагин без портов (`entry.inputs == []` и `entry.outputs == []`) → `port_schemas = None`, backward compat
- Wire из topology YAML без dtype-info → `src_dtype="any"`, `tgt_dtype="any"`, type check пропускается
- `NodeItem` с 3 inputs: расположить равномерно по высоте ноды — шаг `NODE_HEIGHT / (count + 1)`

---

### Task 14.2 — Inspector + CardsFieldFactory

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Status:** [DONE]
**Goal:** `NodeInspectorPanel` показывает типизированные виджеты из `CardsFieldFactory` вместо `QLineEdit`, изменения поля идут через `ActionBus` как undoable действия.

**Контекст:**
`NodeInspectorPanel` в `inspector/inspector_panel.py` уже имеет всю нужную архитектуру: `field_changed Signal`, `update_field()` с signal suppression, `show_node(process_name, category, plugins, params)`. Нужно расширить `show_node()`: если `RegistersManager` доступен через `AppContext` — запросить `list[FieldInfo]` и использовать `CardsFieldFactory` для генерации виджетов вместо `QLineEdit`. Если нет — оставить `QLineEdit` (fallback).

`CardsFieldFactory` находится в `frontend/forms/factory.py`, создаёт `FieldEditor` из `FieldInfo`. `FieldEditor` имеет signal `valueChanged`.

`PipelinePresenter` уже подключается к `inspector.field_changed` → нужно добавить обработчик `_on_inspector_field_changed()` который вызывает `ActionBus.execute(V2ActionBuilder.field_set_timed(...))`.

**Файлы:**

Изменить:
- `multiprocess_prototype_2/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py` — добавить CardsFieldFactory-ветку в `show_node()`
- `multiprocess_prototype_2/frontend/widgets/tabs/pipeline/presenter.py` — добавить `_on_inspector_field_changed()` + подписку на сигнал

Тесты (расширить):
- `multiprocess_prototype_2/frontend/widgets/tabs/pipeline/tests/test_inspector.py` — тесты CardsFieldFactory-ветки, ActionBus routing, signal suppression

**Шаги:**

1. В `NodeInspectorPanel.__init__()`:
   - Добавить `self._ctx: AppContext | None = None` и метод `set_context(ctx: AppContext) -> None`
   - Переименовать `self._field_editors: dict[str, QLineEdit]` → `self._field_widgets: dict[str, QWidget]` (для generics)
   - Добавить `self._use_cards: bool = False` (флаг режима)

2. Расширить `show_node()`:
   - После очистки параметров: если `self._ctx` задан → получить `rm = self._ctx.registers_manager()` (если метод существует) или `None`
   - Если `rm` доступен: `fields = rm.get_fields(process_name)` — список `FieldInfo`
   - Если `fields` непустой: для каждого `FieldInfo` создать виджет через `CardsFieldFactory.create(fi)` → `FieldEditor`
   - Подключить `field_editor.valueChanged → lambda: self._on_field_editor_changed(field_name, field_editor)`
   - Сохранить в `self._field_widgets[field_name] = field_editor`
   - Если `rm` недоступен или `fields` пустой → `QLineEdit` fallback (как сейчас)
   - Установить `self._use_cards = (rm is not None and bool(fields))`

3. Обновить `update_field(field_name, value)`:
   - Если `self._use_cards` и виджет — `FieldEditor`: вызвать `field_editor.set_value(value)` вместо `setText`
   - Иначе: `QLineEdit.setText(str(value))` как раньше
   - Signal suppression через `self._suppress_changes` — работает для обоих путей

4. Добавить `_on_field_editor_changed(field_name: str, editor: FieldEditor) -> None`:
   - Если `self._suppress_changes` → return
   - Получить `value = editor.get_value()`
   - Emit `self.field_changed(self._current_process, field_name, value)`

5. Обновить `_clear_params()`:
   - Отключить все сигналы `FieldEditor` перед удалением (избежать emit при deleteLater)
   - Работает для обоих типов виджетов

6. В `PipelinePresenter.__init__()` или `set_scene()`:
   - Добавить `self._inspector: NodeInspectorPanel | None = None` и `set_inspector(panel)` метод
   - При подключении inspector: `inspector.set_context(self._ctx)` + подписаться на `inspector.field_changed → self._on_inspector_field_changed`

7. Добавить `PipelinePresenter._on_inspector_field_changed(process_name: str, field_name: str, new_value: object) -> None`:
   - Получить `old_value`: `rm.get_field_value(process_name, field_name)` если `rm` доступен, иначе `None`
   - Если `ActionBus` доступен: `bus.execute(V2ActionBuilder.field_set_timed(process_name, field_name, old_value, new_value))`
   - Если нет ActionBus: прямой вызов `rm.set_field_value(process_name, field_name, new_value)` если доступен
   - Log warning если ни ActionBus ни rm недоступны

8. В `PipelinePresenter.on_node_selected()` (или в `_topology_to_graph`):
   - При выборе ноды → `inspector.show_node(process_name, category, plugins, params)` где `params = rm.get_field_values(process_name)` если rm доступен

9. Написать тесты (≥10):
   - CardsFieldFactory-ветка активируется при наличии rm + FieldInfo
   - QLineEdit-ветка активируется при `rm=None`
   - `update_field()` не тригерит `field_changed` (signal suppression)
   - `field_changed` → presenter → ActionBus.execute() вызывается
   - При `ActionBus=None` → прямой вызов rm (без исключения)
   - Быстрое переключение нод (clear → show): нет утечек сигналов

**Acceptance criteria:**
- [ ] `NodeInspectorPanel` показывает типизированные виджеты (CardsFieldFactory) если `RegistersManager` и `FieldInfo` доступны
- [ ] Fallback на `QLineEdit` если rm недоступен — без исключений, без визуальных отличий в layout
- [ ] `update_field(name, val)` не тригерит `field_changed` (signal suppression работает для обоих типов виджетов)
- [ ] `field_changed` → `PipelinePresenter._on_inspector_field_changed` → `ActionBus.execute()` — действие undoable
- [ ] При undo: `update_field()` восстанавливает значение виджета
- [ ] Все 181 существующих тестов pipeline проходят
- [ ] Новые тесты: ≥10

**Out of scope:**
- Перенос `CardsFieldFactory` в FW
- Изменение `RegistersManagerV2` API
- Nested field schemas (только flat dict)
- `app_context.py` не добавляет новых методов — используем `ctx.extras.get("registers_manager")` или существующий accessor

**Edge cases:**
- `show_node()` при `RegistersManager = None` → пустой inspector с placeholder, без исключений
- `get_fields(process_name)` возвращает пустой список → fallback на QLineEdit (без ошибок)
- Быстрое переключение нод: `clear()` должен disconnect все `FieldEditor.valueChanged`
- `CardsFieldFactory.create(fi)` может вернуть `None` для неизвестного типа → пропустить без краша

**Dependencies:** нет (Task 14.2 независим от 14.1)

---

### Task 14.3 — dag_utils + layout → FW

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Status:** [DONE]
**Goal:** Перенести `dag_utils.py` и `layout.py` из `pipeline/` в `frontend_module/graph/`, добавить re-exports в прототипе — без изменения поведения.

**Контекст:**
`dag_utils.py` — pure Python, 0 зависимостей, ~88 LOC. `layout.py` — pure Python, использует только `from . import dag_utils` (relative import), ~280 LOC. Оба файла имеют docstring-комментарии "Кандидат в frontend_module/graph/" — перенос одобрен авторами. Все 181 тест импортируют из `multiprocess_prototype_2.*` — re-exports обязательны.

Важно: `layout.py` импортирует `dag_utils` через relative import `from . import dag_utils`. После переноса в FW нужно исправить на absolute или внутри-пакетный импорт.

`frontend_module/actions/` уже существует — аналогично создаём `frontend_module/graph/`.

**Файлы:**

Создать (новые):
- `multiprocess_framework/modules/frontend_module/graph/__init__.py`
- `multiprocess_framework/modules/frontend_module/graph/dag_utils.py` — точная копия из прототипа (убрать docstring-строку про "Кандидат")
- `multiprocess_framework/modules/frontend_module/graph/layout.py` — точная копия с исправленным импортом
- `multiprocess_framework/modules/frontend_module/graph/tests/__init__.py`
- `multiprocess_framework/modules/frontend_module/graph/tests/test_dag_utils.py` — FW-тесты (те же случаи, импорт из FW)
- `multiprocess_framework/modules/frontend_module/graph/tests/test_layout.py` — FW-тесты

Изменить:
- `multiprocess_prototype_2/frontend/widgets/tabs/pipeline/dag_utils.py` → заменить реализацию на re-export
- `multiprocess_prototype_2/frontend/widgets/tabs/pipeline/layout.py` → заменить реализацию на re-export

**Шаги:**

1. Создать `frontend_module/graph/__init__.py`:
   ```python
   """graph — generic DAG algorithms and layout for pipeline editors."""
   from .dag_utils import has_cycle, topological_sort, validate_port_compatibility, find_connected_edges
   from .layout import auto_layout

   __all__ = ["has_cycle", "topological_sort", "validate_port_compatibility", "find_connected_edges", "auto_layout"]
   ```

2. Создать `frontend_module/graph/dag_utils.py`:
   - Точная копия `pipeline/dag_utils.py`
   - Убрать строку `# Кандидат в multiprocess_framework/...` из docstring
   - Если Task 14.1 уже выполнен: убедиться что `validate_port_compatibility()` синхронизирована с версией из прототипа

3. Создать `frontend_module/graph/layout.py`:
   - Точная копия `pipeline/layout.py`
   - Исправить строку `from . import dag_utils` → `from multiprocess_framework.modules.frontend_module.graph import dag_utils`

4. Создать `graph/tests/test_dag_utils.py`:
   - Минимум 8 тестов: `has_cycle` (cycle/no-cycle), `topological_sort` (нормальный DAG, цикл → [], изолированные), `validate_port_compatibility`, `find_connected_edges`
   - Импорты из `multiprocess_framework.modules.frontend_module.graph.dag_utils`

5. Создать `graph/tests/test_layout.py`:
   - Минимум 5 тестов: пустой граф, одна нода, линейная цепочка, DAG с ветвлением, изолированные ноды
   - Импорты из `multiprocess_framework.modules.frontend_module.graph.layout`

6. Заменить `pipeline/dag_utils.py` на re-export:
   ```python
   """dag_utils — re-export из frontend_module.graph (Phase 14.3)."""
   from multiprocess_framework.modules.frontend_module.graph.dag_utils import (
       has_cycle,
       topological_sort,
       validate_port_compatibility,
       find_connected_edges,
   )
   __all__ = ["has_cycle", "topological_sort", "validate_port_compatibility", "find_connected_edges"]
   ```

7. Заменить `pipeline/layout.py` на re-export:
   ```python
   """layout — re-export из frontend_module.graph (Phase 14.3)."""
   from multiprocess_framework.modules.frontend_module.graph.layout import auto_layout
   __all__ = ["auto_layout"]
   ```

8. Убедиться что все тесты прототипа, импортирующие из `pipeline.dag_utils` и `pipeline.layout`, проходят через re-exports без изменений.

**Acceptance criteria:**
- [ ] `from multiprocess_framework.modules.frontend_module.graph.dag_utils import has_cycle` работает
- [ ] `from multiprocess_framework.modules.frontend_module.graph.layout import auto_layout` работает
- [ ] `from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.dag_utils import has_cycle` работает (re-export)
- [ ] `from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.layout import auto_layout` работает (re-export)
- [ ] Все 181 существующих тестов pipeline проходят без изменений в тест-файлах
- [ ] Новые FW-тесты: ≥13 (dag_utils: 8+, layout: 5+)
- [ ] `pipeline/dag_utils.py` и `pipeline/layout.py` содержат только re-export (не дублируют реализацию)

**Out of scope:**
- Изменять поведение алгоритмов
- Переносить `model.py`, `node_item.py`, `port_item.py`, `temp_wire.py` — только dag_utils + layout
- Менять тест-файлы прототипа
- Создавать `base_model.py` (GraphModel) — отложено до Phase 16

**Edge cases:**
- Если Task 14.1 уже изменил `validate_port_compatibility()` в прототипе: синхронизировать изменённую версию в FW, не старую заглушку
- `layout.py` использует `from . import dag_utils` — при копировании в FW заменить именно эту строку

---

### Task 14.4 — Actions handlers → FW

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Status:** [DONE]
**Goal:** Перенести `TopologyMutationHandler` и `NodeMoveHandler` в `frontend_module/actions/handlers/`, обновить прототип через re-exports — без изменения поведения.

**Контекст:**
`topology_mutation_handler.py` и `node_move_handler.py` уже используют `TYPE_CHECKING` импорты из `multiprocess_framework.modules.frontend_module.actions.schemas` — они спроектированы для переноса в FW. Runtime-зависимостей от прототипа нет: `TopologyHolder` и `TopologyBridge` используются только в `TYPE_CHECKING`. При переносе нужны Protocol-заглушки в FW вместо прямых ссылок на классы прототипа.

`frontend_module/actions/` уже содержит `bus.py`, `schemas.py`, `builder.py`. Добавляем подпакет `handlers/`.

Существующие тесты прототипа (`test_plugin.py` или аналогичные для handlers) должны работать через re-exports.

**Файлы:**

Создать (новые):
- `multiprocess_framework/modules/frontend_module/actions/handlers/__init__.py`
- `multiprocess_framework/modules/frontend_module/actions/handlers/topology_handler.py`
- `multiprocess_framework/modules/frontend_module/actions/handlers/move_handler.py`
- `multiprocess_framework/modules/frontend_module/actions/handlers/tests/__init__.py`
- `multiprocess_framework/modules/frontend_module/actions/handlers/tests/test_topology_handler.py`
- `multiprocess_framework/modules/frontend_module/actions/handlers/tests/test_move_handler.py`

Изменить:
- `multiprocess_prototype_2/frontend/actions/handlers/topology_mutation_handler.py` → re-export
- `multiprocess_prototype_2/frontend/actions/handlers/node_move_handler.py` → re-export

**Шаги:**

1. Создать `handlers/__init__.py`:
   ```python
   from .topology_handler import TopologyMutationHandler
   from .move_handler import NodeMoveHandler
   __all__ = ["TopologyMutationHandler", "NodeMoveHandler"]
   ```

2. Создать `topology_handler.py` — на основе `topology_mutation_handler.py`:
   - Добавить `TopologyHolderProtocol(Protocol)` прямо в файл (или в `handlers/protocols.py`):
     ```python
     class TopologyHolderProtocol(Protocol):
         def set_topology(self, topology: dict) -> None: ...
         def on_changed(self, callback: Callable[[dict], None]) -> None: ...
     ```
   - Добавить `TopologyBridgeProtocol(Protocol)`:
     ```python
     class TopologyBridgeProtocol(Protocol):
         def apply_topology_diff(self, old_topo: dict, new_topo: dict) -> None: ...
     ```
   - `TopologyMutationHandler.__init__(topology_holder: TopologyHolderProtocol, *, topology_bridge: TopologyBridgeProtocol | None = None)`
   - TYPE_CHECKING-блок убрать совсем или оставить только для `Action` из FW schemas
   - Логика `apply()`, `revert()`, `_apply_bridge_diff()` — точная копия из прототипа

3. Создать `move_handler.py` — точная копия `node_move_handler.py`:
   - Убрать TYPE_CHECKING import для прототипа если был (у `NodeMoveHandler` его нет)
   - Оставить `TYPE_CHECKING` import только для `Action` из FW schemas — он уже в FW

4. Написать `test_topology_handler.py` (≥6 тестов):
   - `apply()` с mock holder → `holder.set_topology()` вызван с `new_topology`
   - `revert()` с mock holder → `holder.set_topology()` вызван с `old_topology`
   - `apply()` с bridge → `bridge.apply_topology_diff()` вызван
   - `apply()` без bridge → без ошибок
   - `apply()` с пустым `forward_patch["topology"]` → warning залогировано, holder не вызван
   - `revert()` с пустым `backward_patch["topology"]` → warning залогировано

5. Написать `test_move_handler.py` (≥5 тестов):
   - `apply()` с callback → callback вызван с `(node_id, x, y)` из forward_patch
   - `revert()` с callback → callback вызван с координатами из backward_patch
   - `apply()` без callback → без ошибок (только warning)
   - `apply()` с пустым `node_id` в forward_patch → warning, callback не вызван
   - `set_callback()` после init → callback устанавливается и работает в apply

6. Заменить `topology_mutation_handler.py` в прототипе:
   ```python
   """topology_mutation_handler — re-export из frontend_module (Phase 14.4)."""
   from multiprocess_framework.modules.frontend_module.actions.handlers.topology_handler import (
       TopologyMutationHandler,
   )
   __all__ = ["TopologyMutationHandler"]
   ```

7. Заменить `node_move_handler.py` в прототипе:
   ```python
   """node_move_handler — re-export из frontend_module (Phase 14.4)."""
   from multiprocess_framework.modules.frontend_module.actions.handlers.move_handler import (
       NodeMoveHandler,
   )
   __all__ = ["NodeMoveHandler"]
   ```

8. Убедиться что все существующие тесты прототипа для handlers проходят через re-exports.

**Acceptance criteria:**
- [ ] `from multiprocess_framework.modules.frontend_module.actions.handlers import TopologyMutationHandler, NodeMoveHandler` работает
- [ ] `TopologyMutationHandler` в FW не импортирует ничего из `multiprocess_prototype_2` в runtime (только Protocol или TYPE_CHECKING для Action)
- [ ] `NodeMoveHandler` в FW не импортирует ничего из `multiprocess_prototype_2`
- [ ] `topology_mutation_handler.py` и `node_move_handler.py` в прототипе — только re-export (однострочный импорт + `__all__`)
- [ ] Все существующие тесты прототипа для этих handlers проходят без изменений
- [ ] Новые FW-тесты: ≥11 (topology_handler: 6+, move_handler: 5+)

**Out of scope:**
- Переносить `field_set_handler.py` или `recipe_handler.py` — domain-specific
- Менять API handlers (только перенос + Protocol abstractions)
- Создавать общий `handlers/protocols.py` файл — допустимо держать Protocol прямо в `topology_handler.py`

**Edge cases:**
- re-export через `from ... import TopologyMutationHandler` + явный `__all__` чтобы не сломать `from .topology_mutation_handler import *`
- Protocol-классы в FW должны содержать только методы, реально используемые в `TopologyMutationHandler` — не копировать весь интерфейс TopologyHolder

---

## Риски и ограничения

1. **181 тест pipeline** — все импортируют из `multiprocess_prototype_2.*`. Re-exports в Tasks 14.3 и 14.4 обязательны. Tasks 14.1 и 14.2 только добавляют функциональность, не меняют существующие импорты.

2. **validate_port_compatibility() меняет signature** (Task 14.1): старый код вызывает `validate_port_compatibility("output", "input")` — теперь параметры это dtype, не "output"/"input". Нужен обратный совместимый вариант или убедиться что старый вызов нигде кроме заглушки не используется. Проверить grep по кодовой базе.

3. **CardsFieldFactory.create() API** (Task 14.2): проверить точную сигнатуру — принимает `FieldInfo` напрямую или через другой интерфейс. В `factory.py` метода `create()` нет как toplevel — нужно проверить реальный вызов в других табах (services, plugins).

4. **TYPE_CHECKING circular imports** (Task 14.4): при переносе handlers в FW убедиться что Protocol-заглушки не создают import cycle с `actions/schemas.py` в том же пакете.

5. **Порядок Wave 2**: Tasks 14.3 и 14.4 независимы и не блокируют друг друга. Task 14.3 нужно выполнять после 14.1 если 14.1 меняет `validate_port_compatibility()` — синхронизировать версию.

---

## Оценка объёма

| Task | LOC создать | LOC изменить | Тестов новых |
|------|------------|-------------|-------------|
| 14.1 | ~80 (port_schema.py) | ~100 (node_item, dag_utils, model, presenter) | 10+ |
| 14.2 | 0 новых файлов | ~120 (inspector_panel, presenter) | 10+ |
| 14.3 | ~380 (FW graph/ + tests) | ~20 (re-exports) | 13+ |
| 14.4 | ~200 (FW handlers/ + tests) | ~10 (re-exports) | 11+ |
| **Итого** | **~660** | **~250** | **44+** |
