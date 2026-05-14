# Ревью framework-components (1.1–1.8) для миграции прототипа

**Дата:** 2026-05-14
**Статус:** review
**Область:** `multiprocess_framework/modules/frontend_module/components/`
**План:** [`plans/frontend-widgets-cleanup-phase2.md`](../../plans/frontend-widgets-cleanup-phase2.md) — Phase 1 артефакт (PR1)

---

## Контекст

Прототип в [`multiprocess_prototype/frontend/forms/factory.py`](../../multiprocess_prototype/frontend/forms/factory.py) собирает 9 сырых Qt-виджетов из Pydantic `FieldInfo`: `QCheckBox`, `QComboBox`, `QSpinBox`, `QDoubleSpinBox`, `QLineEdit`, `QPlainTextEdit`, `ColorTripletWidget` (3 × `QSpinBox`). У каждого — ручной getter/setter и сырой Qt-сигнал в `FieldEditor.change_signal`. Никакого `RegisterAdapter`, touch-keyboard, access-control, debounce, `ControlHooks` или `effective_access_level` — всё это уже зрело реализовано во фреймворке, но не используется.

Цель документа — пройтись по каждому компоненту фреймворка, зафиксировать API + фичи + прототипный аналог, и решить как именно он будет применён в Phase 2 (`CardsFieldFactory` → framework-фасады). Документ — артефакт **PR1** (только docs); код-изменения — PR2.

**Конвенция структуры компонента (Traits + Presenter + View + Facade):**

```
<component>/
├── __init__.py        — экспорт публичного API
├── config.py          — *Config (SchemaBase + FieldMeta); наследует BaseControlConfig
├── view.py            — Qt-виджет (QWidget); протокол IControlView[T] / INumericView
├── presenter.py       — композиция traits (Schema/Sync/Debounce/Access/LegacySync)
├── facade.py          — *Control.create() — статическая фабрика, возвращает *ControlResult
└── defaults.py        — пресеты конфигурации (опционально)
```

Запись всегда идёт через `RegisterAdapter(rm)` внутри `SyncTrait.write(...)` → `rm.set_field_value(...)`. Hooks (`ControlHooks.on_write_committed/rejected/access_denied`) — наблюдатели, не пути записи.

---

## Сводная таблица решений

| # | Компонент | Прототипный аналог | Решение для Phase 2 | Правка фреймворка |
|---|-----------|--------------------|---------------------|-------------------|
| 1.1 | `checkbox/` | `QCheckBox` + `QLabel` (`_build_bool`) | `CheckboxControl.create(...)` | **+** `value_changed: Signal(bool)` в `CheckboxView` |
| 1.2 | `numeric/` | `QDoubleSpinBox` (`_build_float`) | `NumericControl.create(view_type="spinbox")` для `float` | нет (есть `value_changed`) |
| 1.3 | `slider/` | не используется | `SliderControl.create(...)` для `int` с малым диапазоном | нет (есть `value_changed`) |
| 1.4 | `spinbox/` | `QSpinBox` (`_build_int`) | `SpinBoxControl.create(...)` для `int` (большой диапазон или без `meta.min/max`) | нет (есть `value_changed`) |
| 1.5 | `compound/` | `ColorTripletWidget` (62 LOC, 3 × `QSpinBox`) | `CompoundNumericControl.create(...)` + удаление `ColorTripletWidget` | нет |
| 1.6 | `label/` | `QLabel` напрямую (`_build_unsupported`) | оставить `QLabel` — `LabelView` без presenter для read-only не даёт выгоды | нет |
| 1.7 | `group/` | нет аналога | используется внутри `numeric/`, `spinbox/`, `slider/` фасадов | **+** `value_changed: Signal(float)` proxy из `LabeledNumericGroupView` |
| 1.8 | **`combo/` (новый)** | `QComboBox` (`_build_literal`) | **создать в Phase 2** (Traits+Presenter+View+Facade, 8-й компонент) | **+** новый пакет |

**Итог по правкам фреймворка:** добавить `value_changed: Signal` в 2 view (`CheckboxView`, `LabeledNumericGroupView` — proxy). В `SpinBoxValueView` и `SliderValueView` сигнал **уже есть** (см. 1.3, 1.4). Создать `combo/` пакет (6 файлов). Поменять `ActionBus.execute() -> bool` (отдельный блокер из плана Phase 2).

---

## 1.1 `checkbox/` — Checkbox

**Файлы:** [`checkbox/`](../../multiprocess_framework/modules/frontend_module/components/checkbox/) (389 LOC: `config.py` 27, `view.py` 108, `presenter.py` 164, `facade.py` 78, `defaults.py` 12)

### API

- **`CheckboxControl.create(registers_manager, binding, view_config=None, current_access_level=0, hooks=None) -> CheckboxControlResult`** — статическая фабрика; возвращает `(widget: CheckboxView, presenter: CheckboxPresenter)`.
- **`CheckboxView(position: Literal["left","right","top","bottom"]="left")`** — `QLabel` + `QCheckBox` 44×44 px, четыре варианта layout. Методы: `setup(label, tooltip, enabled)`, `set_value`, `set_value_silent`, `get_value`, `set_enabled`, `on_changed(callback)`, `show_error(msg) → QMessageBox`.
- **`CheckboxViewConfig(BaseControlConfig)`** — `position`, плюс наследованные `label`, `tooltip`, `enabled`, `access_level`, `required_view_permission`, `required_edit_permission`.
- **`CheckboxPresenter`** — `SchemaTrait` + `SyncTrait` + `AccessTrait`. Эмитит hooks: `on_write_committed`, `on_write_rejected` (при `SyncTrait.write` → False), `on_access_denied` (при `!can_modify()`).

### Фичи (сверх сырого `QCheckBox`)

- **RegisterAdapter binding** — `binding.register_name + field_name` → запись и подписка через `SyncTrait`.
- **Access-control** — `effective_access_level` из `SchemaTrait` (max между `binding.access_level` и `meta.access_level`) → `setEnabled(can_modify())`. RBAC: `required_view_permission` (скрыть) / `required_edit_permission` (disable).
- **Hooks-наблюдатели** — `ControlHooks` callbacks при write/reject/access_denied.
- **`refresh_metadata()`** — пересчёт label/tooltip/access при смене регистра.
- **`set_access_context(AccessContext)`** — реакция на login/logout/смену роли.
- **Silent-sync** — внешние изменения (от другого источника) приходят через `SyncTrait.subscribe` → `set_value_silent` (без обратной записи).

### Прототипный аналог

[`factory.py:_build_bool`](../../multiprocess_prototype/frontend/forms/factory.py#L159-L173) — `QCheckBox(parent)`, `setChecked(default)`, отдельный `QLabel`. Связка с регистром — снаружи через `FieldEditor.change_signal → tab._on_field_changed → V2ActionBuilder → ActionBus`.

### Решение для Phase 2

**Использовать `CheckboxControl.create(...)`** в `_build_bool`. Маппинг:
- `registers_manager` ← `form_ctx.registers_manager` (через мост `ActionBusRegistersManager`)
- `binding` ← `BindingConfig(fi.plugin_name, fi.field_name)`
- `view_config` ← `CheckboxViewConfig(label=fi.title, tooltip=fi.meta.info, position="left")` (либо `defaults.checkbox_left`)
- `current_access_level` ← `form_ctx.current_access_level`
- `hooks` ← `ControlHooks(on_write_rejected=show_error, on_access_denied=show_toast)`

### Правка фреймворка

**Добавить `value_changed: Signal(bool)`** в `CheckboxView` (3-5 строк). Эмит в `on_changed`-обвязке (`stateChanged → callback → emit value_changed`). Это публичный API для composability с `FieldEditor.change_signal` (см. план Phase 2 — observability в `RegisterView`).

### Открытые вопросы

- Использовать `CheckboxViewConfig.position="left"` или `defaults.checkbox_left()`? — выбрать в Phase 2 по симметрии с другими 9 builders.

---

## 1.2 `numeric/` — Numeric (универсальный slider/spinbox)

**Файлы:** [`numeric/`](../../multiprocess_framework/modules/frontend_module/components/numeric/) (395 LOC: `config.py` 46, `presenter.py` 229, `facade.py` 83, `defaults.py` 14). **Свой view отсутствует** — фасад собирает `LabeledNumericGroupView` через [`group/labeled_numeric_factory.py`](../../multiprocess_framework/modules/frontend_module/components/group/labeled_numeric_factory.py).

### API

- **`NumericControl.create(registers_manager, binding, view_config=None, current_access_level=0, legacy_context=None, hooks=None) -> NumericControlResult`** — фасад. `view_config.view_type ∈ {"slider", "spinbox"}` определяет, какой value-view создать.
- **`NumericViewConfig(BaseControlConfig)`** — `view_type`, `show_ticks`, `tick_interval`, `touch_keyboard`, `touch_keyboard_factory`, `min_val`, `max_val`, `label_position`.
- **`NumericPresenter`** — `SchemaTrait` + `SyncTrait` + **`DebounceTrait(ms=100)`** + `AccessTrait` + `ValueTransformer` (+ опциональный `LegacySyncTrait` для совместимости с `ui_elements`/`controls`).
- **Контракт View:** `INumericView` (методы `setup`, `set_range`, `set_validator_int/float`, `set_value_silent`, `get_value`, `set_enabled`, `on_changed`, `on_finished`, `get_legacy_element`, `show_error`).

### Фичи (сверх сырого `QDoubleSpinBox`)

- **DebounceTrait** — `_on_changing` (движение слайдера / valueChanged) задерживается на 100 мс; `_on_finished` (Enter / editingFinished) пишет сразу с отменой debounce. Защита от штормов write при перетаскивании слайдера / зажатом spin-arrow.
- **ValueTransformer** — `meta.transfer_k` (scale storage→UI) и `meta.round_k` (decimals); `clamp_to_range`, `to_ui`, `to_storage`. Например, для `meta.transfer_k=0.01` UI показывает `2.50`, хранится `250`.
- **Touch-keyboard** — `TouchKeyboardConfig` или `touch_keyboard_factory` → mini/full клавиатура подключается к `QLineEdit` внутри slider/spinbox. Для тачскрин-стенда.
- **`set_range/set_validator_int/float`** — рассчитываются из `ResolvedMeta` (через `SchemaTrait`) → `min/max/step/decimals`.

### Прототипный аналог

[`factory.py:_build_float`](../../multiprocess_prototype/frontend/forms/factory.py#L252-L293) — `QDoubleSpinBox`, ручной `setRange`, `setDecimals(meta.round_k)`, `setSingleStep(meta.transfer_k)`, `setSuffix(unit)`. Никакого debounce, никакого touch-keyboard, никакого transform для storage↔UI.

### Решение для Phase 2

**Использовать `NumericControl.create(view_type="spinbox", ...)`** в `_build_float`:
- `min_val/max_val` ← `field_info.min_value/max_value`
- `decimals` — присутствует автоматически через `ValueTransformer(meta.round_k)`
- `suffix` (unit) — **не покрыт** `NumericViewConfig` напрямую; пока остаётся проблемой (см. «Открытые вопросы»)

Slider-режим (`view_type="slider"`) — отдельно для `int` с малым диапазоном (см. 1.3).

### Правка фреймворка

Не требуется (`value_changed` уже есть в `SpinBoxValueView` и `SliderValueView`; debounce и touch-keyboard работают).

### Открытые вопросы

- **`suffix` (unit) в `NumericViewConfig`** — прототипный `_build_float` показывает ` mm` / ` ms` после числа через `QDoubleSpinBox.setSuffix`. В `NumericViewConfig` поля нет. Варианты: (a) добавить `suffix: Optional[str]`; (b) показывать unit в label (`f"{title} ({unit})"`); (c) сохранить как в прототипе через label. Решить в Phase 2.1+. Дефолт: показывать в label (минимум кода).
- **Slider vs SpinBox для `int`** — критерий выбора в плане Phase 2 (см. 1.3 / 1.4).

---

## 1.3 `slider/` — Slider (числовое поле + ползунок)

**Файлы:** [`slider/`](../../multiprocess_framework/modules/frontend_module/components/slider/) (349 LOC: `config.py` 35, `view.py` 135, `presenter.py` 39, `facade.py` 107, `defaults.py` 6)

### API

- **`SliderControl.create(registers_manager, binding, view_config=None, current_access_level=0, legacy_context=None, hooks=None) -> SliderControlResult`** — фасад. Внутри собирает `LabeledNumericGroupView` (Label + `SliderValueView`).
- **`SliderConfig(BaseControlConfig)`** — `show_ticks`, `tick_interval`, `min_val`, `max_val`, `label_position`. **Без touch_keyboard** (есть в SliderValueView через TouchKeyboardConfig — пробрасывается опосредованно).
- **`SliderValueView`** — `QLineEdit` (с QDoubleValidator или QIntValidator) + `QSlider` (Horizontal). **`value_changed: Signal(float)` и `value_finished: Signal(float)` УЖЕ ОБЪЯВЛЕНЫ** ([slider/view.py:33-34](../../multiprocess_framework/modules/frontend_module/components/slider/view.py#L33-L34)).
- **`SliderPresenter`** — тонкий наследник `NumericPresenter` с `control_kind="slider"`; вся логика debounce/sync/access — там.

### Фичи (сверх сырого `QSlider`)

- **Двойной ввод** — клавиатурный `QLineEdit` + drag `QSlider`. Touch-keyboard опционально для тачскрина.
- **`wheelEvent = lambda e: None`** — отключён скролл-мыши (защита от случайного изменения при скроллинге формы).
- **Tick marks** — `setTickPosition(QSlider.TicksBelow)`, настраиваемый интервал.
- **Validator** — `QIntValidator` / `QDoubleValidator(StandardNotation)` подключается к `QLineEdit` в зависимости от `meta.round_k`.
- **Step** — `set_range(min, max, step)` пересчитывает диапазон под целочисленный internal-pos `QSlider`.
- **Все фичи `NumericPresenter`** — debounce, transform, access, hooks.

### Прототипный аналог

Не используется в прототипе (`_build_int` и `_build_float` дают только spinbox-варианты). Slider — новая возможность.

### Решение для Phase 2

**Использовать `SliderControl.create(...)`** в `_build_int` (и потенциально `_build_float`) **по критерию**: если `meta.min_value` и `meta.max_value` заданы И диапазон ≤ 1000 — рендерить slider, иначе spinbox.

Критерий уточняется в Phase 2.1+. Альтернатива — явный флаг `meta.ui_hint="slider"` (потребует правки `FieldMeta`).

### Правка фреймворка

Не требуется (`value_changed` уже есть). `SliderConfig` не имеет полей `touch_keyboard*`, как у `SpinBoxConfig` — потенциально стоит добавить для симметрии, но не блокер.

### Открытые вопросы

- **Range-критерий slider/spinbox** — `≤ 1000` обсуждается, но конкретное число — Phase 2.1 после первых ползунков.
- **Touch-keyboard для slider** — пробрасывать из формы или сразу через `SliderConfig` (как в `SpinBoxConfig`). Симметрия.

---

## 1.4 `spinbox/` — SpinBox (целочисленное значение через QDoubleSpinBox)

**Файлы:** [`spinbox/`](../../multiprocess_framework/modules/frontend_module/components/spinbox/) (272 LOC: `config.py` 36, `view.py` 87, `presenter.py` 39, `facade.py` 86, `defaults.py` 5)

### API

- **`SpinBoxControl.create(registers_manager, binding, view_config=None, current_access_level=0, legacy_context=None, hooks=None) -> SpinBoxControlResult`** — фасад. Внутри `_spinbox_config_to_numeric_view_config(config)` строит `NumericViewConfig(view_type="spinbox")`, далее `create_labeled_numeric_view`.
- **`SpinBoxConfig(BaseControlConfig)`** — `min_val`, `max_val`, `label_position`, **`touch_keyboard`**, **`touch_keyboard_factory`** (в отличие от `SliderConfig`, поля присутствуют здесь явно).
- **`SpinBoxValueView`** — `QDoubleSpinBox`. **`value_changed: Signal(float)` и `value_finished: Signal(float)` УЖЕ ОБЪЯВЛЕНЫ** ([spinbox/view.py:25-26](../../multiprocess_framework/modules/frontend_module/components/spinbox/view.py#L25-L26)). Touch-keyboard подключается к `lineEdit()` через `install_touch_keyboard_on_line_edit`.
- **`SpinBoxPresenter`** — тонкий наследник `NumericPresenter` с `control_kind="spinbox"`.

### Фичи (сверх сырого `QSpinBox`)

- **`QDoubleSpinBox` с decimals=0** — единый API для int/float (`set_validator_int` → `setDecimals(0)`, `set_validator_float` → `setDecimals(4)`).
- **Touch-keyboard** — нативно через `TouchKeyboardConfig`.
- **`interpretText` + `clearFocus`** на Enter в touch-keyboard handler — корректная commit-логика.
- **Все фичи `NumericPresenter`** — debounce, transform, access, hooks.

### Прототипный аналог

[`factory.py:_build_int`](../../multiprocess_prototype/frontend/forms/factory.py#L213-L249) — `QSpinBox`, ручной `setRange/setSingleStep/setSuffix`. **Range 32-bit limit:** `-2**31`/`2**31-1` — для `meta.min/max=None`. В framework `set_range` приходит из `ResolvedMeta` — без явного fallback'а, нужно убедиться что `min_val=None`/`max_val=None` корректно обрабатывается (Phase 2.1 — тест).

### Решение для Phase 2

**Использовать `SpinBoxControl.create(...)`** в `_build_int`:
- `min_val/max_val` ← `field_info.min_value/max_value` (или fallback в `NumericViewConfig`)
- если `meta.min/max=None` — пройдёт `set_range(None, None, ...)` ? — проверить (см. «Открытые вопросы»)
- Slider-альтернатива по range-критерию (см. 1.3)

### Правка фреймворка

Не требуется (`value_changed` уже есть).

### Открытые вопросы

- **Поведение при `meta.min/max=None`** — `NumericPresenter.attach_view` зовёт `self._transform.to_ui(meta.min_val)` — поведение при `None` нужно зафиксировать тестом в Phase 2.0 / 2.1.
- **Прототипный `_build_int` использует `QSpinBox` (int-only)**, а фреймворк — `QDoubleSpinBox` с `setDecimals(0)`. Поведение должно совпадать, но визуально 33-bit диапазон ≤ float53. Для большинства полей это не важно (timeout/area/threshold), но для bitmask/id — стоит проверить.

---

## 1.5 `compound/` — CompoundNumeric (массив из 3 контролов)

**Файлы:** [`compound/`](../../multiprocess_framework/modules/frontend_module/components/compound/) (313 LOC: `config.py` 46, `facade.py` 245). **Свой view и presenter отсутствуют** — фасад создаёт 3 × `NumericControl` (для `CompoundNumericControl`) или N × `NumericControl/CheckboxControl` (для `CompoundControl`).

### API

- **`CompoundNumericControl.create(registers_manager, config: CompoundNumericConfig, current_access_level=0, legacy_context=None, hooks=None) -> CompoundNumericControlResult`** — создаёт 3 × `NumericControl` для индексов `0,1,2` одного поля-массива.
- **`CompoundNumericConfig`** — `binding: BindingConfig`, `labels: List[str]` (например, `["R","G","B"]`), `view_config: Optional[NumericViewConfig]`.
- **`CompoundControl.create(...)`** — универсальный (Array mode = N × `NumericControl` для индексов 0..N-1; Mixed mode = `List[(BindingConfig, ChildConfig)]`).
- **`ControlFactory.create(...)`** — единая точка входа: принимает `NumericViewConfig | CheckboxViewConfig | CompoundControlConfig`, dispatch'ит в соответствующий `*Control.create`.

### Фичи

- **Per-index binding** — `BindingConfig(..., index=i)` — каждый контрол пишет/читает `register.field[i]` (`SyncTrait` понимает `index`).
- **Spacing/orientation** — `CompoundControlConfig.orientation ∈ {horizontal, vertical}`, `spacing` между элементами.
- **Mixed mode** — может содержать разнотипные контролы (slider + checkbox + spinbox) в одной группе, по списку `(binding, view_config)`.
- **Все фичи `NumericPresenter`** для каждого ребёнка.

### Прототипный аналог

[`factory.py:_build_color3`](../../multiprocess_prototype/frontend/forms/factory.py#L196-L210) → [`widgets/color_picker.py:ColorTripletWidget`](../../multiprocess_prototype/frontend/forms/widgets/color_picker.py) (62 LOC) — 3 × `QSpinBox(0..255)` в `QHBoxLayout`. `get_value() → (R, G, B)`, `set_value((r,g,b)) → block + set + emit`. Сигнал `value_changed = Signal()` (без аргументов). Получение значения — через `getter`, который возвращает tuple.

### Решение для Phase 2

**Использовать `CompoundNumericControl.create(...)`** в `_build_color3`:
```
config = CompoundNumericConfig(
    binding=BindingConfig(fi.plugin_name, fi.field_name),
    labels=["R","G","B"],
    view_config=NumericViewConfig(view_type="spinbox", min_val=0, max_val=255),
)
```

**Удалить** [`multiprocess_prototype/frontend/forms/widgets/color_picker.py`](../../multiprocess_prototype/frontend/forms/widgets/color_picker.py) и убрать экспорт из `widgets/__init__.py`.

### Правка фреймворка

Не требуется.

### Открытые вопросы

- **Получение целого triplet значения** — `_build_color3` в прототипе отдавал tuple через `getter`. Фреймворк не предоставляет агрегированный getter — `CompoundNumericControlResult.results: List[NumericControlResult]`, каждый со своим presenter. `FieldEditor.getter` должен возвращать tuple — придётся писать `lambda: tuple(r.presenter._sync.read() for r in results)` или похожее. Альтернатива — писать каждый компонент через `binding.index=i` без агрегатора, и `FieldEditor` для `color3` строить иначе (запись поэлементная, чтение по index). Решить в Phase 2.1+.
- **Сигнал `value_changed` для всего composite** — нет нативного. В план Phase 2 эта особенность вписана: `FieldEditor.change_signal = view.value_changed` через result.widget. Для color3 — придётся прокинуть отдельно (или агрегировать `Signal` из 3 детей).

---

## 1.6 `label/` — Label (read-only подпись)

**Файлы:** [`label/`](../../multiprocess_framework/modules/frontend_module/components/label/) (56 LOC: `config.py` 21, `view.py` 29, **нет presenter и facade**).

### API

- **`LabelView`** — `QLabel` в `QHBoxLayout`. Методы: `setup(text, tooltip)`, `set_enabled(enabled)`.
- **`LabelConfig(BaseControlConfig)`** — `position`, `visible`. **Без `value_changed`** (read-only).

### Фичи

- Используется как часть других компонентов (`LabeledNumericGroupView` композирует `LabelView` + value-view).
- Самостоятельной фабрики (`LabelControl.create`) **нет** — компонент пассивный.

### Прототипный аналог

[`factory.py:_build_unsupported`](../../multiprocess_prototype/frontend/forms/factory.py#L352-L366) — `QLabel(repr(default))` disabled. Это путь для «не поддерживаемых» типов (показать значение, не редактировать).

[`factory.py:_make_label`](../../multiprocess_prototype/frontend/forms/factory.py#L142-L148) — `QLabel(title (unit))` — используется во всех 9 builders как имя поля. **Это не read-only поле**, это часть `FieldEditor.label`.

### Решение для Phase 2

**`_build_unsupported`** — оставить сырой `QLabel(repr(default))` disabled. `LabelView`/`LabelConfig` не дают существенной выгоды для read-only «значение поля» (нет access-control, нет binding — оно и не нужно).

**`_make_label`** (создаёт label для каждого поля рядом с виджетом) — **не нужен после Phase 2**: framework view-классы (`CheckboxView`, `LabeledNumericGroupView`) уже содержат label внутри. Только `_build_str_short/long/path` сохранят отдельный `QLabel`, потому что для них framework-аналога нет.

### Правка фреймворка

Не требуется.

### Открытые вопросы

- **`LabelControl.create()` фасад для read-only биндинга** — потенциально полезно для отображения «текущего значения регистра без записи». Не блокер Phase 2.

---

## 1.7 `group/` — Group (Label + Value композит)

**Файлы:** [`group/`](../../multiprocess_framework/modules/frontend_module/components/group/) (285 LOC: `config.py` 62, `view.py` 105, `labeled_numeric_factory.py` 62, `defaults.py` 31). **Свой presenter и facade отсутствуют**.

### API

- **`LabeledNumericGroupView`** — `QWidget`, композирует `LabelView` + `SliderValueView | SpinBoxValueView` (через `labeled_numeric_factory.create_labeled_numeric_view`). Реализует **`INumericView`** для `NumericPresenter`. Методы: `setup`, `set_value(_silent)`, `get_value`, `set_enabled`, `set_range`, `set_validator_int/float`, `on_changed(cb)` (делегат в `value_view.on_changed`), `on_finished(cb)`, `show_error(msg)`, `get_legacy_element()`.
- **`GroupConfig` / `LabeledNumericGroupConfig`** — описание (config-driven сборка из `children: List[ChildConfig]`).
- **`label_slider_default`, `label_spinbox_default`, `label_bgr_slider_default`** — фабрики предустановленных групп.

### Фичи

- **INumericView для `NumericPresenter`** — критическая обёртка, чтобы Numeric/Slider/SpinBox фасады могли использовать единый `NumericPresenter` поверх композита.
- **Label position** — `"left" | "right" | "top" | "bottom"` через `QHBoxLayout`/`QVBoxLayout`.
- **`get_legacy_element()`** — для совместимости с `LegacySyncTrait` (`ui_elements`/`controls`).
- **`set_value_silent`** делегирует во `value_view`.

### Прототипный аналог

В прототипе нет аналога — `FieldEditor.label` + `FieldEditor.widget` хранятся отдельно, `form_builder.build_form_for_register` кладёт их через `QFormLayout.addRow(label, widget)`. После Phase 2 — label внутри `LabeledNumericGroupView`, и `addRow("", widget)` для value-полей.

### Решение для Phase 2

**Используется как value-view внутри `NumericControl` / `SpinBoxControl` / `SliderControl`** — отдельно в прототипе не вызывается. Только маппинг layout: `QFormLayout.addRow("", editor.widget)` (label-меньше) для value-полей, `addRow(label, widget)` для str/path (где остался отдельный label).

### Правка фреймворка

**Добавить `value_changed: Signal(float)`** в `LabeledNumericGroupView` (3-5 строк), который проксирует из `self._value_view.value_changed`. План Phase 2 требует это для observability (`FieldEditor.change_signal`).

Подключение в `__init__`: `self._value_view.value_changed.connect(self.value_changed.emit)`.

### Открытые вопросы

- **Поддержка нечисловых value-view** — `LabeledNumericGroupView` жёстко завязан на `INumericView`. Для `combo/` (1.8) понадобится либо отдельный `LabeledComboGroupView`, либо более общий `LabeledControlGroupView`. Решить в Phase 2 при создании `combo/`.

---

## 1.8 `combo/` — ComboBox (НОВЫЙ компонент)

**Файлы:** **отсутствуют в фреймворке** — создаются в Phase 2.

### API (предлагаемый)

```
combo/
├── __init__.py
├── config.py    — ComboBoxConfig(BaseControlConfig): items: list[Any], item_labels: list[str] | None, label_position
├── view.py      — ComboBoxView(QWidget): QLabel + QComboBox, value_changed: Signal(int) (по index) или Signal(str)
├── presenter.py — ComboBoxPresenter: SchemaTrait + SyncTrait + AccessTrait (+ value_transform str↔T)
├── facade.py    — ComboBoxControl.create(rm, binding, view_config, current_access_level, hooks) -> ComboBoxControlResult
└── defaults.py  — combo_left, combo_right
```

### Дизайн

- **Items** — `list[Any]` (произвольные значения; `Literal[1, 2, 3]` → `[1, 2, 3]`; `Literal["a","b"]` → `["a","b"]`).
- **Item labels** — опциональные строковые подписи (`item_labels: list[str] | None = None` → fallback `str(item)`).
- **`set_value(value)` / `get_value()`** — работают со значением из `items` (не со строкой). Внутри `ComboBoxPresenter` конвертация `value ↔ str(value)` для `QComboBox.setCurrentText`.
- **Без debounce** — выбор пункта = одна запись (как checkbox).
- **`value_changed: Signal(object)`** — emit с значением из items (не index, не строка).

### Прототипный аналог

[`factory.py:_build_literal`](../../multiprocess_prototype/frontend/forms/factory.py#L175-L193) — `QComboBox`, `addItem(str(item))` для каждого `get_args(Literal[...])`, `setCurrentText(str(default))`. Connected to `combo.currentTextChanged` (всегда str). При записи в регистр (`Literal[1,2,3]`) — нужна конвертация `str → int`, чего сейчас нет (баг — записывается строка "1" вместо int 1).

### Решение для Phase 2

**Создать `combo/` пакет** (6 файлов, паттерн Traits+Presenter+View+Facade). Использовать в `_build_literal`:
```
items = list(get_args(field_info.field_type))
ComboBoxControl.create(
    bus_rm,
    BindingConfig(fi.plugin_name, fi.field_name),
    ComboBoxConfig(items=items, label=fi.title),
    current_access_level=form_ctx.current_access_level,
    hooks=ControlHooks(...),
)
```

### Правка фреймворка

**Новый пакет** + регистрация в `components/__init__.py` + тесты в `multiprocess_framework/tests/frontend_module/components/test_combo.py` (5-7 тестов: setup, set_value/get_value через адаптер, access-denied, items rendering, value_changed signal, конвертация типа для `Literal[int]`).

### Открытые вопросы

- **`Literal[]` с не-str значениями** — `Literal[1, 2, 3]` хранит int, `QComboBox` работает со строкой → `ComboBoxPresenter` конвертирует `str ↔ item_value` по `items` list. Юнит-тест на тип-возврат.
- **Item labels отдельно от value** — для `Literal["webcam","hikvision"]` отображать «Webcam» / «Hikvision». Поле `item_labels` опционально; если None — использовать `str(value)`.
- **Поведение если current value не в items** — `setCurrentText` устанавливает текст, но `currentIndex()=-1` → возможны баги в `get_value`. Защитная логика: если значение отсутствует в `items`, добавить временный пункт и подсветить как «invalid».

---

## Связь с правками фреймворка в Phase 2

**ActionBus** (отдельный блокер из плана):
- `ActionBus.execute(action) -> bool` — изменить сигнатуру (сейчас `-> None`), 3 теста (success → True, `pre_execute_hook` False → False, handler not found → False).

**Signals (`value_changed`):**
- `CheckboxView.value_changed: Signal(bool)` — **добавить**.
- `SpinBoxValueView.value_changed: Signal(float)` — **уже есть** ✓.
- `SliderValueView.value_changed: Signal(float)` — **уже есть** ✓.
- `LabeledNumericGroupView.value_changed: Signal(float)` — **добавить** (proxy из `value_view`).

**Новый пакет:**
- `components/combo/` (6 файлов) + `components/__init__.py` экспорт + `tests/test_combo.py` (5-7 тестов).

---

## Verification (PR1)

- [x] `docs/refactors/widgets-component-review.md` создан, 8 секций
- [ ] `plans/frontend-widgets-cleanup.md` — чекбоксы 1.1–1.7 отмечены `[x]`, добавлен 1.8 (см. следующий шаг)
- [x] Все правки фреймворка зафиксированы (value_changed × 2, combo пакет, ActionBus.execute → bool)

---

## Связанные документы

- План Phase 1+2: [`plans/frontend-widgets-cleanup-phase2.md`](../../plans/frontend-widgets-cleanup-phase2.md)
- Родительский план: [`plans/frontend-widgets-cleanup.md`](../../plans/frontend-widgets-cleanup.md)
- Прототипная фабрика: [`multiprocess_prototype/frontend/forms/factory.py`](../../multiprocess_prototype/frontend/forms/factory.py)
- Реорг widgets v3 (предыдущий refactor): [`docs/refactors/2026-04_widgets_reorg.md`](2026-04_widgets_reorg.md)
