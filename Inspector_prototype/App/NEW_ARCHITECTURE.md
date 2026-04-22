# App Inspector — Архитектурная Документация

**Версия:** 2.0 (рефакторинг 2024)  
**Автор:** Technical Lead / Senior Engineer  
**Статус:** Production Ready

---

## 1. Общая Оценка Архитектуры

### 1.1 Сводная таблица оценок (10-балльная шкала)

| Критерий | Балл | Обоснование | Что улучшить |
|----------|------|-------------|--------------|
| **Single Responsibility Principle (SRP)** | 9/10 | Чёткое разделение на 4 слоя, каждый класс имеет одну причину для изменения | WindowManager всё ещё немного тяжеловат (fullscreen + cursor + access_level) |
| **Open/Closed Principle (OCP)** | 9/10 | Новое окно = 1 строка в registry, новый регистр = файл в папку | Добавить плагиновую систему для виджетов |
| **Liskov Substitution Principle (LSP)** | 8/10 | Все QWidget наследники взаимозаменяемы, потоки стандартизированы | Проверить все override методы на совместимость сигнатур |
| **Interface Segregation (ISP)** | 9/10 | Минимальные интерфейсы: SortController не знает про WindowManager | CameraService можно разделить на чтение/запись |
| **Dependency Inversion (DIP)** | 9/10 | Всё инжектируется через конструкторы, нет new внутри бизнес-логики | Фабрики в registry можно заменить на DI-контейнер |
| **DRY (Don't Repeat Yourself)** | 9/10 | CameraMessageThread только в Hikvision, FPS только в ImagePanel | Вынести common UI компоненты в отдельную библиотеку |
| **KISS (Keep It Simple)** | 7/10 | 4 слоя абстракции — много для junior разработчика | Нужна визуальная схема для onboarding |
| **Testability** | 8/10 | Слои изолированы, можно мокать зависимости | Qt-сигналы усложняют unit-тесты, нужен абстрактный брокер сообщений |
| **Performance** | 9/10 | Zero-copy для кадров, async IPC, неблокирующие очереди | Можно добавить backpressure для очереди кадров |
| **Observability** | 7/10 | Есть метрики FPS, но нет centralized logging | Добавить структурированные логи и tracing |

### 1.2 Итоговая оценка: **8.4/10** (Senior/Staff Engineer уровень)

**Что отличает от Junior архитектуры:**
- ✅ Инверсия зависимостей (не создаём внутри, получаем снаружи)
- ✅ Слои изолированы (UI не знает про IPC напрямую)
- ✅ Единый источник истины (RegistersManager)
- ✅ Observer pattern вместо polling
- ✅ Graceful shutdown на всех уровнях

**Что отличает от Principal/Architect уровня:**
- ❌ Нет распределённой трассировки (distributed tracing)
- ❌ Нет circuit breaker для IPC
- ❌ Нет автоматического масштабирования потоков
- ❌ Нет hot-reload конфигурации

---

## 2. Архитектурные Принципы (must read для разработчиков)

### 2.1 Золотое Правило: "Сигналы Вниз, Данные Вверх"
┌─────────────────┐
│   UI Layer 4    │ ← Эмитит сигналы действий (reset_requested)
│  (MainWindow)   │ ← НЕ знает про бизнес-логику!
└────────┬────────┘
│ СИГНАЛ (что случилось)
▼
┌─────────────────┐
│  Application    │ ← Решает ЧТО делать (Coordinator)
│   Layer 3       │ ← Маршрутизирует сигналы между слоями
└────────┬────────┘
│ КОМАНДА (какое действие)
▼
┌─────────────────┐
│   Domain        │ ← Выполняет бизнес-логику (DataManager)
│   Layer 2       │ ← Меняет состояние (RegistersManager)
└────────┬────────┘
│ ДАННЫЕ (результат)
▼
┌─────────────────┐
│   Core/Infra    │ ← Персистентность, IPC (RouterManager)
│   Layer 1       │ ← Отправка в бэкенд
└─────────────────┘

### 2.2 Запрещённые Паттерны (красные флаги)

| ❌ Запрещено | ✅ Правильно | Почему |
|-------------|-------------|--------|
| `main_window.fps = value` | `image_thread.frame_ready.emit(frames, metrics)` | Нарушение инкапсуляции |
| `if hasattr(obj, 'attr'): obj.attr = value` | Чёткий интерфейс с typing | Хрупкость, нет проверок |
| `global config` | Инжекция через конструктор | Невозможно тестировать |
| `thread.start()` в `__init__` | `thread_manager.start_all()` | Неконтролируемый lifecycle |
| `QMessageBox` в бизнес-логике | Сигнал `error_occurred` + обработка в UI | UI зависимость в логике |

### 2.3 Разрешённые Зависимости (стрелки только вниз!)
Layer 4 (UI) ──────► Layer 3 (App) ──────► Layer 2 (Domain) ──────► Layer 1 (Core)
Разрешено: MainWindow → DataManager (чтение)
Запрещено: DataManager → MainWindow (UI зависимость!)
Разрешено: HikvisionWidget → CameraService (IPC)
Запрещено: CameraService → HikvisionWidget (циклическая зависимость!)

---

## 3. Структура Проекта (дерево файлов)
Inspector_prototype/
│
├── App/
│   │
│   ├── Core/                            # Слои 1-3: Domain + Application
│   │   │
│   │   ├── Config/                      # Cross-cutting: конфигурация
│   │   │   └── app_config.py            # AppConfig (Pydantic, read-only)
│   │   │
│   │   ├── Domain/                      # Layer 2: бизнес-логика
│   │   │   │
│   │   │   ├── Registers/               # Layer 1.5: состояние системы
│   │   │   │   ├── manager.py           # RegistersManager (observer)
│   │   │   │   └── models/
│   │   │   │       ├── registers/       # Pydantic + FieldMeta (UI + IPC)
│   │   │   │       │   ├── draw.py      # HoughCircles параметры
│   │   │   │       │   ├── camera.py    # Источник, запись видео
│   │   │   │       │   ├── processing.py # HSV, обрезка
│   │   │   │       │   └── ...
│   │   │   │       └── data/            # Чистые структуры (CameraData, RegionData)
│   │   │   │
│   │   └── Services/                   # Re-export из Core.Managers (архитектурная прослойка)
│   │       └── __init__.py             # DataManager, CameraManager, RegionManager, RecipeManager, ConverterManager
│   │
│   ├── Managers/                       # Реализация Domain-сервисов (фактическое расположение)
│   │   ├── data_manager.py           # Главный координатор
│   │   ├── camera_manager.py         # Управление CameraData
│   │   ├── region_manager.py         # Управление RegionData
│   │   ├── recipe_manager.py         # YAML persistence
│   │   ├── converter_manager.py      # Flat ↔ Structured conversion
│   │   ├── params_manager.py         # Применение/сохранение рецептов
│   │   └── ...
│   │   │
│   │   ├── Infrastructure/              # Layer 2.5: IPC, persistence
│   │   │   └── Ipc/
│   │   │       └── camera_service.py    # Bridge: domain ↔ multiprocessing
│   │   │
│   │   └── Application/                 # Layer 3: оркестрация
│   │       ├── coordinator.py           # Главный фасад (владеет всеми)
│   │       ├── window_manager.py        # Управление окнами (WindowRegistry)
│   │       ├── window_registry.py       # Фабрика и хранение окон
│   │       └── thread_manager.py        # Управление QThread
│   │           └── register_standard_threads()  # Регистрация UpdateImage, BotThread
│   │
│   ├── Threads/                         # QThread-потоки
│   │   ├── thread_image_update.py      # UpdateImage — кадры из display_queue
│   │   ├── thread_bot_message.py       # BotThread — сообщения от бота
│   │   └── thread_loading.py           # Loading
│   │
│   ├── base_configurable_widget.py      # ConfigurableWidget — базовый класс виджетов с RegistersManager
│   │
│   ├── UI/                              # Layer 4: presentation
│   │   │
│   │   ├── Windows/                     # Окна-контейнеры (только компоновка!)
│   │   │   ├── main_window.py           # Главное окно (Header + ImagePanel + Tabs)
│   │   │   ├── loading_window.py        # Экран загрузки
│   │   │   ├── neuroun_window.py        # Окно нейросети
│   │   │   └── message_window.py        # Всплывающие сообщения
│   │   │
│   │   ├── Widgets/                     # Переиспользуемые виджеты
│   │   │   │
│   │   │   ├── ImagePanel_widget/       # Центральная панель
│   │   │   │   ├── image_panel.py       # ImagePanelWidget + PerformanceOverlay
│   │   │   │   └── Performance_overlay.py # FPS, размер, время (поверх изображения)
│   │   │   │
│   │   │   ├── Hikvision_widget/        # Управление камерой
│   │   │   │   ├── Hikvision.py         # HikvisionWidget (автономный!)
│   │   │   │   └── Threads/thread_camera_message.py # CameraMessageThread
│   │   │   │
│   │   │   ├── Sort_widget/             # Рецепты/сорта
│   │   │   │   ├── sort_container.py   # SortContainer (фасад для MainWindow)
│   │   │   │   ├── sort_controller.py  # Логика рецептов (без WindowManager!)
│   │   │   │   ├── Sort_widget.py      # UI выбора рецепта
│   │   │   │   ├── sort_data.py        # YAML хранилище рецептов
│   │   │   │   └── sort_excel_export.py # Экспорт в Excel
│   │   │   │
│   │   │   ├── Visual_config_widget/   # Масштаб изображения
│   │   │   ├── Logging_widget/         # Логирование
│   │   │   ├── PostProcessing_widget/  # Регионы, цепочки обработки
│   │   │   ├── Processing_widget/      # HSV, обрезка, параметры
│   │   │   ├── Circle_widget/          # Параметры формы (Hough circles)
│   │   │   └── ...
│   │   │
│   │   └── Components/                 # Переиспользуемые UI-компоненты
│   │       ├── header.py               # HeaderWidget, ButtonHeader
│   │       ├── tab_widget.py           # TabWidget, BaseTab
│   │       ├── checkbox_enhanced.py   # CheckboxControlEnhanced (→ RegistersManager)
│   │       ├── slider_enhanced.py      # SliderControlEnhanced (→ RegistersManager)
│   │       ├── structured_table.py    # Таблица с структурированными данными
│   │       ├── table_with_toolbar.py   # Таблица с тулбаром
│   │       └── keyboard.py, keyboard_mini.py, ...
│   │
│   ├── main_app.py                     # Entry point: QueueManager → Coordinator → run()
│   ├── resource_paths.py               # Пути к ресурсам (иконки, изображения)
│   └── Data/                           # Конфиги, рецепты, логи
│       ├── config.yaml                 # Конфигурация (App/Data/config.yaml)
│       ├── app_config.json
│       └── Recipes/value_settings.yaml # Рецепты (YAML)
```

*Внешние зависимости:* `multiprocess_framework` — IPC, очереди, shared memory, RouterManager

---

## 4. Точка входа и жизненный цикл

```
main_app.main()
    │
    ├── 1. QueueManager, stop_event (инфраструктура)
    ├── 2. ApplicationCoordinator(queue_manager, stop_event, config_path)
    ├── 3. coordinator.initialize()
    │       ├── _init_config()        → AppConfig
    │       ├── _init_domain()        → RegistersManager, DataManager
    │       ├── _init_infrastructure() → RouterManager, каналы IPC
    │       └── _init_application_services() → ThreadManager, WindowManager
    ├── 4. _connect_cross_layer_signals()
    │       ├── image_thread.frame_ready → main_window.display_frame
    │       └── window_manager.reset/recipe → Coordinator callbacks
    ├── 5. thread_manager.register_standard_threads()  # Важно: вызвать до create_all!
    ├── 6. thread_manager.create_all() + start_all()
    ├── 7. window_manager.show_initial_window()
    └── 8. QApplication.exec_()
```

---

## 5. Поток данных (кадры и регистры)

### 5.1 Кадры: Backend → UI

```
[Backend] → display_queue
    → UpdateImage.run() → frame_ready.emit(frames, metrics)
    → MainWindow.display_frame(frames, metrics)
    → ImagePanelWidget.display_frame() → QLabel + PerformanceOverlay
```

### 5.2 Регистры: UI → Backend

```
[User] → CheckboxControlEnhanced / SliderControlEnhanced
    → set_field_value() → RegistersManager
    → subscribe_all callback → Coordinator._on_register_changed
    → RouterManager.send_async(Message) → control_* queue → [Backend]
```

---

## 6. Импорты (рекомендуемые пути)

| Что импортировать | Путь |
|-------------------|------|
| DataManager, CameraManager, ... | `App.Core.Managers` или `App.Core.Domain.Services` |
| RegistersManager | `App.Core.Domain.Registers.manager` |
| MainWindow | `App.UI.Windows.main_window` |
| HeaderWidget, TabWidget | `App.UI.Components.header`, `App.UI.Components.tab_widget` |
| ImagePanelWidget | `App.UI.Widgets.ImagePanel_widget.image_panel` |
| SortContainer | `App.UI.Widgets.Sort_widget.sort_container` |
| AppConfig | `App.Core.Config.app_config` |

---

## 7. Связанные документы

- **docs/APP_REFERENCE.md** — справочник классов и ответственностей (для AI и разработчиков)
- **docs/ARCHITECTURE_EVALUATION.md** — оценка архитектуры, известные проблемы, рекомендации