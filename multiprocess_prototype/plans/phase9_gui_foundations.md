# Plan: Phase 9 — GUI Foundations (MainWindow + Система табов)

**Date:** 2026-05-07
**Status:** DONE

## Обзор

Фундамент GUI для Inspector v2: AppContext (DI-контейнер), MainWindow с layout
Header + ImagePanel + TabWidget, TabFactory с ленивой инициализацией, стилевая система
(перенос QSS из v1), рефакторинг app.py. Наполнение табов (Settings, Recipes и пр.) = Phase 10+.

**Что есть в v2 сейчас:**
- `MainWindow` -- минимальный: QTabWidget как centralWidget + StatusBar (fps/latency)
- `CameraView` / `CameraPresenter` -- MVP для отображения BGR-кадров
- `CommandSender` -- обёртка для IPC-команд из GUI
- `DataReceiverBridge` -- мост worker -> Qt main thread (frame/state/command callbacks)
- `app.py` -- хардкодит 3 таба (Camera, Controls, Topology), привязывает bridge, fps timer
- `GuiProcess` -- ProcessModule с Qt event loop, SHM middleware, data_receiver worker

**Что берём из v1 как референс:**
- `MainWindow` (v1) -- layout Header + ImagePanel + TabWidget, Pydantic конфиг, undo/redo
- `AppHeaderWidget` -- BrandLabel, InfoTicker, StatusStrip, ModeToggle, action_triggered signal
- `FrontendAppContext` -- dataclass DI-контейнер (config, registers, recipe, camera, extras)
- `TabWidgetFactory` -- callable фабрика `(widget_key, tab_config) -> QWidget`
- `ThemeManager` (framework) -- QSS hot-reload + CSS-переменные из variables.yaml
- `ImagePanelWidget` (framework) -- N image slots, display_frame/display_frames
- QSS стили: `styles/themes/innotech_theme/` -- 9 модульных файлов + variables.yaml + main.qss

## Порядок выполнения

### Phase 1: Инфраструктура (DI + стили)
- Task 9.1: AppContext v2 [DONE]
- Task 9.2: Стили и ThemeManager [DONE]

### Phase 2: Окно и компоненты
- Task 9.3: MainWindow v2 layout [DONE] (зависит от 9.1, 9.2)
- Task 9.4: ImagePanel (адаптация CameraView) [DONE] (зависит от 9.3)

### Phase 3: Табы и интеграция
- Task 9.5: TabFactory + заглушки табов [DONE] (зависит от 9.1, 9.3)
- Task 9.6: Рефакторинг app.py + интеграция [DONE] (зависит от 9.1-9.5)

---

### Task 9.1 — AppContext v2 (DI-контейнер)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать DI-контейнер для v2 GUI -- единая точка доступа к зависимостям для виджетов и табов
**Context:** В v2 сейчас зависимости передаются напрямую (process._bridge, process._camera_presenter).
В v1 есть `FrontendAppContext` (dataclass) с config, registers, camera, extras.
Для v2 нужен аналог, адаптированный под v2 архитектуру: GuiProcess, CommandSender, DataReceiverBridge, StateStore.

**Files:**
- `multiprocess_prototype/frontend/app_context.py` -- создать
- `multiprocess_prototype/frontend/tests/test_app_context.py` -- создать

**Steps:**
1. Создать `multiprocess_prototype/frontend/app_context.py` с dataclass `AppContext`:
   ```
   @dataclass
   class AppContext:
       process: "GuiProcess"           # ссылка на GuiProcess (TYPE_CHECKING)
       command_sender: CommandSender    # обёртка для IPC-команд
       bridge: DataReceiverBridge       # мост worker->Qt
       config: dict[str, Any]           # конфиг окна (window, header, image_panel, tabs)
       extras: dict[str, Any]           # расширяемый словарь для будущих фаз
   ```
2. Добавить фабрику `build_app_context(process: GuiProcess, config: dict | None = None) -> AppContext`:
   - Создаёт CommandSender(process)
   - Берёт process._bridge (уже создан в _init_application_threads)
   - Возвращает собранный AppContext
3. Добавить метод `get(key, default=None)` для доступа к extras
4. Написать тесты в `test_app_context.py`:
   - Создание с моками (mock GuiProcess, mock bridge)
   - `build_app_context` с mock process
   - Доступ через `get()`
   - Проверить что все поля доступны

**Acceptance criteria:**
- [ ] `AppContext` -- dataclass с полями process, command_sender, bridge, config, extras
- [ ] `build_app_context()` собирает context из GuiProcess
- [ ] Нет глобальных переменных или синглтонов
- [ ] Тесты проходят: `pytest multiprocess_prototype/frontend/tests/test_app_context.py -v`

**Out of scope:** Поля для registers_manager, recipe_manager, state_proxy -- добавятся в Phase 10+.
Не добавлять action_bus, topology_editor -- это v1-специфика.

**Edge cases:** GuiProcess без bridge (ещё не инициализирован) -- build_app_context должен падать с понятной ошибкой.

---

### Task 9.2 — Стили и ThemeManager v2

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Перенести стилевую систему из v1 (QSS + ThemeManager + variables) в v2 для единообразного дизайна
**Context:** В v1 есть зрелая система: `styles/themes/innotech_theme/` с 9 модульными QSS-файлами,
`variables.yaml` с палитрой (30+ переменных), `ThemeManager` (framework) с hot-reload и resolve_qss.
В v2 стилей нет вообще -- виджеты используют inline styles.

**Files:**
- `multiprocess_prototype/frontend/styles/` -- создать директорию
- `multiprocess_prototype/frontend/styles/__init__.py` -- создать
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/main.qss` -- скопировать из v1
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/variables.yaml` -- скопировать из v1
- `multiprocess_prototype/frontend/styles/theme_loader.py` -- создать
- `multiprocess_prototype/frontend/tests/test_theme_loader.py` -- создать

**Steps:**
1. Создать директорию `multiprocess_prototype/frontend/styles/themes/innotech_theme/`
2. Скопировать `main.qss` из v1 `multiprocess_prototype/frontend/styles/themes/innotech_theme/main.qss` (773 строки).
   НЕ копировать модульные файлы (01_base.qss...09_utilities.qss) -- в v2 используем только main.qss,
   потому что модульные файлы дублируют main.qss.
3. Скопировать `variables.yaml` из v1 (палитра, шрифты) без изменений
4. Создать `theme_loader.py`:
   ```python
   from pathlib import Path
   from multiprocess_framework.modules.frontend_module.managers.theme_manager import ThemeManager

   _STYLES_DIR = Path(__file__).resolve().parent

   def create_theme_manager() -> ThemeManager:
       """Создать ThemeManager с путём к v2 styles/."""
       return ThemeManager(_STYLES_DIR)

   def apply_default_theme(app: QApplication) -> None:
       """Применить дефолтную тему innotech_theme к QApplication."""
       tm = create_theme_manager()
       tm.apply_theme("innotech_theme")
   ```
5. Тесты в `test_theme_loader.py`:
   - `create_theme_manager()` возвращает ThemeManager
   - `available_themes()` содержит "innotech_theme"
   - `read_theme("innotech_theme")` возвращает непустую строку
   - `resolve_qss` корректно подставляет переменные

**Acceptance criteria:**
- [ ] `styles/themes/innotech_theme/main.qss` существует и содержит QSS (700+ строк)
- [ ] `variables.yaml` содержит палитру (bg_deep, accent, text_0 и т.д.)
- [ ] `create_theme_manager()` работает
- [ ] `apply_default_theme()` вызывается без ошибок (с mock QApplication)
- [ ] Тесты: `pytest multiprocess_prototype/frontend/tests/test_theme_loader.py -v`

**Out of scope:** Редактор тем в GUI, переключение тем в runtime. Кастомные стили для v2-специфичных виджетов -- добавятся по мере создания табов.

**Dependencies:** Нет

---

### Task 9.3 — MainWindow v2 Layout (Header + ImagePanel + TabWidget)

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Рефакторинг MainWindow из простого QTabWidget в полноценный layout: AppHeader сверху, ImagePanel по центру, TabWidget снизу
**Context:** Текущий v2 MainWindow -- это QTabWidget как centralWidget + StatusBar.
Целевой layout повторяет v1: Header (лого + статус) | ImagePanel (кадры) | TabWidget (табы).
Но v2 MainWindow должен быть проще v1 -- без undo/redo, без side panels, без topology_editor.
Важно: НЕ переносить v1 MainWindow один-к-одному, а создать упрощённую версию для v2.

**Files:**
- `multiprocess_prototype/frontend/windows/main_window.py` -- полный рефакторинг
- `multiprocess_prototype/frontend/windows/config.py` -- создать
- `multiprocess_prototype/frontend/widgets/chrome/__init__.py` -- создать
- `multiprocess_prototype/frontend/widgets/chrome/app_header.py` -- создать
- `multiprocess_prototype/frontend/tests/test_main_window.py` -- создать

**Steps:**
1. Создать `windows/config.py` с Pydantic-конфигами:
   - `WindowConfig(SchemaBase)` -- title, min_width, min_height (аналог v1)
   - `MainWindowConfig(SchemaBase)` -- window: WindowConfig
   Без image_panel config -- ImagePanel задача 9.4
2. Создать `widgets/chrome/app_header.py`:
   - Упрощённый `AppHeaderWidget(QWidget)`:
     - `BrandLabel` -- QLabel с objectName="BrandLabel" (текст "INNOTECH", стилизуется через QSS)
     - `StatusLabel` -- QLabel для статуса системы (fps, статус backend)
     - Layout: [BrandLabel] --- [StatusLabel] --- [пустое место для будущих кнопок]
     - `setObjectName("AppHeader")` для QSS-стилей
     - Сигнал `status_updated(str)` для обновления статуса извне
   - НЕ переносить из v1: ModeToggle, InfoTicker, StatusStrip, HeaderButtonsWidget,
     QPainterPath BrandLabel, connect_action_handlers. Это Phase 10+ задачи.
3. Рефакторинг `windows/main_window.py`:
   - Конструктор: `__init__(self, config: dict | None = None, parent=None)`
   - Layout:
     ```
     QVBoxLayout(central)
     ├── AppHeaderWidget          (фиксированная высота ~60px)
     ├── _image_panel_placeholder (QWidget, stretch=1, заглушка до Task 9.4)
     └── _tab_widget (QTabWidget, для TabFactory из Task 9.5)
     ```
   - Сохранить существующий API (для обратной совместимости с app.py):
     - `add_tab(widget, title) -> int`
     - `update_status(fps, latency_ms)`
     - `increment_frame_count()` / `reset_frame_count()`
   - Добавить новый API:
     - `set_image_panel(widget: QWidget)` -- заменяет placeholder реальным ImagePanel
     - `header` property -- доступ к AppHeaderWidget
   - StatusBar: оставить fps_label + latency_label (как сейчас)
4. Тесты в `test_main_window.py`:
   - Создание MainWindow с конфигом
   - Layout содержит 3 компонента (header, image_placeholder, tab_widget)
   - `add_tab` работает
   - `update_status` обновляет StatusBar
   - `set_image_panel` заменяет placeholder

**Acceptance criteria:**
- [ ] MainWindow отображает 3 зоны: header сверху, центр (placeholder), табы снизу
- [ ] AppHeaderWidget показывает "INNOTECH" и статусную метку
- [ ] objectName="AppHeader" установлен для QSS-стилизации
- [ ] Обратная совместимость: add_tab, update_status, frame_count работают
- [ ] set_image_panel заменяет placeholder
- [ ] Тесты: `pytest multiprocess_prototype/frontend/tests/test_main_window.py -v`

**Out of scope:**
- ModeToggle, InfoTicker, StatusStrip, кнопки переключения окон -- Phase 10+
- Undo/Redo UI -- Phase 10+
- Side panels (CollapsibleSidePanel) -- Phase 10+
- WatchdogOverlay -- Phase 10+

**Edge cases:** config=None -- использовать дефолты из WindowConfig.

**Dependencies:** Task 9.2 (стили применяются к AppHeader через objectName)

---

### Task 9.4 — ImagePanel (адаптация CameraView -> мульти-дисплей)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать ImagePanel -- центральную область отображения кадров, адаптируя CameraView/CameraPresenter под мульти-дисплейную архитектуру
**Context:** В v2 есть CameraView (один QLabel для одного потока).
В v1 есть ImagePanelWidget (framework) с N слотами.
Целевая архитектура Phase 9: ImagePanel показывает один или несколько дисплеев.
Таб "Displays" (Phase 10+) будет управлять ImagePanel.
Сейчас нужен рабочий ImagePanel с хотя бы одним дисплеем.

**Files:**
- `multiprocess_prototype/frontend/widgets/image_panel/__init__.py` -- создать
- `multiprocess_prototype/frontend/widgets/image_panel/widget.py` -- создать
- `multiprocess_prototype/frontend/widgets/image_panel/display_slot.py` -- создать
- `multiprocess_prototype/frontend/widgets/image_panel/presenter.py` -- создать
- `multiprocess_prototype/frontend/tests/test_image_panel.py` -- создать

**Steps:**
1. Создать `display_slot.py` -- `DisplaySlot(QWidget)`:
   - Переиспользует логику CameraView: QLabel + placeholder + масштабирование
   - `slot_id: str` -- идентификатор слота
   - `update_pixmap(pixmap: QPixmap)` -- показать кадр
   - `set_placeholder(text: str)` -- показать текст
   - `resizeEvent` -- перемасштабирование
   - objectName="ImageSlot" для QSS-стилей
2. Создать `presenter.py` -- `ImagePanelPresenter`:
   - Управляет N DisplaySlot
   - `on_frame(slot_id: str, frame: np.ndarray)` -- конвертация BGR->QPixmap, вызов slot.update_pixmap
   - `on_frames(frames: dict[str, np.ndarray])` -- несколько кадров за раз
   - Переиспользует логику CameraPresenter (BGR->RGB->QImage->QPixmap)
3. Создать `widget.py` -- `ImagePanelWidget(QWidget)`:
   - Конструктор: `__init__(self, slots: list[dict] | None = None)`:
     - По умолчанию 1 слот: `[{"id": "main", "label": "Main"}]`
   - Layout: QHBoxLayout с DisplaySlot'ами
   - `presenter` property -- доступ к ImagePanelPresenter
   - `add_slot(slot_id, label) -> DisplaySlot`
   - `remove_slot(slot_id)`
   - `display_frame(slot_id, frame)` -- делегирует presenter
   - `display_frames(frames_dict)` -- делегирует presenter
4. Интегрировать в MainWindow:
   - В Task 9.6 (app.py) -- создать ImagePanelWidget и вызвать `window.set_image_panel(image_panel)`
   - Подключить bridge frame callback к `image_panel.display_frame("main", frame)`
5. Тесты в `test_image_panel.py`:
   - Создание с дефолтным конфигом (1 слот)
   - Создание с кастомным конфигом (2 слота)
   - add_slot / remove_slot
   - display_frame с mock frame (numpy array)
   - Placeholder при None frame

**Acceptance criteria:**
- [ ] ImagePanelWidget отображает N слотов в горизонтальном layout
- [ ] DisplaySlot масштабирует кадры с сохранением пропорций
- [ ] ImagePanelPresenter конвертирует BGR numpy -> QPixmap
- [ ] add_slot / remove_slot динамически меняют количество дисплеев
- [ ] objectName="ImageSlot" на каждом слоте для QSS
- [ ] Тесты: `pytest multiprocess_prototype/frontend/tests/test_image_panel.py -v`

**Out of scope:**
- Управление слотами из GUI (таб Displays) -- Phase 10+
- Grid/PIP layout -- Phase 10+
- Привязка слотов к pipeline выходам -- Phase 10+
- Crosshair overlay, bbox overlay -- Phase 10+

**Edge cases:**
- remove_slot для несуществующего id -- игнорировать с warning
- display_frame для несуществующего slot_id -- игнорировать с warning
- frame = None -> показать placeholder

**Dependencies:** Task 9.3 (MainWindow с set_image_panel)

---

### Task 9.5 — TabFactory + заглушки табов

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Создать TabFactory -- фабрику табов с ленивой инициализацией и заглушками для будущих фаз
**Context:** В v2 app.py хардкодит 3 таба. В v1 TabWidgetFactory -- callable `(widget_key, tab_config) -> QWidget`.
Целевые табы v2 (Phase 9 = заглушки):
  1. Settings -- администрирование
  2. Recipes -- пресеты/рецепты
  3. Processes -- управление процессами
  4. Services -- тяжёлые интеграции
  5. Plugins -- лёгкие обработки
  6. Pipeline -- визуальный конструктор
  7. Displays -- управление дисплеями

**Files:**
- `multiprocess_prototype/frontend/tab_factory.py` -- создать
- `multiprocess_prototype/frontend/widgets/tabs/__init__.py` -- создать
- `multiprocess_prototype/frontend/widgets/tabs/placeholder.py` -- создать
- `multiprocess_prototype/frontend/tests/test_tab_factory.py` -- создать

**Steps:**
1. Создать `widgets/tabs/placeholder.py` -- `PlaceholderTab(QWidget)`:
   - Конструктор: `__init__(self, tab_id: str, title: str, description: str = "")`
   - Layout: центрированный QLabel с текстом "{title}\n\n{description}\n\n(Phase 10+)"
   - Стиль: тёмный фон, серый текст, font-size 14px
   - Нужен для табов, которые ещё не реализованы
2. Создать `tab_factory.py`:
   ```python
   TAB_ORDER = [
       {"id": "settings",  "title": "Settings",  "description": "Администрирование, конфиг системы"},
       {"id": "recipes",   "title": "Recipes",   "description": "Пресеты/рецепты обработки"},
       {"id": "processes", "title": "Processes", "description": "Управление процессами"},
       {"id": "services",  "title": "Services",  "description": "Камеры SDK, БД, робот, нейронки"},
       {"id": "plugins",   "title": "Plugins",   "description": "Обработка изображений, мосты"},
       {"id": "pipeline",  "title": "Pipeline",  "description": "Визуальный конструктор цепочек"},
       {"id": "displays",  "title": "Displays",  "description": "Управление экранами вывода"},
   ]
   ```
   - `TabFactory`:
     - Конструктор: `__init__(self, ctx: AppContext, custom_factories: dict[str, Callable] | None = None)`
     - `custom_factories`: dict `{tab_id: callable(ctx) -> QWidget}` для override заглушек реальными виджетами
     - `create_tabs(tab_widget: QTabWidget)`: итерирует TAB_ORDER, для каждого:
       - Если есть custom_factory -- вызвать его
       - Иначе -- создать PlaceholderTab
       - Добавить в tab_widget через addTab
     - `create_tab(tab_id: str) -> QWidget`: создать один таб (для ленивой загрузки)
   - Ленивая инициализация: wrapper `LazyTabWidget(QWidget)`:
     - При первом showEvent -- вызывает factory и заменяет содержимое
     - До showEvent -- показывает "Loading..."
3. Тесты в `test_tab_factory.py`:
   - TabFactory создаёт 7 табов-заглушек
   - custom_factories override работает (передать mock для "settings")
   - LazyTabWidget вызывает factory при первом show
   - Порядок табов соответствует TAB_ORDER

**Acceptance criteria:**
- [ ] TabFactory.create_tabs добавляет 7 табов в QTabWidget
- [ ] Порядок: Settings -> Recipes -> Processes -> Services -> Plugins -> Pipeline -> Displays
- [ ] Каждый таб -- PlaceholderTab с описанием
- [ ] custom_factories позволяет заменить любой таб реальным виджетом
- [ ] LazyTabWidget откладывает создание до первого показа
- [ ] Тесты: `pytest multiprocess_prototype/frontend/tests/test_tab_factory.py -v`

**Out of scope:**
- Реализация содержимого табов -- Phase 10+
- Настраиваемый порядок/видимость табов из конфига -- Phase 10+
- Иконки табов -- Phase 10+

**Edge cases:**
- custom_factory возвращает None -- использовать PlaceholderTab
- custom_factory выбрасывает исключение -- логировать, использовать PlaceholderTab

**Dependencies:** Task 9.1 (AppContext передаётся в TabFactory)

---

### Task 9.6 — Рефакторинг app.py + интеграция

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Рефакторинг app.py: убрать хардкод, использовать AppContext + MainWindow v2 + TabFactory + ImagePanel + ThemeManager
**Context:** Текущий app.py вручную создаёт виджеты, связывает bridge, запускает таймеры.
После Tasks 9.1-9.5 все компоненты готовы -- нужно собрать их в app.py.

**Files:**
- `multiprocess_prototype/frontend/app.py` -- полный рефакторинг
- `multiprocess_prototype/frontend/tests/test_app_integration.py` -- создать (опционально)

**Steps:**
1. Рефакторинг `run_gui(process: GuiProcess)`:
   ```python
   def run_gui(process: "GuiProcess") -> None:
       app = QApplication.instance() or QApplication(sys.argv)

       # 1. Применить тему
       from .styles.theme_loader import apply_default_theme
       apply_default_theme(app)

       # 2. Создать AppContext
       from .app_context import build_app_context
       ctx = build_app_context(process)

       # 3. Создать MainWindow
       from .windows.main_window import MainWindow
       window = MainWindow(config=ctx.config)

       # 4. Создать и установить ImagePanel
       from .widgets.image_panel import ImagePanelWidget
       image_panel = ImagePanelWidget()
       window.set_image_panel(image_panel)

       # 5. Создать TabFactory и заполнить табы
       from .tab_factory import TabFactory
       tab_factory = TabFactory(ctx)
       tab_factory.create_tabs(window._tab_widget)  # или через публичный API

       # 6. Подключить bridge callbacks
       _setup_bridge_callbacks(process, image_panel, window)

       # 7. Запустить таймеры (fps, safety)
       _setup_timers(app, process, window)

       # 8. Сохранить ссылки в process
       process._window = window
       process._app_context = ctx

       window.show()
       app.exec()
   ```
2. Вынести логику в helper-функции:
   - `_setup_bridge_callbacks(process, image_panel, window)`:
     - frame callback -> `image_panel.display_frame("main", frame)`
     - state callback -> будущее (пока noop или ProcessStatusWidget если оставляем)
   - `_setup_timers(app, process, window)`:
     - fps_timer (1 сек, обновляет StatusBar)
     - safety_timer (1 сек, проверяет stop flag)
3. Удалить хардкод:
   - Удалить прямое создание CameraView, CameraPresenter, CommandPanel, ProcessStatusWidget
   - Удалить прямое создание TopologyEditorWidget
   - Удалить ручное создание Controls таба
4. Сохранить обратную совместимость:
   - `process._window` -- ссылка на MainWindow
   - `process._bridge` -- используется внутри run_gui
   - `app.aboutToQuit` -> `process._stop_requested = True`

**Acceptance criteria:**
- [ ] app.py использует AppContext, MainWindow v2, TabFactory, ImagePanel, ThemeManager
- [ ] Нет хардкодных виджетов (CameraView, CommandPanel, ProcessStatusWidget)
- [ ] Тема применяется при старте
- [ ] 7 табов-заглушек отображаются в правильном порядке
- [ ] ImagePanel показывает кадры через bridge callback
- [ ] FPS таймер обновляет StatusBar
- [ ] Safety таймер проверяет stop flag
- [ ] `app.aboutToQuit` корректно сигнализирует об остановке

**Out of scope:**
- ProcessStatusWidget (state callback) -- будет интегрирован в таб Processes (Phase 10+)
- TopologyEditorWidget -- будет частью таба Pipeline (Phase 10+)
- Реальное наполнение табов

**Edge cases:**
- process._bridge не существует -- build_app_context должен бросить AttributeError с понятным сообщением
- QApplication уже существует (второй вызов run_gui) -- использовать instance()

**Dependencies:** Tasks 9.1, 9.2, 9.3, 9.4, 9.5

---

## Риски и ограничения

1. **Совместимость с GuiProcess:** run_gui вызывается из GuiProcess.run(). Рефакторинг app.py
   не должен ломать GuiProcess -- process._bridge должен быть уже инициализирован к моменту вызова.
2. **QSS из v1:** main.qss содержит @-переменные. ThemeManager.resolve_qss подставляет значения
   из variables.yaml. Если variables.yaml неполный -- неподставленные переменные останутся как есть
   (безопасный fallback в ThemeManager).
3. **ImagePanel vs CameraView:** CameraView/CameraPresenter НЕ удаляются из кодовой базы --
   они могут использоваться в тестах. Но app.py перестаёт их использовать напрямую.
4. **Phase 10+ зависимости:** TabFactory с custom_factories позволяет постепенно заменять
   PlaceholderTab реальными виджетами без изменения app.py.
