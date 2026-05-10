# Фаза 10B — GUI: Plugins, Processes, Displays + StateProxy Wiring

**Дата:** 2026-05-07
**Статус:** DRAFT

---

## Контекст

Фаза 10A закрыла инфраструктуру:

- `frontend/forms/` — `CardsFieldFactory` v2, `RegisterView`, `ViewModeToggle`, `ColorTripletWidget`
- `frontend/state/` — `GuiStateBindings` + `match_glob` (подписан на `bridge.set_state_callback`)
- `frontend/prefs/` — `UiPrefsStore` (YAML, атомарная запись)
- `frontend/app_context.py` — `AppContext.registers_manager()`, `plugin_registry()`, `bindings()`
- `frontend/widgets/tabs/settings/` — `SettingsTab` end-to-end (пилот)
- `frontend/app.py` — `PluginRegistry.discover()` + `RegistersManagerV2.from_registry()` при старте

Фаза 10B наполняет ещё три placeholder-таба и подключает живой StateStore:
**Plugins**, **Processes**, **Displays** + **Wiring `state.changed` IPC → `GuiStateBindings`**.

Оставшиеся placeholder (Recipes, Services, Pipeline) → Phase 11+.

---

## Готовые компоненты (используем как есть)

| Компонент | Путь | Что есть |
|---|---|---|
| `RegisterView` + `CardsFieldFactory` | `frontend/forms/register_view.py`, `factory.py` | Авто-генерация форм из `list[FieldInfo]`; Cards/Table; `editors() → dict[str, FieldEditor]` |
| `UiPrefsStore` | `frontend/prefs/store.py` | `get/set` по dotted-ключу, YAML persist |
| `GuiStateBindings` | `frontend/state/bindings.py` | `bind(path, widget, prop)`, `_on_state_msg`; занимает `bridge.set_state_callback` |
| `match_glob` | `frontend/state/glob_match.py` | `*` / `**` матчинг путей |
| `AppContext` | `frontend/app_context.py` | `.registers_manager()`, `.plugin_registry()`, `.bindings()` |
| `RegistersManagerV2` | `registers/manager.py` | `get_fields(plugin_name)`, `get_categories()`, `register_names()` |
| `FieldInfo` / `extract_fields` | `registers/field_info.py` | `plugin_name, field_name, field_type, default, meta, category` |
| `TabFactory` / `LazyTabWidget` | `frontend/tab_factory.py` | `custom_factories={"settings": ...}`; lazy show |
| `DataReceiverBridge` | `frontend/bridge_impl.py` | `dispatch(msg)` → `_state_cb` когда `data_type in ("status", "state_changed", "fps_update")` |
| `GuiStateProxy` (FW) | `multiprocess_framework/…/proxy/gui_state_proxy.py` | Qt-safe `StateProxy`; `on_state_changed` → `invokeMethod` в main thread |
| `StateProxy.subscribe(pattern)` (FW) | `multiprocess_framework/…/proxy/state_proxy.py` | IPC-подписка на `state.changed`; `callback(list[Delta])` |
| `CommandSender` | `frontend/bridge/command_sender.py` | `send_command(target, command, args)` |
| Плагины-source | `plugins/capture/`, `plugins/camera_service/` | `category="source"` |
| Плагины-processing | `plugins/color_mask/`, `plugins/blob_detector/`, `plugins/render_overlay/` и др. | `category="processing"` |
| Плагины-output | `plugins/database/`, `plugins/frame_saver/` | `category="output"` |
| Плагины с registers | `plugins/*/registers.py` (9 штук) | Pydantic-схемы с `FieldMeta` → готовы к `RegisterView` |
| Topology (пример) | `topology/region_pipeline.yaml` | Процессы: camera_0, preprocessor, region_splitter, process_*, stitcher, gui |
| StateStore initial_state | `state/bootstrap.py` | `processes.<name>.state.{status, fps, frame_count, error}` |

---

## Архитектурные решения, зафиксированные перед реализацией

### 1. Паттерн подписки StateProxy в GUI-процессе

**Решение: один широкий паттерн `processes.**`**, подписывается при старте в `app.py`.

Аргументация:
- Подписки `StateProxy` — это IPC-команды `state.subscribe` на сервер (ProcessManager); плодить их много накладно.
- Все пути, интересные GUI в 10B, живут под `processes.**` (FPS, status, latency каждого процесса). Wildcard `**` покрывает текущие пути и любые будущие (plugins, wires) без изменения подписки.
- Фильтрация по конкретному path до нужного виджета выполняется локально в `GuiStateBindings.bind(pattern, ...)` — это дёшево (dict lookup + `match_glob`).
- Альтернатива («несколько точечных паттернов») дала бы более строгий сервер-фильтр, но потребовала бы изменения при каждом новом типе данных. Не оправдано на текущем этапе.

### 2. Где инициализировать StateProxy и подписываться

**Решение: в `frontend/app.py:run_gui()`, после создания `GuiStateBindings`**, через новый хелпер `_setup_state_proxy(process, bindings)`.

- GUI-процесс уже имеет `router_manager` (создан `ProcessModule._init_system_threads()`).
- `StateProxy` должен быть создан в **том же потоке**, что и `GuiStateBindings` (main thread), а router-операции thread-safe.
- Важно: `bridge.dispatch()` классифицирует `data_type in ("status", "state_changed", "fps_update")` → `kind="state"` → `_state_cb`. Но `StateProxy.on_state_changed` принимает сырое IPC-сообщение (`msg["data"]["deltas"]`), а `GuiStateBindings._on_state_msg` ожидает `{"data_type": "state_delta", "path": ..., "value": ...}`. Это **два разных протокола** → нужен адаптер.
- **Решение по протоколу:** `GuiStateProxy` из FW вызывает `_invoke_callbacks(deltas: list[Delta])`. Мы заводим мини-адаптер `_delta_to_bindings(deltas, bindings)`, который для каждой `Delta` формирует `{"data_type": "state_delta", "path": delta.path, "value": delta.new_value}` и вызывает `bindings._on_state_msg(...)` напрямую. Таким образом `GuiStateBindings` по-прежнему не знает о `Delta` и тестируется изолированно.
- `router.register_message_handler("state.changed", proxy.on_state_changed)` регистрируется сразу после создания `proxy`.

### 3. Как карточки Plugins/Displays получают данные

**Решение: `ctx.registers_manager().get_fields(plugin_name)` напрямую в конструкторе таба.**

- `registers_manager` уже готов при старте (`app.py` Task 10A.1). Любой таб получает его через `ctx.registers_manager()`.
- Карточка плагина = `RegisterView(fields)` для полей этого плагина.
- Для реактивного обновления (Processes) — `ctx.bindings().bind(path, widget, prop)`.
- Fallback при пустом `registers_manager` (нет плагинов с registers) → `QLabel("Нет параметров")` вместо пустого `RegisterView`.

### 4. Что делать если плагин не имеет `register_classes` (нет register-файла)

Большинство плагинов (`capture`, `flip`, `grayscale` и т.д.) не имеют `registers.py` — у них нет runtime-параметров. Только 9 плагинов имеют register-файлы.

**Решение:**
- В Plugins-табе показываем карточку для **каждого плагина** (заголовок + категория + описание), но `RegisterView` добавляем только если `get_fields(plugin_name)` возвращает непустой список.
- Если полей нет — вместо `RegisterView` показываем `QLabel("Параметры не настраиваются")`.
- Это честнее для пользователя, чем скрывать такие плагины.

### 5. Wiring: расположение `StateProxy` относительно `GuiStateProxy`

В FW уже есть `GuiStateProxy` (`proxy/gui_state_proxy.py`) — Qt-safe вариант, который через `QMetaObject.invokeMethod` доставляет callbacks в main thread. Однако в 10B мы **не используем `signal_emitter` QObject**: вместо этого callbacks вызываются через `_delta_to_bindings` адаптер. `GuiStateProxy` создаётся с `signal_emitter=None` — это включает fallback-режим прямого вызова, который безопасен, потому что `router.register_message_handler("state.changed", ...)` вызывается из `_data_receiver_loop` (worker thread), а мы уже в main thread через bridge. Более строгий вариант с `signal_emitter` — Phase 11 если понадобится.

---

## Задачи

Зависимости: T1 → T2, T1 → T3, T1 → T4. T2, T3, T4 независимы между собой.
Порядок мёрджа: T1 → T2 → T3 → T4.

---

### Task 10B.1 — StateProxy IPC Wiring → GuiStateBindings

**Уровень:** Senior (Opus, normal thinking) | **Assignee:** teamlead
**Зависит от:** ничего (независим)

**Что получим в итоге (для пользователя):**
GUI-процесс начнёт **живо реагировать на состояние системы**. До этой задачи `GuiStateBindings` подписан на `bridge.set_state_callback`, но bridge никогда не получает `state.changed` (IPC-маршрут не установлен). После — виджеты, привязанные через `bindings.bind(...)`, начинают обновляться в реальном времени при изменении FPS, статуса процесса и т.д.

**Как было в v1 (для сравнения):**
В v1 был polling-bridge `ProcessDataBridge` с таймером на 2 сек, который вытаскивал `ProcessMonitorModel.merged_tree` и вручную обновлял `ProcessTreeView`. Никакого push-механизма, постоянная задержка 2с, хардкод в каждом presenter.

**Files:**
- Modify: `frontend/app.py` — добавить `_setup_state_proxy(process, bindings)`
- Create: `frontend/state/state_proxy_adapter.py` — адаптер `Delta → bindings._on_state_msg`
- Modify: `frontend/state/__init__.py` — экспорт `StateProxyAdapter`
- Create: `frontend/state/tests/test_state_proxy_adapter.py`

**API:**
```python
# frontend/state/state_proxy_adapter.py

from multiprocess_framework.modules.state_store_module.core.delta import Delta, MISSING

class StateProxyAdapter:
    """Адаптирует list[Delta] от StateProxy в GuiStateBindings._on_state_msg.

    Является callback'ом для StateProxy.subscribe(pattern).
    Для каждой Delta формирует state_delta-сообщение и прокидывает
    в GuiStateBindings.

    Удалённые узлы (delta.new_value is MISSING) → пропускаем (нет setter-а для None).
    """
    def __init__(self, bindings: "GuiStateBindings") -> None: ...

    def on_deltas(self, deltas: list[Delta]) -> None:
        """Callback для StateProxy.subscribe. Вызывается в Qt main thread."""
        ...

# frontend/app.py — новая функция (вызывается в run_gui после создания bindings)
def _setup_state_proxy(
    process: "GuiProcess",
    bindings: "GuiStateBindings",
) -> None:
    """Создать StateProxy в GUI-процессе и подписаться на 'processes.**'.

    1. Создать StateProxy(process.name, router=process.router_manager).
    2. Зарегистрировать handler: router.register_message_handler("state.changed", proxy.on_state_changed).
    3. Создать StateProxyAdapter(bindings).
    4. proxy.subscribe("processes.**", adapter.on_deltas, exclude_self=True).
    5. Сохранить ссылку proxy в process._state_proxy (чтобы GC не убил).
    """
    ...
```

**Steps:**
1. Создать `state_proxy_adapter.py`:
   - `__init__(self, bindings)` — сохранить ссылку.
   - `on_deltas(self, deltas: list[Delta])` — для каждой `delta` где `delta.new_value is not MISSING` вызвать `self._bindings._on_state_msg({"data_type": "state_delta", "path": delta.path, "value": delta.new_value})`.
2. В `frontend/app.py` добавить функцию `_setup_state_proxy(process, bindings)`:
   - Импортировать `StateProxy` из FW.
   - Создать `proxy = StateProxy(process.name, router=process.router_manager)`.
   - `proxy.initialize()`.
   - `process.router_manager.register_message_handler("state.changed", proxy.on_state_changed)`.
   - Создать `adapter = StateProxyAdapter(bindings)`.
   - `proxy.subscribe("processes.**", adapter.on_deltas, exclude_self=True)`.
   - Сохранить: `process._state_proxy = proxy`, `process._state_proxy_adapter = adapter`.
3. В `run_gui()` вызвать `_setup_state_proxy(process, bindings)` сразу после создания `bindings`.
4. Обработка ошибок: если `process.router_manager is None` — логировать `logger.warning("StateProxy wiring пропущен: нет router_manager")` и не бросать исключение (GUI должен стартовать без StateStore).

**Acceptance:**
- [ ] Синтетический тест: создать `StateProxyAdapter(mock_bindings)`, вызвать `on_deltas([Delta(path="processes.cam.state.fps", new_value=30)])` → `mock_bindings._on_state_msg` вызван с `{"data_type": "state_delta", "path": "processes.cam.state.fps", "value": 30}`.
- [ ] Delta с `new_value is MISSING` → `_on_state_msg` не вызван (нет None-setter).
- [ ] `_setup_state_proxy` с `router_manager=None` → не падает, логирует warning.
- [ ] GUI стартует без исключений при наличии полноценного StateProxy.

**Tests** (~8, pytest, без Qt):
- `test_adapter_converts_delta_to_msg` — основной сценарий
- `test_adapter_skips_missing_value` — MISSING-дельты
- `test_adapter_multiple_deltas` — пакет из 3 дельт
- `test_adapter_empty_deltas` — пустой список
- `test_setup_no_router_does_not_raise` — `router_manager=None`
- `test_setup_registers_message_handler` — `register_message_handler` вызван
- `test_setup_calls_subscribe` — `proxy.subscribe` вызван с `"processes.**"`
- `test_adapter_stores_bindings_ref` — ссылка сохранена

---

### Task 10B.2 — Plugins Tab

**Уровень:** Middle+ (Sonnet, extended thinking) | **Assignee:** developer
**Зависит от:** —

**Что получим в итоге (для пользователя):**
Таб **Plugins** — сводная страница всех плагинов системы, сгруппированных по категории (`source / processing / output`). Для каждого плагина — карточка с названием, описанием, категорией и, если плагин имеет register-файл, — авто-сгенерированной формой параметров (`RegisterView` с Cards/Table). Карточки прокручиваются. Выбранный режим (Cards/Table) запоминается в `UiPrefsStore`.

Это первый таб, где пользователь видит **все параметры всех плагинов** в одном месте, не зная заранее о конкретных полях.

**Как было в v1 (для сравнения):**
В v1 не было единого Plugins-таба. Параметры `source`-плагинов жили в `SourcesWidget` (отдельный таб), параметры `processing`-плагинов — в `ProcessingPanelWidget` (другой таб). Каждый был написан вручную под конкретный набор параметров. Добавить новый плагин = написать новый виджет.

В v2 — один таб, всё авто-генерируется из `RegistersManagerV2`.

**Files:**
- Create: `frontend/widgets/tabs/plugins/__init__.py`
- Create: `frontend/widgets/tabs/plugins/tab.py` — `PluginsTab(QWidget)`
- Create: `frontend/widgets/tabs/plugins/plugin_card.py` — `PluginCard(QWidget)`
- Create: `frontend/widgets/tabs/plugins/tests/__init__.py`
- Create: `frontend/widgets/tabs/plugins/tests/test_plugins_tab.py`
- Modify: `frontend/app.py` — добавить `"plugins": PluginsTab.create` в `custom_factories`

**API:**
```python
# plugin_card.py

class PluginCard(QWidget):
    """Карточка одного плагина: заголовок + описание + RegisterView (если есть поля).

    Показывает:
      - QLabel с именем плагина (bold, крупнее)
      - QLabel с категорией (цветной badge: source=синий / processing=оранжевый / output=зелёный)
      - QLabel с описанием (из PluginEntry.description)
      - RegisterView(fields) если get_fields(name) непустой
      - QLabel "Параметры не настраиваются" если полей нет

    Args:
        plugin_name: имя плагина в реестре.
        fields: list[FieldInfo] — может быть пустым.
        description: строка описания плагина.
        category: "source" / "processing" / "output" / др.
        initial_mode: ViewMode для RegisterView.
        parent: родительский QWidget.
    """
    def __init__(
        self,
        plugin_name: str,
        fields: list[FieldInfo],
        *,
        description: str = "",
        category: str = "",
        initial_mode: ViewMode = ViewMode.CARDS,
        parent: QWidget | None = None,
    ) -> None: ...

    def editors(self) -> dict[str, FieldEditor]:
        """Editors данного плагина (пусто если нет RegisterView)."""
        ...

    def plugin_name(self) -> str: ...


# tab.py

_CATEGORY_ORDER = ["source", "processing", "output"]

_CATEGORY_TITLES: dict[str, str] = {
    "source":     "Источники",
    "processing": "Обработка",
    "output":     "Вывод",
    "utility":    "Утилиты",
}

class PluginsTab(QWidget):
    """Таб Plugins — карточки всех плагинов по категориям.

    Layout:
        QVBoxLayout
          +-- QHBoxLayout (header)
          |     +-- QLabel "Плагины"
          |     +-- stretch
          +-- QScrollArea
                +-- QVBoxLayout
                      +-- QLabel "Источники" (category header)
                      +-- PluginCard (для каждого source-плагина)
                      +-- QLabel "Обработка"
                      +-- PluginCard ...
                      +-- ...

    Режим отображения (Cards/Table) единый для всех карточек, запоминается
    в UiPrefsStore под ключом "plugins.view_mode".
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None: ...

    @classmethod
    def create(cls, ctx: "AppContext") -> "PluginsTab": ...

    def cards(self) -> list[PluginCard]:
        """Список всех созданных карточек (для тестов)."""
        ...
```

**Steps:**
1. `plugin_card.py` — `PluginCard`:
   - В `__init__` строим `QVBoxLayout`: заголовок (plugin_name bold), цветной badge-лейбл категории, описание.
   - Если `fields` непустой — создаём `RegisterView(fields, initial_mode=initial_mode)` и добавляем; сохраняем `self._view`.
   - Иначе — `QLabel("Параметры не настраиваются")`, `self._view = None`.
   - `editors()` — `self._view.editors() if self._view else {}`.
   - `QFrame` вокруг всего (со `setFrameShape(StyledPanel)`) — визуальный контейнер карточки.
2. `tab.py` — `PluginsTab.__init__`:
   - Прочитать `rm = ctx.registers_manager()`.
   - Прочитать `prefs = UiPrefsStore()`.
   - `initial_mode = ViewMode(prefs.get("plugins.view_mode", "cards"))`.
   - Если `rm is None` → показать `QLabel("Плагины недоступны: registry не инициализирован")`, выйти.
   - `categories = rm.get_categories()` → `dict[category, list[plugin_name]]`.
   - Для каждой категории в `_CATEGORY_ORDER` + оставшихся:
     - Добавить `QLabel(_CATEGORY_TITLES.get(cat, cat))` как заголовок секции.
     - Для каждого `plugin_name` в категории:
       - `fields = rm.get_fields(plugin_name)`.
       - Получить `description` из `ctx.plugin_registry().get(plugin_name).description if registry else ""`.
       - Создать `PluginCard(plugin_name, fields, description=description, category=cat, initial_mode=initial_mode)`.
       - Сохранить в `self._cards`.
   - Обернуть в `QScrollArea`.
   - При изменении режима в любой карточке → sync остальных карточек (`_on_mode_changed`).
   - Изменение режима → `prefs.set("plugins.view_mode", mode.value)`.
3. В `frontend/app.py` добавить `"plugins": PluginsTab.create` в `custom_factories`.

**Acceptance:**
- [ ] При открытии таба — карточки всех плагинов с `register_classes` отображают форму параметров.
- [ ] Плагины без register-файла отображают `"Параметры не настраиваются"`.
- [ ] Группировка по категориям: `"Источники" / "Обработка" / "Вывод"`.
- [ ] Переключение Cards/Table синхронизируется по всем карточкам.
- [ ] Выбранный режим сохраняется в `data/ui_prefs.yaml` и восстанавливается при следующем запуске.
- [ ] `ctx.registers_manager()` is None → таб показывает fallback-сообщение, не падает.
- [ ] `PluginsTab.cards()` возвращает непустой список при наличии плагинов.

**Tests** (~15, pytest + `qtbot`, `monkeypatch UiPrefsStore`):

`PluginCard`:
- `test_card_with_fields_shows_register_view`
- `test_card_without_fields_shows_no_params_label`
- `test_card_has_plugin_name_label`
- `test_card_editors_empty_when_no_fields`
- `test_card_editors_nonempty_when_has_fields`

`PluginsTab`:
- `test_tab_shows_all_registered_plugins`
- `test_tab_groups_by_category`
- `test_tab_no_registry_shows_fallback`
- `test_tab_mode_persists_to_prefs`
- `test_tab_mode_restored_from_prefs`
- `test_tab_mode_sync_across_cards`
- `test_tab_create_factory_method`
- `test_tab_scroll_area_present`
- `test_tab_unknown_category_still_shown`
- `test_tab_plugin_description_in_card`

---

### Task 10B.3 — Processes Tab

**Уровень:** Middle+ (Sonnet, extended thinking) | **Assignee:** developer
**Зависит от:** 10B.1 (StateProxy wiring — без него метрики не обновляются live)

**Что получим в итоге (для пользователя):**
Таб **Processes** — список процессов системы, для каждого — карточка с **живыми метриками**: статус (running/stopped), FPS, количество кадров, ошибки. Метрики обновляются реактивно через `GuiStateBindings` — без таймеров, без polling. Данные приходят из `StateStore` (`processes.<name>.state.*`) через установленный в 10B.1 IPC-канал.

Начальные значения берутся из `state_proxy.get_subtree("processes")` при открытии таба (snapshot на момент открытия), затем `GuiStateBindings` поддерживает их актуальность.

**Как было в v1 (для сравнения):**
В v1 был `ProcessTreeView` + `ProcessDataBridge` с polling каждые 2 секунды. `ProcessMonitorModel` опрашивал дерево процессов через отдельный IPC-канал, merging в единый dict. `ProcessTreeView` рендерил `QTreeWidget` с фиксированными колонками. Задержка 2с, хардкод полей.

В v2 — push-механизм через StateStore, карточки по одному процессу, авто-прунинг мёртвых weakref.

**Files:**
- Create: `frontend/widgets/tabs/processes/__init__.py`
- Create: `frontend/widgets/tabs/processes/tab.py` — `ProcessesTab(QWidget)`
- Create: `frontend/widgets/tabs/processes/process_card.py` — `ProcessCard(QWidget)`
- Create: `frontend/widgets/tabs/processes/tests/__init__.py`
- Create: `frontend/widgets/tabs/processes/tests/test_processes_tab.py`
- Modify: `frontend/app.py` — добавить `"processes": ProcessesTab.create` в `custom_factories`

**API:**
```python
# process_card.py

_STATUS_COLORS: dict[str, str] = {
    "running": "#4CAF50",   # зелёный
    "stopped": "#9E9E9E",   # серый
    "error":   "#F44336",   # красный
}

class ProcessCard(QWidget):
    """Карточка одного процесса с реактивными метриками.

    Отображает:
      - QLabel process_name (bold)
      - QLabel status — цветной (running=зелёный, stopped=серый, error=красный)
      - QLabel fps — "FPS: 0.0"
      - QLabel frame_count — "Кадров: 0"
      - QLabel error — скрыт если None

    Поля обновляются через GuiStateBindings.bind(...).

    Args:
        process_name: имя процесса из topology.
        initial_state: dict из subtree "processes.<name>.state" (snapshot).
        bindings: GuiStateBindings для реактивных подписок.
        parent: родительский QWidget.
    """
    def __init__(
        self,
        process_name: str,
        initial_state: dict,
        bindings: "GuiStateBindings",
        parent: QWidget | None = None,
    ) -> None: ...

    def process_name(self) -> str: ...
    def status_label(self) -> QLabel: ...   # для тестов
    def fps_label(self) -> QLabel: ...      # для тестов


# tab.py

class ProcessesTab(QWidget):
    """Таб Processes — карточки всех процессов с live-метриками.

    Layout:
        QVBoxLayout
          +-- QHBoxLayout (header)
          |     +-- QLabel "Процессы"
          |     +-- stretch
          +-- QScrollArea
                +-- QVBoxLayout
                      +-- ProcessCard (для каждого процесса)

    Список процессов берётся из state_proxy.get_subtree("processes") при открытии.
    Если snapshot пуст — показывается QLabel "Нет активных процессов".
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None: ...

    @classmethod
    def create(cls, ctx: "AppContext") -> "ProcessesTab": ...

    def cards(self) -> list[ProcessCard]: ...
```

**Steps:**
1. `process_card.py` — `ProcessCard.__init__(process_name, initial_state, bindings)`:
   - Создать `QLabel` для каждой метрики: `_status_lbl`, `_fps_lbl`, `_frame_count_lbl`, `_error_lbl`.
   - Установить начальные значения из `initial_state` через прямой `setText`.
   - Подписаться через `bindings.bind(...)`:
     ```
     bindings.bind(f"processes.{process_name}.state.status", _status_lbl, "text")
     bindings.bind(f"processes.{process_name}.state.fps", _fps_lbl, "text",
                   formatter=lambda v: f"FPS: {v:.1f}")
     bindings.bind(f"processes.{process_name}.state.frame_count", _frame_count_lbl, "text",
                   formatter=lambda v: f"Кадров: {v}")
     bindings.bind(f"processes.{process_name}.state.error", _error_lbl, "text",
                   formatter=lambda v: str(v) if v else "")
     ```
   - Цвет `_status_lbl` — устанавливается в `formatter` (или дополнительным `bind` на `styleSheet`).
   - `QFrame` с `StyledPanel` вокруг всей карточки.
2. `tab.py` — `ProcessesTab.__init__`:
   - `bindings = ctx.bindings()`.
   - `process = ctx.process`.
   - `snapshot = {}`: если `process` имеет `_state_proxy` (установлен в 10B.1) — `snapshot = process._state_proxy.get_subtree("processes")`. Иначе — пустой dict.
   - Если `snapshot` пуст → `QLabel("Нет активных процессов")`.
   - Для каждого `(proc_name, proc_data)` в `snapshot.items()`:
     - `initial_state = proc_data.get("state", {})`.
     - Создать `ProcessCard(proc_name, initial_state, bindings)`.
   - Обернуть карточки в `QScrollArea`.
3. В `frontend/app.py` добавить `"processes": ProcessesTab.create` в `custom_factories`.

**Edge cases:**
- `bindings is None` (нет bridge) → `ProcessCard` показывает только initial_state без live-обновлений; не падает.
- `_state_proxy` ещё не установлен (10B.1 не выполнен) → `getattr(process, "_state_proxy", None)` → `snapshot = {}` → placeholder.
- `initial_state.get("fps")` может быть `None` — обернуть setter в `try/except`.

**Acceptance:**
- [ ] Карточки создаются для всех процессов в snapshot.
- [ ] `bindings.bind` вызван для каждой метрики каждого процесса.
- [ ] Синтетический `bindings._on_state_msg({"data_type": "state_delta", "path": "processes.cam.state.fps", "value": 25.3})` → `fps_label.text()` обновился до `"FPS: 25.3"`.
- [ ] `snapshot = {}` → таб показывает `"Нет активных процессов"`, не падает.
- [ ] `bindings=None` → карточки не падают.

**Tests** (~14, pytest + `qtbot`):

`ProcessCard`:
- `test_card_shows_process_name`
- `test_card_initial_values_from_snapshot`
- `test_card_bind_called_for_all_metrics`
- `test_card_fps_formatter`
- `test_card_frame_count_formatter`
- `test_card_bindings_none_no_crash`

`ProcessesTab`:
- `test_tab_creates_cards_for_all_processes`
- `test_tab_empty_snapshot_shows_placeholder`
- `test_tab_no_state_proxy_attr_no_crash`
- `test_tab_live_update_via_bindings`
- `test_tab_create_factory_method`
- `test_tab_scroll_area_present`
- `test_card_status_color_running`
- `test_card_status_color_stopped`

---

### Task 10B.4 — Displays Tab

**Уровень:** Middle (Sonnet, normal thinking) | **Assignee:** developer
**Зависит от:** —

**Что получим в итоге (для пользователя):**
Таб **Displays** — карточки плагинов категории `output` (frame_saver, database и т.п.) с их параметрами через `RegisterView`. По назначению — управление вывода результатов (куда пишем кадры, в какую БД). Структурно — близок к Plugins-табу, но отфильтрован по `category="output"`.

Дополнительно: для плагинов-рендереров (если появятся с `category="display"`) — аналогичная карточка. В 10B `display`-плагинов в коде нет (в topology `gui`-процесс не плагин), поэтому Displays-таб отображает только `output`-плагины. Если реестр пуст — fallback-сообщение.

**Как было в v1 (для сравнения):**
В v1 отдельного Displays-таба не было. Вывод настраивался через `SettingsTab` (секция `Storage`) и `ProcessingPanelWidget` (frame_saver controls). В v2 — явный таб для управления вывода.

**Files:**
- Create: `frontend/widgets/tabs/displays/__init__.py`
- Create: `frontend/widgets/tabs/displays/tab.py` — `DisplaysTab(QWidget)`
- Create: `frontend/widgets/tabs/displays/tests/__init__.py`
- Create: `frontend/widgets/tabs/displays/tests/test_displays_tab.py`
- Modify: `frontend/app.py` — добавить `"displays": DisplaysTab.create` в `custom_factories`

**API:**
```python
# tab.py

_DISPLAY_CATEGORIES = ("output", "display")

class DisplaysTab(QWidget):
    """Таб Displays — карточки output/display плагинов.

    Использует PluginCard из Task 10B.2 напрямую (повторное использование).

    Layout:
        QVBoxLayout
          +-- QHBoxLayout (header)
          |     +-- QLabel "Отображение и вывод"
          |     +-- stretch
          +-- QScrollArea
                +-- QVBoxLayout
                      +-- PluginCard (для каждого output/display плагина)

    Если плагинов нет → QLabel("Плагины вывода не найдены").
    Режим Cards/Table запоминается в UiPrefsStore под ключом "displays.view_mode".
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None: ...

    @classmethod
    def create(cls, ctx: "AppContext") -> "DisplaysTab": ...

    def cards(self) -> list["PluginCard"]: ...
```

**Steps:**
1. Импортировать `PluginCard` из `frontend/widgets/tabs/plugins/plugin_card`.
2. `DisplaysTab.__init__`:
   - `rm = ctx.registers_manager()`.
   - `prefs = UiPrefsStore()`.
   - `initial_mode = ViewMode(prefs.get("displays.view_mode", "cards"))`.
   - Если `rm is None` → fallback-label.
   - `categories = rm.get_categories()`.
   - Отфильтровать плагины: `display_plugins = [name for cat in _DISPLAY_CATEGORIES for name in categories.get(cat, [])]`.
   - Если `display_plugins` пуст → `QLabel("Плагины вывода не найдены")`.
   - Для каждого `plugin_name`: `PluginCard(plugin_name, rm.get_fields(plugin_name), description=..., category=..., initial_mode=initial_mode)`.
   - Обернуть в `QScrollArea`.
   - При изменении режима → `prefs.set("displays.view_mode", mode.value)`.
3. В `frontend/app.py` добавить `"displays": DisplaysTab.create`.

**Acceptance:**
- [ ] Таб отображает карточки для всех плагинов категорий `output` и `display`.
- [ ] Плагины других категорий в таб не попадают.
- [ ] `rm is None` или нет output-плагинов → fallback без краша.
- [ ] `PluginCard` переиспользован, не дублируется.
- [ ] Режим Cards/Table запоминается в `data/ui_prefs.yaml` под ключом `displays.view_mode`.

**Tests** (~10, pytest + `qtbot`):
- `test_tab_shows_output_plugins`
- `test_tab_excludes_source_and_processing`
- `test_tab_no_registry_shows_fallback`
- `test_tab_empty_output_category_shows_fallback`
- `test_tab_mode_persists_to_prefs`
- `test_tab_mode_restored_from_prefs`
- `test_tab_create_factory_method`
- `test_tab_cards_list_correct_length`
- `test_tab_reuses_plugin_card`
- `test_tab_scroll_area_present`

---

## Verification (E2E)

```bash
# Unit-тесты новых пакетов 10B
python scripts/run_framework_tests.py multiprocess_prototype/frontend/state/tests/test_state_proxy_adapter.py
python scripts/run_framework_tests.py multiprocess_prototype/frontend/widgets/tabs/plugins/tests
python scripts/run_framework_tests.py multiprocess_prototype/frontend/widgets/tabs/processes/tests
python scripts/run_framework_tests.py multiprocess_prototype/frontend/widgets/tabs/displays/tests

# Регресс (все тесты фреймворка и прототипа)
python scripts/validate.py
python scripts/run_framework_tests.py

# Ручная проверка
python multiprocess_prototype/run.py
# → открыть таб Plugins
# → убедиться что карточки сгруппированы: Источники / Обработка / Вывод
# → у color_mask, blob_detector, render_overlay — форма с параметрами (HSV sliders и т.п.)
# → у capture, flip, grayscale — "Параметры не настраиваются"
# → переключить Cards ↔ Table — параметры сохранились
# → закрыть, открыть — режим восстановился

# → открыть таб Processes
# → убедиться что карточки есть для всех процессов из topology
# → запустить систему (если доступна камера/симулятор) — FPS обновляется live
# → status=running → зелёный; stopped → серый

# → открыть таб Displays
# → карточки database, frame_saver с их параметрами
# → остальные плагины не отображаются
```

---

## Out of scope (для 10B)

| Что | Фаза |
|---|---|
| Recipes-таб | Phase 11 |
| Services-таб | Phase 12+ |
| Pipeline-таб | Phase 13 |
| Полноценный ColorPicker (HSV-колесо) | `ColorTripletWidget` — заглушка, Phase 11 |
| Отправка изменений Settings/Plugins в runtime через CommandSender | Phase 12 (TopologyBridge) |
| Per-plugin-instance config override из topology | Phase 12 |
| Undo/Redo (ActionBus) | Phase 11 |
| `signal_emitter`-режим `GuiStateProxy` (полный Qt-safe wiring) | Phase 11 |
| Watchdog overlay / сигнализация ошибок в заголовке при падении процесса | Phase 11 |
| `display`-плагины (рендереры/окна OpenCV) | Появятся в Phase 11 вместе с Recipes |

---

## Open follow-up на Phase 11+

1. **CommandSender в Plugins-табе** — кнопка «Применить» отправляет изменённые параметры в соответствующий процесс через `ctx.command_sender.send_command(process_name, "update_register", {field: value})`. Требует TopologyBridge (маппинг plugin_name → process_name из topology).

2. **`from_topology()` overrides в Plugins-табе** — показывать instance-конфиг конкретного запущенного процесса (из topology YAML), а не только defaults register. `RegistersManagerV2.from_topology(topology_dict, plugin_registry)` уже готов.

3. **DisplaysTab: OpenCV-рендереры** — если появятся плагины `category="display"`, карточки Displays-таба автоматически их подхватят (фильтр `_DISPLAY_CATEGORIES` уже включает `"display"`).

4. **ProcessCard: кнопка «Рестарт»** — `ctx.command_sender.send_command("ProcessManager", "restart_process", {"process_name": name})`. UX простой, но требует ProcessManager API.

5. **Полный `GuiStateProxy` с `signal_emitter`** — заменить текущий `StateProxyAdapter` (прямой вызов из worker thread) на `GuiStateProxy(signal_emitter=emitter)` c `QMetaObject.invokeMethod`. Нужно если появятся проблемы с thread-safety при высокой нагрузке (> 100 дельт/сек).

6. **Подписка на `wires.**`** — в Displays/Processes-табе показывать статус IPC-соединений (wire status: pending/connected/error). Источник — `StateStore.wires.*`.

---

## Сводная таблица тестов

| Задача | Тестов |
|---|---|
| 10B.1 — StateProxy Adapter | ~8 |
| 10B.2 — Plugins Tab | ~15 |
| 10B.3 — Processes Tab | ~14 |
| 10B.4 — Displays Tab | ~10 |
| **Итого 10B** | **~47** |
| Накопленные 10A | ~65-70 |
| **Всего Phase 10** | **~112-117** |
