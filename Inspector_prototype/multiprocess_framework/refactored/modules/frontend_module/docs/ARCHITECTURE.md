# frontend_module — Архитектура

## Ответственность

Гибкий фреймворк для создания окон и наполнения компонентами и виджетами.
Workers строятся на QThread. Регистры — shared схемы (data_schema_module) + connection к бэкенду.

**Скелет (2026-03-18):**
- **FrontendManager** (BaseManager) — единая точка входа
- **FrontendRegistersBridge** — связь регистров с backend (connection_map)
- **Config hot-reload** — подписка на config_module, обновление UI без перезапуска

---

## Структура

```
frontend_module/
  application/       # FrontendManager, Coordinator, WindowManager, ThreadManager
  components/        # Переиспользуемые UI-компоненты
  core/              # BaseConfigurableWidget, WidgetRegistry, WindowRegistry, FrontendRegistersBridge, LayoutComposer
  windows/           # Окна-контейнеры (приложение заполняет)
  widgets/           # Виджеты предметной области (приложение заполняет)
  schemas/           # WidgetDescriptor, WindowConfig
  docs/
```

---

## Компоненты

| Файл | Класс | Ответственность |
|------|-------|-----------------|
| header.py | HeaderWidget, ButtonHeader | Шапка: callbacks (on_main_show, on_neuroun_show, on_fullscreen_toggle, on_close, on_admin) |
| slider_control.py | SliderControl | Слайдер с привязкой к RegistersManager |
| checkbox_control.py | CheckboxControl | Чекбокс с привязкой к RegistersManager |
| structured_table.py | StructuredTableWidget | Таблица по конфигу колонок |
| table_with_toolbar.py | TableWithToolbar | Таблица + тулбар |
| tab_widget.py | TabWidget, BaseTab | Вкладки с кнопкой сворачивания |
| keyboard.py | VirtualKeyboard | Полная виртуальная клавиатура |
| keyboard_mini.py | VirtualKeyboardMini | Цифровая клавиатура |
| performance_monitor.py | PerformanceMonitor | Метрики FPS, время обработки |

---

## Регистры и connection

- Frontend и backend используют **одни схемы** (shared_registers).
- `connection_map`: {register_name: backend_channel} — при изменении → send_callback.
- RegistersManager (registers_module): subscribe_all, set_field_value, connection_map, send_callback.

---

## Правила

- Компоненты без бизнес-логики предметной области.
- Header — callbacks вместо прямых зависимостей.
- Окна и виджеты — приложение создаёт в windows/ и widgets/.

---

## Связанные документы

- **[IDEAS_AND_IMPROVEMENTS.md](IDEAS_AND_IMPROVEMENTS.md)** — идеи по архитектуре, улучшения, следующие шаги (для передачи в другой чат).
