# Plan: Полировка архитектуры виджетов на пилотном Checkbox

**Slug:** widgets-arch-polish
**Дата:** 2026-05-15
**Ветка:** refactor/widgets-arch-polish
**Родительский план:** [`plans/frontend-widgets-cleanup-phase2.md`](frontend-widgets-cleanup-phase2.md) (Phase 2.0 завершён, эта работа — между 2.0 и 2.1)
**Принцип:** **только упрощения**. Каждая задача снимает слой/дубликат, не добавляет новых.

---

## Зачем

Phase 2.0 закрыл пилот: `pilot_widgets.enabled` пишется через CheckboxControl → ActionBusRegistersManager → ActionBus → FieldSetHandler → RM + IPC. Архитектура **работает**, но в ней есть боли, которые сейчас изолированы на одном виджете, а после Phase 2.1-2.7 (расширение на spinbox/slider/numeric/combo/color3) **разойдутся в 8 местах**.

Сделать **сейчас** правильную модель на пилоте → потом тиражировать на остальные builders **без переделки контракта**. Иначе — потом будет в 8 раз дороже.

---

## Принципы

1. **Упрощение, не усложнение.** Каждая задача = снять слой/дубликат. Если нельзя — не делаем.
2. **Пилот:** все правки и smoke только на `CheckboxControl` + `pilot_widgets`. Остальные builders (int/float/literal/color3/...) не трогаем.
3. **Multi-target — проверка, не реализация.** Инфраструктура уже есть (`FieldRouting.process_targets` + dispatch). Нужен только regression-тест.
4. **UI-only без плагина — out of scope.** Заложим только если естественно ляжет в API; форсировать не будем.
5. **Один коммит — одна задача.** Чекбоксы в этом плане = коммиты.

---

## Целевая архитектура (что должно получиться)

### До (текущее состояние)

```python
# Caller:
form_ctx = FormBuildingContext(rm, bus, V2ActionBuilder, access_level)
bus_rm = ActionBusRegistersManager(rm, bus, V2ActionBuilder)  # ← прокси-мост
binding = BindingConfig("pilot_widgets", "enabled")
hooks = ControlHooks(on_write_rejected=..., on_access_denied=...)
result = CheckboxControl.create(bus_rm, binding, view_config,
                                 current_access_level=access_level,
                                 hooks=hooks)

# Резолв виджета:
# - FieldMeta.WidgetType (Literal) ← один источник правды
# - factory._resolve_kind widget_to_kind dict ← дублирует
# - FieldInfo обёртка над pydantic FieldInfo ← дублирует
```

### После

```python
# Caller:
form_ctx = ctx.form_context()  # один объект: rm + bus + builder + access + hooks_factory
result = CheckboxControl.create(form_ctx, binding=("pilot_widgets", "enabled"), view_config=...)

# Резолв виджета:
# - FieldMeta.widget — единственный источник
# - factory читает meta.widget напрямую, без своего dict
# - SchemaBase / FieldMeta достаточно, FieldInfo растворён
```

**Слои write (не меняются по смыслу, но без прокси-моста):**
```
view → presenter → form_ctx.write(binding, value)
  → V2ActionBuilder.field_set_timed
  → ActionBus.execute
  → FieldSetHandler.apply → rm.set_field_value + bridge.on_field_set (fan-out по process_targets)
```

**Что было — что стало:**

| Артефакт | До | После |
|----------|----|----|
| Маппинг widget→kind | 2 места | 1 (FieldMeta.widget) |
| Контексты для write | 4 (FormBuildingContext, BindingConfig, ControlHooks, AccessContext) | 1 (FormContext, binding — tuple/dataclass-arg) |
| Прокси-RM | ActionBusRegistersManager ~60 LOC | удалён, bus передаётся явно |
| FieldInfo | отдельный класс | property на SchemaBase / FieldMeta |
| RegistersManager | FW + V2 в прототипе | единый в FW |
| Legacy в _build_bool | dual-mode | один путь |

---

## Задачи (порядок исполнения)

### 0. Discovery — РЕЗУЛЬТАТЫ (2026-05-15, без коммита)

**Реальные числа callers** (Grep):

| Артефакт | Файлов | Решение |
|----------|--------|---------|
| `FormBuildingContext` | **6** (prototype) | F: заменяем на `FormContext` — реалистично |
| `BindingConfig` | **41** (FW core: 8 фасадов + presenters + tests + examples) | F: **НЕ трогаем сигнатуру**. Остаётся Pydantic SchemaBase. Расширения tuple → не делаем (blast radius огромный) |
| `FieldInfo` (prototype, обёртка с plugin_name+field_name) | **19** (вкл. тесты) | D: **НЕ растворяем**. Это не дубликат pydantic FieldInfo, а binding context для UI factory (отдельная ответственность). Опционально переименование в `FieldBinding` — отложено в backlog (косметика, не упрощение) |
| `ControlHooks` | **18** (FW) | F: **НЕ трогаем**. Остаётся как dataclass хуков; будет полем `FormContext.hooks_factory` |
| `ActionBusRegistersManager` | **5** (3 кода + 1 тест + 1 коммент в FW) | E: **удаляем**, blast radius малый ✓ |
| `RegistersManagerV2` | **9** (вкл. тесты) | G: поднимаем функционал во FW как **замена** старого `RegistersManager` (по уточнению пользователя) |
| Multi-target fan-out в TopologyBridge | **НЕТ** | B: **реализовать** (`resolve_field_command` возвращает один `process_name` — пилот broadcast'а сейчас НЕ работает) |

**Ключевые факты:**
- **B (multi-target) — это РЕАЛИЗАЦИЯ, не только smoke.** [`CommandCatalog.resolve_field_command`](multiprocess_prototype/frontend/bridge/command_catalog.py#L147) возвращает `ResolvedCommand(process_name=...)` — один target. `TopologyBridge.on_field_set` шлёт `sender.send_field_command(resolved.process_name, ...)` — один send. Хотя `FieldRouting.process_targets: tuple[str,...]` есть в схеме и framework-dispatcher умеет, GUI-мост это игнорирует. Нужна правка `ResolvedCommand` → `process_names: tuple[str, ...]` + цикл в `on_field_set`.
- **D исключаем из плана.** [`FieldInfo`](multiprocess_prototype/registers/field_info.py) — 81 LOC, простой dataclass с `@property title/min_value/max_value/unit`. Это **полезная абстракция**, не дубликат. Растворение в SchemaBase усложнило бы, а не упростило. Имя путается с `pydantic.FieldInfo` — это **косметика**, не архитектура.
- **BindingConfig оставляем как есть.** Это [Pydantic SchemaBase](multiprocess_framework/modules/frontend_module/components/base/config.py#L49) с дополнительными полями (`access_level`, `index`), поддерживает позиционные args. Tuple ничего не упростил бы при 41 caller.
- **Прототип = данные, FW = механизмы (уточнение пользователя).** `FormContext` создаём СРАЗУ в `multiprocess_framework/modules/frontend_module/`, не в прототипе. RegistersManagerV2 → FW. ActionBus уже в FW. В прототипе остаются: `AppContext` (composition root), регистры плагинов (через `Plugins/`), `TopologyBridge` (пока, постепенно).

**Финальный набор задач после Discovery: A, F, E, B, G, H (D исключён).**

---

### A. Единый widget mapping — `FieldMeta.widget` как единственный источник

**Сейчас:** [`FieldMeta.WidgetType`](multiprocess_framework/modules/data_schema_module/core/field_meta.py#L45) — Literal с 14 вариантами; [`factory._resolve_kind`](multiprocess_prototype/frontend/forms/factory.py#L136) — `widget_to_kind` dict, дублирует маппинг (combo↔literal, spinbox↔int, numeric↔float).

**Делаем:**
- [x] Внести нормализацию алиасов в `FieldMeta.__init__` (combo→literal, spinbox→int, numeric→float). После нормализации `meta.widget` хранит каноническое имя kind'а. — `09191e3`
- [x] `factory._resolve_kind`: dict упрощён, алиасы удалены, на модульном уровне. — `09191e3`
- [x] Удалить алиасы из `widget_to_kind` dict (combo/spinbox/numeric). — `09191e3`
- [x] 5 regression-тестов на нормализацию в `test_field_meta.py` + 1 в `test_factory.py`. — `09191e3`
- [x] Все 19 `test_factory.py` зелёные; 89 `test_field_meta.py` зелёные; 2643 framework-тестов зелёные. — `09191e3`

**Коммит:** `09191e3 refactor(factory): FieldMeta.widget — единственный источник widget→kind` (LOC: +76/−21, рост за счёт тестов; production-код нейтрально).

**Reviewer (Opus) APPROVED** с backlog-замечанием: docstring `FieldMeta` не описывает параметр `widget` — техдолг, не регрессия.

**Слоёв убрали:** дубликат маппинга.

---

### F. Единый `FormContext` (фундамент для остальных правок)

**Сейчас:** при создании виджета caller собирает 4 объекта:
- `FormBuildingContext(rm, bus, builder, access_level)` — для factory (6 callers)
- `BindingConfig(plugin_name, field_name)` — для facade (41 caller, **не трогаем**, передаётся отдельно)
- `ControlHooks(on_write_rejected, on_access_denied, ...)` — для facade (18 callers, **не трогаем**, fabricируется из FormContext)
- `AccessContext(level, ...)` — для AccessTrait (передаётся внутри FormContext)

**Делаем:**
- [x] Спроектировать `FormContext` (один dataclass) в **`multiprocess_framework/modules/frontend_module/forms/form_context.py`** (учитываем "FW = механизмы"):
  ```python
  @dataclass(frozen=True)
  class FormContext:
      registers_manager: RegistersManagerV2
      action_bus: ActionBus
      action_builder: type[V2ActionBuilder]
      access_level: int = 0
      on_write_rejected: Callable[[str], None] | None = None
      on_access_denied: Callable[[str], None] | None = None
  ```
- [x] Метод `AppContext.form_context() -> FormContext` (заменяет текущий `form_building_context()`).
- [x] `CardsFieldFactory.create(field_info, form_ctx, parent=None)` — `form_ctx: FormContext`.
- [x] `BindingConfig` оставляем как идентификатор поля (plugin, field) — внутри фасадов. Caller передаёт `binding=("pilot_widgets", "enabled")` (или объект — решить в Discovery).
- [x] Обновить пилот `_build_bool_binding_aware` под новый `FormContext`.
- [x] Удалить `FormBuildingContext` (старый dataclass).
- [x] Тесты: переписать 3 form_ctx-теста в `test_factory.py` под новое имя; остальные 15 не трогаем.

**Коммит:** `fe25d12 refactor(forms): FormContext в framework — единый контекст вместо FormBuildingContext`

**Слоёв убрали:** 3 контекста сливаются в один.

---

### E. ActionBus как явная зависимость фасадов — удалить `ActionBusRegistersManager`

**Сейчас:** [`ActionBusRegistersManager`](multiprocess_prototype/frontend/actions/action_bus_register_adapter.py) — прокси-RM (~60 LOC), который превращает `rm.set_field_value(...)` в `bus.execute(field_set_action)`. Существует только потому, что framework-фасады принимают `RegistersManagerLike` и не знают про ActionBus.

**Делаем:**
- [x] Расширить framework-фасад: `CheckboxControl.create(..., form_ctx=...)` kwarg.
  - Если `form_ctx` передан → presenter пишет через `form_ctx.write(register, field, new, old)` (ActionBus + coalescing + undo/redo).
  - Если `form_ctx=None` (legacy для unit-тестов framework без ActionBus) → старый путь через `SyncTrait.write` → `RegisterAdapter` → `rm.set_field_value`.
- [x] Helper `FormContext.write(register_name, field_name, new_value, old_value) -> bool` с thread-guard и on_write_rejected hook.
- [x] Thread-guard (`QThread.currentThread() != app.thread()`) — в `FormContext.write`.
- [x] Удалён `multiprocess_prototype/frontend/actions/action_bus_register_adapter.py` (160 LOC) + его тесты (300 LOC), экспорт в `__init__.py`.
- [x] 5 тестов `FormContext.write` в FW (`test_form_context_write.py`): write/undo/reject/exception/no-callback.

**Коммит:** `refactor(actions): FormContext.write — явный ActionBus, удалён прокси-мост`

**Слоёв убрали:** -1 слой (60 LOC), на ровном месте.

**Риск:** изменение публичного API framework-фасадов. Но пока используется только в одном месте (`_build_bool_binding_aware`) — миграция дешёвая.

---

### ~~D. Растворить FieldInfo~~ — **ИСКЛЮЧЕНО ПОСЛЕ DISCOVERY**

**Причина:** [`FieldInfo`](multiprocess_prototype/registers/field_info.py) — 81 LOC простого frozen dataclass с binding context (plugin_name + field_name + type + default + ref на meta + property title/min_value/max_value/unit). Это **не дубликат** `pydantic.FieldInfo`, а отдельная ответственность — UI binding view. 19 callers. Растворение усложнило бы, не упростило.

**Альтернатива (опционально, backlog):** переименование `FieldInfo` → `FieldBinding` для устранения путаницы имён с `pydantic.FieldInfo`. Косметический рефакторинг, не упрощение архитектуры.

---

### G. `RegistersManagerV2` **заменяет** `RegistersManager` в framework

**Уточнение пользователя:** V2 функционал не "поднимается" — он **становится единственным** `RegistersManager`. Прототип хранит только данные (`AppContext`, регистры плагинов).

**Делаем:**
- [x] Сравнить `multiprocess_prototype/registers/manager.py` (V2) и `multiprocess_framework/modules/registers_module/manager.py` (FW). V2 добавляет: `from_registry()`, `from_topology()`, `get_fields()`, `plugin_categories`, `_fields_cache`.
- [x] Перенести `from_registry()` + `get_fields()` + `get_categories()` + `set_value()` + `validate()` + `plugin_categories` + `_fields_cache` в FW `RegistersManager`.
- [x] Перенести `FieldInfo` + `extract_fields` в FW `registers_module/core/field_info.py`. Прототипный `field_info.py` стал re-export обёрткой (0 callers сломано).
- [x] `from_topology()` — превращён в `build_rm_from_topology()` функцию в прототипе.
- [x] Удалён `RegistersManagerV2` класс. Все импорты `RegistersManagerV2` → `RegistersManager` (mass rename, 12 файлов).
- [x] Layer rules: `from_registry()` принимает `registry: Any` с duck-typing Protocol `_PluginRegistryLike` — FW не импортирует Plugins/process_module.
- [x] Тесты: 2664 FW passed (46 в test_manager), 1234 prototype passed, 4 build_rm_from_topology passed.

**Коммит:** `refactor(registers): V2 функционал поглощён framework RegistersManager`

**Слоёв убрали:** один класс-обёртка (V2 как класс исчезает).

---

### B. Multi-target fan-out — РЕАЛИЗАЦИЯ + smoke (по итогам Discovery)

**Discovery findings:** инфраструктура `FieldRouting.process_targets` есть в FW (8 тестов в `test_dispatch_routing.py`), но **`TopologyBridge.on_field_set` НЕ делает fan-out** — [`CommandCatalog.resolve_field_command`](multiprocess_prototype/frontend/bridge/command_catalog.py#L147) возвращает `ResolvedCommand(process_name=...)` (один target). GUI-мост шлёт только в один процесс. Это **разрыв контракта** — схема обещает multi-target, мост не выполняет.

**Делаем:**
- [x] Расширить `ResolvedCommand`: `process_names: tuple[str, ...]` вместо `process_name: str` (alias `process_name` для backward-compat ← deprecated).
- [x] `CommandCatalog.resolve_field_command` — читать `FieldRouting.process_targets` из meta. Если `process_targets` непусто → `process_names=process_targets`; иначе → `(pc.process_name,)` (current behaviour для single-target).
- [x] `TopologyBridge.on_field_set` — цикл `for proc in resolved.process_names: sender.send_field_command(proc, ...)`. Возвращаемое значение — `True` если **все** отправки успешны.
- [x] Регрессионный тест: `pilot_widgets.broadcast_flag` (новое поле с `process_targets=("pilot_a","pilot_b")`) → `bridge.on_field_set` → 2 вызова `sender.send_field_command`.
- [x] Добавить поле `broadcast_flag` в `Plugins/utility/pilot_widgets/registers.py` (опциональное, для smoke).
- [ ] Smoke (manual): toggle через GUI → 2 IPC-сообщения в логах router_module.

**Коммит:** `feat(bridge): multi-target fan-out по FieldRouting.process_targets`

**Слоёв убрали:** ноль, но закрыли архитектурный gap (схема обещает, мост не выполнял).

---

### H. Удалить legacy путь в `_build_bool` — **DEFERRED → Phase 2.6**

**Обоснование переноса (2026-05-15):** `_build_bool` сейчас `if form_ctx is not None → binding-aware, else → QCheckBox legacy`. Legacy ветка используется **5+ callers** в прототипе, которые НЕ имеют ActionBus/plugin binding:
- `InspectorPanel` (pipeline tab — inspector params)
- `ServicesTab` (services config)
- `SettingsSystem section` (GUI theme/settings)
- `form_builder` (generic form builder)
- yaml_io / другие

Эти callers — не plugin-формы; они рисуют конфиги без binding на регистры плагинов. Удаление legacy пути сломает их.

**Условие активации Task H:** после перевода всех 5+ callers на FormContext (это Phase 2.1-2.6 — миграция оставшихся builders на framework-фасады).

**Что НЕ блокируется:** B (multi-target) и G (RM merge) не зависят от H — продолжаем без H.

**Не отменено, только отложено.**

---

## Acceptance (вся фаза)

- [ ] **Один контекст** для создания виджета: `ctx.form_context()` → `FormContext`
- [ ] **Один источник** widget→kind: `FieldMeta.widget` (с нормализацией алиасов)
- [ ] **Прокси-мост удалён**, ActionBus передаётся явно
- [ ] `FieldInfo` либо read-only view, либо растворён
- [ ] `RegistersManager` единый, без V2-wrapper
- [DEFERRED] Legacy путь в `_build_bool` удалён → Phase 2.6 (после миграции остальных callers)
- [ ] Multi-target fan-out verified тестом
- [ ] **Линии кода:** должно стать **меньше**, не больше (delta LOC < 0)
- [ ] `python scripts/validate.py`, `python scripts/run_framework_tests.py`, factory-tests — зелёные
- [ ] `mcp__sentrux__check_rules` — нет новых violations
- [ ] `mcp__sentrux__health` — score не упал
- [ ] Smoke: `pilot_widgets.enabled` toggle → undo/redo работает; IPC уходит worker'у
- [ ] **Контракт готов к Phase 2.1**: для добавления SpinBoxControl достаточно `_build_int(..., form_ctx)` без других правок инфраструктуры

---

## Out of scope (в этом плане НЕ делаем)

- **Расширение на остальные builders** (int/float/literal/color3/...) — это Phase 2.1-2.7
- **UI-only компоненты без плагина** — backlog, реализуем когда появится реальный use-case (тулбар, dialog с GUI-state)
- **Component Design System / стилизация** — DEFERRED (см. [memory](docs/claude/memory/project_component_scoped_styles.md))
- **Touch-keyboard, telemetry, audit middleware** — это надстройки, работают как есть через ActionBus

---

## Метрика «упростили ли»

После закрытия плана — `git diff main..HEAD --shortstat` должен показать:
- LOC: **delete > add** (упрощение)
- Удалённые файлы: `action_bus_register_adapter.py` + его тесты + `FormBuildingContext` dataclass
- Новые файлы: `form_context.py` (один)
- Контексты в factory call site: 4 → 1
- Classes-обёрток: `RegistersManagerV2` → удалён или alias

Если delta LOC > 0 (стало больше) — что-то усложнили, остановиться и пересмотреть.

---

## Verification

```pwsh
python scripts/validate.py
python scripts/run_framework_tests.py
pytest multiprocess_prototype/frontend/forms/tests/ -v
pytest multiprocess_framework/modules/registers_module/tests/test_dispatch_routing.py -v
make check
make test
python multiprocess_prototype/run.py   # smoke pilot_widgets
```

**Smoke checklist:**
- [ ] `pilot_widgets` рендерится (все 12 полей)
- [ ] Toggle `enabled` (checkbox) → значение в RM меняется, undo/redo работают
- [ ] `broadcast_flag` (multi-target) → 2 IPC-сообщения в логах
- [ ] `admin_only` (access_level=5) с user_level=0 → UI disabled

---

## Карта зависимостей задач (после Discovery)

```
0 (Discovery — DONE)
├─ A (independent, простой) ────────────────┐
├─ G (independent, mass rename) ────────────┤
├─ B (independent, отдельный слой bridge) ──┤
└─ F (фундамент: FormContext в FW)          │
   └─ E (после F: фасады принимают FormContext, удаляем ActionBusRegistersManager)
      └─ H (после E: legacy в _build_bool удалён, form_ctx обязательный)
```

**Параллельные потоки** (можно запускать через /pipeline независимо):
- Поток 1: **A** (быстро, изолированно)
- Поток 2: **G** (mass rename, изолированно — кроме layer rules)
- Поток 3: **B** (bridge fan-out, изолированно)
- Поток 4: **F → E → H** (последовательный блок)

**Реалистичная оценка после Discovery:** 6 коммитов, ~3-4 рабочих дня.

D исключена, multi-target оказался реализацией (не verify) → нетто-сложность примерно та же.
