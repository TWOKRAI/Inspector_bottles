# Components — Архитектура

## Ответственность
Переиспользуемые **UI-компоненты без бизнес-логики предметной области**.
Компонент знает только о своём отображении и вводе пользователя.
Никаких менеджеров, никаких прямых зависимостей от конкретных виджетов предметной области.

---

## Файлы

| Файл | Класс | Ответственность |
|------|-------|-----------------|
| `header.py` | `HeaderWidget(QWidget)`, `ButtonHeader` | Шапка приложения: кнопки Admin / Home / Neuroun / Fullscreen / Close, логотип. Эмитирует `main_show`, `neuroun_show` |
| `slider.py` | `SliderControl(QWidget)` | Базовый слайдер с числовым полем. Принимает `name`, `min`, `max`, `init_val` напрямую (без автоконфигурации) |
| `slider_enhanced.py` | `SliderControlEnhanced(ConfigurableWidget)` | Слайдер с авто-привязкой к полю `RegistersManager`. Конфигурируется из metadata Pydantic-поля |
| `checkbox.py` | `CheckboxControl(QWidget)` | Базовый чекбокс. Принимает `name` и начальное значение напрямую |
| `checkbox_enhanced.py` | `CheckboxControlEnhanced(ConfigurableWidget)` | Чекбокс с авто-привязкой к полю `RegistersManager`. Конфигурируется из metadata Pydantic-поля |
| `keyboard_mini.py` | `VirtualKeyboardMini(QWidget)` | Виртуальная цифровая клавиатура (touch-ввод) без рамки |
| `structured_table.py` | `StructuredTableWidget(QTableWidget)` | Универсальная таблица с конфигурируемыми колонками (text/checkbox), сигналы `cell_changed`, `row_selected` |
| `table_with_toolbar.py` | `TableWithToolbar(QWidget)` | `StructuredTableWidget` + тулбар: Add / Delete / Up / Down / Copy / Paste |

---

## Разделение: базовые vs. enhanced

```
SliderControl            CheckboxControl
(name + min/max вручную)  (name + value вручную)
        │                         │
        └──── для legacy-виджетов ──────┘

SliderControlEnhanced    CheckboxControlEnhanced
(поле RegistersManager)   (поле RegistersManager)
        │                         │
        └── ConfigurableWidget ───┘  ← наблюдатель за регистром
```

Новый код должен использовать `*Enhanced`-версии — они автоматически конфигурируются из metadata Pydantic-поля и реагируют на изменения `RegistersManager`.

---

## Правила

- **Нет бизнес-логики**: компонент не знает, что такое "сорт", "рецепт", "камера" или "регион".
- **Нет менеджеров предметной области**: `DataManager`, `ParamsManager`, `RecipeManager` — не для Components.
- Единственная допустимая зависимость на `Core` — `ConfigurableWidget` (базовый класс) и `RegistersManager` (только через `ConfigurableWidget`).
- Исключение: `HeaderWidget` знает о `PasswordDialog` (окно пароля) — технически допустимо как часть шапки.
