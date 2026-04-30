# Оценка v2 Controls и план реализации v2/slider

*(Актуально: контролы в `frontend_module.components` без вложенного `control_v2/`; примеры — `components/examples/`; см. ADR-077.)*

## 1. Сеньор-оценка реализации

### 1.1 v2/base — 8.5/10

**Что хорошо:**
- Чёткое разделение на интерфейсы (`IControlView`, `INumericView`, `IFieldBinding`, `IRegisterPort`), конфиги, traits и инфраструктуру.
- Duck typing через Protocol — низкая связанность, легко подменять реализации.
- Traits как «кубики» — `SchemaTrait`, `SyncTrait`, `AccessTrait`, `DebounceTrait` переиспользуемы без наследования.
- `ValueTransformer` и `RegisterAdapter` — единая точка работы с метаданными и регистрами.
- Хороший README с диаграммами, примерами, описанием портов.

**Что улучшить:**
- `SchemaTrait._meta` загружается один раз в `__init__`; при динамическом обновлении метаданных регистра не обновится (минус 0.5).
- В `interfaces.py` отсутствуют stub-типы для `ResolvedMeta` — используется `TYPE_CHECKING` (приемлемо, но можно явнее документировать).

---

### 1.2 v2 — оркестрационный слой — 8/10

**Что хорошо:**
- Единый реэкспорт `__init__.py` — один вход для всех контролов.
- `merge_config`, `LegacySyncContext`, `BindingConfig` доступны из корня v2.
- Концепция «конструктор из кубиков» соблюдена.

**Что улучшить:**
- В `__init__.py` импортируется `SliderConfig`, но нет `SliderControl` — slider пока не самодостаточен как checkbox (минус 1).
- Документация дерева v2 разбросана (checkbox/README, base/README, group).

---

### 1.3 v2/checkbox — 9/10

**Что хорошо:**
- Полный цикл: View → Presenter → Facade, соответствует base-архитектуре.
- `CheckboxView` реализует `IControlView[bool]` полностью; `on_finished` — осознанный no-op.
- `CheckboxPresenter` — минимальная композиция traits (Schema + Sync + Access), без лишнего.
- `CheckboxControl.create()` — удобный фасад с явным возвратом `CheckboxControlResult`.
- `defaults.py` — типовые конфиги для типовой раскладки.

**Что улучшить:**
- `checkbox_left`/`checkbox_right` можно вынести в общие defaults при появлении нескольких контролов с `position`.

---

### 1.4 v2/slider — 6/10 (текущее состояние)

**Что хорошо:**
- `SliderValueView` реализует INumericView-подобный контракт (set_range, set_validator_*, on_changed/on_finished, get_legacy_element).
- `SliderConfig` с `to_label_override()` — согласован с base.
- Используется через `NumericControl` + `GroupView` + `label_slider_default`.

**Что плохо / чего не хватает:**
- Нет собственного `SliderPresenter` и `SliderControl` — slider «зашит» внутрь NumericControl.
- Нет самодостаточного API вида `SliderControl.create(rm, binding, SliderViewConfig)`.
- `SliderValueView` не реализует `setup()` и `set_value()` — используется только внутри `LabeledNumericGroupView`.
- Нет аналога `example_with_data_schema` для slider — нельзя собрать слайдер из SchemaBase по образцу checkbox.
- Слабая разделённость по папкам (schema/, view/, presenter/ и т.д.) — всё в плоской структуре.

---

## 2. Сводная таблица оценок

| Компонент       | Оценка | Комментарий                                      |
|-----------------|--------|--------------------------------------------------|
| v2/base         | 8.5/10 | Сильная база, traits, интерфейсы                  |
| v2 (оркестрация)| 8/10   | Хороший реэкспорт, slider не завершён            |
| v2/checkbox     | 9/10   | Эталонная реализация MVP                         |
| v2/slider       | 6/10   | Только value-view и config, нет facade/presenter  |

---

## 3. План реализации v2/slider по образцу checkbox и example_with_data_schema

### 3.1 Цель

Привести v2/slider к той же структуре, что и checkbox:
- самодостаточный `SliderControl.create()`;
- разделение на папки (schema, view, presenter, facade);
- пример `example_slider_with_data_schema` с SchemaBase и adapter.

### 3.2 Структура папок

```
controls/
├── v2/
│   ├── slider/
│   │   ├── schema/           # NEW: конфиги и override
│   │   │   ├── __init__.py
│   │   │   └── config.py     # SliderViewConfig (переименованный/расширенный SliderConfig)
│   │   ├── view/             # NEW: выделение view в подпапку
│   │   │   ├── __init__.py
│   │   │   ├── value_view.py # SliderValueView (QLineEdit + QSlider)
│   │   │   └── labeled.py    # SliderLabeledView — label + value (реализует INumericView)
│   │   ├── presenter.py       # NEW: SliderPresenter (композиция NumericPresenter-логики)
│   │   ├── facade.py         # NEW: SliderControl, SliderControlResult
│   │   ├── defaults.py       # slider_default, bgr_slider_default
│   │   └── __init__.py       # реэкспорт
│   └── ...
├── example_with_data_schema/     # checkbox — уже есть
└── example_slider_with_data_schema/   # NEW: slider по тому же паттерну
    ├── schemas/
    │   ├── __init__.py
    │   └── register_ui.py     # ExampleSliderValueRegister + ExampleSliderUiConfig
    ├── adapter.py            # slider_binding, slider_view_config_from_ui, create_example_slider
    ├── README.md
    └── __init__.py
```

### 3.3 Пошаговый план

#### Шаг 1: Реорганизация v2/slider (schema + view)

1. Создать `v2/slider/schema/`:
   - `config.py` — `SliderViewConfig` (расширяет `BaseControlConfig`, наследует поля из текущего `SliderConfig`: `show_ticks`, `tick_interval`, `min_val`, `max_val`, `label_position`), метод `to_label_override()`.
2. Создать `v2/slider/view/`:
   - `value_view.py` — перенести `SliderValueView` из `view.py`, добавить `setup(label, tooltip, enabled)` и `set_value(value)` для полной совместимости с `INumericView`, если нужно для standalone-режима.
   - `labeled.py` — `SliderLabeledView` = `LabelView` + `SliderValueView` в одном виджете (аналог `CheckboxView` или использование существующего `LabeledNumericGroupView`).
3. Обновить `v2/slider/__init__.py` — импорты из `schema/`, `view/`.

#### Шаг 2: SliderPresenter и SliderControl (facade)

1. `v2/slider/presenter.py`:
   - `SliderPresenter` — композиция traits как в `NumericPresenter` (Schema, Sync, Debounce, Access, ValueTransformer, опционально LegacySync).
   - Контракт View: `INumericView`.
   - Методы: `attach_view()`, `set_access_level()`, внутренние `_on_changing`, `_on_finished`, `_on_external_change`, `_sync_from_model`.

2. `v2/slider/facade.py`:
   - `SliderControlResult` — dataclass `(widget, presenter)`.
   - `SliderControl.create(registers_manager, binding, view_config, current_access_level, legacy_context)`:
     - Создаёт `RegisterAdapter`, `SliderPresenter`, `SliderLabeledView` (или `create_labeled_numeric_view("slider", view_config)`),
     - Вызывает `presenter.attach_view(view)`,
     - Возвращает `SliderControlResult`.

#### Шаг 3: Интеграция с group/numeric

1. Сохранить совместимость: `NumericControl.create(view_config=NumericViewConfig(view_type="slider", ...))` продолжает работать через `GroupView` + `SliderValueView`.
2. `SliderControl.create()` — альтернативный фасад для явного создания слайдера с подписью, без зависимости от `NumericViewConfig`.

#### Шаг 4: example_slider_with_data_schema

1. Создать `example_slider_with_data_schema/`:
   - `schemas/register_ui.py`:
     - `ExampleSliderValueRegister` — числовое поле с `BINDING_REGISTER`, `BINDING_FIELD`, `FieldMeta` (min, max, transfer_k, round_k, label, unit).
     - `ExampleSliderUiConfig` — `slider_label`, `slider_tooltip`, `slider_position`, `slider_show_ticks`, `slider_min`, `slider_max`, `slider_widget_enabled`.
   - `adapter.py`:
     - `slider_binding(access_level=0) -> BindingConfig`
     - `slider_view_config_from_ui(ui: ExampleSliderUiConfig) -> SliderViewConfig`
     - `coerce_ui(ui) -> ExampleSliderUiConfig`
     - `create_example_slider(registers_manager, ui, *, access_level=0) -> SliderControlResult`
   - `__init__.py` — реэкспорт.
   - `README.md` — описание паттерна по образцу example_with_data_schema.

#### Шаг 5: Обновление v2/__init__.py и документации

1. Добавить в `v2/__init__.py`: `SliderControl`, `SliderControlResult`, `SliderViewConfig` (если выносим в публичный API).
2. Обновить `v2/slider/README.md` (создать при отсутствии) — диаграммы, примеры, сравнение с checkbox.

### 3.4 Зависимости между шагами

```
Шаг 1 (schema + view) ─┬─► Шаг 2 (presenter + facade) ─► Шаг 3 (интеграция)
                        │
                        └─► Шаг 4 (example_slider_with_data_schema)
                                    │
                                    └─► Шаг 5 (документация, реэкспорт)
```

### 3.5 Важные решения

| Вопрос | Решение |
|--------|---------|
| Дублировать ли логику NumericPresenter? | Нет. `SliderPresenter` = thin wrapper над той же композицией traits или явный вызов `NumericPresenter` внутри `SliderControl`. |
| SliderLabeledView vs GroupView | Использовать `create_labeled_numeric_view("slider", ...)` для единообразия с `NumericControl`. Либо выделить `SliderLabeledView` как алиас. |
| Schema/UI в example — один файл или два? | Один `register_ui.py` по аналогии с `schemas.py` в example_with_data_schema (две SchemaBase в одном модуле). |
| Папки schema/view — обязательны? | Рекомендуется для масштабируемости; при малом объёме можно оставить `config.py` и `view/` в корне `slider/`. |

### 3.6 Критерии готовности

- [x] `SliderControl.create()` возвращает `SliderControlResult(widget, presenter)`.
- [x] `SliderPresenter` (= NumericPresenter) поддерживает `attach_view(INumericView)`, `set_access_level()`.
- [x] `example_slider_with_data_schema` — `create_example_slider()` создаёт слайдер из UI-схемы.
- [x] Совместимость с `NumericControl` и `label_slider_default` сохранена.
- [x] README создан; циклический импорт устранён (lazy import в group.view).
