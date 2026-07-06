# План разбиения трёх god-файлов

> Приложение к [`2026-07-03_review-and-constructor-plan.md`](2026-07-03_review-and-constructor-plan.md) (волна F / W6).
> Подготовлено агентом-проектировщиком по полному чтению трёх файлов (2026-07-03); факты о подписках
> и утечках перепроверены вручную по коду. Все пути — относительно корня репозитория.

---

## 0. Предварительное условие: teardown подписок (чинить ДО первого разреза)

**Факт (проверен по коду):** `presenter.py:167` и `presenter.py:177` подписываются на EventBus (`TopologyReplaced`, `RecipeActivated`) и сохраняют `_Subscription`-хэндлы, но **ни в presenter.py, ни в tab.py нет ни одного вызова `unsubscribe()` / `dispose()`** (grep по tab.py — teardown отсутствует; `event_bus.py:107-119` возвращает `_Subscription` — context-manager для auto-unsubscribe, т.е. механизм есть, он просто не используется). Failure scenario: пересоздание вкладки Pipeline (или пересоздание presenter в тестах) оставляет мёртвый presenter в списке handler'ов EventBus → каждый `TopologyReplaced` дёргает `_on_topology_replaced` зомби-объекта, который трогает разрушенную Qt-сцену (`RuntimeError: Internal C++ object already deleted`) + утечка объекта. Вторая утечка рядом: `presenter.py:986` — `QTimer()` без parent, никогда не останавливается.

**Шаг 0 (до split):**
```python
# presenter.py
def dispose(self) -> None:
    self._topology_sub.unsubscribe()
    self._recipe_activated_sub.unsubscribe()
    if self._persist_timer is not None:
        self._persist_timer.stop()
    self._scene = None
```
Вызов — из `PipelineTab` (closeEvent/деструктор вкладки). Тест: создать presenter на fake-EventBus, `dispose()`, опубликовать `TopologyReplaced` — handler не вызван. Это обязательный шаг, потому что после split подписки переедут в core-presenter, а lifetime новых объектов (LayoutController с QTimer) должен закрываться тем же `dispose()`.

Аналогично в inspector: `inspector_panel.py:496-507` (`_hide_camera_actual`) отписка есть, но она вызывается только при смене ноды/clear — при разрушении панели с активной camera-нодой хэндлы `_bindings.bind(...)` (строки 525-571) остаются живыми. При split camera-секции завести `dispose()` и там.

---

## 1. `pipeline/presenter.py` (1828 LOC) → 6 модулей + core

### Кластеры (с точными границами)

**A. Graph↔blueprint codec (W6, одобрен) — строки 55-83, 1251-1532:**
`_NODE_SUBTITLE_PARAM`, `_plugin_config_value`, `_node_subtitle` (55-83), `_topology_to_graph` (1251), `_unique_plugin_node_id` (1384), `_node_position` (1404), `_endpoint_to_node_id` (1432), `_build_display_nodes` (1455), `_resolve_display_name` (1519), `_blueprint_to_graph` (1529).

→ **`pipeline/graph_codec.py`** (чистый, без Qt):

```python
@dataclass(frozen=True)
class GraphViewState:          # snapshot GUI-состояния, вход codec'а
    gui_positions: Mapping[str, tuple[float, float]]
    locked_nodes: frozenset[str]
    placed_display_ids: frozenset[str]

@dataclass
class GraphBuildResult:
    nodes: list[NodeData]
    edges: list[EdgeData]
    display_nodes: list[DisplayNodeData]
    port_schemas: dict[str, list[PortSchema]]

class TopologyGraphCodec:
    def __init__(self, plugins: PluginCatalog, displays: DisplayCatalog): ...
    def topology_to_graph(self, topo: dict, view: GraphViewState) -> GraphBuildResult: ...
```

**Ключевая предпосылка:** `NodeData` сейчас объявлен в `graph/node_item.py`, который импортирует PySide6 (node_item.py:7-8) — «тестируем без Qt» не выйдет, пока dataclass'ы живут рядом с QGraphicsItem. **Шаг 1a: вынести `NodeData`/`EdgeData`/`DisplayNodeData`/`PortSchema` в новый чистый `graph/data.py`** (re-export из старых мест для совместимости). Только после этого codec действительно импортируется headless.

Побочные эффекты, которые codec НЕ должен делать (сейчас делает): запись в `self._port_schemas_cache`/`self._display_nodes_cache` (1269-1270), warning-лог о дубликатах. Кэши уходят в `GraphBuildResult`; presenter кладёт результат в свои поля. `next_fallback_index` (1464) — локальная переменная, переносится как есть.

Обратное направление (`graph_to_blueprint`) уже в `pipeline/io.py` (216 LOC) — codec и io.py объединить логически: round-trip тест `topology_to_graph → graph_to_blueprint ≈ identity` станет главным контрактом.

**B. Layout-персист и позиции — строки 922-1019, 958 (`_PERSIST_DEBOUNCE_MS`), 1128-1197:**
`on_node_moved`, `set_node_lock`, `toggle_node_lock`, `_sync_positions_from_scene`, `_schedule_layout_persist`, `_persist_layout_to_recipe`, `auto_layout_scene`.

→ **`pipeline/layout_controller.py`**:
```python
class LayoutController:
    def __init__(self, recipes: RecipeStore, scene_provider: Callable[[], GraphScene | None]): ...
    gui_positions: dict[str, tuple[float, float]]   # владелец состояния
    locked_nodes: set[str]
    def on_node_moved(...); def set_lock(...); def snapshot(self) -> GraphViewState
    def auto_layout(self, topo: dict, placed_display_ids: set[str]) -> None
    def dispose(self) -> None                        # stop QTimer
```
Владение `_gui_positions`/`_locked_nodes` переходит сюда целиком — codec получает их через `snapshot()`. Это разрывает самую плотную связку файла (позиции читаются/пишутся из 9 мест).

**C. Валидация wire-портов — строки 777-920 (`_validate_wire_ports`):**
→ **`pipeline/wire_validation.py`** — чистая функция:
```python
@dataclass
class WireValidation:
    ok: bool
    reason: str = ""
    src_dtype: str = ""; tgt_dtype: str = ""

def validate_wire(source: str, target: str, catalog: PluginCatalog) -> WireValidation: ...
```
QMessageBox (906-917) остаётся в presenter/tab как реакция на `not ok`. Тестируется без Qt (единственный Qt-импорт там — локальный, ради MessageBox).

**D. Мутации через domain dispatch — строки 205-425, 522-775:**
`_on_inspector_field_changed`, `_on_target_process_changed`, `_on_display_id_changed`, `_on_move_to_process_requested`, `_delete_command_for`, `add_process_from_plugin`, `remove_selected`, `add_wire`, `place_display`.

→ **`pipeline/mutations.py`** (`PipelineMutations`): зависимости — `services.commands`, `services.plugins`, `PipelineModel` (read), callbacks `report(msg)` и `is_suppressed()`. Самый связанный кластер (все ходят в `self._model` + `dispatch` + `_report`), поэтому режется одним куском. `place_display`/`remove_selected` дополнительно трогают `placed_display_ids` и перерисовку — этот кусок GUI-состояния (`_placed_display_ids`) оставить в core-presenter, а mutations сообщает результат через return-значения (`RemoveResult(had_pure_unbound, dispatched)`), core решает про explicit reload.

**E. Runtime-контроль живого backend — строки 1610-1814:**
`launch_active_recipe`, `_on_recipe_launch_result`, `restart_topology`, `control_process`, `_notify_status`.

→ **`pipeline/runtime_control.py`** (`RuntimeController(pm_proxy, recipes, model_provider, notify)`). Ни одной связи с scene/positions — режется безболезненно первым из «крупных». `_on_recipe_launch_result` (1685-1713) — чистый разбор dict-ответа, отдельно тестируем таблицей случаев (полный PM-ответ / транспортная ошибка / rollback).

**F. Персист рецепта/файлов — строки 458-516, 1207-1231, 1538-1604:**
`load_topology_from_config`, `load_topology_from_file`, `export_topology_with_positions`, `save_topology_to_file`, `compute_active_recipe_diff`, `save_to_active_recipe`, `get_yaml_preview` → **`pipeline/recipe_io.py`** (или расширить существующий `io.py`). QMessageBox'ы из `save_to_active_recipe` (1554-1603) поднять в tab: функция возвращает `SaveResult(ok, error)`.

**Core-presenter (остаётся ~350-450 LOC):** конструктор/DI, `set_scene`/`set_inspector`, `_block_signals`/`is_suppressed`, `_report`, подписки EventBus + `dispose()`, `_on_topology_replaced`/`_on_recipe_activated`, `_capture_selection`/`_restore_selection`, `load_scene_with_ports`, `_placed_display_ids`, legacy `add_process`/`remove_process`.

### Порядок разреза (presenter)

1. **Шаг 0** — `dispose()` + вызов из tab (см. выше).
2. **Шаг 1a** — `graph/data.py`: чистые dataclass'ы, re-export.
3. **Шаг 1b** — характеризационные тесты codec'а на ТЕКУЩЕМ `_topology_to_graph` (через presenter с fake-services, headless): см. список ниже.
4. **Шаг 2 (W6)** — вынести codec; presenter делегирует. Тесты из 1b переключить на `TopologyGraphCodec` — должны пройти без правок ожиданий.
5. **Шаг 3** — `wire_validation.py` (маленький, чистый).
6. **Шаг 4** — `runtime_control.py` (нет связей с остальным).
7. **Шаг 5** — `layout_controller.py` (владение позициями; самый рискованный — после него полный ручной прогон drag/lock/автосейва).
8. **Шаг 6** — `recipe_io.py`, затем `mutations.py`.

### Характеризационные тесты ДО разреза (codec)

Fixtures — topology-dict'ы, ожидания — snapshot списков NodeData/EdgeData/display_nodes/port_schemas:
- процесс с 1 плагином; с цепочкой 3 плагинов (implicit edges 1355-1358);
- процесс без плагинов → fallback-нода `plugin_index=-1` (1288-1306);
- `protected: true` → нода не рисуется (1276-1279);
- дубликат `plugin_name` в одном процессе → суффикс `#i`, первое вхождение без суффикса (1384-1402);
- wires с endpoint `proc.plugin.port`, endpoint без plugin-сегмента, endpoint на процесс без плагинов (1431-1453);
- displays: fan-in (2 источника → 1 бокс), binding без `display_id` (skip, 1476-1477), fallback-позиции с инкрементом (1482-1486);
- placed-but-unbound: id в `placed_display_ids`, но не в topo → бокс дорисован; id в обоих → дедуп (1505-1515);
- приоритет позиций: node_id в gui_positions > anchor процесса > дефолтный кластер (1421-1429);
- locked_nodes → `NodeData.locked=True`;
- subtitle: `color_convert` c `mode` в плоском и вложенном config (61-83);
- round-trip с `io.graph_to_blueprint`.

Для mutations — тесты уже частично есть в `pipeline/tests/`; добавить: `remove_selected` смешанный кейс (process + pure-unbound бокс, порядок «process первым») — фиксирует поведение ФИКСА #2 (574-599).

---

## 2. `frontend/forms/factory.py` (1191 LOC) → пакет `forms/factory/`

### Кластеры

**A. Резолвер kind (чистый, без Qt-виджетов)** — строки 39-178: `_UNDEFINED_TYPES`, `_is_undefined`, `_safe_default` (195), `_unwrap_optional`, `_is_tuple_3int`, kind-константы, `_WIDGET_TO_KIND`, `_resolve_kind`.
→ **`forms/factory/kinds.py`**. Публичный API: `resolve_kind(field_info) -> str`, константы `KIND_*`, `safe_default`, `unwrap_optional`. Тестируется полностью без Qt.

**B. Legacy-builders (raw Qt-виджеты)** — legacy-ветки `_build_bool` (215-226), `_build_literal` (503-520), `_build_color3` (537-562), `_build_int` (584-621), `_build_float` (694-734), `_build_str_short` (746-764), `_build_str_long` (828-842), `_build_path` (909-921), `_build_unsupported` (1067-1085), `_make_label` (186).
→ **`forms/factory/builders_legacy.py`**.

**C. Binding-aware builders (FW-компоненты + FormContext)** — `_build_bool_binding_aware` (229), `_build_int_binding_aware` (278), `_build_slider_binding_aware` (330), `_build_color3_binding_aware` (382), `_build_literal_binding_aware` (444), `_build_float_binding_aware` (624), `_build_str_short_binding_aware` (767), `_build_str_long_binding_aware` (845), `_build_path_binding_aware` (924).
→ **`forms/factory/builders_binding.py`**. Внутри — общий хелпер: код чтения old_value из RM (`_on_editing_finished`, дословно повторён 3 раза: 789-802, 866-878, 942-954) → одна функция `_rm_old_value(form_ctx, register, field) -> str` + `_connect_commit_write(...)`. Это устраняет тройную копию с одинаковым `except (AttributeError, KeyError, TypeError)`.

**D. JSON-редактор** — строки 974-1064: `_JsonTextEdit`, `_json_dumps`, `_set_json_error`, `_build_json` → **`forms/factory/json_editor.py`**. `_json_dumps` и parse-логика getter'а — отдельно тестируемы (кэш последнего валидного значения — ключевой контракт, строки 1031-1046).

**E. Реестр + фасад** — `_BUILDERS` (1092) + `CardsFieldFactory` (1111-1190) → остаётся в **`forms/factory/__init__.py`** (re-export `CardsFieldFactory`, чтобы `from ...forms.factory import CardsFieldFactory` в `inspector_panel.py:1007` не сломался).

**Ключевой рефакторинг реестра:** сейчас `create()` (1144-1171) — восемь ручных `if kind == X and builder is _build_x` проверок, где identity-check ловит переопределение через `register_type`. Заменить на реестр пар:
```python
@dataclass
class KindBuilders:
    legacy: Builder
    binding: Builder | None = None   # None → legacy даже при form_ctx

_REGISTRY: dict[str, KindBuilders] = {...}
```
`create()` сводится к 5 строкам; `register_type(key, builder)` пишет `KindBuilders(legacy=builder)` — семантика «переопределённый builder не получает form_ctx» сохраняется и становится явной.

### Порядок разреза (factory)

1. Характеризационные тесты (до любых правок):
   - `resolve_kind` — таблица: `bool` (до int!), `Optional[int]`, `Literal`, `tuple[int,int,int]`, `str` с default>120 символов → `str_long`, `Path`, `list`/`dict[str,int]`, `meta.widget="slider"`, неизвестный `meta.widget` → type-fallback, `model_picker` без builder'а → unsupported;
   - для каждого legacy-builder'а (pytest-qt): create → тип widget, `getter()` == default, `setter(v)` → `getter()`, наличие/отсутствие `change_signal`;
   - для binding-aware: с fake FormContext — что `change_signal is None` (контракт «не дублировать write», комментарии 264-267) и что commit (editingFinished/committed) зовёт `form_ctx.write` ровно один раз;
   - JSON: невалидный текст → getter возвращает прежнее валидное значение + красная рамка; пустой текст → прежнее значение; roundtrip setter/getter;
   - `register_type("int", custom)` → `create` вызывает custom БЕЗ form_ctx (identity-контракт).
2. Вырезать `kinds.py` (без Qt — нулевой риск).
3. Превратить factory.py в пакет, вынести D (json), затем B и C, ввести `KindBuilders`-реестр последним шагом (тест из п.1 про register_type — гейт).

Порядок безопасен: модуль без состояния (кроме `_BUILDERS`), один QThread, внешних подписок нет.

---

## 3. `pipeline/inspector/inspector_panel.py` (1152 LOC) → секции-виджеты

Панель — классический «form of forms»: 5 независимых секций, каждая со своим состоянием и (частично) подписками. Резать по образцу уже выделенной `IoDebugSection` (io_debug_section.py — прецедент в том же пакете: `set_bindings`/`set_target`/`clear_target`).

### Кластеры

**A. Camera actual telemetry** — строки 306-327 (UI), 496-571 (`_hide_camera_actual`/`_show_camera_actual`), поле `_cam_actual_handles`, `_cam_res`.
→ **`inspector/cam_actual_section.py`**:
```python
class CamActualSection(QWidget):
    def set_bindings(self, bindings) -> None
    def show_for(self, process_name: str) -> None   # bind 6 путей state store
    def hide_and_unbind(self) -> None               # teardown хэндлов
```
Подписки `bindings.bind(...)` и их unbind инкапсулируются здесь; `hide_and_unbind` вызывается и из `dispose()` секции. Внимание при переносе: замыкание `_res_update` (552-560) мутирует `self._cam_res` — состояние переезжает внутрь секции. Молчаливый `except Exception: pass` на unbind (502-503) при переносе сузить до реального типа.

**B. Exec-info блок** — строки 183-187 (UI), 656-712 (`_worker_for_plugin`, `_populate_exec_info`, `_clear_exec_info`).
→ **`inspector/exec_info_section.py`**. `_worker_for_plugin` — чистая функция форматирования, вынести на module-level (`worker_label(category, name, step, total) -> str`) — тестируется без Qt.

**C. Селекторы процессов/воркеров/display** — строки 198-284 (UI combo), 718-971 (populate + handlers + `_get_process_names_from_recipe`, `_get_display_entries`, `_get_workers_for_process`, `_DisplayEntry` (37)).
Два модуля:
- **`inspector/selectors_data.py`** (без Qt): `process_names_from_recipe(recipes) -> list[str]` (сейчас 803-842), `display_entries(displays) -> list[DisplayEntry]` (844-863), `workers_for_process(topology, name) -> list[str]` (925-941). Чистые функции над services-протоколами — юнит-тесты на fake-store без Qt.
- **`inspector/process_selector_section.py`** (QWidget): move_process combo + worker combo + lock-кнопки + bypass-чекбокс (строки 198-254, 340-368, 889-971), сигналы `move_to_process_requested`, `worker_selected`, `lock_set`, `bypass_toggled`. Свой локальный `_suppress` — убирает хрупкий паттерн двойного входа в `self._suppress_changes = True` внутри уже-подавленного `show_plugin_node` (409 и 448-454: вложенный `finally` на 454 сбрасывает флаг в False, «внешний» finally на 490 спасает, но это ловушка при любом рефакторинге — с локальными флагами секций она исчезает).
- target_process combo + display combo (261-284, 718-797, 869-887) — туда же или отдельный `display_selector_section.py`; они мелкие, допустимо оставить парой в одном файле.

**D. Форма параметров плагина** — строки 297-301 (UI), 977-1039 (`_try_build_cards_editors`), 1070-1077 (`_build_lineedit_editors`), 1107-1152 (`_on_field_edited`, `_on_field_editor_changed`, `_clear_params`), поле `_field_editors`.
→ **`inspector/params_form_section.py`**:
```python
class ParamsFormSection(QWidget):
    field_changed = Signal(str, object)   # (field_name, value); process добавляет panel
    def build(self, plugin_name: str, params: dict | None, registers_manager, plugins_header: list) -> bool
    def clear(self) -> None               # disconnect change_signal'ов + deleteLater
    def insert_top_widget(self, w: QWidget) -> None   # для hikvision-встройки
```
Teardown сигналов (1126-1145) — внутренняя ответственность секции.

**E. Hikvision-встройка** — строки 1041-1068 (`_embed_hikvision_controls`, поля `_hik_controller`/`_hik_runner`).
→ **`inspector/hikvision_embed.py`**: `create_hikvision_widget(services, command_sender, topology_bridge) -> tuple[QWidget, controller, runner]`. Панель хранит только ссылки; сброс — в `ParamsFormSection.clear()` как сейчас (1143-1145).

**Panel остаётся (~300-350 LOC):** сигналы, `set_services` (раздаёт зависимости секциям), `_init_ui` (композиция секций), `show_plugin_node`/`show_display_node`/`show_node` как оркестраторы («какие секции видимы + какие данные передать»), `clear`, properties `current_process`/`current_plugin_index`.

### Порядок разреза (inspector)

1. Характеризационные тесты (pytest-qt, до правок):
   - `show_plugin_node` → title/badge/видимость форм (target_process_form видима только при непустом списке процессов — 440-442), `current_plugin_index` проброшен;
   - `show_display_node` → display-combo видим, exec-info скрыт, io-debug спит;
   - смена ноды camera→не-camera → все `_cam_actual_handles` отвязаны (fake-bindings считает bind/unbind, баланс = 0);
   - `_populate_move_worker_combo` preselect по `assigned_worker` из params (450-452);
   - выбор воркера → `field_changed("proc", "assigned_worker", w)` один раз, при `_suppress_changes` — ноль;
   - `clear()` после cards-режима → `_field_editors` пуст, повторный `show_plugin_node` не даёт дублей строк;
   - `refresh_display_combo` в plugin-режиме — no-op;
   - чистые: `worker_label`, `process_names_from_recipe` (blueprint отсутствует/не dict/объекты вместо dict), `workers_for_process` (вставка `message_processor`).
2. Вырезать чистые `selectors_data.py` + `worker_label` (без Qt).
3. `CamActualSection` (там подписки — сразу с `dispose`, самый ценный по надёжности).
4. `ParamsFormSection` + `hikvision_embed.py`.
5. `ProcessSelectorSection` (+ display selector), убрать вложенные `_suppress_changes`-манипуляции.
6. `ExecInfoSection` последним (тривиален).

---

## Зависимости новых модулей (сводно)

```
graph/data.py            ← ничего (чистые dataclass'ы)
pipeline/graph_codec.py  ← graph/data, PluginCatalog, DisplayCatalog     (без Qt)
pipeline/wire_validation.py ← PluginCatalog, framework port               (без Qt)
pipeline/layout_controller.py ← RecipeStore, QTimer, scene (протокол)
pipeline/mutations.py    ← services.commands/plugins, PipelineModel, wire_validation
pipeline/runtime_control.py ← pm_proxy, RecipeStore, io.graph_to_blueprint
pipeline/recipe_io.py    ← RecipeStore, io.py, layout_controller.snapshot
presenter.py (core)      ← всё выше + EventBus (единственный владелец подписок, dispose)

forms/factory/kinds.py   ← FieldInfo                                      (без Qt)
forms/factory/builders_legacy.py  ← kinds, PySide6, field_editor
forms/factory/builders_binding.py ← kinds, FW components, FormContext
forms/factory/json_editor.py      ← PySide6
forms/factory/__init__.py         ← реестр KindBuilders + фасад CardsFieldFactory

inspector/selectors_data.py ← services-протоколы                          (без Qt)
inspector/{cam_actual,exec_info,process_selector,params_form}_section.py ← PySide6
inspector/hikvision_embed.py ← services tab hikvision controller, RequestRunner
inspector_panel.py (core)    ← секции (композиция, сигналы наружу без изменений)
```

Внешние контракты, которые нельзя менять при split: сигналы `NodeInspectorPanel` (field_changed и др. — их слушает presenter.py:199-203), `CardsFieldFactory.create/register_type/resolve_kind`, публичные методы presenter, вызываемые из tab.py (`load_scene_with_ports`, `wire_metrics_model`, `model`, `save_to_active_recipe`, `auto_layout_scene` и др.).

Попутные находки, релевантные split: (1) отсутствие teardown EventBus-подписок presenter — presenter.py:167,177, известный класс проблем (category="known-issue", M-leak-*), но конкретно эти две подписки нигде не отписываются; (2) QTimer-утечка presenter.py:986; (3) тройное дублирование RM-old-value кода в factory.py:789-802/866-878/942-954; (4) хрупкий вложенный `_suppress_changes` в inspector_panel.py:448-454.
