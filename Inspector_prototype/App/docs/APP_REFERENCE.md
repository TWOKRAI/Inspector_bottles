# App Inspector — Справочник для AI и разработчиков

**Версия:** 1.0  
**Назначение:** Быстрая навигация по кодовой базе, классы и ответственности  
**Аудитория:** AI-ассистенты, новые разработчики, code review

---

## 1. Обзор архитектуры

### 1.1 Слои (сверху вниз)

| Слой | Путь | Роль |
|------|------|------|
| **UI (4)** | `App/UI/` | Окна, виджеты, компоненты — только отображение и сигналы |
| **Application (3)** | `App/Core/Application/` | Coordinator, WindowManager, ThreadManager — оркестрация |
| **Domain (2)** | `App/Core/Domain/`, `App/Core/Managers/` | RegistersManager, DataManager — бизнес-логика и состояние |
| **Core/Infra (1)** | `multiprocess_framework` | IPC, очереди, shared memory |

**Правило:** Сигналы вниз, данные вверх. UI не знает про IPC, Domain не знает про Qt.

### 1.2 Точка входа

```
main_app.py → main()
    → QueueManager, stop_event (инфраструктура)
    → ApplicationCoordinator(queue_manager, stop_event, config_path)
    → coordinator.initialize()  # Config → Domain → IPC → App
    → coordinator.run()        # ThreadManager.start_all() → WindowManager.show_initial_window() → QApplication.exec_()
```

---

## 2. Ключевые файлы по назначению

### 2.1 Entry & Coordinator

| Файл | Класс/Функция | Ответственность |
|------|---------------|-----------------|
| `main_app.py` | `main()` | Создание QueueManager, Coordinator, signal handlers, запуск |
| `main_app.py` | `run_with_context()` | Контекстный менеджер для тестов |
| `Core/Application/coordinator.py` | `ApplicationCoordinator` | Фасад: инициализация всех слоёв, lifecycle, связь сигналов |

### 2.2 Application Layer

| Файл | Класс | Ответственность |
|------|-------|-----------------|
| `Core/Application/window_manager.py` | `WindowManager` | Реестр окон, show/hide/close, fullscreen, cursor, access_level |
| `Core/Application/window_registry.py` | `WindowRegistry` | Фабрика и хранение окон (singleton/multi) |
| `Core/Application/window_entry.py` | `WindowEntry` | Конфигурация окна (needs_fullscreen, auto_close и т.д.) |
| `Core/Application/thread_manager.py` | `ThreadManager` | Создание, запуск, остановка QThread (UpdateImage, BotThread) |

### 2.3 Domain Layer

| Файл | Класс | Ответственность |
|------|-------|-----------------|
| `Core/Domain/Registers/manager.py` | `RegistersManager` | Единый источник истины для регистров, observer API (subscribe/set_field_value) |
| `Core/Managers/data_manager.py` | `DataManager` | Координатор: CameraManager, RegionManager, RecipeManager, ConverterManager |
| `Core/Managers/camera_manager.py` | `CameraManager` | Управление CameraData (камеры, Hikvision params) |
| `Core/Managers/region_manager.py` | `RegionManager` | Регионы, цепочки обработки (ChainStepData) |
| `Core/Managers/recipe_manager.py` | `RecipeManager` | YAML рецепты, load/save, model_dump/model_validate |
| `Core/Managers/converter_manager.py` | `ConverterManager` | Flat ↔ Structured (Pydantic) конвертация |
| `Core/Managers/params_manager.py` | `ParamsManager` | Применение/сохранение рецептов, связь виджетов с SortData |
| `Core/Managers/logging_manager.py` | `LoggingManager` | Логирование |
| `Core/Managers/error_manager.py` | `ErrorManager` | Обработка ошибок |
| `Core/Managers/translation_manager.py` | `TranslationManager` | Локализация |

### 2.4 Registers (модели)

| Файл | Модель | Поля (примеры) |
|------|--------|----------------|
| `Core/Domain/Registers/models/registers/draw.py` | `DrawRegisters` | draw, circles, rectangles, dp, minDist, param1, param2, minRadius, maxRadius |
| `Core/Domain/Registers/models/registers/camera.py` | `CameraRegisters` | source, enable_camera, record_video, fps |
| `Core/Domain/Registers/models/registers/robot.py` | `RobotRegisters` | servo_on, position, shift_time, shift, length, back, DO1, DO2 |
| `Core/Domain/Registers/models/registers/processing.py` | `ProcessingRegisters` | HL, SL, VL, HM, SM, VM, area, crop, mode |
| `Core/Domain/Registers/models/registers/neuroun.py` | `NeurounRegisters` | server, processing |
| `Core/Domain/Registers/models/registers/conveyor.py` | `ConveyorRegisters` | conveyor_freq |
| `Core/Domain/Registers/models/registers/hikvision.py` | `HikvisionRegisters` | Параметры Hikvision SDK |
| `Core/Domain/Registers/models/registers/post_processing.py` | `PostProcessingRegisters` | regions, region_chains |
| `Core/Domain/Registers/models/registers/visual.py` | `VisualRegisters` | image_scale |
| `Core/Domain/Registers/models/registers/frame_process.py` | `FrameProcessRegisters` | Параметры обработки кадров |

### 2.5 Threads

| Файл | Класс | Ответственность |
|------|-------|-----------------|
| `Core/Threads/thread_image_update.py` | `UpdateImage` | Чтение display_queue → frame_ready.emit(frames, metrics) |
| `Core/Threads/thread_bot_message.py` | `BotThread` | Сообщения от бота |
| `Core/Threads/thread_loading.py` | — | Загрузка |
| `Core/Threads/thread_camera_message.py` | `CameraMessageThread` | Сообщения от камеры (в HikvisionWidget) |

### 2.6 UI — Windows

| Файл | Класс | Ответственность |
|------|-------|-----------------|
| `UI/Windows/main_window.py` | `MainWindow` | **Конечный файл.** Компоновка: Header + ImagePanel + TabWidget. Проксирование сигналов. |
| `UI/Windows/loading_window.py` | `LoadingWindow` | Экран загрузки |
| `UI/Windows/neuroun_window.py` | `NeurounWindow` | Окно нейросети |
| `UI/Windows/message_window.py` | `MessageWindow` | Всплывающие сообщения |
| `UI/Windows/admin_window.py` | `PasswordDialog` | Диалог пароля администратора |

**Legacy (для справки):**
- `main_windows_old.py` — оригинальный монолит (~2300 строк) до разделения
- `main_window copy.py` — промежуточная версия (~400 строк), упрощённый UI
- `main_window_old2.py`, `main_window_old3.py` — промежуточные версии

### 2.7 UI — Widgets (вкладки MainWindow)

| Виджет | Путь | Ответственность |
|--------|------|-----------------|
| `ImagePanelWidget` | `UI/Widgets/ImagePanel_widget/image_panel.py` | Кадры + чекбоксы (Draw/Camera/Robot) + PerformanceOverlay (FPS) |
| `SortContainer` | `UI/Widgets/Sort_widget/sort_container.py` | Обёртка: SortWidget + SortController, рецепты, сброс |
| `HikvisionWidget` | `UI/Widgets/Hikvision_widget/Hikvision.py` | Управление камерой Hikvision, CameraMessageThread |
| `VisualConfigWidget` | `UI/Widgets/Visual_config_widget/visual_config.py` | Масштаб изображения |
| `LoggingWidget` | `UI/Widgets/Logging_widget/logging_widget.py` | Логирование |
| `PostProcessingWidget` | `UI/Widgets/PostProcessing_widget/post_processing.py` | Регионы, цепочки обработки |
| `ProcessingWidget` | `UI/Widgets/Processing_widget/processing.py` | HSV, обрезка, параметры |
| `CircleWidget` | `UI/Widgets/Circle_widget/circle_widget.py` | Параметры формы (Hough circles) |

### 2.8 UI — Components (переиспользуемые)

| Файл | Класс | Ответственность |
|------|-------|-----------------|
| `UI/Components/header.py` | `HeaderWidget` | Кнопки: Домой, Нейрон, ЭКРАН, ЗАКРЫТЬ, Admin |
| `UI/Components/header.py` | `ButtonHeader` | Кнопка с иконкой и анимацией |
| `UI/Components/tab_widget.py` | `TabWidget` | QTabWidget + кнопка «Скрыть/Показать» |
| `UI/Components/tab_widget.py` | `BaseTab` | Базовый класс вкладок (on_tab_selected/on_tab_deselected) |
| `UI/Components/checkbox_enhanced.py` | `CheckboxControlEnhanced` | Чекбокс, привязанный к RegistersManager |
| `UI/Components/slider_enhanced.py` | `SliderControlEnhanced` | Слайдер, привязанный к RegistersManager |
| `UI/Components/structured_table.py` | — | Таблица с структурированными данными |
| `UI/Components/table_with_toolbar.py` | — | Таблица с тулбаром |
| `UI/Components/performance_monitor.py` | — | Мониторинг производительности |
| `UI/Widgets/ImagePanel_widget/Performance_overlay.py` | `PerformanceOverlay` | FPS, размер, время обработки поверх изображения |

### 2.9 Core — Base

| Файл | Класс | Ответственность |
|------|-------|-----------------|
| `Core/base_configurable_widget.py` | `ConfigurableWidget` | Базовый класс виджетов с привязкой к RegistersManager (register_name, field_name, access_level) |

### 2.10 Config

| Файл | Класс | Ответственность |
|------|-------|-----------------|
| `Core/Config/app_config.py` | `AppConfig` | Pydantic-конфиг: window (min size, fullscreen limit), language |

---

## 3. Поток данных (упрощённо)

```
[Backend] → display_queue → UpdateImage.run() → frame_ready.emit(frames, metrics)
                                    ↓
            Coordinator._connect_cross_layer_signals: image_thread.frame_ready → main_window.display_frame
                                    ↓
            MainWindow.display_frame(frames, metrics) → ImagePanelWidget.display_frame()
                                    ↓
            ImagePanelWidget: QLabel + PerformanceOverlay обновляются
```

```
[User] → CheckboxControlEnhanced (Draw.dp) → set_field_value() → RegistersManager
                                    ↓
            RegistersManager.subscribe_all → Coordinator._on_register_changed
                                    ↓
            RouterManager.send_async(Message) → control_draw queue → [Backend]
```

---

## 4. Эволюция MainWindow

| Версия | Файл | Строк | Описание |
|--------|------|-------|----------|
| **Монолит** | `main_windows_old.py` | ~2314 | Всё в одном: controls_*, update_controls_*, create_widgets, RouterManager, ParamsManager, все виджеты |
| **Copy** | `main_window copy.py` | ~408 | Упрощённый: Header + image_label + tabs с хардкодом слайдеров/чекбоксов, queue_manager.put(control) |
| **Рефакторинг** | `main_window.py` | ~289 | **Конечный.** Только компоновка: Header + ImagePanel + TabWidget. Логика в виджетах и менеджерах. |

**Что вынесено из монолита:**
- Регистры → `RegistersManager` + Pydantic-модели
- Камеры/регионы/рецепты → `DataManager`, `CameraManager`, `RegionManager`, `RecipeManager`
- IPC → `RouterManager` (в Coordinator)
- Потоки → `ThreadManager`, `UpdateImage`
- Окна → `WindowManager`, `WindowRegistry`
- Сорта → `SortContainer`, `SortController`, `SortWidget`, `SortData`
- Изображение → `ImagePanelWidget`, `PerformanceOverlay`
- Чекбоксы/слайдеры → `CheckboxControlEnhanced`, `SliderControlEnhanced` + `ConfigurableWidget`

---

## 5. Известные несоответствия (требуют исправления)

### 5.1 Импорты Domain.Services

**Проблема:** Coordinator, main_window, sort_container, window_manager импортируют:
```python
from App.Core.Domain.Services.data_manager import DataManager
from App.Core.Domain.Services.camera_manager import CameraManager
# и т.д.
```
**Факт:** Папки `App/Core/Domain/Services/` не существует. Менеджеры находятся в `App/Core/Managers/`.

**Решение:** Создать `App/Core/Domain/Services/` с re-export или заменить импорты на `App.Core.Managers`.

### 5.2 DataManager — сигнатура конструктора

**Coordinator передаёт:**
```python
DataManager(registers_manager=..., recipe_manager=..., converter=...)
```
**Core.Managers.data_manager принимает:**
```python
def __init__(self, recipe_manager=None, converter=None):  # нет registers_manager
```

**Решение:** Добавить `registers_manager` в DataManager или убрать из вызова Coordinator.

### 5.3 SortContainer — путь импорта

**Проблема:** sort_container импортирует:
```python
from App.UI.Widgets.Sort.sort_data import SortData
from App.UI.Widgets.Sort.sort_controller import SortController
# ...
```
**Факт:** Папка называется `Sort_widget`, не `Sort`.

**Решение:** Заменить на `App.UI.Widgets.Sort_widget.*`.

### 5.4 HeaderWidget — window_manager

**Проблема:** MainWindow создаёт `HeaderWidget()` без аргументов. HeaderWidget ожидает `window_manager` в конструкторе для `toggle_fullscreen`, `close_programm`, `admin`.

**Решение:** WindowManager должен инжектировать себя в Header после создания MainWindow, или Header получать ссылку через parent/signals.

### 5.5 App.Windows vs App.UI.Windows

**Проблема:** header.py импортирует `from App.Windows.admin_window import PasswordDialog`. Core.Managers.window_manager импортирует `from App.Windows.main_window`. Git показывает удаление `App/Windows/`.

**Факт:** Активные файлы в `App/UI/Windows/`. Нужно проверить наличие `App/Windows/` или `App/UI/Windows/` и унифицировать импорты.

### 5.6 Дублирование Registers

**Проблема:** Существуют `App.Registers` и `App.Core.Domain.Registers` с похожими моделями.

**Решение:** Использовать только `App.Core.Domain.Registers` как источник истины.

---

## 6. Зависимости (внешние)

- **PyQt5** — UI
- **qdarkstyle** — тема
- **Pydantic** — модели
- **numpy** — изображения
- **opencv-python (cv2)** — обработка кадров
- **PyYAML** — конфиги и рецепты
- **multiprocess_framework** — QueueManager, RouterManager, RegistersContainer, shared memory

---

## 7. Быстрый поиск по ключевым словам

| Ищу | Где |
|-----|-----|
| Где создаётся MainWindow? | `Core/Application/window_manager.py` → `_create_main_window()` |
| Где подключается frame_ready? | `Core/Application/coordinator.py` → `_connect_cross_layer_signals()` |
| Где хранятся регистры draw/camera/robot? | `Core/Domain/Registers/manager.py` (RegistersManager) |
| Где загружаются рецепты? | `Core/Managers/recipe_manager.py`, `Core/Managers/data_manager.py` |
| Где отправляются команды в бэкенд? | Coordinator._on_register_changed → RouterManager.send_async |
| Где отображаются кадры? | `UI/Widgets/ImagePanel_widget/image_panel.py` → `display_frame()` |
| Где логика сортов/рецептов? | `UI/Widgets/Sort_widget/sort_controller.py`, `sort_data.py` |
| Где Hikvision камера? | `UI/Widgets/Hikvision_widget/Hikvision.py` |
| Где FPS вычисляется? | `Core/Threads/thread_image_update.py` (UpdateImage), метрики в frame_ready |

---

*Документ создан для быстрой навигации AI и разработчиков. Детальная архитектура — см. NEW_ARCHITECTURE.md.*
