# Plan: Phase 7 — ActionBus: полная миграция presenters + persistence

**Дата:** 2026-04-22
**Статус:** DONE
**Ветка:** `feat/phase-7-actionbus-migration`
**Зависимости:** Phase 2.5, Phase 3-6 завершены

## Обзор

Phase 7 вводит **ActionBus** — шину команд с undo/redo стеком, coalescing для слайдеров,
SQL-логом и crash recovery. Все presenters переводятся с прямых `rm.set_field_value(...)` на
`bus.execute(action)`. Итог: Ctrl+Z/Ctrl+Y в UI, восстановление состояния после аварийного
завершения, replay-тест из 20 Actions.

Архитектурный принцип: ActionBus живёт в frontend-процессе как синглтон, доступный через
`FrontendAppContext.action_bus`. RegisterBindingContext адаптируется (не удаляется) — теперь
его `rm` используется внутри `ActionHandler.apply()`, а не напрямую в presenter.

---

## Порядок выполнения

### Фаза 7A: ActionBus foundation (ядро)
- Task 7A.1: Action schema + ActionBuilder base [DONE]
- Task 7A.2: ActionBus — execute, undo/redo, coalescing [DONE]
- Task 7A.3: ActionBus → FrontendAppContext + RegisterBindingContext адаптация [DONE]

### Фаза 7B: ActionBuilder доменные операции
- Task 7B.1: ActionBuilder для field mutations (camera_tab, processing_panel) [DONE] (depends on 7A.1-7A.3)
- Task 7B.2: ActionBuilder для регионов (region_add/remove) [DONE] (depends on 7A.1-7A.3)
- Task 7B.3: ActionBuilder для chain steps и display [DONE] (depends on 7A.1-7A.3)
- Task 7B.4: ActionBuilder для profile/recipe switch [DONE] (depends on 7A.1-7A.3)

### Фаза 7C: Persistence + recovery
- Task 7C.1: ActionLogSchema + ActionLogRepository (SQL) [DONE] (depends on 7A.1)
- Task 7C.2: Batched writes через UnitOfWork [DONE] (depends on 7C.1)
- Task 7C.3: Crash recovery — чтение + forward_patch при старте [DONE] (depends on 7C.1-7C.2)
- Task 7C.4: Rotation action_log → archive [DONE] (depends on 7C.1)

### Фаза 7D: UI финализация
- Task 7D.1: Ctrl+Z/Ctrl+Y глобальные shortcuts + кнопки в header [DONE] (depends on 7A.2)
- Task 7D.2: Статус-бар с описанием последнего Action [DONE] (depends on 7A.2)
- Task 7D.3: Dropdown «История» — последние 20 Actions [DONE] (depends on 7A.2, 7D.1)
- Task 7D.4: Тесты Phase 7 [DONE] (depends on all 7A-7C)

---

## Риски и ограничения

- RegisterBindingContext не удаляется — он используется в camera_common/binder.py и fps_section; его
  `rm` передаётся в компоненты. Адаптация — добавить optional `action_bus` параллельно.
- Coalescing критичен для слайдеров: без него каждый тик = отдельный Action в стеке.
- Crash recovery предполагает детерминированное применение Actions на чистый state — нужен
  стабильный порядок применения до показа UI.
- HikvisionCameraMvpPresenter и SimWebcamPresenter не имеют `rm` напрямую — они используют
  `GuiCommandHandler`; их Actions — command-type, без undo (помечаются `undoable=False`).

---

## Детальные задачи

---

### Task 7A.1 — Action schema + ActionBuilder base

**Уровень:** Senior+ (Opus, extended thinking)
**Исполнитель:** teamlead
**Цель:** Создать неизменяемую схему Action и базовый ActionBuilder с фабриками для field mutations

**Контекст:** Action — единица изменения состояния. Должен содержать достаточно данных для
`apply()` (forward patch) и `revert()` (backward patch). Использует `SchemaBase` из
`multiprocess_framework/modules/data_schema_module/` — это даёт автоматический маппинг в SQL
через `SchemaBaseMapper`. Coalescing-ключ (`coalesce_key`) нужен для группировки тиков слайдера
в один Action; если два подряд Action имеют одинаковый `coalesce_key`, второй заменяет первый
в стеке (не добавляет новый).

**Файлы:**
- `frontend/actions/__init__.py` — создать (пустой re-export)
- `frontend/actions/schemas.py` — создать: `Action(SchemaBase)` + `ActionType(str, Enum)`
- `frontend/actions/builder.py` — создать: `ActionBuilder` (статические фабричные методы)

**Шаги:**

1. **`schemas.py`** — определить `ActionType(str, Enum)`:
   - `FIELD_SET` — изменение одного поля регистра
   - `REGION_ADD`, `REGION_REMOVE` — добавление/удаление ROI
   - `STEP_ADD`, `STEP_REMOVE`, `STEP_MODIFY`, `STEP_REORDER` — chain-операции
   - `DISPLAY_SUBSCRIBE`, `DISPLAY_UNSUBSCRIBE`, `LAYOUT_CHANGE` — display-операции
   - `PROFILE_SWITCH`, `RECIPE_SWITCH` — переключение профиля/рецепта
   - `COMMAND` — side-effect без undo (IPC, camera open/close)

2. **`schemas.py`** — определить `Action(SchemaBase)`:
   ```
   action_id: str (UUID, auto-generated default)
   action_type: ActionType
   register_name: Optional[str]  — какой регистр затронут
   field_name: Optional[str]     — какое поле
   forward_patch: Dict[str, Any] — данные для apply (новое значение)
   backward_patch: Dict[str, Any]— данные для revert (старое значение)
   coalesce_key: Optional[str]   — если совпадает у двух подряд Action → второй заменяет первый
   undoable: bool = True         — False для COMMAND type
   description: str = ""         — человекочитаемое описание для UI
   timestamp: float (time.time(), auto)
   ```
   Добавить `SQLMeta` nested class с `table_name = "action_log"`.

3. **`builder.py`** — `ActionBuilder` со статическими методами:
   - `field_set(register_name, field_name, new_value, old_value, *, description="") -> Action`
     - `coalesce_key = f"field:{register_name}.{field_name}"`
   - `command(description) -> Action` — `undoable=False`, `action_type=COMMAND`
   - `_make_id() -> str` — `str(uuid4())`

4. Добавить `from_field(binding: RegisterBinding, new_value, old_value) -> Action` — удобный
   метод, принимающий `RegisterBinding` из `frontend_module.schemas.register_binding`.

**Критерии приёмки:**
- [ ] `Action()` создаётся с auto-UUID и auto-timestamp
- [ ] `Action` round-trip через `model_dump/model_validate`
- [ ] `ActionBuilder.field_set(...)` возвращает Action с корректным `coalesce_key`
- [ ] `Action` имеет `SQLMeta` с `table_name = "action_log"`
- [ ] `ActionBuilder.from_field(binding, 42, 0)` → `register_name == binding.register_name`

**Вне scope:** Handlers (apply/revert), bus execution, регистрация в context.

**Edge cases:** `old_value` может быть `None` при первичной инициализации — допустимо.

---

### Task 7A.2 — ActionBus: execute, undo/redo, coalescing

**Уровень:** Senior+ (Opus, extended thinking)
**Исполнитель:** teamlead
**Цель:** Реализовать шину ActionBus с immutable undo-стеком, coalescing и callback-уведомлениями

**Контекст:** ActionBus — синглтон в frontend. Содержит undo-стек (list[Action]), redo-стек
(list[Action]) и словарь `_handlers: Dict[ActionType, ActionHandler]`. При `execute(action)`:
1. вызывает `handler.apply(action)`, 2. если `undoable=True` — добавляет в undo-стек с coalescing,
3. очищает redo-стек, 4. уведомляет callbacks.

Coalescing: если undo-стек непустой и `undo_stack[-1].coalesce_key == action.coalesce_key` (не None)
→ заменить последний элемент стека новым action (backward_patch из заменяемого сохраняется).

**Файлы:**
- `frontend/actions/bus.py` — создать: `ActionBus`, `ActionHandler` Protocol
- `frontend/actions/handlers/__init__.py` — создать (пустой)
- `frontend/actions/handlers/field_set_handler.py` — создать: `FieldSetHandler`

**Шаги:**

1. **`bus.py`** — `ActionHandler(Protocol)`:
   ```
   def apply(self, action: Action, rm: IRegistersManagerGui) -> None: ...
   def revert(self, action: Action, rm: IRegistersManagerGui) -> None: ...
   ```

2. **`bus.py`** — `ActionBus`:
   ```python
   class ActionBus:
       def __init__(self, rm: IRegistersManagerGui) -> None
       def register_handler(self, action_type: ActionType, handler: ActionHandler) -> None
       def execute(self, action: Action) -> None
       def undo(self) -> Optional[Action]
       def redo(self) -> Optional[Action]
       def can_undo(self) -> bool
       def can_redo(self) -> bool
       def add_change_callback(self, cb: Callable[[], None]) -> None
       def remove_change_callback(self, cb: Callable[[], None]) -> None
       def history(self, n: int = 20) -> List[Action]
       def last_action(self) -> Optional[Action]
       def clear(self) -> None
   ```

3. **Coalescing в `execute()`:**
   - Если `action.coalesce_key is not None` и стек непустой и `undo_stack[-1].coalesce_key == action.coalesce_key`:
     - Создать merged action: `action_id` и `backward_patch` берём из `undo_stack[-1]`, остальное из нового
     - Заменить последний элемент стека merged action (не добавляем новый)
   - Иначе — добавить в стек. Ограничить стек: `max_history = 200` (конфигурируемо при создании).

4. **`undo()`/`redo()`:** при undo — вызвать `handler.revert(action, rm)`, переложить в redo-стек,
   уведомить callbacks. При redo — вызвать `handler.apply(action, rm)`, переложить в undo-стек.

5. **`field_set_handler.py`** — `FieldSetHandler`:
   - `apply()`: `rm.set_field_value(action.register_name, action.field_name, action.forward_patch["value"])`
   - `revert()`: `rm.set_field_value(action.register_name, action.field_name, action.backward_patch["value"])`
   - Guard: если `register_name` или `field_name` отсутствует в action — log warning, return.

6. **`execute()` guard для COMMAND type:** `undoable=False` → apply handler, не добавлять в стек,
   уведомить callbacks.

**Критерии приёмки:**
- [ ] `bus.execute(action)` → handler.apply вызван, action в undo_stack
- [ ] `bus.undo()` → handler.revert вызван, action перемещён в redo_stack
- [ ] `bus.redo()` → handler.apply вызван, action вернулся в undo_stack
- [ ] Coalescing: 3 подряд field_set для того же поля → undo_stack содержит 1 запись с `backward_patch` от первого
- [ ] COMMAND action → в undo_stack не попадает
- [ ] Callbacks вызываются после каждого execute/undo/redo
- [ ] `max_history=5`, добавить 7 actions → стек содержит 5

**Вне scope:** Persistence (Task 7C), UI (Task 7D), handlers для REGION_ADD и др. — в 7B.

**Edge cases:**
- `undo()` при пустом стеке → return None, no error
- `redo()` после `execute()` → redo_stack очищается
- Handler не зарегистрирован для action_type → log warning, action не выполняется

**Зависимости:** Task 7A.1

---

### Task 7A.3 — ActionBus в FrontendAppContext + RegisterBindingContext адаптация

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Подключить ActionBus как зависимость FrontendAppContext и адаптировать RegisterBindingContext для передачи bus в компоненты без разрушения обратной совместимости

**Контекст:** `FrontendAppContext` (`frontend/app_context.py`) уже содержит `registers_manager`,
`camera_registry` и другие зависимости. `ActionBus` добавляется как `Optional[Any]` поле с
`default=None` — это сохраняет backward compat для тестов без bus.

`RegisterBindingContext` (`frontend_module.widgets.tabs.binding_context`) — frozen dataclass
с единственным полем `rm`. Добавить `action_bus: Optional[Any] = None`. Это позволит компонентам
(slider, checkbox) опционально использовать bus вместо прямого `rm.set_field_value`.

**Файлы:**
- `frontend/app_context.py` — изменить: добавить поле `action_bus`
- `frontend/launcher.py` — изменить: создать ActionBus, зарегистрировать FieldSetHandler, записать в app_ctx
- `multiprocess_framework/modules/frontend_module/widgets/tabs/binding_context.py` — изменить:
  добавить `action_bus: Optional[Any] = None`
- `frontend/actions/default_bus_factory.py` — создать: `create_default_action_bus(rm) -> ActionBus`

**Шаги:**

1. **`app_context.py`:** добавить поле:
   ```python
   action_bus: Optional[Any] = None
   ```

2. **`default_bus_factory.py`:**
   - Создать `create_default_action_bus(rm: IRegistersManagerGui) -> ActionBus`
   - Создать bus, зарегистрировать `FieldSetHandler` для `ActionType.FIELD_SET`
   - Вернуть готовый bus

3. **`launcher.py`:** в `register_windows()` после создания `app_ctx`:
   ```python
   from multiprocess_prototype.frontend.actions.default_bus_factory import create_default_action_bus
   app_ctx.action_bus = create_default_action_bus(registers_manager)
   ```

4. **`binding_context.py`:** изменить `RegisterBindingContext` — добавить `action_bus: Optional[Any] = None`.
   Поскольку frozen=True, нужно обновить все места создания (только в binder.py и fps_section.py —
   их не нужно трогать, они передают `action_bus=None` по умолчанию).

5. **Добавить метод `FrontendAppContext.get_action_bus()`:**
   ```python
   def get_action_bus(self) -> Optional[Any]:
       return self.action_bus
   ```

**Критерии приёмки:**
- [ ] `FrontendAppContext(config={}, registers_manager=None, ...)` без `action_bus` — работает (backward compat)
- [ ] `launcher.py` создаёт bus и он доступен через `app_ctx.get_action_bus()`
- [ ] `RegisterBindingContext(rm=None)` создаётся без ошибок (action_bus=None по умолчанию)
- [ ] `RegisterBindingContext(rm=rm_mock, action_bus=bus_mock)` — оба поля доступны
- [ ] Существующие тесты без bus не ломаются

**Вне scope:** Изменение компонентов slider/checkbox для использования bus (это откладывается
до полной миграции presenters; компоненты продолжают работать через rm напрямую).

**Зависимости:** Task 7A.2

---

### Task 7B.1 — Миграция: camera_tab + processing_panel presenters

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Перевести CameraTabPresenter и ProcessingPanelPresenter на ActionBus для всех mutations регистра

**Контекст:** `CameraTabPresenter` использует `set_camera_type_field(self._rm, camera_type)` через
`register_ops.py`. `ProcessingPanelPresenter` пока является заглушкой, но содержит `_model.registers_manager`.
После миграции: все `rm.set_field_value(...)` в этих presenters заменяются на
`bus.execute(ActionBuilder.field_set(...))`.

Тонкость `CameraTabPresenter`: `on_camera_type_changed` вызывается интерактивно пользователем —
это undo-able action. `apply_initial_camera_type` вызывается при старте — это не undo-able
(начальное состояние), должно идти в bus с `undoable=False` или через direct rm.

**Файлы:**
- `frontend/widgets/tabs_setting/camera_tab/presenter.py` — изменить
- `frontend/widgets/tabs_setting/camera_tab/register_ops.py` — изменить (добавить bus-версию)
- `frontend/widgets/processing_panel_widget/presenter.py` — изменить

**Шаги:**

1. **`register_ops.py`** — добавить функцию:
   ```python
   def set_camera_type_via_bus(bus, rm, camera_type: str) -> None:
       """Записать camera_type через ActionBus (undo-able) или fallback на rm напрямую."""
       if bus is None:
           set_camera_type_field(rm, camera_type)
           return
       old = rm.get_field_value(CAMERA_REGISTER, "camera_type") if rm else None
       action = ActionBuilder.field_set(CAMERA_REGISTER, "camera_type", camera_type, old,
                                        description=f"Тип камеры: {camera_type}")
       bus.execute(action)
   ```

2. **`CameraTabPresenter.__init__`** — добавить `action_bus: Optional[Any] = None`, сохранить как
   `self._bus`.

3. **`on_camera_type_changed()`** — заменить `set_camera_type_field(self._rm, camera_type)` на
   `set_camera_type_via_bus(self._bus, self._rm, camera_type)`.

4. **`apply_initial_camera_type()`** — НЕ менять: прямой rm-вызов, это не пользовательское действие.

5. **`ProcessingPanelPresenter`** — добавить `action_bus: Optional[Any] = None`. Добавить метод-stub
   `on_field_changed(register_name, field_name, new_value, old_value)` — выполняет
   `ActionBuilder.field_set(...)` через bus (для будущего использования панелью).

6. **Debug-guard:** в `on_camera_type_changed` добавить `assert self._bus is not None or self._rm is not None`
   в DEBUG-build (флаг из `__debug__`).

**Критерии приёмки:**
- [ ] `on_camera_type_changed("hikvision")` с bus → action в bus.undo_stack, `rm.set_field_value` не вызван напрямую
- [ ] `on_camera_type_changed("hikvision")` с `bus=None` → fallback на `set_camera_type_field` (backward compat)
- [ ] `apply_initial_camera_type(...)` → не добавляет в undo_stack
- [ ] `bus.undo()` → camera_type вернулось к предыдущему значению

**Вне scope:** Миграция других presenters (отдельные задачи 7B.2–7B.4).

**Зависимости:** Task 7A.1, 7A.2, 7A.3

---

### Task 7B.2 — Миграция: CroppedRegionsPresenter + PostProcessingPresenter

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Перевести операции с регионами на ActionBus: region_add, region_remove, region_modify — через специализированные типы Actions

**Контекст:** `CroppedRegionsPresenter` и `PostProcessingPresenter` вызывают `_push_register()`,
который делает `rm.set_field_value(PROCESSOR_REGISTER, "vision_pipeline", cfg)`. Это composite
action — изменяется весь `vision_pipeline`. Нужны `ActionBuilder.region_add/region_remove` из мета-плана 7.2.

После миграции: `_push_register()` заменяется вызовом `bus.execute(action)` с типом
`REGION_ADD`/`REGION_REMOVE`/`FIELD_SET` в зависимости от операции. `backward_patch` содержит
полный snapshot `vision_pipeline` до изменения (для надёжного undo).

**Файлы:**
- `frontend/actions/builder.py` — изменить: добавить `region_add()`, `region_remove()`, `region_modify()`
- `frontend/actions/handlers/region_handler.py` — создать: `RegionActionHandler`
- `frontend/widgets/cropped_regions_widget/presenter.py` — изменить
- `frontend/widgets/post_processing_widget/presenter.py` — изменить

**Шаги:**

1. **`builder.py`** — добавить:
   - `ActionBuilder.region_add(camera_id, region_data, pipeline_snapshot_before, *, register_name) -> Action`
     - `action_type=REGION_ADD`, `forward_patch={"camera_id": ..., "region": region_data, "pipeline_after": ...}`,
       `backward_patch={"pipeline_before": pipeline_snapshot_before}`
     - `description=f"Добавить регион '{region_data.get('name', '')}' (камера {camera_id})"`
   - `ActionBuilder.region_remove(camera_id, region_name, pipeline_snapshot_before, pipeline_snapshot_after, *, register_name) -> Action`
   - `ActionBuilder.region_modify(camera_id, region_name, pipeline_before, pipeline_after, *, register_name) -> Action`
     - `coalesce_key = f"region_modify:{register_name}:{camera_id}:{region_name}"`

2. **`region_handler.py`** — `RegionActionHandler`:
   - `apply()`: для REGION_ADD/REMOVE/MODIFY — `rm.set_field_value(action.register_name, "vision_pipeline", action.forward_patch["pipeline_after"])`
   - `revert()`: `rm.set_field_value(action.register_name, "vision_pipeline", action.backward_patch["pipeline_before"])`

3. **`CroppedRegionsPresenter._push_register_via_bus(operation_type, region_data=None)`:**
   - Снять snapshot `before` из rm
   - Применить изменение в `self._model.crop_regions_by_camera`
   - Построить `pipeline_after`
   - Создать action через соответствующий `ActionBuilder` метод
   - Вызвать `bus.execute(action)` или fallback `_push_register()` если bus=None

4. Заменить все прямые вызовы `self._push_register()` в `on_add`, `on_remove`, `on_form_apply`,
   `on_move`, `on_paste` → `self._push_register_via_bus(...)`.

5. Аналогично для `PostProcessingPresenter`.

6. **Регистрация в default_bus_factory.py** (Task 7A.3): добавить `RegionActionHandler` для
   `REGION_ADD`, `REGION_REMOVE`, `REGION_MODIFY`.

**Критерии приёмки:**
- [ ] `on_add()` → action с `action_type=REGION_ADD` в bus.undo_stack
- [ ] `bus.undo()` → vision_pipeline вернулось к snapshot before
- [ ] `on_remove()` → `REGION_REMOVE` action, undo восстанавливает удалённый регион
- [ ] `on_form_apply()` с изменением имени → REGION_MODIFY с coalesce_key
- [ ] Без bus → старый `_push_register()` (backward compat)
- [ ] Undo/Redo не нарушает дерево камер (другая камера не затронута)

**Вне scope:** Визуализация истории в UI (Task 7D), тесты (Task 7D.4).

**Зависимости:** Task 7A.1, 7A.2, 7A.3, 7B.1

---

### Task 7B.3 — Миграция: ChainPresenter + CatalogPresenter + DisplayRouter

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Перевести операции с chain steps и display-подписками на ActionBus

**Контекст:** `ChainEditorModel` (`frontend/widgets/chain_editor/model.py`) хранит nodes в dict.
`CatalogEditorPresenter` — тонкий presenter без прямых mutations. `DisplayRouter` управляет
subscribe/unsubscribe — это command-type (side-effect, `undoable=False`).

Для chain steps: `STEP_ADD`, `STEP_REMOVE`, `STEP_MODIFY`, `STEP_REORDER`. Snapshot chain_before/after
хранится в patches.

Для display: `DISPLAY_SUBSCRIBE`, `DISPLAY_UNSUBSCRIBE`, `LAYOUT_CHANGE` — все `undoable=False`
(нет смысла отменять display-подписку через undo).

**Файлы:**
- `frontend/actions/builder.py` — изменить: добавить step_* и display_* методы
- `frontend/actions/handlers/chain_handler.py` — создать: `ChainActionHandler`
- `frontend/actions/handlers/display_handler.py` — создать: `DisplayActionHandler` (command-type)
- `frontend/widgets/chain_editor/presenter.py` — изменить (если presenter существует)
- `frontend/managers/display_router.py` — изменить: оборачивать subscribe/unsubscribe в bus.execute

**Шаги:**

1. **`builder.py`** — добавить:
   - `ActionBuilder.step_add(region_id, node_data, nodes_snapshot_before) -> Action`
     - `action_type=STEP_ADD`, snapshot → backward_patch
   - `ActionBuilder.step_remove(region_id, node_id, nodes_snapshot_before, nodes_snapshot_after) -> Action`
   - `ActionBuilder.step_modify(region_id, node_id, node_before, node_after) -> Action`
     - `coalesce_key = f"step_modify:{region_id}:{node_id}"`
   - `ActionBuilder.step_reorder(region_id, node_id, direction, nodes_before, nodes_after) -> Action`
   - `ActionBuilder.display_subscribe(source_ref, subscription_data) -> Action`
     - `undoable=False`, `action_type=DISPLAY_SUBSCRIBE`
   - `ActionBuilder.display_unsubscribe(source_ref) -> Action` — `undoable=False`
   - `ActionBuilder.layout_change(preset_name, subscriptions_before, subscriptions_after) -> Action`
     - `undoable=True` (layout можно откатить)

2. **`chain_handler.py`** — `ChainActionHandler`:
   - `apply()/revert()` для STEP_* — применяет `nodes_after`/`nodes_before` snapshot к
     `region.nodes` через `rm.set_field_value(register_name, "vision_pipeline", ...)`.

3. **`display_handler.py`** — `DisplayActionHandler`:
   - `apply()` для DISPLAY_SUBSCRIBE: вызывает `display_router.subscribe(...)` напрямую
   - `apply()` для DISPLAY_UNSUBSCRIBE: вызывает `display_router.unsubscribe(...)`
   - `revert()` — no-op (undoable=False, не вызывается)
   - `display_router` инжектируется в handler при создании

4. **`display_router.py`** — добавить `action_bus: Optional[Any] = None` параметр в `__init__`.
   В методах `subscribe()/unsubscribe()` — если bus не None:
   ```python
   action = ActionBuilder.display_subscribe(source_ref, subscription_data)
   bus.execute(action)  # handler вызывает реальный subscribe
   ```
   Иначе — вызывать напрямую как сейчас (backward compat).

5. **`default_bus_factory.py`** (Task 7A.3): добавить `ChainActionHandler` для STEP_*,
   `DisplayActionHandler` для DISPLAY_* — передать `display_router` из app_context.

**Критерии приёмки:**
- [ ] `step_add(...)` → STEP_ADD action в стеке, bus.undo() восстанавливает nodes snapshot
- [ ] `step_modify(...)` 3 раза подряд на одном node → 1 запись в стеке (coalescing)
- [ ] `display_subscribe(...)` → action NOT in undo_stack (undoable=False)
- [ ] `layout_change(...)` → action IN undo_stack (undoable=True)
- [ ] `DisplayRouter` без bus → работает как раньше

**Вне scope:** Интеграция с backend (register propagation остаётся как в Phase 5a).

**Зависимости:** Task 7A.1, 7A.2, 7A.3

---

### Task 7B.4 — ActionBuilder для profile/recipe switch

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Перевести переключение профилей и рецептов на ActionBus — один Action = весь switch

**Контекст:** `SettingsProfilePresenter.on_apply_clicked()` вызывает `profile_manager.switch_profile(profile_id, rm)`,
который обновляет множество полей сразу. `RegisterRecipePresenter.on_load_clicked()` аналогично.

Для undo нужен snapshot всего затронутого регистра до/после. `PROFILE_SWITCH` и `RECIPE_SWITCH` —
это compound actions. `backward_patch` содержит `{register_name: {field: old_value}}` для всех
изменённых полей.

**Файлы:**
- `frontend/actions/builder.py` — изменить: добавить `profile_switch()`, `recipe_switch()`
- `frontend/actions/handlers/profile_handler.py` — создать: `ProfileSwitchHandler`
- `frontend/actions/handlers/recipe_handler.py` — создать: `RecipeSwitchHandler`
- `frontend/widgets/settings_profile_widget/presenter.py` — изменить
- `frontend/widgets/recipes_widget/presenter.py` — изменить
- `frontend/widgets/settings_recipe_widget/presenter.py` — изменить

**Шаги:**

1. **`builder.py`** — добавить:
   - `ActionBuilder.profile_switch(profile_id, registers_snapshot_before, registers_snapshot_after) -> Action`
     - `action_type=PROFILE_SWITCH`, нет coalesce_key
     - `forward_patch={"profile_id": ..., "snapshot": registers_snapshot_after}`
     - `backward_patch={"snapshot": registers_snapshot_before}`
     - `description=f"Профиль: {profile_id}"`
   - `ActionBuilder.recipe_switch(slot_id, registers_snapshot_before, registers_snapshot_after) -> Action`
     - аналогично для `RECIPE_SWITCH`

2. **`profile_handler.py`** — `ProfileSwitchHandler`:
   - `apply()`: применить `action.forward_patch["snapshot"]` → для каждого (register, {field: val}) вызвать `rm.set_field_value`
   - `revert()`: применить `action.backward_patch["snapshot"]`

3. **`recipe_handler.py`** — `RecipeSwitchHandler` — аналогичная логика.

4. **`SettingsProfilePresenter.on_apply_clicked()`:**
   - Снять snapshot before: `rm.model_dump_all().get(SETTINGS_REGISTER, {})`
   - Вызвать `profile_manager.switch_profile(profile_id, rm)` напрямую (он меняет rm)
   - Снять snapshot after
   - Создать action через `ActionBuilder.profile_switch(...)` с `undoable=True`
   - `bus.execute(action)` — handler НЕ вызывает switch ещё раз; switch уже сделан. Handler нужен только для undo/redo.
   - **Важно:** `apply()` в handler при undo/redo применяет snapshot, не вызывает `profile_manager.switch_profile` повторно.

5. Аналогично для `RegisterRecipePresenter.on_load_clicked()`.

6. `SettingsRecipePresenter` — аналогично для своих операций.

**Критерии приёмки:**
- [ ] `on_apply_clicked()` → PROFILE_SWITCH action в стеке, содержит snapshot before и after
- [ ] `bus.undo()` → все поля регистра вернулись к snapshot before
- [ ] `bus.redo()` → поля вернулись к snapshot after
- [ ] Без bus → старое поведение (backward compat)
- [ ] Один profile switch = **1 Action** в стеке (не N actions по числу полей)

**Вне scope:** История профилей в UI (Task 7D).

**Зависимости:** Task 7A.1, 7A.2, 7A.3

---

### Task 7C.1 — ActionLogSchema + ActionLogRepository (SQL)

**Уровень:** Senior+ (Opus, extended thinking)
**Исполнитель:** teamlead
**Цель:** Создать SQL-слой для персистентного хранения Actions в таблице action_log через GenericRepository

**Контекст:** `Action` уже имеет `SQLMeta(table_name="action_log")`. `SchemaBaseMapper` из
`sql_module/adapters/schema_mapper.py` умеет маппить `SchemaBase` → SQL columns. `GenericRepository`
(в `sql_module/core/base_repository.py`) предоставляет CRUD.

Проблема: `forward_patch` и `backward_patch` — это `Dict[str, Any]`, нельзя хранить как
отдельные колонки. Решение: сериализация в JSON-строку через `SQLMeta` column override.

`ActionLogRepository` = тонкая обёртка над `GenericRepository[Action]` с методами:
- `append(action)` — INSERT
- `find_recent(n)` — SELECT последних N по timestamp
- `rotate(max_count)` — DELETE старых + INSERT в archive

**Файлы:**
- `frontend/actions/persistence/__init__.py` — создать
- `frontend/actions/persistence/repository.py` — создать: `ActionLogRepository`
- `frontend/actions/persistence/schema_ext.py` — создать: `ActionLogRow` (SQL-friendly schema)
- `backend/processes/database/action_log_setup.py` — создать: DDL-хелпер для action_log таблицы

**Шаги:**

1. **`schema_ext.py`** — `ActionLogRow(SchemaBase)`:
   ```python
   class ActionLogRow(SchemaBase):
       class SQLMeta:
           table_name = "action_log"
           primary_key = ["action_id"]
       action_id: str
       action_type: str
       register_name: Optional[str]
       field_name: Optional[str]
       forward_patch_json: str  # json.dumps(forward_patch)
       backward_patch_json: str  # json.dumps(backward_patch)
       coalesce_key: Optional[str]
       undoable: bool
       description: str
       timestamp: float
   ```
   Добавить конвертеры `Action.to_log_row() -> ActionLogRow` и
   `ActionLogRow.to_action() -> Action`.

2. **`repository.py`** — `ActionLogRepository`:
   - `__init__(adapter: ISyncEngineAdapter)` — создать `GenericRepository[ActionLogRow]`
   - `append(action: Action) -> None` — конвертировать → insert
   - `find_recent(n: int = 200) -> List[Action]` — `SELECT * ORDER BY timestamp DESC LIMIT n`
   - `find_since(timestamp: float) -> List[Action]` — для recovery
   - `count() -> int` — для rotation check
   - `delete_before(timestamp: float) -> int` — для rotation

3. **`action_log_setup.py`** — `create_action_log_table(sql_manager: SQLManager) -> None`:
   - Использовать `DDLBuilder` из `sql_module/core/ddl_builder.py` или прямой SQL CREATE TABLE IF NOT EXISTS.
   - Вызывается из `DatabaseProcess._init_custom_managers()`.

4. Обновить **`DatabaseProcess._init_custom_managers()`** — вызвать `create_action_log_table(self.sql_manager)`.

**Критерии приёмки:**
- [ ] `ActionLogRow.to_action()` + `Action.to_log_row()` — round-trip без потерь
- [ ] `repository.append(action)` → запись в БД
- [ ] `repository.find_recent(5)` → 5 последних по timestamp
- [ ] `repository.find_since(t)` → только записи с timestamp >= t
- [ ] Таблица создаётся автоматически при старте DatabaseProcess (IF NOT EXISTS)

**Вне scope:** Batched writes (Task 7C.2), rotation (Task 7C.4).

**Edge cases:** `forward_patch`/`backward_patch` могут содержать numpy-типы — использовать
`json.dumps(..., default=str)` для сериализации.

**Зависимости:** Task 7A.1

---

### Task 7C.2 — Batched writes через UnitOfWork

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** ActionBus записывает Actions в лог батчами, а не по одному — для производительности

**Контекст:** Слайдер при движении генерирует ~30 Actions/сек (тики). Coalescing схлопывает их
в стеке, но до persistence — каждый execute() может триггерить INSERT. Решение:
`ActionLogWriter` — буфер с flush по таймеру (500ms) или по размеру (≥10 actions).

`ActionLogWriter` запускает QTimer в GUI-потоке (или threading.Timer). Coalesced actions —
пишем только финальный вариант (тот, что в undo_stack).

**Файлы:**
- `frontend/actions/persistence/log_writer.py` — создать: `ActionLogWriter`
- `frontend/actions/bus.py` — изменить: подключить `ActionLogWriter` при наличии

**Шаги:**

1. **`log_writer.py`** — `ActionLogWriter`:
   ```python
   class ActionLogWriter:
       def __init__(self, repository: ActionLogRepository,
                    flush_interval_ms: int = 500,
                    max_buffer_size: int = 10) -> None
       def enqueue(self, action: Action) -> None
       def flush(self) -> None  # записать pending buffer в БД
       def start(self) -> None  # запустить таймер
       def stop(self) -> None   # flush + остановить таймер
   ```
   - `enqueue()`: если `action.coalesce_key` совпадает с последним pending — заменить. Иначе append.
   - `flush()`: batch INSERT через `repository.append(a)` в цикле внутри `uow.connection()`.
   - Таймер: `threading.Timer` (не Qt-зависимый для тестируемости).

2. **`bus.py`** — добавить `set_log_writer(writer: Optional[ActionLogWriter]) -> None`.
   После каждого `execute()` (для undoable actions) — `self._log_writer.enqueue(action)` если writer установлен.
   После `undo()` — пометить действие как reverted или записать специальный UNDO-action (проще: записать
   Action c `description="[UNDO] " + original.description`).

3. **`launcher.py`** — после создания ActionBus:
   - Создать `ActionLogWriter(repository, flush_interval_ms=500)`
   - `bus.set_log_writer(writer)`
   - `writer.start()`
   - Зарегистрировать `writer.stop()` в shutdown-hook.

**Критерии приёмки:**
- [ ] 20 подряд `field_set` для одного поля → в БД попадает ≤2 записей после flush (coalescing в буфере)
- [ ] `flush()` при пустом буфере → no-op, no error
- [ ] `stop()` перед завершением → все pending записаны
- [ ] Writer не блокирует GUI-поток (flush в фоне)

**Вне scope:** Async writes (достаточно sync с threading.Timer).

**Зависимости:** Task 7C.1, 7A.2

---

### Task 7C.3 — Crash recovery: чтение лога + forward_patch при старте

**Уровень:** Senior+ (Opus, extended thinking)
**Исполнитель:** teamlead
**Цель:** При старте приложения восстановить состояние из последних N Actions из action_log

**Контекст:** Kill -9 в середине редактирования → `RegistersManager` вернётся к дефолтам.
При следующем старте — прочитать последние 200 Actions из `action_log`, отфильтровать
только `undoable=True` и не-reverted, применить в порядке timestamp на чистый state через
`handler.apply()` каждого Action.

Применение до показа UI — состояние восстановлено до открытия главного окна.
Проблема: recovery применяет Actions в порядке timestamp, но некоторые могут быть
compound (PROFILE_SWITCH содержит snapshot). Recovery не должна воспроизводить их через
handler (там `rm.set_field_value`) — иначе двойное применение. Решение: recovery применяет
только FIELD_SET Actions через `FieldSetHandler`; PROFILE_SWITCH/RECIPE_SWITCH — применяют snapshot напрямую.

**Файлы:**
- `frontend/actions/persistence/recovery.py` — создать: `ActionLogRecovery`
- `frontend/launcher.py` — изменить: вызвать recovery перед `register_windows()`

**Шаги:**

1. **`recovery.py`** — `ActionLogRecovery`:
   ```python
   class ActionLogRecovery:
       def __init__(self, repository: ActionLogRepository,
                    bus: ActionBus,
                    rm: IRegistersManagerGui) -> None
       def recover(self, max_actions: int = 200) -> int:
           """Восстановить состояние. Возвращает количество применённых Actions."""
   ```

2. **`recover()` алгоритм:**
   - `actions = repository.find_recent(max_actions)` → отсортировать по timestamp ASC
   - Фильтр: оставить только `action.undoable == True`
   - Проверить нет ли в конце "UNDO" записей — если есть `[UNDO] field:X` после `field:X` — компенсировать пары
   - Для каждого action: найти handler по `action_type` → `handler.apply(action, rm)`
   - Обернуть в try/except: если apply упал → log warning, skip, continue
   - Вернуть count применённых

3. Специальная обработка PROFILE_SWITCH/RECIPE_SWITCH в recovery:
   - `apply()` берёт `forward_patch["snapshot"]` и применяет через `rm.set_field_value` напрямую

4. **`launcher.py`** — в `register_windows()` после создания `registers_manager` и ActionBus:
   ```python
   recovery = ActionLogRecovery(action_log_repo, bus, registers_manager)
   count = recovery.recover()
   if count:
       logger.info("Crash recovery: применено %d Actions", count)
   ```
   Recovery перед созданием окон, но после инициализации RegistersManager.

5. **Replay test:** создать специальный тестовый метод `recovery.dry_run(actions) -> bool` —
   применяет Actions к copy state и проверяет детерминированность.

**Критерии приёмки:**
- [ ] 20 FIELD_SET в лог → kill process → start → все 20 применены, state идентичен
- [ ] UNDO запись в лог → при recovery соответствующий FIELD_SET пропускается
- [ ] Malformed action в лог → warning, skip, recovery продолжается
- [ ] `recover()` при пустом лог → return 0, no error
- [ ] Recovery применяется ДО показа главного окна

**Edge cases:**
- Actions из очень старого сеанса (>24h) — игнорировать (фильтр по timestamp: max_age_hours=24)
- Незавершённый compound action (нет backward_patch) — skip с warning

**Зависимости:** Task 7C.1, 7A.2

---

### Task 7C.4 — Rotation: action_log → archive

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** Ротация action_log при превышении 10k записей — старые переносятся в таблицу-архив

**Контекст:** При длительной работе action_log будет расти. Решение: при достижении
`max_count=10000` записей — переименовать текущую таблицу в
`action_log_archive_{date}` и создать чистую `action_log`. Это проще, чем DELETE+INSERT в архив.

SQLite не поддерживает RENAME TABLE из коробки — использовать CREATE TABLE AS + DROP старой.

**Файлы:**
- `frontend/actions/persistence/rotation.py` — создать: `ActionLogRotation`
- `frontend/actions/persistence/log_writer.py` — изменить: вызывать rotation в `flush()`

**Шаги:**

1. **`rotation.py`** — `ActionLogRotation`:
   ```python
   class ActionLogRotation:
       def __init__(self, adapter: ISyncEngineAdapter,
                    max_count: int = 10_000) -> None
       def maybe_rotate(self, current_count: int) -> bool:
           """Ротировать если current_count >= max_count. Возвращает True если ротация была."""
       def _do_rotate(self, adapter) -> None
   ```

2. **`_do_rotate()` алгоритм:**
   - Сформировать имя архивной таблицы: `action_log_archive_{datetime.now().strftime("%Y%m%d_%H%M%S")}`
   - `CREATE TABLE {archive_name} AS SELECT * FROM action_log`
   - `DELETE FROM action_log`
   - Логировать факт ротации

3. **`log_writer.py`** — в `flush()` после batch INSERT:
   - `count = repository.count()`
   - `rotation.maybe_rotate(count)`

4. `ActionLogRotation` создаётся в `launcher.py` вместе с `ActionLogWriter` и передаётся в writer.

**Критерии приёмки:**
- [ ] При count >= max_count → архивная таблица создана, `action_log` очищена
- [ ] Архивная таблица содержит ровно те записи, что были в `action_log`
- [ ] При count < max_count → ротации нет
- [ ] Имя архивной таблицы содержит дату

**Вне scope:** Удаление старых архивных таблиц, экспорт архива.

**Зависимости:** Task 7C.1, 7C.2

---

### Task 7D.1 — Ctrl+Z / Ctrl+Y + кнопки undo/redo в header

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** Подключить глобальные keyboard shortcuts Ctrl+Z/Ctrl+Y и кнопки Undo/Redo в HeaderWidget

**Контекст:** `MainWindow` (`frontend/windows/main_window/window.py`) — главное окно.
`HeaderWidget` (`frontend_module/widgets/header/`) уже имеет `action_triggered` сигнал и
`connect_action_handlers`. Нужно добавить кнопки "Undo"/"Redo" (или иконки ←/→) в header
и глобальные `QShortcut` для Ctrl+Z/Ctrl+Y.

Состояние кнопок (enabled/disabled) синхронизируется с `bus.can_undo()` / `bus.can_redo()`
через callback `bus.add_change_callback(self._update_undo_redo_state)`.

**Файлы:**
- `frontend/windows/main_window/window.py` — изменить: добавить shortcuts + undo/redo кнопки
- `frontend/windows/main_window/config.py` — изменить: добавить `show_undo_redo: bool = True`

**Шаги:**

1. **`config.py`** — добавить в конфигурацию MainWindow:
   ```python
   show_undo_redo: bool = True
   undo_shortcut: str = "Ctrl+Z"
   redo_shortcut: str = "Ctrl+Y"
   ```

2. **`window.py` — `_setup_undo_redo_ui()`:**
   - Если `config.show_undo_redo = False` → skip
   - Создать `QShortcut(QKeySequence("Ctrl+Z"), self)` → connect `self._on_undo`
   - Создать `QShortcut(QKeySequence("Ctrl+Y"), self)` → connect `self._on_redo`
   - Также Ctrl+Shift+Z как альтернатива для redo (стандарт macOS)

3. **`_on_undo()` / `_on_redo()`:**
   - Получить `bus = self._app_ctx.get_action_bus()` (если None → no-op)
   - `bus.undo()` / `bus.redo()`

4. **Кнопки в header:**
   - Получить `HeaderWidget` из `self._header`
   - Добавить `btn_undo = QPushButton("↩")`, `btn_redo = QPushButton("↪")` в header layout
   - `btn_undo.clicked.connect(self._on_undo)`
   - `btn_redo.clicked.connect(self._on_redo)`
   - Состояние: обновлять в `_update_undo_redo_state()`:
     ```python
     btn_undo.setEnabled(bus.can_undo())
     btn_redo.setEnabled(bus.can_redo())
     ```

5. `bus.add_change_callback(self._update_undo_redo_state)` в `__init__`.
   `bus.remove_change_callback(self._update_undo_redo_state)` в `closeEvent`.

**Критерии приёмки:**
- [ ] Ctrl+Z → `bus.undo()` вызван
- [ ] Ctrl+Y → `bus.redo()` вызван
- [ ] Кнопка Undo disabled при `can_undo() == False`
- [ ] Кнопка Redo enabled после undo
- [ ] При отсутствии bus (app_ctx.action_bus = None) → shortcuts — no-op, без ошибок

**Вне scope:** Иконки (использовать text-символы), touch-keyboard compat.

**Зависимости:** Task 7A.2, 7A.3

---

### Task 7D.2 — Статус-бар с описанием последнего Action

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** Показывать в статус-баре MainWindow description последнего выполненного Action

**Контекст:** `MainWindow` (QMainWindow) имеет стандартный `statusBar()`. После каждого
`bus.execute()` / `bus.undo()` / `bus.redo()` — обновить текст статус-бара через callback.

**Файлы:**
- `frontend/windows/main_window/window.py` — изменить: подключить статус-бар к bus

**Шаги:**

1. В `__init__` MainWindow — если `app_ctx.get_action_bus()` не None:
   - `bus.add_change_callback(self._update_status_bar)`
   - `self._update_status_bar()` — инициализировать текст

2. **`_update_status_bar()`:**
   ```python
   def _update_status_bar(self) -> None:
       bus = self._app_ctx.get_action_bus()
       if bus is None:
           return
       action = bus.last_action()
       if action is None:
           self.statusBar().showMessage("Готово")
       else:
           self.statusBar().showMessage(f"Последнее действие: {action.description}")
   ```

3. При `undo()` — показывать `"Отменено: {action.description}"`.
   При `redo()` — `"Повторено: {action.description}"`.
   Реализовать через дополнительный `ActionBus.last_event()` -> tuple[str, Action]:
   `("execute"|"undo"|"redo", action)`.

**Критерии приёмки:**
- [ ] После `execute(action)` → статус-бар показывает `action.description`
- [ ] После `undo()` → статус-бар показывает "Отменено: ..."
- [ ] После `redo()` → статус-бар показывает "Повторено: ..."
- [ ] Без bus → статус-бар не изменяется

**Вне scope:** Цветовое форматирование статус-бара, иконки типа Action.

**Зависимости:** Task 7A.2, 7A.3, 7D.1

---

### Task 7D.3 — Dropdown «История» — последние 20 Actions

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** Кнопка «История» в header открывает dropdown с последними 20 Actions; клик на Action → откат до него

**Контекст:** Dropdown = `QMenu` с `QAction` для каждого шага истории. Клик на N-й элемент →
повторный `bus.undo()` пока текущий top-of-stack != выбранный action. Это реализуется через
`bus.undo_to(action_id)` — undo до (не включая) указанного action.

**Файлы:**
- `frontend/actions/bus.py` — изменить: добавить `undo_to(action_id)`, `history(n)`
- `frontend/windows/main_window/window.py` — изменить: кнопка «История» + QMenu

**Шаги:**

1. **`bus.py`** — добавить:
   - `history(n: int = 20) -> List[Action]` — уже есть как требование в 7A.2
   - `undo_to(target_action_id: str) -> int`:
     - Проверить что action_id есть в undo_stack
     - Делать `undo()` пока `undo_stack[-1].action_id != target_action_id`
     - Вернуть количество сделанных undo-шагов

2. **`window.py`** — кнопка «История» в header:
   - `btn_history = QPushButton("История ▼")`
   - `btn_history.clicked.connect(self._show_history_menu)`

3. **`_show_history_menu()`:**
   ```python
   def _show_history_menu(self) -> None:
       bus = self._app_ctx.get_action_bus()
       if bus is None:
           return
       actions = bus.history(20)  # список от newest к oldest
       menu = QMenu(self)
       for i, action in enumerate(actions):
           label = f"{i+1}. {action.description} ({action.action_type.value})"
           menu_action = menu.addAction(label)
           menu_action.triggered.connect(lambda _, aid=action.action_id: bus.undo_to(aid))
       menu.exec_(self._btn_history.mapToGlobal(self._btn_history.rect().bottomLeft()))
   ```

4. Обновить `_update_undo_redo_state()` из Task 7D.1 — также обновлять `btn_history.setEnabled(bus.can_undo())`.

**Критерии приёмки:**
- [ ] Кнопка «История» отображает список последних 20 Actions
- [ ] Клик на N-й элемент → `undo_to(action_id)` вызван, state откатился
- [ ] Список пустой при `can_undo() == False` → меню пустое
- [ ] Текущий top-of-stack выделен (bold или маркер "●")

**Вне scope:** Redo-история в отдельном dropdown, иконки типов Action.

**Зависимости:** Task 7A.2, 7D.1

---

### Task 7D.4 — Тесты Phase 7

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer / tester
**Цель:** Покрыть тестами все компоненты Phase 7: ActionBus, ActionBuilder, handlers, persistence, recovery

**Файлы (новые):**
- `tests/unit/test_action_schema.py`
- `tests/unit/test_action_builder.py`
- `tests/unit/test_action_bus.py`
- `tests/unit/test_field_set_handler.py`
- `tests/unit/test_region_handler.py`
- `tests/unit/test_action_log_repository.py`
- `tests/unit/test_action_log_writer.py`
- `tests/unit/test_action_log_rotation.py`
- `tests/integration/test_action_bus_recovery.py`
- `tests/integration/test_action_bus_replay.py`

**Тест-кейсы по файлам:**

**`test_action_schema.py`:**
1. `Action()` — auto UUID, auto timestamp
2. `Action.to_log_row()` + `ActionLogRow.to_action()` round-trip
3. JSON-сериализация forward_patch с нестандартными типами (numpy int64 → str)

**`test_action_builder.py`:**
4. `field_set(...)` → корректный coalesce_key, action_type=FIELD_SET
5. `region_add(...)` → REGION_ADD, description содержит имя региона
6. `profile_switch(...)` → PROFILE_SWITCH, 1 action не N
7. `command(...)` → undoable=False

**`test_action_bus.py`:**
8. execute → handler.apply вызван, action в undo_stack
9. undo → handler.revert вызван, action в redo_stack
10. redo → handler.apply вызван снова
11. Coalescing: 3 field_set на одно поле → 1 запись в стеке, backward_patch от первого
12. `max_history=5`, 7 actions → стек = 5
13. COMMAND action → not in undo_stack
14. `can_undo=False` на старте, True после execute
15. `undo_to(action_id)` → N шагов undo до нужного action

**`test_field_set_handler.py`:**
16. apply → `rm.set_field_value` вызван с forward_patch["value"]
17. revert → вызван с backward_patch["value"]
18. Нет register_name → warning, no exception

**`test_region_handler.py`:**
19. REGION_ADD apply → vision_pipeline обновлён
20. REGION_ADD revert → вернулся к snapshot before

**`test_action_log_repository.py`:**
21. append + find_recent → round-trip
22. find_since(timestamp) → только новые
23. count() → корректное число
24. delete_before(t) → удалены только старые

**`test_action_log_writer.py`:**
25. enqueue 5 actions → flush → 5 в БД
26. Coalescing в буфере: 3 field_set одного поля → после flush 1 запись
27. stop() перед завершением → все pending записаны

**`test_action_log_rotation.py`:**
28. count >= max_count → archive таблица создана, action_log пуста
29. count < max_count → ротации нет

**`test_action_bus_recovery.py` (integration):**
30. 20 FIELD_SET → `repository.append` → `recovery.recover()` → state идентичен
31. UNDO-запись в лог → recovery компенсирует

**`test_action_bus_replay.py` (integration — критерий мета-плана):**
32. 20 Actions сохранены в лог → применены на чистый state → результат идентичен исходному
33. Debug-guard: 0 WARN'ов при корректном использовании bus

**Критерии приёмки:**
- [ ] `pytest tests/unit/test_action*.py tests/unit/test_field_set*.py tests/unit/test_region*.py -v` — все проходят
- [ ] `pytest tests/integration/test_action_bus_*.py -v` — все проходят
- [ ] Все тесты без Qt (mock rm, нет QApplication)
- [ ] Replay test (п.32) верифицирует детерминированность

**Зависимости:** Task 7A.1, 7A.2, 7B.1-7B.4, 7C.1-7C.4

---

## Граф зависимостей

```
7A.1 (Action schema) ────────────────────────────────────────────────────┐
         │                                                                 │
         ↓                                                                 ↓
7A.2 (ActionBus) ──────────────────────────────────────────────────── 7C.1 (SQL repo)
         │                                                                 │
         ↓                                                                 ↓
7A.3 (Context wiring) ─────────────────────────────────────────────── 7C.2 (Batched writes)
         │                                                                 │
    ┌────┴──────────────────────────────────────────────────────┐          ↓
    ↓    ↓             ↓              ↓                          ↓    7C.3 (Recovery)
7B.1   7B.2          7B.3           7B.4                        │         │
(cam) (regions)     (chain/display) (profile/recipe)            │    7C.4 (Rotation)
    │                                                            │
    └──────────────────────────────────────────────────────────→7D.4 (Tests)
                                                                 ↑
7A.2 ──→ 7D.1 (shortcuts) ──→ 7D.2 (status bar) ──→ 7D.3 (history) ──┘
```

**Параллельное исполнение:**
- **Batch 1:** 7A.1 (блокирующий для всего)
- **Batch 2:** 7A.2 + 7C.1 (параллельно, оба от 7A.1)
- **Batch 3:** 7A.3 (от 7A.2)
- **Batch 4:** 7B.1, 7B.2, 7B.3, 7B.4, 7C.2, 7D.1 (параллельно, все от 7A.3 или 7C.1)
- **Batch 5:** 7C.3, 7C.4, 7D.2, 7D.3 (от своих зависимостей)
- **Batch 6:** 7D.4 (все завершены)

---

## Ключевые файлы (существующие, переиспользовать)

Все пути относительно `multiprocess_prototype/`.

| Что | Путь | Использование |
|-----|------|---------------|
| SchemaBase | `../../multiprocess_framework/modules/data_schema_module/` | Базовый класс Action |
| Dispatcher | `../../multiprocess_framework/modules/dispatch_module/` | Паттерн для ActionBus handlers |
| GenericRepository | `../../multiprocess_framework/modules/sql_module/core/base_repository.py` | ActionLogRepository |
| SchemaBaseMapper | `../../multiprocess_framework/modules/sql_module/adapters/schema_mapper.py` | Маппинг ActionLogRow |
| UnitOfWork | `../../multiprocess_framework/modules/sql_module/core/unit_of_work.py` | Batched writes |
| SQLManager | `../../multiprocess_framework/modules/sql_module/core/sql_manager.py` | DDL для action_log |
| DatabaseProcess | `backend/processes/database/process.py` | action_log_setup |
| FrontendAppContext | `frontend/app_context.py` | Добавить action_bus |
| RegisterBindingContext | `../../multiprocess_framework/modules/frontend_module/widgets/tabs/binding_context.py` | Добавить action_bus |
| DisplayRouter | `frontend/managers/display_router.py` | display Actions |
| MainWindow | `frontend/windows/main_window/window.py` | shortcuts, status bar, history |

**Новые директории/файлы:**
- `frontend/actions/` — schemas, builder, bus, handlers/, persistence/
- `tests/unit/test_action*.py` — unit тесты
- `tests/integration/test_action_bus_*.py` — integration тесты

---

## Верификация Phase 7 (финальные критерии мета-плана)

```bash
# Unit тесты
 && python -m pytest multiprocess_prototype/tests/unit/test_action*.py -v
# Integration тесты
python -m pytest multiprocess_prototype/tests/integration/test_action_bus_*.py -v
# Все тесты
python -m pytest multiprocess_prototype/tests/ -v
# Ruff
ruff check multiprocess_prototype/ && ruff format --check multiprocess_prototype/
# Validate
python scripts/validate.py
```

**Smoke-тест (manual):**
1. Запустить прототип
2. Изменить параметр слайдером (10 тиков) → Ctrl+Z × 1 → параметр откатился к значению ДО серии тиков
3. Recipe switch → 1 Action в стеке (не N по числу полей)
4. Добавить регион → Ctrl+Z → регион исчез
5. Kill -9 → перезапуск → состояние восстановлено
6. Проверить в лог: 0 WARN'ов связанных с debug-guard
