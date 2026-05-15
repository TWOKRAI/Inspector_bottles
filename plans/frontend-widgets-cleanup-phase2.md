# Plan: Frontend widgets cleanup — Phase 1 (component review) + Phase 2 (binding-aware factory)

**Slug:** frontend-widgets-cleanup-phase2 (детализация продолжения)
**Дата:** 2026-05-14
**Ветка:** refactor/frontend-widgets-cleanup
**Родительский план:** [`plans/frontend-widgets-cleanup.md`](frontend-widgets-cleanup.md) — верхнеуровневая карта (Phase 0-3)
**PR-стратегия:** 2 раздельных PR (PR1 = Phase 1 docs, PR2 = Phase 2 code)

---

## Context

Текущая фабрика `multiprocess_prototype/frontend/forms/factory.py` создаёт сырые Qt-виджеты (`QCheckBox`, `QSpinBox`, `QDoubleSpinBox`, `QComboBox`, `ColorTripletWidget`) из `FieldInfo`. В фреймворке есть зрелые контролы (`CheckboxControl`, `NumericControl`, `SpinBoxControl`, `SliderControl`, `CompoundNumericControl`) с touch-keyboard, `ControlHooks`, `effective_access_level`, debounce, `resolve_meta`. Прототип их не использует — техдолг и одновременно точка переосмысления связки «Plugin → регистр → форма».

Пользователь хочет:
1. Полностью использовать framework-компоненты (с минимальными правками их кода — разрешено).
2. Регистры (Pydantic+FieldMeta) должны лежать в `Plugins/<cat>/<name>/registers.py` — как `multiprocess_prototype_backup/registers/display/schemas.py` (паттерн уже работает в `Plugins/control/robot_control/`).
3. Без dual-mode костыля — binding-aware из коробки везде.
4. Все ключевые инфраструктуры — `Access-level`, `Undo/Redo` (через `ActionBus`), `IPC bridge` (Phase 12), `coalescing` — должны продолжать работать.

---

## Целевая архитектура

### Главный архитектурный приём: мост `ActionBusRegistersManager`

Фреймворк-фасады (`CheckboxControl.create`, `NumericControl.create`, …) принимают `registers_manager: RegistersManagerLike` и **внутри** делают `RegisterAdapter(rm)` → `adapter.write(...) → rm.set_field_value(...)`. Если прокинуть «настоящий» `RegistersManagerV2`, мы обойдём `FieldSetHandler.apply` → не получим coalescing и IPC bridge (Phase 12 `_notify_bridge` отправляет change в worker через router_module). Это сломает IPC-синхронизацию runtime.

**Решение:** в прототипе создаём тонкий мост — `ActionBusRegistersManager` (`multiprocess_prototype/frontend/actions/action_bus_register_adapter.py`):

```python
class ActionBusRegistersManager:
    """RegistersManagerLike-обёртка, превращающая write в ActionBus.execute(field_set).

    read / subscribe / get_field_metadata / get_register делегируются в реальный RM.
    set_field_value — единственное место разница: строит field_set action и
    отправляет в ActionBus, который вызывает FieldSetHandler.apply → rm.set_field_value
    + _notify_bridge (IPC в runtime worker через router_module).

    Coalescing (V2ActionBuilder.field_set_timed, 1.5s bucket) — нативно через ActionBus.
    Undo/Redo — нативно (action попадает в undo_stack).
    """
    def __init__(self, real_rm, action_bus, action_builder):
        self._rm = real_rm
        self._bus = action_bus
        self._builder = action_builder

    def get_register(self, name): return self._rm.get_register(name)
    def get_field_metadata(self, register, field): return self._rm.get_field_metadata(register, field)
    def subscribe(self, register, field, callback): return self._rm.subscribe(register, field, callback)

    def set_field_value(self, register, field, value):
        # Runtime thread guard — единственное безопасное место использования (ревью, критичный фикс)
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication
        assert QThread.currentThread() == QApplication.instance().thread(), (
            "ActionBusRegistersManager must be called from GUI thread (subscriber "
            "callbacks из RegistersManager._notify_observers диспатчатся через "
            "Qt event loop; вызов из worker thread сломает blockSignals)"
        )
        old = getattr(self._rm.get_register(register), field, None)
        # ПОРЯДОК АРГУМЕНТОВ: V2ActionBuilder.field_set_timed(register, field, NEW_value, OLD_value)
        # Перепутывание new/old → инвертированный undo/redo (баг, выявлен ревью)
        action = self._builder.field_set_timed(register, field, value, old)
        try:
            result = self._bus.execute(action)
        except Exception as exc:
            return (False, f"ActionBus handler error: {exc!r}")
        # Семантика execute() после правки framework (см. ниже):
        #   True  → handler.apply выполнился успешно
        #   False → pre_execute_hook отклонил ИЛИ handler not found
        if result is True:
            return (True, None)
        return (False, "ActionBus rejected or no handler")
```

**⚠️ Прерывающая правка фреймворка (учтена в Phase 2):** на текущий момент `ActionBus.execute() -> None` (`multiprocess_framework/modules/actions_module/bus.py:199`). Это блокер: если оставить так, `ok` всегда `None` → `if None` всегда False → мост каждый раз возвращает `(False, "ActionBus rejected")`. Меняем сигнатуру `execute() -> bool` с обратной совместимостью: возвращаем `True` при успешном apply, `False` если `pre_execute_hook` отклонил. Существующие callers, игнорирующие return value, продолжают работать без изменений.

Фреймворк-фасады получают этот мост вместо «голого» RM — и автоматически унаследуют coalescing, IPC bridge, undo/redo, audit pre/post hooks.

### Принципы

1. **Plugin владеет регистром.** `Plugins/<cat>/<name>/registers.py` объявляет `@register_schema("NameRegistersV1") class NameRegisters(SchemaBase)` с `Annotated[Type, FieldMeta(...)]`. Плагин в `plugin.py` → `register_class = NameRegisters`. Существующий механизм — не выдумываем новый.

2. **`RegistersManagerV2.from_registry(PluginRegistry)`** — единая точка сбора. **Не меняется.**

3. **`CardsFieldFactory.create(field_info, form_ctx, parent=None)`.** `form_ctx: FormBuildingContext` — обёртка над 4 параметрами (`registers_manager`, `action_bus`, `action_builder`, `current_access_level`). Внутри: создаёт `ActionBusRegistersManager(rm, bus, builder)`, передаёт в фасады.

4. **Запись + Undo/Redo.** Запись пользователя:
   ```
   view.on_changed → presenter.write
     → RegisterAdapter.write → ActionBusRegistersManager.set_field_value
       → ActionBuilder.field_set_timed (coalesce_key = register.field:bucket)
       → ActionBus.execute(action)
         → pre_execute_hook (auth-guard, если есть)
         → FieldSetHandler.apply(action, REAL_rm)
           → REAL_rm.set_field_value(...)
             → _notify_observers → подписчики (включая наш же presenter, но silent через block_signals)
             → _notify_bridge (Phase 12 IPC в runtime worker)
         → post_execute_callbacks (audit, наш ControlHooks-наблюдатель)
         → undo_stack += action
   ```
   Undo: `ActionBus.undo() → FieldSetHandler.revert → rm.set_field_value(old)` → subscribers (presenter) → `view.set_value_silent(old)`. Цикла нет, т.к. `set_value_silent` блокирует Qt-сигнал.

5. **Access-level (реальный, не заглушка).** `AppContext.auth.user_level()` существует. Фабрика прокидывает `current_access_level=ctx.auth.user_level()` в каждый `*.create(...)`. `effective_access_level = max(binding.access_level, meta.access_level)` уже рассчитывается в `SchemaTraits`. UI блокируется через `BaseControlConfig.access_level` при `current < effective`. Дополнительно: `ControlHooks.on_access_denied` → toast/MessageBox.

6. **ControlHooks как наблюдатель (без write-роли).** Каждая фабрика контрола передаёт `ControlHooks(on_write_committed=..., on_write_rejected=..., on_access_denied=...)`. Это **наблюдатели**, не пути записи: запись уже идёт через ActionBus. Hooks используются:
   - `on_write_rejected` → `view.show_error(msg)` (валидация регистра)
   - `on_access_denied` → UI-фидбек (логирование + опциональный toast)
   - `on_write_committed` → опционально, для observability/telemetry

7. **Регистры — мост GUI ↔ multiprocess backend через FieldMeta.routing + TopologyBridge + state_store_module.** Это **существующая инфраструктура**, мы её **не меняем**, но обязаны не сломать. Полный контур:

   **Вперёд (GUI → worker), при изменении поля через UI:**
   ```
   user → view → presenter → ActionBusRegistersManager.set_field_value
     → V2ActionBuilder.field_set_timed(coalesce_key=register.field:bucket)
     → ActionBus.execute(action)
       → FieldSetHandler.apply(action, REAL_rm)
         → REAL_rm.set_field_value(register, field, value)
           → _notify_observers → локальные subscribers (наш presenter получит silent-update)
         → bridge.on_field_set(register, field, value)  ← Phase 12 IPC
           → catalog.resolve_field_command(plugin, field) (использует FieldMeta.routing.channel и process_targets, fallback на connection_map.py)
           → validator.validate_field_command
           → debounce (50ms для slider-полей, 0 для остальных)
           → sender.send_field_command(target_process, command, {field: value})
             → RouterManager.send → QueueChannel → IPC → worker process
   worker:
     → router-handler → plugin.handle_command(command_name, args)
     → plugin updates local register: setattr(self._reg, field, value)
   ```

   **Назад (worker → GUI), при изменении worker'ом своего регистра или публикации метрик:**
   ```
   worker plugin → ctx.state_proxy.set("processes.<proc>.config.<field>", value)
     → IPC → StateStoreManager (в ProcessManager) → TreeStore.update → DeltaDispatcher
     → state.changed event → IPC обратно в GUI
   GUI:
     → TopologyBridge.on_state_delta(path, value)
       → если path matches "processes.*.config.*" → rm.set_value(plugin, field, value)
         → REAL_rm.set_field_value → _notify_observers → наш presenter → view.set_value_silent
       → этот путь **минует ActionBus** (worker — система, не пользователь → не записываем в undo)
   ```

   **Важно для нашего рефакторинга:**
   - `FieldMeta.routing` (channel, process_targets, priority, transform) — данные регистра, никакой нашей логики не касаются. Просто пробрасываются через `bridge.on_field_set`.
   - **`ActionBusRegistersManager` встраивается как декоратор RM для GUI-слоя**: write идёт через ActionBus → FieldSetHandler → REAL_rm + bridge. IPC отправка worker'у сохраняется автоматически.
   - **state_store обратный путь работает как раньше**: presenter подписан на REAL_rm через `RegisterAdapter.subscribe(register, field, cb)` → при `_notify_observers` (от любого источника, включая state_store→TopologyBridge.on_state_delta) → `cb(new_value)` → `view.set_value_silent`.
   - **Не дублировать запись в worker:** `ActionBusRegistersManager.set_field_value` НЕ должен сам звать `bridge.on_field_set` — это делает `FieldSetHandler.apply` после успешного RM-write. Наш мост только конструирует action.

8. **Layout.** Для value-полей (bool/int/float/literal/color3) — framework view (Label+Widget внутри): в `QFormLayout` → `addRow("", widget)`, в `QTableWidget` → widget в cell col=1, имя в col=0. Для str/str_long/path — оставляем `QLineEdit` / `QPlainTextEdit` + отдельный `QLabel` (нет framework-аналогов, отдельная задача в backlog).

9. **`value_changed: Signal` в 4 view-классах.** Добавляем явный Qt-сигнал-прокси в `CheckboxView`, `SpinBoxValueView`, `SliderValueView`, `LabeledNumericGroupView` (3-5 строк каждый). Это публичный API для FieldEditor.change_signal (observability в RegisterView) и общая практика для composability. Backward-compat 100%.

10. **`combo/` — новый компонент в фреймворке.** По паттерну Traits+Presenter+View+Facade (8-й компонент):
    ```
    components/combo/
    ├── __init__.py, config.py (ComboBoxConfig: items: list[str], ...)
    ├── view.py (ComboBoxView: QLabel+QComboBox, value_changed: Signal(str))
    ├── presenter.py (ComboBoxPresenter с SyncTrait/SchemaTrait/AccessTrait)
    ├── facade.py (ComboBoxControl.create)
    └── defaults.py (combo_left, combo_right)
    ```
    Регистрация в `components/__init__.py`. Тесты в `multiprocess_framework/tests/frontend_module/components/test_combo.py` (5-7).

11. **ColorTripletWidget удаляется.** color3 → `CompoundNumericControl` с лейблами R/G/B.

---

## Phase 1: Component review (PR1)

**Артефакт:** `docs/refactors/widgets-component-review.md` (новый).

| # | Компонент | Прототипный аналог | Решение для Phase 2 |
|---|-----------|--------------------|---------------------|
| 1.1 | `checkbox/` | `QCheckBox` + отд.`QLabel` | `CheckboxControl` |
| 1.2 | `numeric/` | `QDoubleSpinBox` | `NumericControl` для float |
| 1.3 | `slider/` | не используется | `SliderControl` для int с маленьким диапазоном (критерий уточняется в Phase 2) |
| 1.4 | `spinbox/` | `QSpinBox` | `SpinBoxControl` для int |
| 1.5 | `compound/` | `ColorTripletWidget` (62 LOC) | `CompoundNumericControl`, удалить ColorTripletWidget |
| 1.6 | `label/` | `QLabel` напрямую | `LabelConfig`/lookup для readonly/unsupported |
| 1.7 | `group/` | нет аналога | используется внутри numeric/spinbox/slider |
| **1.8** | **`combo/` (новый)** | `QComboBox` | **создать в Phase 2** |

**Формат каждой секции:**
- **API:** ключевые методы View (после правки value_changed: Signal), сигнатура фасада `*.create(...)`
- **Фичи:** touch-keyboard, hooks, access-control, debounce, resolve_meta — что есть сверх сырого Qt
- **Прототипный аналог:** путь, LOC, текущее поведение
- **Решение:** использовать как есть / правка / новый компонент
- **Открытые вопросы:** что уточняется в Phase 2

**Acceptance Phase 1:**
- [ ] `docs/refactors/widgets-component-review.md` создан, 8 секций
- [ ] В `plans/frontend-widgets-cleanup.md` чекбоксы 1.1-1.7 отмечены `[x]`, добавлен 1.8
- [ ] Все решения по правкам фреймворка зафиксированы (value_changed × 4, новый combo/)

**Коммиты PR1:**
- `docs(refactors): ревью framework components 1.1-1.8 для Phase 2`

---

## Phase 2: Итеративный rollout — пилот → расширение по компонентам

**Стратегия (по запросу пользователя):** сначала довести **один** компонент + **один** реальный виджет до production-quality (полный smoke + двусторонний I/O с worker), убедиться что архитектура работает, потом распространять. Это снижает риск большого PR и даёт обратную связь.

### Phase 2.0 — Pilot: Checkbox для `robot_control.enabled` (PR2)

**Цель:** доказать, что архитектура `view → presenter → ActionBusRegistersManager → ActionBus → FieldSetHandler → REAL_rm + bridge` работает end-to-end в production-условиях. Один регистр (`robot_control` — единственный плагин с реальным `register_class`), одно bool-поле (`enabled`), один компонент (`CheckboxControl`), один tab (`PluginsTab`).

**Скоуп (минимальный):**

**A. Framework (минимум):**
- `multiprocess_framework/modules/actions_module/bus.py` — `execute(action) -> bool` (см. блокер из ревью)
- `components/checkbox/view.py` — `value_changed: Signal(bool)`
- Тест на новый Signal + тест на `execute() -> bool`

**B. Prototype — новый мост (нужен сразу, без него пилот не имеет смысла):**
- `multiprocess_prototype/frontend/actions/action_bus_register_adapter.py` — `ActionBusRegistersManager` (~60 LOC)
- `multiprocess_prototype/frontend/actions/__init__.py` — экспорт
- `multiprocess_prototype/frontend/actions/tests/test_action_bus_register_adapter.py` — 5 тестов

**C. Prototype — точечная замена в factory ТОЛЬКО для bool:**
- `multiprocess_prototype/frontend/forms/factory.py`:
  - Добавить опциональный параметр `form_ctx: FormBuildingContext | None = None` (НЕ обязательный пока — пилот не ломает старых callers)
  - `_build_bool` — если `form_ctx` передан, используем `CheckboxControl.create(bus_rm, BindingConfig(...), ...)` и оборачиваем в FieldEditor; если нет — старый путь с QCheckBox (для остальных callers)
  - Остальные 8 builders (int/float/literal/color3/str/...) — **не трогаем в пилоте**

**D. Prototype — один caller с form_ctx:**
- `multiprocess_prototype/frontend/widgets/tabs/plugins/tab.py` — передать `form_ctx` в `RegisterView` ТОЛЬКО при отображении `robot_control` (либо через флаг, либо всегда — но `RegisterView` пробрасывает в фабрику только если передан). Старая цепочка `_on_field_changed` для остальных регистров остаётся.

**E. Тесты пилота:**
- `test_action_bus_register_adapter.py` — 5 unit-тестов (см. выше)
- `test_factory.py` — добавить 2-3 теста для бул через form_ctx (старые 15 тестов не ломаем — они идут по старому пути без form_ctx)
- Smoke (manual): `python multiprocess_prototype/run.py` → Plugins-tab → `robot_control` → toggle `enabled`:
  - значение в RM меняется
  - IPC-команда уходит worker'у (проверить в логах router_module / Plugin.handle_command)
  - undo/redo работают (Ctrl+Z/Y)
  - access_level: если изменить `FieldMeta.access_level=5` в robot_control.enabled и user_level=0 — UI блокируется, `on_access_denied` срабатывает
  - state_store обратный путь: если worker меняет `enabled` (например, плагин сам его установит и опубликует через `ctx.state_proxy.set("processes.robot.config.enabled", False)`) → UI обновляется silent через `TopologyBridge.on_state_delta → rm.set_value → subscribe callback`

**Acceptance Phase 2.0 (Pilot):**
- [x] `ActionBus.execute() -> bool` + 3 теста (success, pre_execute reject, handler not found) — `2222204` + регрессионный `2938cf9` (rejected actions не загрязняют undo_stack)
- [x] `CheckboxView.value_changed: Signal` + тест — `2222204`
- [x] `ActionBusRegistersManager` + 5 unit-тестов + 1 интеграционный pytest-qt round-trip — `ca32cdc` (+ регрессионный «один user-click = один action» в `cd23adc`)
- [x] `_build_bool` поддерживает оба пути (form_ctx и legacy) — `1e9ba6d`. **Отступление:** `DeprecationWarning` убран в `cd23adc` по результатам ревью (он зашумлял логи для всех bool-полей вне robot_control). TODO Phase 2.6: re-enable когда `form_ctx` станет обязательным во всех callers.
- [x] PluginsTab прокидывает form_ctx для robot_control — `bcdb061`
- [N/A] Smoke (5 чекпоинтов) — **blocked**: агентская среда без camera runtime (`run.py` требует физические камеры + ProcessManagerProcess). End-to-end pipeline покрыт автотестами: `CheckboxControl click → ActionBusRegistersManager → ActionBus.execute → FieldSetHandler.apply → rm.set_field_value → subscribe callback → view update` + `bus.undo() → view rollback` (integration test в `test_action_bus_register_adapter.py`). Ручной smoke рекомендуется при следующем запуске приложения.
- [x] `mcp__sentrux__check_rules` (9 правил, 0 violations), `python scripts/validate.py` (OK), `python scripts/run_framework_tests.py` (2638 passed, 8 skipped) — зелёные
- [ ] **Точка решения:** оценка результата с пользователем — расширять ли на остальные компоненты (Phase 2.1-2.7), или скорректировать архитектуру

**Коммиты Phase 2.0 (фактически 6):**
1. `2222204` feat(framework): ActionBus.execute() -> bool, CheckboxView.value_changed Signal
2. `ca32cdc` feat(actions): ActionBusRegistersManager — мост между framework-фасадами и ActionBus
3. `1e9ba6d` refactor(forms): пилотная интеграция CheckboxControl в factory для bool через form_ctx
4. `bcdb061` feat(plugins-tab): прокидывать form_ctx для robot_control (пилот binding-aware)
5. `2938cf9` test(actions): pre_execute reject не должен попадать в undo_stack (регрессия от tester)
6. `cd23adc` fix(forms): устранение двойной записи в ActionBus для binding-aware checkbox (review iter 1)

---

### Phase 2.1 — Расширение после успеха пилота

После подтверждения концепции на пилоте — последовательно расширяем (каждое — отдельный коммит/PR):

**2.1.** SpinBoxControl для `int` (например, `robot_control.min_defect_area`)
**2.2.** NumericControl для `float` (нет в robot_control, но потребуется для других регистров → ждать Phase 3 миграции, либо тестировать на синтетическом регистре)
**2.3.** `combo/` — новый компонент в фреймворке (8-й) + builder в factory для `Literal`
**2.4.** SliderControl для `int` с малым диапазоном (критерий уточняется в 2.1)
**2.5.** CompoundNumericControl для `color3` → удаление `ColorTripletWidget`
**2.6.** Прокидывание `form_ctx` во всех остальных callers: `RegisterView` конструктор обязательный, `form_builder`, `InspectorPanel`, `services/tab.py`, `settings/system/section.py` (с правкой двойной подписки)
**2.7.** Удаление legacy-пути в factory (`form_ctx` становится обязательным), очистка

**Принцип:** каждый sub-step — отдельный PR, со своими acceptance и smoke. После 2.6 можно удалять legacy.

### Скоуп изменений (полный, для справки — реализуется в Phase 2.1+)

**A. Framework (минимум):**

- `multiprocess_framework/modules/actions_module/bus.py` — изменить сигнатуру `execute(action) -> bool` с явным покрытием **всех** ветвлений (после ревью):
  - `True` — `handler.apply()` выполнился успешно, action в undo_stack
  - `False` — `pre_execute_hook` отклонил, **ИЛИ** handler not found (current implicit `return` → теперь `return False`)
  - **Exception из `handler.apply`** — НЕ ловим (пробрасываем как раньше); мост `ActionBusRegistersManager` ловит сам и возвращает `(False, err)`
  - Обновить docstring + покрыть 3 unit-тестами: success → True; pre_execute_hook False → False; handler not found → False
- `components/checkbox/view.py` — `value_changed: Signal(bool)` (эмит в `_on_state_changed`)
- `components/spinbox/view.py` — `value_changed: Signal(float)` в `SpinBoxValueView`
- `components/slider/view.py` — `value_changed: Signal(float)` в `SliderValueView`
- `components/group/view.py` (LabeledNumericGroupView) — `value_changed: Signal(float)` проксирует из value-части
- `components/combo/` — новый пакет (6 файлов: `__init__.py`, `config.py`, `view.py`, `presenter.py`, `facade.py`, `defaults.py`)
- `components/__init__.py` — экспорт `ComboBoxControl`, `ComboBoxView`, `ComboBoxConfig`, `combo_left`, `combo_right`
- `multiprocess_framework/tests/frontend_module/components/test_combo.py` — 5-7 тестов (setup, set_value, read/write через адаптер, access-denied, items rendering, value_changed signal)
- Дополнительные тесты для существующих view: проверить новый `value_changed: Signal` (по 1 тесту на каждое = 4 теста)

**B. Prototype — новый мост:**

- `multiprocess_prototype/frontend/actions/action_bus_register_adapter.py` — `ActionBusRegistersManager` (~60 LOC, см. код выше)
- `multiprocess_prototype/frontend/actions/__init__.py` — экспорт
- `multiprocess_prototype/frontend/actions/tests/test_action_bus_register_adapter.py` — тесты:
  - `write` строит field_set action с правильным coalesce_key
  - `write` вызывает `bus.execute(action)` и возвращает успех
  - `write` возвращает (False, err) если bus отклоняет (pre_execute_hook возвращает False)
  - `read/subscribe/get_field_metadata` делегируются в реальный RM
  - Coalescing двух быстрых write — один action в стеке undo

**C. Prototype — factory переписана:**

- `multiprocess_prototype/frontend/forms/factory.py` — полный rewrite:
  - `@dataclass class FormBuildingContext: registers_manager, action_bus, action_builder, current_access_level=0`
  - `CardsFieldFactory.create(field_info, form_ctx, parent=None)` — `form_ctx` обязателен
  - Внутри: `bus_rm = ActionBusRegistersManager(form_ctx.registers_manager, form_ctx.action_bus, form_ctx.action_builder)`
  - 9 builders:
    - bool → `CheckboxControl.create(bus_rm, BindingConfig(fi.plugin_name, fi.field_name), CheckboxViewConfig(...), current_access_level=form_ctx.current_access_level, hooks=ControlHooks(on_write_rejected=_on_rejected, on_access_denied=_on_denied))`
    - int → `SpinBoxControl.create(bus_rm, binding, SpinBoxConfig(min_val, max_val), current_access_level=..., hooks=...)` или `SliderControl.create(...)` если `meta.min` и `meta.max` заданы и range ≤ 1000
    - float → `NumericControl.create(bus_rm, binding, NumericViewConfig(view_type="spinbox", min_val, max_val, decimals=meta.round_k, suffix=unit), ...)`
    - color3 → `CompoundNumericControl.create(bus_rm, CompoundNumericConfig(binding=..., labels=["R","G","B"], view_config=NumericViewConfig(view_type="spinbox", min_val=0, max_val=255)), ...)`
    - literal → `ComboBoxControl.create(bus_rm, binding, ComboBoxConfig(items=list(get_args(t))), ...)`
    - str_short → остаётся `QLineEdit` (TODO: framework `text/` компонент в backlog)
    - str_long → остаётся `QPlainTextEdit` (read-only h=60)
    - path → остаётся `QLineEdit` (полный picker — отдельная задача)
    - unsupported → `LabelControl.create(...)` если возможно, иначе disabled `QLabel`
  - `FieldEditor.change_signal = view.value_changed` (через result.widget.value_changed для composites)
  - `FieldEditor.getter/setter` — делегируют `view.get_value` / `view.set_value_silent`
  - Удалить `_build_color3` (старая ColorTripletWidget логика)
  - Удалить импорты `QCheckBox`, `QSpinBox`, `QDoubleSpinBox`, `QComboBox` (кроме str/path)

- `multiprocess_prototype/frontend/forms/widgets/color_picker.py` — **удалить**
- `multiprocess_prototype/frontend/forms/widgets/__init__.py` — убрать экспорт `ColorTripletWidget`

**D. Prototype — все callers фабрики прокидывают FormBuildingContext:**

- `multiprocess_prototype/frontend/forms/form_builder.py`:
  - Сигнатуры `build_form_for_register(fields, *, form_ctx, ...)`, `build_table_for_register(fields, *, form_ctx, ...)`
  - Прокидывают `form_ctx` в `CardsFieldFactory.create(fi, form_ctx)`
  - Layout: `addRow("", editor.widget)` для value-полей (label внутри composite); для str/path — `addRow(editor.label, editor.widget)` как раньше
- `multiprocess_prototype/frontend/forms/register_view.py`:
  - Конструктор `__init__(fields, *, form_ctx, ...)`
  - Удалить подписку `editor.change_signal.connect(self._on_editor_changed)` — writes теперь идут через ActionBus, не через signal-перехват. Вместо этого: подписка на `ActionBus.add_change_callback` для UI-refresh при undo/redo (`_on_bus_changed` — паттерн из существующего `PluginsTab._on_bus_changed`)
  - `field_changed` сигнал остаётся для observability (опционально), но не используется для записи
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py`:
  - В `_try_build_cards_editors` создать `FormBuildingContext(ctx.registers_manager(), ctx.action_bus(), ctx.action_builder(), ctx.auth.user_level())` и передать в `CardsFieldFactory.create(fi, form_ctx, parent=self._params_widget)`
  - Удалить fallback на QLineEdit (теперь отсутствие RM — программная ошибка, не runtime degrade)
- `multiprocess_prototype/frontend/widgets/tabs/plugins/tab.py`:
  - Передать `form_ctx` в `RegisterView(fields, form_ctx=form_ctx, ...)`
  - Удалить `_on_field_changed` (writes идут через ActionBus напрямую)
  - Сохранить `_on_bus_changed` для UI-refresh при undo/redo
- `multiprocess_prototype/frontend/widgets/tabs/services/tab.py` — то же
- `multiprocess_prototype/frontend/widgets/tabs/settings/system/section.py` — то же. **ВАЖНО:** здесь сейчас **двойная подписка**: `editor.change_signal.connect(self._presenter.on_field_changed)` (строка 91) И `self._register_view.field_changed.connect(self._presenter.on_field_changed_action_bus)` (строки 92-93). Обе подписки удалить — writes теперь идут через ActionBus через мост. Подписаться на `ActionBus.add_change_callback` для UI-refresh при undo/redo (как в `PluginsTab._on_bus_changed`). Метод `on_field_changed_action_bus` в presenter — удалить или переименовать в наблюдатель

**E. AppContext — гибрид (struct + convenience-метод):**

`FormBuildingContext` — отдельный struct (изоляция тестов factory от полного AppContext), но callers получают его одной строкой через convenience-метод:

```python
# multiprocess_prototype/frontend/forms/factory.py
@dataclass(frozen=True)
class FormBuildingContext:
    registers_manager: RegistersManagerV2
    action_bus: ActionBus
    action_builder: V2ActionBuilder
    current_access_level: int = 0

# multiprocess_prototype/frontend/app_context.py — convenience-метод
class AppContext:
    def form_building_context(self) -> FormBuildingContext:
        return FormBuildingContext(
            registers_manager=self.registers_manager(),
            action_bus=self.action_bus(),
            action_builder=V2ActionBuilder,
            current_access_level=self.auth.user_level(),
        )
```

Каждый caller: `RegisterView(fields, form_ctx=ctx.form_building_context())` — одна строка, без дублирования сборки. Тесты factory: фейковый RM + реальный ActionBus + V2ActionBuilder, без поднятия AppContext.

**F. Тесты:**

- `multiprocess_prototype/frontend/forms/tests/test_factory.py` — переписать 15 тестов:
  - Заменить просто `CardsFieldFactory.create(fi)` на `CardsFieldFactory.create(fi, _make_test_form_ctx())`
  - `_make_test_form_ctx()` — хелпер с фейковым RM (паттерн из `test_controls_v2_base.py:46-80`), реальным `ActionBus` (изолированный экземпляр), реальным `V2ActionBuilder`
  - Проверка типа виджета (framework view) + проверка чтения через bus_rm
  - Добавить 3-5 новых тестов: write через ActionBus → action в undo-стеке; undo → значение откатывается; coalescing двух быстрых write
- `multiprocess_prototype/frontend/forms/tests/test_form_builder.py` (если есть) — обновить аналогично
- `multiprocess_prototype/frontend/tests/test_action_bus_v2.py` — добавить интеграционный тест: создать `ActionBusRegistersManager`, выполнить write через него, проверить что action в undo_stack
- Smoke (вручную после автотестов): `python multiprocess_prototype/run.py` → Plugins-tab `robot_control` → form рендерится → toggle `enabled` → undo/redo работают → values отражаются в RM

### Acceptance Phase 2 (после 2.1-2.7)

- [ ] `value_changed: Signal` в 4 framework view; 4 unit-теста зелёные
- [ ] `components/combo/` создан; 5-7 тестов зелёные; экспорт работает
- [ ] `ActionBusRegistersManager` создан; 5 unit-тестов зелёные
- [ ] `FormBuildingContext` dataclass + `CardsFieldFactory.create(fi, form_ctx)` API
- [ ] 9 builders в factory.py используют framework-фасады (5 binding-aware + 3 сырых для str/path + label для unsupported)
- [ ] `ColorTripletWidget` удалён, `forms/widgets/color_picker.py` удалён
- [ ] Все 5 callers (`RegisterView`, `form_builder`, `InspectorPanel`, `plugins/tab.py`, `services/tab.py`, `settings/system/section.py`) прокидывают `form_ctx`
- [ ] 15+ тестов test_factory.py зелёные; добавлено 3-5 новых
- [ ] `make check`, `make test`, `python scripts/validate.py`, `python scripts/run_framework_tests.py` — всё зелёное
- [ ] Smoke: `python multiprocess_prototype/run.py` — формы рендерятся framework-виджетами; toggle/edit сохраняется; undo/redo работают; access-level блокирует поля для user_level=0 если `FieldMeta.access_level > 0`
- [ ] `mcp__sentrux__check_rules` — нет новых violations (layer-импорты соблюдены)
- [ ] `mcp__sentrux__health` — score не упал
- [ ] `ActionBus.execute()` возвращает `bool`, юнит-тест на отказ pre_execute_hook
- [ ] `ComboBoxPresenter` корректно конвертирует `str ↔ non-str` для `Literal[1,2,3]` (юнит-тест в `test_combo.py`)
- [ ] `settings/system/section.py` — двойная подписка удалена, метод `on_field_changed_action_bus` в presenter переработан/удалён

**Коммиты Phase 2 целиком (ориентировочно 5-6 после пилота):**
1. `feat(components): value_changed Signal в checkbox/spinbox/slider/group views`
2. `feat(components): новый combo/ компонент (View+Presenter+Facade+тесты)`
3. `feat(actions): ActionBusRegistersManager — мост между framework и ActionBus`
4. `refactor(forms): CardsFieldFactory на framework-фасадах, FormBuildingContext`
5. `refactor(forms): RegisterView/InspectorPanel/tabs прокидывают form_ctx, удалён ColorTripletWidget`
6. `test(forms): factory-тесты на фейковом RM + интеграция с ActionBus`

---

## Phase 3 (Roadmap, отдельный план): domain-регистры в Plugins

Из `multiprocess_prototype_backup/registers/` в `Plugins/<cat>/<name>/registers.py`:
- `camera/schemas.py` → `Plugins/sources/camera_service/registers.py`
- `display/schemas.py` → новый плагин `Plugins/render/display/` (или интеграция в `renderer_compositor`)
- `processor/processings/*.py` (blur, clahe, color_detection) → соответствующие плагины в `Plugins/processing/`
- `processing/schemas.py` → распределить
- `theme/schemas.py` — **остаётся в `multiprocess_prototype/registers/theme/`** (GUI-конфиг, не plugin-настройка)

Каждая миграция — отдельный коммит, проверяется через PluginsTab.

---

## Что взаимодействует и как (карта интеграций)

| Подсистема | Текущее состояние | После Phase 2 |
|------------|-------------------|---------------|
| **Access-level** | API есть (`current_access_level=0` заглушка везде), `effective_access_level` в SchemaTraits, но user_level=0 константа | `ctx.auth.user_level()` прокидывается во все фабрики через `FormBuildingContext`. `effective_access_level` блокирует UI. `on_access_denied` даёт фидбек |
| **Undo/Redo** | `widget.change_signal → tab._on_field_changed → V2ActionBuilder.field_set_timed → ActionBus.execute → FieldSetHandler.apply → RM` | `view.on_changed → presenter → RegisterAdapter.write → ActionBusRegistersManager.set_field_value → V2ActionBuilder.field_set_timed → ActionBus.execute → FieldSetHandler.apply → RM`. Тот же ActionBus, тот же coalescing, тот же undo-stack |
| **Coalescing** (1.5s bucket) | работает | работает (через тот же `V2ActionBuilder.field_set_timed`) |
| **IPC bridge (Phase 12 — runtime worker sync)** | `FieldSetHandler._notify_bridge` отправляет через `router_module` после apply | **работает** (apply вызывается тем же FieldSetHandler через ActionBus); ничего не меняется |
| **Subscribers RM** | `RM._notify_observers` вызывает field-specific и global observers | работает; presenter подписан на RM через `RegisterAdapter.subscribe`, при внешнем write получает `set_value_silent` обновление |
| **state_store_module** | **активно используется** для метрик и состояния worker → GUI; `TopologyBridge.on_state_delta` мостит `state.changed → rm.set_value` для path `processes.*.config.*` | работает; presenter подписан на RM → автоматически получает silent-update от state_store-driven changes |
| **router_module + TopologyBridge** | `FieldSetHandler.apply → bridge.on_field_set → router.send_field_command` с debounce 50ms для slider | работает; наш мост вклинивается ПЕРЕД FieldSetHandler, IPC-отправка сохраняется автоматически |
| **FieldMeta.routing (channel, process_targets, priority)** | `catalog.resolve_field_command` использует для определения target process | работает; никаких изменений в данных регистров не требуется |
| **connection_map.py** | fallback маппинг `plugin → process` если нет `process_targets` в FieldMeta | работает |
| **command_module** | не затрагивается | не затрагивается |
| **PluginContext** | плагины НЕ знают про factory/ActionBus, видят только RM через `ctx.registers` | без изменений; рефакторинг GUI-слоя плагинов не касается |
| **Тема (ThemeVariables)** | живёт в `multiprocess_prototype/registers/theme/`, нет отдельной theme-tab | остаётся как обычный регистр; если добавится theme-tab — использует ту же factory |
| **Touch-keyboard** | недоступен в прототипе (виджеты сырые) | автоматически через `view_config.touch_keyboard=True` в фасадах (per-control) |
| **Audit-middleware** | `ActionBus.add_post_execute_callback` готов, не используется в factory | не меняется; новые контролы НЕ требуют доп. интеграции — post_execute уже ловит все writes через ActionBus |
| **PreAuthGuard** | `ActionBus.set_pre_execute_hook` готов | не меняется; auth-блокировка writes работает на уровне ActionBus, до фабрики не доходит |

**Главное:** ActionBus остаётся центральной точкой записи. Всё, что в нём работало (coalescing, undo, IPC bridge, post-execute audit, pre-execute auth-guard) — продолжит работать. Мост `ActionBusRegistersManager` гарантирует, что framework-фасады попадают в этот же контур.

---

## Критические файлы

**Чтение:**
- `multiprocess_framework/modules/frontend_module/components/{checkbox,spinbox,slider,numeric,group,compound,label}/` — facades + views
- `multiprocess_framework/modules/frontend_module/components/base/{register_adapter,config,interfaces,control_hooks,traits}.py`
- `multiprocess_framework/modules/frontend_module/tests/test_controls_v2_base.py:46-80` — паттерн _FakeRegistersManager
- `multiprocess_framework/modules/actions_module/bus.py` — ActionBus API (execute, record, undo, redo, hooks, callbacks)
- `multiprocess_prototype/frontend/actions/builder.py` — V2ActionBuilder.field_set_timed
- `multiprocess_prototype/frontend/actions/handlers/field_set_handler.py` — apply/revert + _notify_bridge
- `multiprocess_prototype/registers/manager.py` — RegistersManagerV2
- `multiprocess_prototype/registers/field_info.py` — FieldInfo (plugin_name+field_name)
- `multiprocess_prototype/frontend/app_context.py` — AppContext (auth, action_bus, registers_manager)
- `multiprocess_prototype/frontend/widgets/tabs/plugins/tab.py:112-151` — `_on_field_changed`, `_on_bus_changed` (паттерн для replacement)

**Запись (PR1, docs):**
- `docs/refactors/widgets-component-review.md` — новый
- `plans/frontend-widgets-cleanup.md` — отметить [x] 1.1-1.7, добавить 1.8

**Запись (PR2, code):**

Framework:
- `multiprocess_framework/modules/frontend_module/components/checkbox/view.py` — +Signal
- `multiprocess_framework/modules/frontend_module/components/spinbox/view.py` — +Signal
- `multiprocess_framework/modules/frontend_module/components/slider/view.py` — +Signal
- `multiprocess_framework/modules/frontend_module/components/group/view.py` — +Signal
- `multiprocess_framework/modules/frontend_module/components/combo/` — новый пакет (6 файлов)
- `multiprocess_framework/modules/frontend_module/components/__init__.py` — экспорт combo
- `multiprocess_framework/tests/frontend_module/components/test_combo.py` — новый
- `multiprocess_framework/tests/frontend_module/components/test_signals.py` (или отдельные тестовые добавления) — value_changed signals

Prototype:
- `multiprocess_prototype/frontend/actions/action_bus_register_adapter.py` — новый
- `multiprocess_prototype/frontend/actions/__init__.py` — экспорт
- `multiprocess_prototype/frontend/actions/tests/test_action_bus_register_adapter.py` — новый
- `multiprocess_prototype/frontend/forms/factory.py` — переписан
- `multiprocess_prototype/frontend/forms/widgets/color_picker.py` — **удалён**
- `multiprocess_prototype/frontend/forms/widgets/__init__.py` — убран экспорт
- `multiprocess_prototype/frontend/forms/form_builder.py` — form_ctx
- `multiprocess_prototype/frontend/forms/register_view.py` — form_ctx, hooks-driven UI refresh
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py` — form_ctx
- `multiprocess_prototype/frontend/widgets/tabs/plugins/tab.py` — form_ctx
- `multiprocess_prototype/frontend/widgets/tabs/services/tab.py` — form_ctx
- `multiprocess_prototype/frontend/widgets/tabs/settings/system/section.py` — form_ctx
- `multiprocess_prototype/frontend/app_context.py` — convenience-метод `form_building_context()` (опц.)
- `multiprocess_prototype/frontend/forms/tests/test_factory.py` — переписан
- `multiprocess_prototype/frontend/tests/test_action_bus_v2.py` — добавить integration test

---

## Verification

**PR1 (docs only):**
- `docs/refactors/widgets-component-review.md` читается за 5 минут, даёт решение по каждому из 8 компонентов
- В `plans/frontend-widgets-cleanup.md` отмечены 1.1-1.7, добавлен 1.8

**PR2 (code):**
```pwsh
python scripts/validate.py
python scripts/run_framework_tests.py
pytest multiprocess_prototype/frontend/forms/tests/ -v
pytest multiprocess_prototype/frontend/actions/tests/test_action_bus_register_adapter.py -v
pytest multiprocess_framework/tests/frontend_module/components/test_combo.py -v
pytest multiprocess_prototype/frontend/tests/test_action_bus_v2.py -v
make check
make test
python multiprocess_prototype/run.py   # smoke
```

**Smoke checklist (после `run.py`):**
- [ ] Plugins-tab: `robot_control` → форма рендерится через CheckboxControl + SpinBoxControl (visual)
- [ ] Toggle `enabled` (checkbox) → значение в RM меняется (`rm.get_register("robot_control").enabled` == False/True)
- [ ] Ctrl+Z → checkbox откатывается, RM откатывается, view.set_value_silent (без новой записи)
- [ ] Ctrl+Y → значение возвращается
- [ ] Быстрые клики на чекбокс → coalesce_key объединяет в один undo-step (один Ctrl+Z откатывает группу)
- [ ] Spinbox `min_defect_area` out-of-range → `on_write_rejected` → QMessageBox с ошибкой; значение не сохранилось
- [ ] Тестовая правка `access_level=5` в FieldMeta + user_level=0 → поле disabled или показывает `on_access_denied`
- [ ] Pipeline-tab InspectorPanel — форма параметров рендерится framework-виджетами
- [ ] Settings-tab system section — формы работают

**Health gates:**
- `mcp__sentrux__check_rules` — нет новых violations
- `mcp__sentrux__health` — score не упал
- `mcp__sentrux__test_gaps` — coverage по новому `combo/` приемлемое (≥80%)

---

## Известные риски

1. **RegisterAdapter.write возвращает `tuple[bool, str|None]`.** `ActionBusRegistersManager.set_field_value` тоже возвращает `tuple`, но семантика «success» здесь означает «action принят шиной» — фактический результат записи (от `set_field_value` внутри handler) теряется. Митигация: pre_execute_hook возвращает False, если auth/validation отклоняет → `bus.execute` возвращает False → `set_field_value` возвращает `(False, "ActionBus rejected")`. Для отказа на уровне регистра — handler.apply записывает ошибку через `on_write_rejected` callback (через ControlHooks).

2. **`presenter` подписан на RM и получает обновление при write от себя самого** (через `_notify_observers`). Митигация: presenter использует `set_value_silent` (blockSignals), новый Action не создаётся. **Уже работает в существующем `PluginsTab._on_bus_changed`** — тот же паттерн.

3. **`combo/` для `Literal[]` с не-str значениями** (`Literal[1, 2, 3]`) — `ComboBoxView` хранит `str`; нужна конвертация `str ↔ value_type` в ComboBoxPresenter. Решить в Phase 2 (Phase 1.8 review должен это зафиксировать).

4. **Slider vs SpinBox для int** — критерий выбора в Phase 2: если `meta.min` и `meta.max` заданы и `(max - min) ≤ 1000` → slider, иначе spinbox. Уточнить с пользователем после первых тестов (возможно, нужен явный флаг в FieldMeta).

5. **str/str_short/str_long/path — нет framework-аналога.** Остаются сырыми Qt. Отдельная задача в backlog (компонент `text/` или `path/`).

6. **Layer-импорты (`.sentrux/rules.toml`):** `factory.py` (prototype) импортирует `multiprocess_framework.modules.frontend_module.components` — разрешено (prototype → framework). `ActionBusRegistersManager` в prototype — разрешено.

7. **PluginContext.registers — `RegistersManager | None`.** Плагины НЕ должны получать `ActionBusRegistersManager` — он только для UI-слоя. Плагины продолжают писать через `ctx.registers` (REAL_rm), что НЕ попадает в undo. Это корректное поведение: undo — пользовательский (GUI) механизм.

8. **Thread-safety контракт (runtime guard, по итогам ревью).** Subscriber callbacks из `RegistersManager._notify_observers` (`manager.py:183-194`) вызываются **синхронно** в том же потоке, где был вызван `set_field_value`. Контракт: IPC-handler в GUI-процессе диспатчится через Qt event loop (router_module через QueuedConnection или аналог), subscriber-callback всегда в GUI thread → `view.set_value_silent` безопасен. **Закрепляем `assert QThread.currentThread() == QApplication.instance().thread()` в `ActionBusRegistersManager.set_field_value`** (см. псевдокод выше) — runtime guard, который сразу ловит будущие нарушения контракта (например, если кто-то начнёт писать в RM из worker thread). Cost: 2 строки, нулевой overhead в `python -O`.

---

## Отвергнутые альтернативы (по итогам ревью)

**A. Подменить RM глобально на ActionBus-прокси в AppContext.**
Идея: `ctx.registers_manager()` всегда возвращает `ActionBusProxy(real_rm)`, никакой `FormBuildingContext` не нужен. **Отвергнуто:** worker-side writes через `PluginContext.registers` и `TopologyBridge.on_state_delta → rm.set_value` (state_store обратный путь) тоже попали бы через ActionBus → засорили бы undo-стек мусорными worker-driven changes. План чётко разделяет: GUI-writes через мост (с undo), всё остальное через REAL_rm (без undo).

**B. Signal-based binding вместо `adapter.write` (текущая архитектура до рефакторинга).**
Идея: каждый caller-tab сам подписывается на `view.value_committed` и вручную строит action → `ActionBus.execute`. **Отвергнуто:** дублирование логики в N callers; framework-фасады теряют undo-интеграцию «из коробки»; `ControlHooks.on_write_rejected` не имеет информации о причине отказа ActionBus. Мост `ActionBusRegistersManager` инкапсулирует логику write **в одном месте**.

**C. Прямая запись presenter → REAL_rm, в обход ActionBus.**
Идея: пусть presenter пишет в RM напрямую через `RegisterAdapter.write`, а ActionBus подписывается на hooks/observers для undo. **Отвергнуто:** теряется IPC bridge (`FieldSetHandler._notify_bridge` вызывается только в `apply`); coalescing (`V2ActionBuilder.field_set_timed`) требует action, а не post-factum-уведомление; нет валидации через `pre_execute_hook` до записи.
