# frontend_module — Идеи по архитектуре и улучшениям

Документ для передачи контекста в другой чат. Содержит идеи, улучшения и следующие шаги.

---

## 1. Текущее состояние (на момент 2026-03-18)

### Реализовано
- **WindowRegistry** — needs_*, filter_names, apply, close_all
- **RegistersManager** — connection_map, send_callback, subscribe_all, set_field_value
- **Компоненты** — SliderControl, CheckboxControl, StructuredTableWidget, TableWithToolbar, TabWidget, HeaderWidget, VirtualKeyboard, VirtualKeyboardMini, PerformanceMonitor
- **Application** — WindowManager, ThreadManager, ApplicationCoordinator (скелет)
- **Папки** — windows/, widgets/ (пустые, для приложения)
- **Регистры** — схемы приложения (SchemaBase), connection_map / register_dispatch для привязки к бэкенду

### Не реализовано
- Интеграция с GuiProcess (multiprocess_prototype)
- Миграция App на frontend_module
- Unit-тесты для новых компонентов
- ADR в DECISIONS.md для frontend

---

## 2. Идеи по архитектуре

### 2.1 Разделение windows и widgets
- **windows/** — окна-контейнеры (MainWindow, LoadingWindow, MessageWindow). Только компоновка, без бизнес-логики.
- **widgets/** — виджеты предметной области (ImagePanel, CircleWidget, SortWidget). Могут зависеть от RegistersManager, DataManager.
- Приложение создаёт свои классы в этих папках или в своём пакете, подключая их к WindowManager через register().

### 2.2 Фабрика окон с инжекцией зависимостей
Сейчас WindowManager.register() принимает factory(**kwargs). Идея: стандартизировать сигнатуру фабрики:
```python
def create_main_window(registers_manager, config, data_manager=None, **kwargs) -> QWidget
```
WindowManager при вызове create() передаёт свои зависимости в factory. Это избавляет от замыканий и упрощает тестирование.

### 2.3 Плагиновая система виджетов
WidgetRegistry уже поддерживает register("type", factory). Идея: загрузка фабрик из конфига или пакетов:
```yaml
widgets:
  - type: slider
    module: frontend_module.components.slider_control
    class: SliderControl
  - type: custom_gauge
    module: my_app.widgets
    class: GaugeWidget
```
Позволяет приложению добавлять свои типы без изменения фреймворка.

### 2.4 Двунаправленная синхронизация регистров
Сейчас: frontend → set_field_value → send_callback → backend.
Идея: backend → обновление регистра → уведомление frontend. Нужен механизм получения обновлений с бэкенда (например, через Router subscribe на канал) и вызов notify_field_changed или прямой setattr + notify. Coordinator мог бы подписываться на ответы от бэкенда и обновлять RegistersManager.

### 2.5 Абстракция UI-фреймворка
Сейчас: жёсткая зависимость от PyQt5. Идея: интерфейс IWidget, ILayout, IApplication. Реализации: PyQt5Adapter, PySide6Adapter. Позволит переключаться между Qt-биндингами или даже на другой фреймворк (теоретически). Высокий объём работ, приоритет низкий.

### 2.6 Ресурсы и локализация
HeaderWidget принимает logo_path. Идея: централизованный ResourceProvider:
```python
class ResourceProvider:
    def get_logo(self) -> Path
    def get_icon(self, name: str) -> Path
    def get_string(self, key: str, lang: str) -> str
```
Инжектируется в HeaderWidget и другие компоненты. Упрощает смену тем и локализацию.

---

## 3. Улучшения кода

### 3.1 Coordinator — хук для регистрации окон
Сейчас приложение должно вызывать window_manager.register() вручную после создания Coordinator. Идея: callback или метод setup():
```python
coordinator = ApplicationCoordinator(...)
coordinator.initialize(config, registers)
coordinator.setup_windows(lambda wm: wm.register("main", create_main, ...))
coordinator.run()
```
Или: Coordinator принимает window_setup: Callable[[WindowManager], None].

### 3.2 ThreadManager — регистрация потоков через конфиг
Аналогично окнам: register_standard_threads() в App жёстко прописан. Идея: конфиг потоков:
```yaml
threads:
  image_update:
    class: App.Core.Threads.thread_image_update.UpdateImage
    auto_start: true
    stop_timeout_ms: 1000
```

### 3.3 HeaderWidget — иконки для кнопок
Сейчас ButtonHeader поддерживает self.image (путь). HeaderWidget создаёт кнопки с name. Идея: передавать icon_path в callbacks или в конфиг кнопок:
```python
HeaderWidget(
    buttons=[
        {"id": "admin", "icon": "icons8-test-account-96.png", "callback": on_admin},
        {"id": "home", "label": "Домой", "callback": on_main_show},
    ],
    ...
)
```

### 3.4 TableWithToolbar — делегирование в StructuredTableWidget
Проверить, что все методы таблицы корректно проксируются. Добавить недостающие (например, itemChanged для редактируемых ячеек).

### 3.5 SliderControl / CheckboxControl — единый интерфейс send_register_update
В App слайдер может вызывать send_register_update напрямую. Во frontend_module — через RegistersManager.set_field_value. Убедиться, что notify_field_changed и send_callback не дублируют отправку.

---

## 4. Интеграция с App

### 4.1 Миграция App на frontend_module
- Заменить App.Core.Application.window_manager → frontend_module.application.WindowManager
- Заменить App.Core.Application.thread_manager → frontend_module.application.ThreadManager
- Заменить App.Core.Application.coordinator → расширить frontend_module.ApplicationCoordinator или создать AppCoordinator(ApplicationCoordinator)
- Окна: App.UI.Windows → frontend_module.windows или оставить в App, регистрируя через factory
- Компоненты: App.UI.Components.*Enhanced → frontend_module.components (SliderControl, CheckboxControl уже есть)

### 4.2 AppConfig → config dict
WindowManager принимает config: dict. App использует AppConfig (Pydantic). Нужен адаптер: config = app_config.model_dump() или WindowManager принимает объект с .window, .get() и т.д.

### 4.3 DataManager, RecipeManager
Coordinator в App создаёт DataManager, RecipeManager. Во frontend_module Coordinator — скелет. При миграции: AppCoordinator наследует ApplicationCoordinator и добавляет _init_domain() с DataManager, RecipeManager.

---

## 5. Тестирование

### 5.1 Unit-тесты
- WindowRegistry: filter_names, apply, close_all
- RegistersManager: set_field_value с connection, subscribe_all
- HeaderWidget: вызов callbacks при клике
- SliderControl: clamp, transfer_k, ValidationError → QMessageBox

### 5.2 Интеграционные тесты
- Coordinator.initialize() + register + run (headless или с mock QApplication)
- compose_layout с несколькими дескрипторами

### 5.3 Моки
- IRegistersManager без Qt для тестов виджетов
- Mock WindowManager для тестов окон

---

## 6. Документация

### 6.1 DECISIONS.md — новые ADR
- ADR-034: frontend_module — структура (application, components, windows, widgets)
- ADR-035: RegistersManager connection_map для frontend-backend sync
- ADR-036: HeaderWidget — callbacks вместо прямых зависимостей

### 6.2 README.md — обновить
- Добавить пример с WindowManager, ThreadManager, Coordinator
- Добавить пример с connection_map и send_callback
- Обновить структуру (application, windows, widgets)

### 6.3 Миграционный гайд
Документ MIGRATION_APP_TO_FRONTEND.md с пошаговой инструкцией переноса App на frontend_module.

---

## 7. Следующие шаги (приоритет)

1. **Интеграция с GuiProcess** — подключить frontend_module к multiprocess_prototype, чтобы GUI использовал WindowManager, RegistersManager с connection.
2. **Миграция App** — поэтапный перенос App на frontend_module (сначала окна, потом компоненты).
3. **Unit-тесты** — покрыть новые компоненты и application layer.
4. **ADR в DECISIONS.md** — зафиксировать решения по frontend_module.
5. **ResourceProvider** — если понадобится единая точка для иконок и строк.

---

## 8. Ключевые пути

```
frontend_module/
  application/window_manager.py   # WindowManager
  application/thread_manager.py   # ThreadManager (QThread)
  application/coordinator.py     # ApplicationCoordinator
  components/header.py           # HeaderWidget (callbacks)
  components/slider_control.py   # SliderControl
  components/structured_table.py  # StructuredTableWidget
  core/window_registry.py        # WindowRegistry, WindowEntry
  core/base_configurable_widget.py
  windows/                       # пусто, для приложения
  widgets/                       # пусто, для приложения

registers_module/manager.py      # connection_map, send_callback, set_field_value
registers/schemas/draw.py         # DrawRegisters (прототип)
```

---

## 9. Контекст для нового чата

При продолжении работы:
1. Прочитать этот документ и ARCHITECTURE.md.
2. Проверить STATUS.md на текущий этап.
3. Правила: .cursor/rules/framework-architecture.mdc, DECISIONS.md.
4. Тестовый запуск: `python multiprocess_prototype/frontend_test/main.py` из Inspector_prototype с PYTHONPATH.
