# Plan: Track 1.2 + 1.3 — SliderControl + NumericControl (form_ctx)

- **Slug:** frontend-widgets-track-1-2-1-3
- **Дата:** 2026-05-15
- **Статус:** DRAFT
- **Ветка:** refactor/frontend-widgets-cleanup
- **Родительский план:** [`rollout-finish.md`](rollout-finish.md), секции «Track 1» (1.2, 1.3) и «Track 2» (2.2)
- **Верхнеуровневая карта:** [`plan.md`](plan.md)
- **Образец:** [`track-1-1-spinbox.md`](track-1-1-spinbox.md) — полностью зелёный, используется как шаблон

---

## Зачем

Track 1.1 закрыл вертикальный срез для SpinBoxControl: dual-mode write в `NumericPresenter._write()`,
`SpinBoxControl.create` с `form_ctx`, `_build_int_binding_aware` в factory. Этот паттерн теперь тиражируется
на Slider (Track 1.2) и NumericControl/float (Track 1.3). Slider — специализация `NumericPresenter` с
`view_type="slider"`, NumericControl — универсальная обёртка с конфигом `NumericViewConfig`. Оба получают
ту же dual-mode логику «бесплатно» через наследование от `NumericPresenter`, остаётся только:
(а) добавить `form_ctx` kwarg в facades + пробросить в presenter; (б) создать binding-aware builders в factory;
(в) покрыть тестами по образцу `test_spinbox_form_ctx.py`.

---

## Ключевые факты из анализа кода

| Что | Факт |
|-----|------|
| `SliderPresenter.__init__` | Уже принимает `form_ctx` kwarg и пробрасывает в `super().__init__()` — готово |
| `NumericPresenter._write()` | Уже dual-mode (form_ctx vs SyncTrait) — наследуется Slider и Numeric |
| `SliderControl.create` | **Нет** `form_ctx` kwarg — это единственная правка в facade.py |
| `NumericControl.create` | **Нет** `form_ctx` kwarg — то же самое |
| `_build_int` в factory | Уже имеет slider guard: `is_slider → legacy до Track 1.2`; guard нужно превратить в dispatch на `_build_slider_binding_aware` |
| `_build_float` в factory | Нет `form_ctx` kwarg и нет binding-aware пути — только legacy QDoubleSpinBox |
| `result.widget` у Slider/SpinBox/Numeric | `LabeledNumericGroupView` с методами `get_value()` + `set_value_silent()` на верхнем уровне |
| `SliderConfig` | Имеет `min_val`, `max_val` — передаются через `_slider_config_to_numeric_view_config` в `NumericViewConfig` |
| `NumericViewConfig` | Имеет `min_val`, `max_val`, `view_type` (default="slider") |
| `_KIND_SLIDER` | Отдельный sentinel не нужен: slider распознаётся через `meta.widget="slider"` + kind=`_KIND_INT`. Float-поля с slider отсутствуют в системе |
| `CardsFieldFactory.create` dispatch | Сейчас только для `_KIND_BOOL` и `_KIND_INT`; нужно добавить `_KIND_FLOAT` |
| Тест-образец | `test_spinbox_form_ctx.py` — 4 теста, все используют `qapp` fixture + `_FakeRegistersManager` + `ActionBus` + `_FakeFieldSetHandler` |

---

## Решения по ключевым вопросам

### 1. Slider guard в `_build_int` — dispatch или удалить?

**Решение: преобразовать guard в dispatch на `_build_slider_binding_aware`.**

Текущий guard:
```python
if form_ctx is not None and not is_slider:
    return _build_int_binding_aware(field_info, form_ctx, parent)
# slider → legacy (до Track 1.2)
```

После Track 1.2 guard становится dispatch:
```python
if form_ctx is not None:
    if is_slider:
        return _build_slider_binding_aware(field_info, form_ctx, parent)
    return _build_int_binding_aware(field_info, form_ctx, parent)
# Legacy: raw QSpinBox (form_ctx=None или non-plugin callers)
```

Mотивация: slider с form_ctx должен создавать SliderControl (правильный UI), а не SpinBox.
Для slider без form_ctx (SettingsSystem, GUI-локальные формы) — по-прежнему legacy raw QSpinBox.
Это корректно: slider в GUI-локальных формах не имеет binding и не нуждается в SliderControl.

### 2. Нужен ли `_KIND_SLIDER` sentinel?

**Решение: нет.** Slider определяется как `meta.widget="slider"` при kind=`_KIND_INT`. Добавление
нового kind усложнит `_resolve_kind` и `_BUILDERS`. Достаточно dispatch'а внутри `_build_int`.

### 3. `result.widget` у SliderControl — методы интерфейса?

**Факт:** `SliderControl.create` возвращает `SliderControlResult(widget=LabeledNumericGroupView, ...)`.
`LabeledNumericGroupView` имеет `get_value()` и `set_value_silent()` напрямую (строки 77-81 group/view.py).
Паттерн `_build_int_binding_aware` применяется без изменений — те же `result.widget.get_value` и
`result.widget.set_value_silent`.

### 4. `NumericControl` vs `SpinBoxControl` — в чём разница?

`SpinBoxControl` — специализированный фасад только для spinbox (использует `SpinBoxConfig`, `SpinBoxPresenter`).
`NumericControl` — универсальный фасад (принимает `NumericViewConfig` с `view_type=slider|spinbox`, создаёт
`NumericPresenter` напрямую). В factory `_build_float` использует `NumericControl` потому что float-поля
рендерятся как QDoubleSpinBox-стиль; в binding-aware пути `_build_float_binding_aware` тоже использует
`NumericControl.create` с `NumericViewConfig(view_type="spinbox")` (или просто дефолт).

---

## Порядок выполнения

### Phase 1: SliderControl facade (Task 1.2.1)

- Task 1.2.1: `form_ctx` kwarg в `SliderControl.create` [PENDING]

### Phase 2: Factory slider (Task 1.2.2)

- Task 1.2.2: `_build_slider_binding_aware` + преобразование slider guard в dispatch [PENDING]

### Phase 3: Тесты Slider (Task 1.2.3)

- Task 1.2.3: 4 теста в `test_slider_form_ctx.py` [PENDING]

### Phase 4: NumericControl facade (Task 1.3.1)

- Task 1.3.1: `form_ctx` kwarg в `NumericControl.create` [PENDING]

### Phase 5: Factory float (Task 1.3.2)

- Task 1.3.2: `_build_float_binding_aware` + `form_ctx` kwarg в `_build_float` + dispatch в `CardsFieldFactory.create` [PENDING]

### Phase 6: Тесты NumericControl (Task 1.3.3)

- Task 1.3.3: 4 теста в `test_numeric_form_ctx.py` [PENDING]

---

## Task 1.2.1 — form_ctx kwarg в SliderControl.create

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** добавить `form_ctx: "FormContext | None" = None` в `SliderControl.create` и пробросить в `SliderPresenter.__init__`

**Context:** `SliderPresenter.__init__` уже принимает `form_ctx` kwarg (добавлен в Track 1.1 ревьюером).
`SliderControl.create` — единственное место без этого kwarg. По аналогии с `SpinBoxControl.create` (строки 56-66
spinbox/facade.py). `NumericPresenter._write()` dual-mode уже работает через наследование.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/components/slider/facade.py` — изменить

**Steps:**
1. Добавить в топ файла `from typing import TYPE_CHECKING` (уже есть `from __future__ import annotations`).
   Добавить блок:
   ```python
   if TYPE_CHECKING:
       from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext
   ```

2. В сигнатуре `SliderControl.create` добавить kwarg последним именованным параметром (после `hooks`):
   ```python
   *,
   form_ctx: "FormContext | None" = None,
   ```

3. В вызове `SliderPresenter(...)` внутри `create` добавить `form_ctx=form_ctx` (SliderPresenter уже принимает).

4. Добавить секцию для `form_ctx` в docstring `create` — по аналогии с расширенным docstring
   `SpinBoxControl.create` (строки 77-83 spinbox/facade.py):
   - production-путь (form_ctx передан): write через ActionBus, coalescing, undo/redo, IPC bridge
   - legacy-путь (form_ctx=None): прямая запись через RegisterAdapter (для non-plugin callers)

**Acceptance criteria:**
- [ ] `SliderControl.create(rm, binding, view_config, current_access_level=0, legacy_context=None, hooks=None, *, form_ctx=None)` — сигнатура корректна
- [ ] `ruff check multiprocess_framework/modules/frontend_module/components/slider/facade.py` — 0 ошибок
- [ ] `ruff format --check multiprocess_framework/modules/frontend_module/components/slider/facade.py` — 0 ошибок
- [ ] `python -c "from multiprocess_framework.modules.frontend_module.components.slider import SliderControl; print('ok')"` — без ImportError
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — все существующие тесты PASSED

**Out of scope:** не трогать `SliderPresenter`, `SliderConfig`, `SliderValueView` — они не меняются в этой задаче.

**Edge cases:** убедиться что `form_ctx` добавляется как keyword-only (после `*,`) — не позиционный параметр.
`legacy_context` уже есть как позиционный — `form_ctx` идёт отдельно.

**Dependencies:** нет (SliderPresenter уже готов)

---

## Task 1.2.2 — _build_slider_binding_aware + преобразование slider guard в _build_int

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** создать `_build_slider_binding_aware()` в factory.py и заменить slider guard в `_build_int` на dispatch

**Context:** `_build_int` содержит guard «slider → legacy до Track 1.2» (строки 372-376 factory.py):
```python
if form_ctx is not None and not is_slider:
    return _build_int_binding_aware(field_info, form_ctx, parent)
```
Нужно добавить `_build_slider_binding_aware` по образцу `_build_int_binding_aware` (строки 269-318)
и изменить guard на dispatch. `SliderControl.create` теперь принимает `form_ctx` (Task 1.2.1).

**Файлы:**
- `multiprocess_prototype/frontend/forms/factory.py` — изменить

**Steps:**
1. Прочитать актуальные строки 269-415 factory.py перед правкой (убедиться в текущем состоянии guard).

2. Добавить функцию `_build_slider_binding_aware` сразу после `_build_int_binding_aware` (перед `_build_literal`):
   ```python
   def _build_slider_binding_aware(
       field_info: FieldInfo,
       form_ctx: FormContext,
       parent: QWidget | None = None,
   ) -> FieldEditor:
       """SliderControl через FormContext.write — binding-aware путь для int-полей c widget="slider".

       Coalescing, undo/redo, IPC bridge — автоматически через ActionBus.

       NOTE: min/max берётся из FieldInfo; unit — из FieldMeta в RM (SliderConfig не имеет suffix).
       """
       from multiprocess_framework.modules.frontend_module.components.base.config import (
           BindingConfig,
       )
       from multiprocess_framework.modules.frontend_module.components.slider import (
           SliderConfig,
           SliderControl,
       )

       binding = BindingConfig(
           field_info.plugin_name or "",
           field_info.field_name or "",
       )
       view_config = SliderConfig(
           label=field_info.title,
           min_val=float(field_info.min_value) if field_info.min_value is not None else None,
           max_val=float(field_info.max_value) if field_info.max_value is not None else None,
       )

       result = SliderControl.create(
           form_ctx.registers_manager,
           binding,
           view_config,
           current_access_level=form_ctx.access_level,
           form_ctx=form_ctx,
       )

       label = _make_label(field_info)
       # change_signal=None: binding-aware путь пишет через presenter →
       # FormContext.write, RegisterView НЕ должен дублировать write.
       return FieldEditor(
           field_info=field_info,
           widget=result.widget,
           getter=result.widget.get_value,
           setter=result.widget.set_value_silent,
           change_signal=None,  # type: ignore[arg-type]
           label=label,
       )
   ```

3. Изменить dispatch в `_build_int` — заменить guard на двойной dispatch:
   ```python
   if form_ctx is not None:
       if is_slider:
           return _build_slider_binding_aware(field_info, form_ctx, parent)
       return _build_int_binding_aware(field_info, form_ctx, parent)
   # Legacy путь — raw QSpinBox без binding-aware моста.
   # Callers без form_ctx (SettingsSystem, GUI-локальные формы) остаются здесь.
   ```
   Удалить комментарий «Slider до Track 1.2 — тоже здесь» и строки, относящиеся к slider guard.

4. Обновить docstring `_build_int` — убрать упоминание «Track 1.2» как ограничения:
   ```python
   """QSpinBox для int (legacy) или SpinBoxControl/SliderControl (binding-aware, если form_ctx передан).

   Dispatch по meta.widget: "slider" → SliderControl, иначе → SpinBoxControl.
   """
   ```

5. Проверить что `SliderConfig` и `SliderControl` экспортируются из
   `multiprocess_framework.modules.frontend_module.components.slider` (проверить `slider/__init__.py`).

**Acceptance criteria:**
- [ ] `grep -n "Track 1.2" multiprocess_prototype/frontend/forms/factory.py` — 0 результатов (старый TODO удалён)
- [ ] `grep -n "_build_slider_binding_aware" multiprocess_prototype/frontend/forms/factory.py` — есть определение и вызов
- [ ] `_build_int(field_info, form_ctx=mock_ctx)` с `meta.widget="slider"` → вызывает `_build_slider_binding_aware`
- [ ] `_build_int(field_info, form_ctx=mock_ctx)` без meta.widget → вызывает `_build_int_binding_aware` (как прежде)
- [ ] `_build_int(field_info)` без form_ctx → legacy QSpinBox (без изменений)
- [ ] `ruff check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок
- [ ] `ruff format --check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок

**Out of scope:** не трогать `_build_float`, `_build_literal`, `CardsFieldFactory.create` dispatch — это Task 1.3.2.

**Edge cases:**
- `SliderConfig` не имеет `label` поля — проверить наследование от `BaseControlConfig`: если `label` там есть (как в `SpinBoxConfig`) — передать. Если нет — пропустить.
- `result.widget.get_value` и `result.widget.set_value_silent` — `LabeledNumericGroupView` имеет оба метода (подтверждено group/view.py строки 77-81).
- `SliderControl` может не иметь `SliderConfig` в `__init__.py` — проверить экспорт перед написанием импорта.

**Dependencies:** Task 1.2.1 (SliderControl.create принимает form_ctx)

---

## Task 1.2.3 — Тесты: SliderControl с form_ctx

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** написать 4 теста по образцу `test_spinbox_form_ctx.py`, покрывающих write, undo, legacy и access guard для SliderControl

**Context:** паттерн полностью аналогичен `test_spinbox_form_ctx.py`. Отличия:
(а) импортировать `SliderControl` и `SliderConfig` вместо SpinBox-аналогов;
(б) тест access guard — `_value_view` у Slider — `SliderValueView`, не `SpinBoxValueView`; способ проверки
виджет disabled может отличаться. Используй `presenter._access.can_modify() is False` как основную проверку,
виджет-уровень — через `widget._value_view.isEnabled()` (или `set_enabled` через view.py).

**Файлы:**
- `multiprocess_framework/modules/frontend_module/tests/test_slider_form_ctx.py` — создать новый файл

**Steps:**
1. Создать файл `test_slider_form_ctx.py` в `multiprocess_framework/modules/frontend_module/tests/`.

2. Скопировать фейки из `test_spinbox_form_ctx.py` **без изменений**:
   `_FakeRegister`, `_FakeRegistersManager`, `_FakeActionBuilder`, `_FakeFieldSetHandler`,
   fixtures `qapp`, `fake_rm`, `bus_with_handler`, `form_ctx`.

3. Написать тест `test_slider_write_via_form_ctx`:
   - `SliderControl.create(fake_rm, BindingConfig("motor", "speed"), SliderConfig(min_val=0.0, max_val=1000.0), current_access_level=0, form_ctx=form_ctx)`
   - `presenter._on_finished(42.0)`
   - Assert: `fake_rm.get_register("motor").speed == 42.0`
   - Assert: `bus_with_handler.last_action() is not None`

4. Написать тест `test_slider_undo_restores_view`:
   - Аналог `test_spinbox_undo_restores_view`: write(100.0) → undo() → rm=0.0 → view.get_value()==0.0
   - Требует `qapp` fixture

5. Написать тест `test_slider_legacy_path_no_form_ctx`:
   - `SliderControl.create(fake_rm, BindingConfig("motor", "speed"), SliderConfig())` без form_ctx
   - `presenter._on_finished(55.0)`
   - Assert: `fake_rm.get_register("motor").speed == 55.0`

6. Написать тест `test_slider_access_level_guard`:
   - `SliderControl.create(..., BindingConfig("motor", "speed", access_level=5), ..., current_access_level=0, form_ctx=form_ctx)`
   - Assert: `presenter._access.can_modify() is False`
   - `presenter._on_finished(99.0)` → `fake_rm.get_register("motor").speed == 0.0` (write заблокирован)
   - После `presenter.set_access_level(5)` → `presenter._access.can_modify() is True`

**Acceptance criteria:**
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_slider_form_ctx.py -v` — 0 FAILED
- [ ] Минимум 4 теста PASSED
- [ ] `ruff check multiprocess_framework/modules/frontend_module/tests/test_slider_form_ctx.py` — 0 ошибок
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — все существующие тесты PASSED (регрессия)

**Out of scope:** не тестировать `show_ticks`/`tick_interval`; не тестировать QSlider raw поведение; дебаунс через `_on_changing` — только `_on_finished` в тестах.

**Edge cases:**
- `SliderValueView` внутри `LabeledNumericGroupView` — доступен как `widget._value_view`. В тесте access guard
  проверять `widget._value_view.isEnabled()` осторожно: `set_enabled` в `LabeledNumericGroupView` делегирует в
  `self._value_view.set_enabled(enabled)` (group/view.py строка 83), итоговый виджет зависит от SliderValueView
  реализации. Основная проверка — через `presenter._access.can_modify()`.
- DeprecationWarning при `set_access_level` — обернуть в `warnings.catch_warnings()` как в spinbox-тестах.

**Dependencies:** Tasks 1.2.1, 1.2.2

---

## Task 1.3.1 — form_ctx kwarg в NumericControl.create

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** добавить `form_ctx: "FormContext | None" = None` в `NumericControl.create` и пробросить в `NumericPresenter.__init__`

**Context:** `NumericControl` создаёт `NumericPresenter` напрямую (не через SpinBoxPresenter/SliderPresenter).
`NumericPresenter.__init__` уже принимает `form_ctx` (добавлен в Task 1.1.1). Правка аналогична Task 1.2.1,
но ещё проще — `NumericControl.create` создаёт `NumericPresenter` без промежуточного класса.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/components/numeric/facade.py` — изменить

**Steps:**
1. Добавить в топ файла:
   ```python
   from typing import TYPE_CHECKING
   ```
   (если нет) и блок:
   ```python
   if TYPE_CHECKING:
       from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext
   ```

2. В сигнатуре `NumericControl.create` добавить kwarg keyword-only последним (после `hooks`):
   ```python
   *,
   form_ctx: "FormContext | None" = None,
   ```
   Внимание: текущая сигнатура не имеет `*,` — нужно добавить разделитель или убедиться что kwarg идёт
   как последний positional (что хуже). Предпочтительно — явный `*,` разделитель.

3. В вызове `NumericPresenter(...)` внутри `create` добавить `form_ctx=form_ctx`.

4. Добавить секцию `form_ctx` в docstring аналогично spinbox/facade.py.

**Acceptance criteria:**
- [ ] `NumericControl.create(rm, binding, view_config, current_access_level=0, legacy_context=None, hooks=None, *, form_ctx=None)` — сигнатура корректна
- [ ] `ruff check multiprocess_framework/modules/frontend_module/components/numeric/facade.py` — 0 ошибок
- [ ] `ruff format --check multiprocess_framework/modules/frontend_module/components/numeric/facade.py` — 0 ошибок
- [ ] `python -c "from multiprocess_framework.modules.frontend_module.components.numeric import NumericControl; print('ok')"` — без ImportError
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — все существующие тесты PASSED

**Out of scope:** не трогать `NumericPresenter`, `NumericViewConfig` — они не меняются. Не трогать `SpinBoxControl` и `SliderControl`.

**Edge cases:** `NumericViewConfig` по умолчанию имеет `view_type="slider"` — binding-aware путь через
NumericControl будет создавать slider-виджет. Для float-полей factory будет использовать
`NumericViewConfig(view_type="spinbox")` или дефолт "slider" — это решается в Task 1.3.2.

**Dependencies:** Task 1.1.1 (NumericPresenter принимает form_ctx — уже готово)

---

## Task 1.3.2 — _build_float_binding_aware + form_ctx kwarg в _build_float + dispatch в CardsFieldFactory

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** создать `_build_float_binding_aware()` в factory.py, добавить `form_ctx` kwarg в `_build_float` и добавить dispatch для `_KIND_FLOAT` в `CardsFieldFactory.create`

**Context:** `_build_float` (строки 418-459 factory.py) — raw QDoubleSpinBox без binding-aware. Нужно добавить
binding-aware путь через `NumericControl.create`. Нюансы по сравнению с int/slider:
(а) `NumericViewConfig` не имеет поля `decimals` — число знаков после запятой; в legacy пути оно берётся из
`meta.round_k`; в binding-aware пути это должно приходить из FieldMeta в RM через `SchemaTrait` — добавить
NOTE в docstring;
(б) `NumericViewConfig(view_type="spinbox")` нужно явно указать для float (иначе дефолт "slider");
(в) dispatch в `CardsFieldFactory.create` — аналогично `_KIND_INT`, добавить ветку для `_KIND_FLOAT`.

**Файлы:**
- `multiprocess_prototype/frontend/forms/factory.py` — изменить

**Steps:**
1. Прочитать актуальные строки 418-460 factory.py (`_build_float`) перед правкой.

2. Добавить функцию `_build_float_binding_aware` сразу после `_build_slider_binding_aware` (перед `_build_literal`):
   ```python
   def _build_float_binding_aware(
       field_info: FieldInfo,
       form_ctx: FormContext,
       parent: QWidget | None = None,
   ) -> FieldEditor:
       """NumericControl через FormContext.write — binding-aware путь для float.

       Coalescing, undo/redo, IPC bridge — автоматически через ActionBus.

       NOTE: decimals (round_k) и unit в этом пути берутся из FieldMeta в RM
       (через SchemaTrait.get_field_metadata), а не из NumericViewConfig.
       Убедись что FieldMeta корректно заполнен.
       """
       from multiprocess_framework.modules.frontend_module.components.base.config import (
           BindingConfig,
       )
       from multiprocess_framework.modules.frontend_module.components.numeric import (
           NumericControl,
           NumericViewConfig,
       )

       binding = BindingConfig(
           field_info.plugin_name or "",
           field_info.field_name or "",
       )
       view_config = NumericViewConfig(
           view_type="spinbox",  # float всегда spinbox-стиль (QDoubleSpinBox)
           label=field_info.title,
           min_val=float(field_info.min_value) if field_info.min_value is not None else None,
           max_val=float(field_info.max_value) if field_info.max_value is not None else None,
       )

       result = NumericControl.create(
           form_ctx.registers_manager,
           binding,
           view_config,
           current_access_level=form_ctx.access_level,
           form_ctx=form_ctx,
       )

       label = _make_label(field_info)
       return FieldEditor(
           field_info=field_info,
           widget=result.widget,
           getter=result.widget.get_value,
           setter=result.widget.set_value_silent,
           change_signal=None,  # type: ignore[arg-type]
           label=label,
       )
   ```

3. Добавить `form_ctx` kwarg в `_build_float`:
   ```python
   def _build_float(
       field_info: FieldInfo,
       parent: QWidget | None = None,
       *,
       form_ctx: FormContext | None = None,
   ) -> FieldEditor:
       """QDoubleSpinBox для float (legacy) или NumericControl (binding-aware, если form_ctx передан)."""
       if form_ctx is not None:
           return _build_float_binding_aware(field_info, form_ctx, parent)
       # Legacy путь — raw QDoubleSpinBox.
       ...  # существующий код без изменений
   ```

4. Добавить dispatch для `_KIND_FLOAT` в `CardsFieldFactory.create`:
   ```python
   if kind == _KIND_FLOAT and builder is _build_float:
       return _build_float(field_info, parent, form_ctx=form_ctx)
   ```
   Вставить после существующего dispatch для `_KIND_INT` (строки 597-598).

5. Обновить docstring `CardsFieldFactory.create` — добавить упоминание float:
   «float-поля рендерятся через NumericControl (через FormContext.write + ActionBus)».

6. Проверить что `NumericControl` и `NumericViewConfig` экспортируются из
   `multiprocess_framework.modules.frontend_module.components.numeric` (проверить `numeric/__init__.py`).

**Acceptance criteria:**
- [ ] `grep -n "_build_float_binding_aware" multiprocess_prototype/frontend/forms/factory.py` — есть определение и вызов из `_build_float`
- [ ] `grep -n "_KIND_FLOAT" multiprocess_prototype/frontend/forms/factory.py` — dispatch в `CardsFieldFactory.create` добавлен
- [ ] `_build_float(field_info, form_ctx=mock_ctx)` → вызывает `_build_float_binding_aware`
- [ ] `_build_float(field_info)` без form_ctx → legacy QDoubleSpinBox (без изменений)
- [ ] `ruff check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок
- [ ] `ruff format --check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок

**Out of scope:** не трогать `_build_literal`, `_build_color3` и другие builders. Не добавлять `decimals` в
`NumericViewConfig` — это отдельный техдолг (Track 4 или отдельный plan). Только NOTE в docstring.

**Edge cases:**
- `NumericViewConfig` не имеет `label` поля — проверить `BaseControlConfig` иерархию перед передачей `label=field_info.title`. Если поля нет — пропустить.
- `result.widget.set_validator_float()` — может понадобиться вызвать после `NumericControl.create` для float-режима. Проверить: `_build_float` legacy вызывает `dsb.setDecimals(decimals)`, в binding-aware пути это делает `NumericPresenter` через `SchemaTrait`. Если validator не применяется автоматически — добавить `result.widget.set_validator_float()` явно после создания.
- float в RM обычно `float`, но `_FakeRegistersManager` хранит как `float = 0.0` — совместимо.

**Dependencies:** Task 1.3.1 (NumericControl.create принимает form_ctx)

---

## Task 1.3.3 — Тесты: NumericControl с form_ctx

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** написать 4 теста по образцу `test_spinbox_form_ctx.py`, покрывающих write, undo, legacy и access guard для NumericControl

**Context:** паттерн аналогичен Slider/SpinBox. Отличия:
(а) использовать `NumericControl` + `NumericViewConfig(view_type="spinbox")` (float-стиль);
(б) числовое поле — `threshold: float = 0.0` (float, не int) для ясности что тестируем float;
(в) в тесте access guard — `widget._value_view` — SpinBoxValueView (если view_type="spinbox"); проверять
через `presenter._access.can_modify()`.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/tests/test_numeric_form_ctx.py` — создать новый файл

**Steps:**
1. Создать файл `test_numeric_form_ctx.py` в `multiprocess_framework/modules/frontend_module/tests/`.

2. Адаптировать фейки из `test_spinbox_form_ctx.py`:
   - `_FakeRegister` — поле `threshold: float = 0.0`
   - `_FakeRegistersManager` — регистр `"sensor"`, поле `"threshold"`, meta с `{"min": 0.0, "max": 10.0, "round_k": 3}`
   - Остальные фейки (`_FakeActionBuilder`, `_FakeFieldSetHandler`, fixtures) — без изменений

3. Написать тест `test_numeric_write_via_form_ctx`:
   - `NumericControl.create(fake_rm, BindingConfig("sensor", "threshold"), NumericViewConfig(view_type="spinbox", min_val=0.0, max_val=10.0), current_access_level=0, form_ctx=form_ctx)`
   - `presenter._on_finished(3.14)`
   - Assert: `fake_rm.get_register("sensor").threshold == pytest.approx(3.14)`
   - Assert: `bus_with_handler.last_action() is not None`

4. Написать тест `test_numeric_undo_restores_view`:
   - write(5.0) → undo() → rm=0.0 → widget.get_value()==pytest.approx(0.0)
   - Требует `qapp` fixture

5. Написать тест `test_numeric_legacy_path_no_form_ctx`:
   - `NumericControl.create(fake_rm, BindingConfig("sensor", "threshold"), NumericViewConfig(view_type="spinbox"))` без form_ctx
   - `presenter._on_finished(2.71)`
   - Assert: `fake_rm.get_register("sensor").threshold == pytest.approx(2.71)`

6. Написать тест `test_numeric_access_level_guard`:
   - `BindingConfig("sensor", "threshold", access_level=3)`, `current_access_level=0`
   - Assert: `presenter._access.can_modify() is False`
   - `presenter._on_finished(9.99)` → `fake_rm.get_register("sensor").threshold == pytest.approx(0.0)`
   - После `presenter.set_access_level(3)` → `presenter._access.can_modify() is True`

**Acceptance criteria:**
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_numeric_form_ctx.py -v` — 0 FAILED
- [ ] Минимум 4 теста PASSED
- [ ] `ruff check multiprocess_framework/modules/frontend_module/tests/test_numeric_form_ctx.py` — 0 ошибок
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — все существующие тесты PASSED (регрессия)

**Out of scope:** не тестировать `view_type="slider"` через NumericControl в этом файле; не проверять decimals/round_k автоприменение.

**Edge cases:**
- `pytest.approx` обязателен для float-сравнений.
- `NumericViewConfig(view_type="spinbox")` — явно указывать, иначе дефолт "slider" создаст SliderValueView,
  и тест `widget._value_view._spinbox.isEnabled()` сломается. Для access guard тест проверять через
  `presenter._access.can_modify()`, а не через внутренности виджета.
- DeprecationWarning при `set_access_level` — обернуть в `warnings.catch_warnings()`.

**Dependencies:** Tasks 1.3.1, 1.3.2

---

## Acceptance вся фаза (Track 1.2 + 1.3)

- [ ] `SliderControl.create(..., *, form_ctx=None)` — kwarg добавлен, backward-совместим
- [ ] `NumericControl.create(..., *, form_ctx=None)` — kwarg добавлен, backward-совместим
- [ ] `_build_int(field_info, form_ctx=form_ctx)` с `meta.widget="slider"` → `_build_slider_binding_aware` → `SliderControl.create(form_ctx=form_ctx)`
- [ ] `_build_int(field_info, form_ctx=form_ctx)` без meta.widget → `_build_int_binding_aware` (без регрессии)
- [ ] `_build_float(field_info, form_ctx=form_ctx)` → `_build_float_binding_aware` → `NumericControl.create(form_ctx=form_ctx)`
- [ ] `_build_int(field_info)` и `_build_float(field_info)` без form_ctx — legacy пути работают без изменений
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_slider_form_ctx.py -v` — 4 PASSED
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_numeric_form_ctx.py -v` — 4 PASSED
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — регрессия 0 FAILED
- [ ] `pytest multiprocess_prototype/frontend/forms/tests/ -v` — регрессия 0 FAILED (если есть)
- [ ] `ruff check` по всем изменённым файлам — 0 ошибок
- [ ] `python scripts/validate.py` — зелёный
- [ ] `python scripts/run_framework_tests.py` — зелёный
- [ ] Техдолг #8 (rollout-finish.md): `value_changed: Signal` в SliderValueView — проверить наличие. Если отсутствует — добавить как отдельный micro-fix (не блокирует эту фазу)

---

## Шаблон commit messages

**Два отдельных коммита** (чистая история: Slider и Float независимы).

**Коммит 1 — Slider:**
```
feat(frontend): SliderControl vertical slice — form_ctx + _build_slider_binding_aware

- SliderControl.create: form_ctx kwarg + TYPE_CHECKING импорт + docstring
- factory._build_int: guard → двойной dispatch (slider → _build_slider_binding_aware)
- factory._build_slider_binding_aware: SliderControl.create с form_ctx
- test_slider_form_ctx.py: 4 теста (write, undo, legacy, access guard)

Why: тиражирование паттерна SpinBox на Slider — второй numeric vertical slice;
     закрывает slider guard в _build_int (был до Track 1.2)
Layer: mixed
Refs: plans/frontend-widgets-cleanup/track-1-2-1-3-slider-numeric.md, plans/frontend-widgets-cleanup/rollout-finish.md
Risk: low — SliderPresenter._write уже dual-mode через NumericPresenter; facade-only правка
Tested: frontend/slider_form_ctx/4 passed, frontend/all/green, validate.py/green
```

**Коммит 2 — Numeric/float:**
```
feat(frontend): NumericControl vertical slice — form_ctx + _build_float_binding_aware

- NumericControl.create: form_ctx kwarg + TYPE_CHECKING импорт + docstring
- factory._build_float: kwarg form_ctx, разветвление на _build_float_binding_aware
- factory._build_float_binding_aware: NumericControl.create с form_ctx (view_type=spinbox)
- CardsFieldFactory.create: dispatch для _KIND_FLOAT с form_ctx
- test_numeric_form_ctx.py: 4 теста (write, undo, legacy, access guard)

Why: тиражирование паттерна на float-поля — третий numeric vertical slice
Layer: mixed
Refs: plans/frontend-widgets-cleanup/track-1-2-1-3-slider-numeric.md, plans/frontend-widgets-cleanup/rollout-finish.md
Risk: low — NumericPresenter._write dual-mode уже в production через Track 1.1
Tested: frontend/numeric_form_ctx/4 passed, frontend/all/green, validate.py/green
```

---

## Verification команды

```powershell
# 1. Новые тесты Slider form_ctx
pytest multiprocess_framework/modules/frontend_module/tests/test_slider_form_ctx.py -v

# 2. Новые тесты Numeric/float form_ctx
pytest multiprocess_framework/modules/frontend_module/tests/test_numeric_form_ctx.py -v

# 3. Регрессия FW frontend тестов (всё)
pytest multiprocess_framework/modules/frontend_module/tests/ -v

# 4. Ruff все изменённые FW файлы
ruff check `
  multiprocess_framework/modules/frontend_module/components/slider/facade.py `
  multiprocess_framework/modules/frontend_module/components/numeric/facade.py

# 5. Ruff factory
ruff check multiprocess_prototype/frontend/forms/factory.py
ruff format --check multiprocess_prototype/frontend/forms/factory.py

# 6. Проверить slider dispatch в _build_int
Select-String -Pattern "_build_slider_binding_aware" multiprocess_prototype/frontend/forms/factory.py

# 7. Проверить _build_float dispatch
Select-String -Pattern "_build_float_binding_aware" multiprocess_prototype/frontend/forms/factory.py

# 8. Проверить _KIND_FLOAT dispatch в CardsFieldFactory.create
Select-String -Pattern "_KIND_FLOAT" multiprocess_prototype/frontend/forms/factory.py

# 9. Убедиться что slider guard «Track 1.2» удалён
Select-String -Pattern "Track 1.2" multiprocess_prototype/frontend/forms/factory.py
# Ожидается: 0 результатов

# 10. Общая валидация
python scripts/validate.py
python scripts/run_framework_tests.py
```

---

## Риски и ограничения

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| `SliderConfig` не имеет `label` поля (только в `BaseControlConfig` или только в SpinBoxConfig) | Средняя | Перед Task 1.2.2 проверить `BaseControlConfig` иерархию через grep; если нет — не передавать label в SliderConfig, оставить дефолт |
| `SliderControl/__init__.py` не экспортирует `SliderConfig` | Низкая | Проверить `slider/__init__.py` перед написанием import в factory; при необходимости добавить экспорт |
| `NumericViewConfig` не имеет `label` поля | Средняя | Проверить `BaseControlConfig`; если нет — пропустить передачу label в view_config (label будет пустым, что ОК для plugin форм где label из FieldInfo.title) |
| `NumericControl.create` — текущая сигнатура без `*,` может нарушить позиционные вызовы при добавлении kwarg | Низкая | Добавить `*,` разделитель явно перед `form_ctx`; проверить grep на существующие вызовы `NumericControl.create(` |
| `result.widget.set_validator_float()` не вызывается автоматически для NumericControl в binding-aware пути | Средняя | Проверить `NumericPresenter.__init__` — если `set_validator_int/float` вызывается через `view.set_validator_float()` в presenter — ОК; если нет — добавить явный вызов в `_build_float_binding_aware` |
| Дефолт `NumericViewConfig.view_type="slider"` создаёт SliderValueView вместо ожидаемого SpinBox для float | Высокая | Явно передавать `view_type="spinbox"` в `_build_float_binding_aware` — уже прописано в Steps |
| Тест `test_numeric_access_level_guard` проверяет `widget._value_view._spinbox.isEnabled()` — если view_type="slider", упадёт | Средняя | Использовать только `presenter._access.can_modify()` как основной assert; виджет-уровень — опционально |
