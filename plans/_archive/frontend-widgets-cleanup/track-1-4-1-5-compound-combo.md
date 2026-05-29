# Plan: Track 1.4 + 1.5 — CompoundNumericControl form_ctx + ComboControl (новый)

- **Slug:** frontend-widgets-track-1-4-1-5
- **Дата:** 2026-05-15
- **Статус:** DONE (2026-05-18, реализация в `82b87d4` (combo align) + `6c2eeb1` + `f5634ec`: form_ctx в CompoundNumericControl, новый ComboControl, `_build_color3` + `_build_literal_binding_aware`, удалён ColorTripletWidget, `test_compound_form_ctx.py` + `test_combo_form_ctx.py`)
- **Ветка:** refactor/frontend-widgets-cleanup
- **Родительский план:** [`rollout-finish.md`](rollout-finish.md), секции «Track 1» (1.4, 1.5) и «Track 2» (2.3, 2.4)
- **Верхнеуровневая карта:** [`plan.md`](plan.md)
- **Образец:** [`track-1-2-1-3-slider-numeric.md`](track-1-2-1-3-slider-numeric.md) — зелёный, используется как шаблон

---

## Зачем

Pipeline B продолжает тиражирование паттерна Checkbox (form_ctx + ActionBus) на оставшиеся компоненты.
Этот трек закрывает **два последних неизмигрированных kind** в `CardsFieldFactory`:

- **Track 1.4 — Compound (color3):** `CompoundNumericControl` уже существует в FW,
  но не принимает `form_ctx`. Нужно пробросить kwarg через facade, обновить `_build_color3` в factory
  и удалить `ColorTripletWidget` (62 LOC legacy). Это самая простая задача трека — только facade-правка
  плюс удаление мёртвого кода.

- **Track 1.5 — Combo (новый компонент):** `ComboControl` в FW **не существует**. Сейчас `_build_literal`
  создаёт `QComboBox` напрямую без binding-aware моста. Нужно создать полноценный пакет `combo/`
  по образцу `checkbox/` (config + view + presenter + facade + defaults) и подключить его в factory.
  Это самая сложная задача трека — компонент с нуля.

**Техдолги из rollout-finish.md, которые закрываются:**
- #9: `ColorTripletWidget` (62 LOC) → удалён после Track 1.4
- #10: нет `combo/` компонента в FW → создан в Track 1.5

---

## Ключевые факты из анализа кода

### CompoundNumericControl (facade.py)

| Что | Факт |
|-----|------|
| `CompoundNumericControl.create` сигнатура | `(registers_manager, config: CompoundNumericConfig, current_access_level=0, legacy_context=None, hooks=None)` — **нет** `form_ctx` |
| `CompoundNumericConfig` | `binding: BindingConfig`, `labels: List[str]`, `view_config: Optional[NumericViewConfig]` |
| Внутри `create` | Создаёт 3 `NumericControl.create(binding_with_index, vc, ...)` в цикле for i in range(3) |
| `NumericControl.create` | Уже принимает `form_ctx` (задача Track 1.3.1 выполнена) |
| Нет presenter у compound | Класс `CompoundPresenter` **не существует** — glob подтвердил. Compound — это container facade без собственного presenter |
| `CompoundControl` (другой класс) | Универсальный составной контрол, поддерживает Checkbox через `ControlFactory`. Тоже нет `form_ctx` |
| `ControlFactory.create` | Тоже нет `form_ctx` — не нужен для color3 |
| Для color3 в factory | Нужен `CompoundNumericControl` (3 числовых sub-field), не `CompoundControl` |
| `color_picker.py` | 62 LOC, `ColorTripletWidget(QWidget)` — 3 QSpinBox в HBoxLayout, API: `get_value() -> tuple[int,int,int]`, `set_value(rgb)` |

**Риск 1.4:** `CompoundNumericControl.create` не принимает `binding` напрямую — он принимает `CompoundNumericConfig` который уже содержит `binding`. Это означает что в `_build_color3_binding_aware` нужно строить `CompoundNumericConfig(binding=..., labels=["R","G","B"], view_config=NumericViewConfig(view_type="spinbox", min_val=0, max_val=255))` вместо отдельного `BindingConfig` + view_config.

### factory.py текущее состояние

| Что | Строки |
|-----|--------|
| `_build_literal` | 373-391 — raw QComboBox, нет `form_ctx` |
| `_build_color3` | 394-408 — `ColorTripletWidget`, нет `form_ctx` |
| `CardsFieldFactory.create` dispatch | 716-723 — есть dispatch для BOOL, INT, FLOAT; **нет** для LITERAL и COLOR3 |

### Checkbox как образец для ComboControl

| Что | Checkbox |
|-----|----------|
| `config.py` | `CheckboxViewConfig(BaseControlConfig)` + одно поле `position: Literal["left","right","top","bottom"] = "left"` |
| `view.py` | `CheckboxView(QWidget)` + `value_changed = Signal(bool)` + `setup(label,tooltip,enabled)` + `set_value/set_value_silent/get_value/set_enabled/on_changed/on_finished/show_error` |
| `presenter.py` | `CheckboxPresenter` — dual-mode write: `if self._form_ctx is not None → form_ctx.write(reg, field, new, old)` else `SyncTrait.write(value)` |
| `facade.py` | `CheckboxControl.create(rm, binding, view_config, current_access_level=0, hooks=None, *, form_ctx=None)` → `CheckboxControlResult(widget, presenter)` |
| Тип value | `bool` (не число) — **это и есть паттерн для Combo**, т.к. `str` тоже не-числовой тип |

**Для ComboControl `str` == аналог `bool` в паттерне Checkbox.** View эмитит `Signal(str)`, write передаёт `str`. Presenter — тот же dual-mode паттерн. Отличие: нужно хранить список `items` и инициализировать QComboBox при `attach_view`.

---

## Порядок выполнения

### Phase 1 — CompoundNumericControl form_ctx (Track 1.4)

- Task 1.4.1: `form_ctx` kwarg в `CompoundNumericControl.create` [PENDING]
- Task 1.4.2: `_build_color3_binding_aware` + `form_ctx` kwarg + удаление ColorTripletWidget [PENDING]
- Task 1.4.3: dispatch для `_KIND_COLOR3` в `CardsFieldFactory.create` [PENDING]
- Task 1.4.4: 4 теста в `test_compound_form_ctx.py` [PENDING]

### Phase 2 — ComboControl (новый компонент, Track 1.5)

- Task 1.5.1: `combo/__init__.py` + `combo/config.py` (`ComboViewConfig`) [PENDING]
- Task 1.5.2: `combo/view.py` (`ComboView` + `value_changed: Signal(str)`) [PENDING]
- Task 1.5.3: `combo/presenter.py` (`ComboPresenter` dual-mode) [PENDING]
- Task 1.5.4: `combo/facade.py` (`ComboControl.create`) [PENDING]
- Task 1.5.5: 5-7 unit-тестов в `test_combo_v2.py` [PENDING]
- Task 1.5.6: `_build_literal_binding_aware` + `form_ctx` kwarg в `_build_literal` + dispatch [PENDING]
- Task 1.5.7: 4 теста form_ctx в `test_combo_form_ctx.py` [PENDING]

**Зависимость:** Tasks 1.5.1-1.5.4 выполняются последовательно (каждый зависит от предыдущего).
Task 1.5.5 можно писать параллельно после 1.5.2. Tasks 1.5.6-1.5.7 требуют 1.5.4 готовым.
Track 1.4 полностью независим от Track 1.5.

---

## Task 1.4.1 — form_ctx kwarg в CompoundNumericControl.create

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** добавить `form_ctx: "FormContext | None" = None` в `CompoundNumericControl.create` и пробросить в каждый `NumericControl.create` внутри цикла

**Context:** `CompoundNumericControl.create` создаёт 3 `NumericControl.create` в цикле `for i in range(3)`.
`NumericControl.create` уже принимает `form_ctx` (Track 1.3.1). Нужно только добавить kwarg в facade
и пробросить его. Compound не имеет собственного presenter — binding-aware логика реализована
на уровне каждого дочернего `NumericControl`.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/components/compound/facade.py` — изменить
- `multiprocess_framework/modules/frontend_module/components/compound/__init__.py` — проверить экспорты (без изменений если всё есть)

**Steps:**
1. Добавить в начало файла (после `from __future__ import annotations`):
   ```python
   from typing import TYPE_CHECKING
   if TYPE_CHECKING:
       from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext
   ```
   Если `TYPE_CHECKING` уже импортирован — только добавить блок `if TYPE_CHECKING`.

2. В сигнатуре `CompoundNumericControl.create` добавить keyword-only kwarg последним
   (после `hooks: Optional[ControlHooks] = None`), с разделителем `*,`:
   ```python
   @staticmethod
   def create(
       registers_manager: Any,
       config: CompoundNumericConfig,
       current_access_level: int = 0,
       legacy_context: Optional[LegacySyncContext] = None,
       hooks: Optional[ControlHooks] = None,
       *,
       form_ctx: "FormContext | None" = None,
   ) -> CompoundNumericControlResult:
   ```

3. В вызове `NumericControl.create(...)` внутри цикла добавить `form_ctx=form_ctx`:
   ```python
   r = NumericControl.create(
       registers_manager,
       binding,
       view_config=vc,
       current_access_level=current_access_level,
       legacy_context=legacy_context,
       hooks=hooks,
       form_ctx=form_ctx,  # <-- добавить
   )
   ```

4. Обновить docstring `CompoundNumericControl.create` — добавить секцию `form_ctx`:
   - Production-путь: каждый из 3 sub-controls пишет через `FormContext.write` (coalescing, undo/redo, IPC bridge). Каждый sub-control имеет `index=i` в BindingConfig — пишет tuple-элемент по индексу.
   - Legacy-путь (form_ctx=None): прямая запись через RegisterAdapter в каждом NumericControl.

**Acceptance criteria:**
- [ ] `CompoundNumericControl.create(..., *, form_ctx=None)` — kwarg добавлен как keyword-only
- [ ] `ruff check multiprocess_framework/modules/frontend_module/components/compound/facade.py` — 0 ошибок
- [ ] `ruff format --check multiprocess_framework/modules/frontend_module/components/compound/facade.py` — 0 ошибок
- [ ] `python -c "from multiprocess_framework.modules.frontend_module.components.compound import CompoundNumericControl; print('ok')"` — без ImportError
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — все существующие тесты PASSED

**Out of scope:** не трогать `CompoundControl.create` и `ControlFactory.create` — они не нужны для color3;
не добавлять presenter к compound — sub-controls уже имеют presenter.

**Edge cases:** `NumericControl.create` — убедиться что его текущая сигнатура уже содержит `form_ctx` kwarg
(должна после Track 1.3.1). Если нет — это блокер, задача зависит от 1.3.1.

**Dependencies:** Task 1.3.1 из `track-1-2-1-3-slider-numeric.md` (NumericControl.create принимает form_ctx — должно быть выполнено)

---

## Task 1.4.2 — _build_color3_binding_aware + form_ctx kwarg + удаление ColorTripletWidget

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** создать `_build_color3_binding_aware()` в factory.py, добавить `form_ctx` kwarg в `_build_color3`, удалить импорт `ColorTripletWidget` и файл `color_picker.py`

**Context:** `_build_color3` (строки 394-408 factory.py) использует `ColorTripletWidget` (62 LOC).
`CompoundNumericControl.create` теперь принимает `form_ctx` (Task 1.4.1).
Паттерн аналогичен `_build_float_binding_aware`, но вместо `NumericControl` используется
`CompoundNumericControl` с `CompoundNumericConfig`.

**Критичный нюанс:** `CompoundNumericControl.create` принимает **`config: CompoundNumericConfig`** (не отдельные
binding + view_config), поэтому в `_build_color3_binding_aware` нужно создавать
`CompoundNumericConfig(binding=..., labels=["R","G","B"], view_config=NumericViewConfig(view_type="spinbox", min_val=0.0, max_val=255.0))`.

**Файлы:**
- `multiprocess_prototype/frontend/forms/factory.py` — изменить
- `multiprocess_prototype/frontend/forms/widgets/color_picker.py` — **удалить файл**

**Steps:**

1. Прочитать актуальные строки 394-410 factory.py перед правкой.

2. Найти и удалить импорт `ColorTripletWidget` в начале factory.py:
   ```python
   # Удалить строку вида:
   from multiprocess_prototype.frontend.forms.widgets.color_picker import ColorTripletWidget
   ```
   Убедиться что это единственный импорт; использование — только в `_build_color3`.

3. Добавить функцию `_build_color3_binding_aware` сразу после `_build_slider_binding_aware` и перед `_build_literal`:
   ```python
   def _build_color3_binding_aware(
       field_info: FieldInfo,
       form_ctx: FormContext,
       parent: QWidget | None = None,
   ) -> FieldEditor:
       """CompoundNumericControl через FormContext.write — binding-aware путь для tuple[int,int,int].

       Создаёт 3 NumericControl (spinbox, 0..255) для R, G, B sub-полей по index=0,1,2.
       Coalescing, undo/redo, IPC bridge — автоматически через ActionBus в каждом sub-control.

       NOTE: CompoundNumericControl.create принимает CompoundNumericConfig (не BindingConfig напрямую).
       Binding с index=i создаётся внутри CompoundNumericControl — каждый sub-control пишет
       отдельный элемент tuple по своему индексу.
       """
       from multiprocess_framework.modules.frontend_module.components.base.config import (
           BindingConfig,
       )
       from multiprocess_framework.modules.frontend_module.components.compound import (
           CompoundNumericControl,
           CompoundNumericConfig,
       )
       from multiprocess_framework.modules.frontend_module.components.numeric.config import (
           NumericViewConfig,
       )

       binding = BindingConfig(
           field_info.plugin_name or "",
           field_info.field_name or "",
       )
       view_config = NumericViewConfig(
           view_type="spinbox",   # RGB-каналы отображаются как QDoubleSpinBox (0-255)
           min_val=0.0,
           max_val=255.0,
       )
       config = CompoundNumericConfig(
           binding=binding,
           labels=["R", "G", "B"],
           view_config=view_config,
       )

       result = CompoundNumericControl.create(
           form_ctx.registers_manager,
           config,
           current_access_level=form_ctx.access_level,
           form_ctx=form_ctx,
       )

       label = _make_label(field_info)
       # getter/setter работают через контейнер-виджет — нет единого value на уровне QWidget.
       # Для binding-aware пути change_signal=None: каждый sub-control пишет через presenter.
       # getter возвращает tuple через агрегацию sub-контролов — не нужен RegisterView напрямую.
       return FieldEditor(
           field_info=field_info,
           widget=result.widget,
           getter=lambda: tuple(r.widget.get_value() for r in result.results),
           setter=lambda v: [
               r.widget.set_value_silent(v[i]) for i, r in enumerate(result.results)
           ] if v is not None else None,
           change_signal=None,  # type: ignore[arg-type]
           label=label,
       )
   ```

4. Обновить `_build_color3` — добавить `form_ctx` kwarg и dispatch:
   ```python
   def _build_color3(
       field_info: FieldInfo,
       parent: QWidget | None = None,
       *,
       form_ctx: FormContext | None = None,
   ) -> FieldEditor:
       """CompoundNumericControl для tuple[int,int,int] (binding-aware) или legacy путь.

       Legacy путь (form_ctx=None) создаёт 3 raw QSpinBox в HBoxLayout без ActionBus-binding.
       Используется для GUI-локальных форм без plugin binding.
       """
       if form_ctx is not None:
           return _build_color3_binding_aware(field_info, form_ctx, parent)

       # Legacy путь: 3 raw QSpinBox без binding (аналог ColorTripletWidget).
       # ColorTripletWidget удалён — воспроизводим минимальный inline.
       from PySide6.QtWidgets import QHBoxLayout, QSpinBox
       container = QWidget(parent)
       layout = QHBoxLayout(container)
       layout.setContentsMargins(0, 0, 0, 0)
       spins: list[QSpinBox] = []
       for _ in range(3):
           spin = QSpinBox(container)
           spin.setRange(0, 255)
           layout.addWidget(spin)
           spins.append(spin)
       default = _safe_default(field_info, (0, 0, 0))
       if isinstance(default, (tuple, list)) and len(default) == 3:
           for spin, val in zip(spins, default):
               spin.setValue(int(val))
       label = _make_label(field_info)
       return FieldEditor(
           field_info=field_info,
           widget=container,
           getter=lambda: tuple(s.value() for s in spins),
           setter=lambda v: [s.setValue(int(v[i])) for i, s in enumerate(spins)] if v else None,
           change_signal=None,  # type: ignore[arg-type]
           label=label,
       )
   ```

5. Физически удалить файл `multiprocess_prototype/frontend/forms/widgets/color_picker.py`.
   Проверить: если директория `widgets/` после удаления пустая — оставить пустой или создать `__init__.py`
   (проверить что там есть ещё файлы через Glob).

**Acceptance criteria:**
- [ ] `grep -rn "ColorTripletWidget" multiprocess_prototype/` — 0 результатов (импорт удалён)
- [ ] Файл `multiprocess_prototype/frontend/forms/widgets/color_picker.py` — не существует
- [ ] `grep -n "_build_color3_binding_aware" multiprocess_prototype/frontend/forms/factory.py` — есть определение
- [ ] `_build_color3(field_info, form_ctx=mock_ctx)` → `_build_color3_binding_aware` (не ColorTripletWidget)
- [ ] `_build_color3(field_info)` без form_ctx → legacy inline (без ColorTripletWidget, без ImportError)
- [ ] `ruff check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок
- [ ] `ruff format --check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — регрессия 0 FAILED

**Out of scope:** не оборачивать legacy inline в отдельный класс; не добавлять `value_changed` Signal в legacy пути; getter/setter для compound — через lambda-агрегацию, не через отдельный view-класс.

**Edge cases:**
- Проверить что `CompoundNumericConfig` и `CompoundNumericControl` экспортируются из `compound/__init__.py` — подтверждено по коду (строки 3-13 `__init__.py`).
- `result.results` — список из 3 `NumericControlResult`, каждый имеет `widget` — `LabeledNumericGroupView` с методами `get_value()` / `set_value_silent()`. Проверить что `LabeledNumericGroupView` действительно имеет эти методы (подтверждено по track-1-2-1-3 плану).
- Если `widgets/` директория содержит другие файлы кроме `color_picker.py` — удалить только `color_picker.py`.

**Dependencies:** Task 1.4.1

---

## Task 1.4.3 — dispatch для _KIND_COLOR3 в CardsFieldFactory.create

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** добавить dispatch для `_KIND_COLOR3` в `CardsFieldFactory.create` по образцу `_KIND_BOOL`, `_KIND_INT`, `_KIND_FLOAT`

**Context:** `CardsFieldFactory.create` (строки 691-723 factory.py) имеет dispatch только для BOOL, INT, FLOAT.
`_build_color3` теперь принимает `form_ctx` kwarg (Task 1.4.2). Нужно добавить ветку для `_KIND_COLOR3`.

**Файлы:**
- `multiprocess_prototype/frontend/forms/factory.py` — изменить

**Steps:**

1. В методе `CardsFieldFactory.create`, после строки с `_KIND_FLOAT` dispatch, добавить ветку:
   ```python
   if kind == _KIND_COLOR3 and builder is _build_color3:
       return _build_color3(field_info, parent, form_ctx=form_ctx)
   ```

2. Обновить docstring `CardsFieldFactory.create` — добавить упоминание color3:
   ```python
   # Добавить к существующему тексту:
   # color3-поля (tuple[int,int,int]) рендерятся через CompoundNumericControl
   # (через FormContext.write + ActionBus) если form_ctx передан.
   ```

**Acceptance criteria:**
- [ ] `grep -n "_KIND_COLOR3" multiprocess_prototype/frontend/forms/factory.py` — есть dispatch в `CardsFieldFactory.create`
- [ ] `_build_color3(field_info, form_ctx=mock_ctx)` вызывается из `CardsFieldFactory.create` с `form_ctx`
- [ ] `_build_color3(field_info)` без form_ctx — legacy путь работает (регрессия не сломана)
- [ ] `ruff check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок

**Out of scope:** не трогать `_KIND_LITERAL` dispatch — это Task 1.5.6.

**Edge cases:** убедиться что `_KIND_COLOR3` определён как константа в factory.py (grep по `_KIND_COLOR3 =`).

**Dependencies:** Task 1.4.2

---

## Task 1.4.4 — Тесты: CompoundNumericControl с form_ctx

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** написать 4 теста по образцу `test_spinbox_form_ctx.py`, покрывающих write через form_ctx, undo, legacy и access guard для CompoundNumericControl (color3 sub-controls)

**Context:** Паттерн фейков идентичен `test_spinbox_form_ctx.py`. Отличия:
(а) поле регистра — `color: tuple = (0, 0, 0)` вместо `speed: float`;
(б) write проверяется не по `fake_rm.get_register(...).color`, а через подписку на sub-field по индексу;
(в) `_on_finished` — нужно вызывать у конкретного sub-control presenter'а (например, `result.results[0].presenter._on_finished(128.0)`);
(г) доступа к `result.widget.get_value()` как к единому value нет — только через lambda-агрегацию или проверку RM напрямую.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/tests/test_compound_form_ctx.py` — создать новый файл

**Steps:**

1. Создать файл `test_compound_form_ctx.py` в `multiprocess_framework/modules/frontend_module/tests/`.

2. Скопировать фейки из `test_spinbox_form_ctx.py` **без изменений** кроме:
   - `_FakeRegister` — заменить `speed: float = 0.0` на поля `color_r: float = 0.0`, `color_g: float = 0.0`, `color_b: float = 0.0` (или оставить `speed` и тестировать index=0 для sub-control с register_name/field_name).
   - `_FakeRegistersManager._meta` — добавить min=0, max=255 для используемого поля.
   - Все остальные фейки и fixtures — без изменений.

3. Написать тест `test_compound_write_sub_control_via_form_ctx`:
   - `CompoundNumericControl.create(fake_rm, CompoundNumericConfig(binding=BindingConfig("motor","speed"), labels=["R","G","B"], view_config=NumericViewConfig(view_type="spinbox",min_val=0,max_val=255)), current_access_level=0, form_ctx=form_ctx)`
   - `result.results[0].presenter._on_finished(128.0)` — пишет элемент с index=0
   - Assert: `fake_rm.get_register("motor").speed == 128.0` ИЛИ через подписку (проверить RM после write)
   - Assert: `bus_with_handler.last_action() is not None`

4. Написать тест `test_compound_undo_restores_sub_control`:
   - Write sub-control 0 → undo → assert RM вернулся к 0.0
   - Требует `qapp` fixture

5. Написать тест `test_compound_legacy_path_no_form_ctx`:
   - `CompoundNumericControl.create(fake_rm, config)` без form_ctx
   - `result.results[0].presenter._on_finished(200.0)`
   - Assert: RM обновлён через legacy путь (SyncTrait)

6. Написать тест `test_compound_access_level_guard`:
   - `BindingConfig("motor", "speed", access_level=5)` + `current_access_level=0`
   - Assert: каждый sub-control `result.results[i].presenter._access.can_modify() is False`
   - `result.results[0].presenter._on_finished(100.0)` → RM не изменился

**Acceptance criteria:**
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_compound_form_ctx.py -v` — 0 FAILED
- [ ] Минимум 4 теста PASSED
- [ ] `ruff check multiprocess_framework/modules/frontend_module/tests/test_compound_form_ctx.py` — 0 ошибок
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — регрессия 0 FAILED

**Out of scope:** не тестировать `CompoundControl` (universal compound) — только `CompoundNumericControl` для color3.
Не тестировать `ControlFactory.create` в этих тестах.

**Edge cases:**
- `_FakeRegistersManager.set_field_value` с `index` kwarg — нужно убедиться, что `BindingConfig(index=0)` транслируется в отдельный вызов `set_field_value` с нужным field. Если `RegisterAdapter` использует `index` как sub-field — проверить как sub-field разрешается в register. Если нет отдельного поля с index — тестировать через `field_name` напрямую без index, добавив `speed_0: float = 0.0` поля.
- `pytest.approx` обязателен для float-сравнений.

**Dependencies:** Tasks 1.4.1, 1.4.2, 1.4.3

---

## Task 1.5.1 — combo/__init__.py + combo/config.py (ComboViewConfig)

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** создать пакет `combo/` с `__init__.py` и `config.py` (`ComboViewConfig` по образцу `CheckboxViewConfig`)

**Context:** Пакет создаётся с нуля по образцу `checkbox/`. `CheckboxViewConfig` наследует `BaseControlConfig`
и добавляет одно поле. `ComboViewConfig` аналогично — содержит поле `placeholder: str = ""` (текст когда
ничего не выбрано) и `items_order: Literal["as_is", "sorted"] = "as_is"` (опционально).

**Файлы:**
- `multiprocess_framework/modules/frontend_module/components/combo/__init__.py` — создать
- `multiprocess_framework/modules/frontend_module/components/combo/config.py` — создать

**Steps:**

1. Создать директорию `multiprocess_framework/modules/frontend_module/components/combo/`.

2. Создать `config.py`:
   ```python
   # -*- coding: utf-8 -*-
   """
   ComboViewConfig — UI-опции выпадающего списка (ComboControl).
   """
   from __future__ import annotations
   from typing import Annotated, Literal, List, Optional
   from multiprocess_framework.modules.data_schema_module import FieldMeta
   from multiprocess_framework.modules.frontend_module.components.base.config import BaseControlConfig

   class ComboViewConfig(BaseControlConfig):
       """
       Настройки отображения ComboBox.

       Поля ``label`` / ``tooltip`` / ``enabled`` наследуются из ``BaseControlConfig``.
       ``items`` — если указаны, используются вместо items из типа поля (Literal args).
       ``placeholder`` — текст при пустом выборе (вставляется как первый пустой item).
       """
       items: Annotated[
           Optional[List[str]],
           FieldMeta("Явный список items (переопределяет Literal args)"),
       ] = None
       placeholder: Annotated[
           str,
           FieldMeta("Текст пустого выбора"),
       ] = ""
   ```

3. Создать `__init__.py` (заглушка — полный экспорт добавляется в Task 1.5.4):
   ```python
   # -*- coding: utf-8 -*-
   """ComboControl — выпадающий список с binding к регистру (form_ctx-aware)."""
   from multiprocess_framework.modules.frontend_module.components.combo.config import ComboViewConfig

   __all__ = ["ComboViewConfig"]
   ```

**Acceptance criteria:**
- [ ] `python -c "from multiprocess_framework.modules.frontend_module.components.combo.config import ComboViewConfig; print('ok')"` — без ImportError
- [ ] `ComboViewConfig()` — инстанциируется с дефолтами
- [ ] `ruff check multiprocess_framework/modules/frontend_module/components/combo/` — 0 ошибок

**Out of scope:** не добавлять `defaults.py` — дефолты не нужны для combo (нет стандартных preset-конфигов
как в checkbox).

**Edge cases:** убедиться что `BaseControlConfig` существует и импортируется корректно (подтверждено по checkbox/config.py).

**Dependencies:** нет

---

## Task 1.5.2 — combo/view.py (ComboView + value_changed: Signal(str))

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** создать `ComboView(QWidget)` с `QComboBox`, публичным `value_changed: Signal(str)` и полным API контракта `IControlView[str]`

**Context:** По образцу `CheckboxView` — тот же контракт `IControlView` для non-числового типа.
Отличия от Checkbox:
(а) `QComboBox` вместо `QCheckBox`;
(б) `value_changed = Signal(str)` (не bool);
(в) `setup(label, tooltip, enabled)` — метка QLabel слева (позиция фиксированная, нет `position` kwarg);
(г) `set_items(items: list[str])` — устанавливает список вариантов;
(д) `get_value() -> str` — `combo.currentText()`;
(е) `set_value_silent(value: str)` — `blockSignals` на время установки.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/components/combo/view.py` — создать

**Steps:**

1. Создать `view.py`:
   ```python
   # -*- coding: utf-8 -*-
   """
   ComboView — QLabel + QComboBox с binding к строковому значению регистра.

   Реализует контракт `IControlView[str]` для `ComboPresenter`.
   """
   from __future__ import annotations
   from typing import Callable, List, Optional
   from multiprocess_framework.modules.frontend_module.components.base.infrastructure.signal_utils import (
       block_signals,
   )
   from multiprocess_framework.modules.frontend_module.core.qt_imports import (
       QComboBox,
       QHBoxLayout,
       QLabel,
       QMessageBox,
       QWidget,
       Signal,
   )

   class ComboView(QWidget):
       """Композитный виджет: QLabel + QComboBox в горизонтальном ряду."""

       # Эмитится при смене выбора пользователем; передаёт str.
       value_changed = Signal(str)

       def __init__(self, parent: Optional[QWidget] = None) -> None:
           super().__init__(parent)
           self._label = QLabel()
           self._combo = QComboBox()
           layout = QHBoxLayout(self)
           layout.setContentsMargins(4, 4, 4, 4)
           layout.setSpacing(4)
           layout.addWidget(self._label)
           layout.addWidget(self._combo)
           # Эмит value_changed при смене выбора пользователем.
           self._combo.currentTextChanged.connect(
               lambda text: self.value_changed.emit(text)
           )

       def setup(self, label: str, tooltip: str, enabled: bool) -> None:
           """Задать текст метки, подсказку и доступность редактирования."""
           self._label.setText(label)
           self._label.setToolTip(tooltip)
           self.set_enabled(enabled)

       def set_items(self, items: List[str]) -> None:
           """Установить список вариантов; сохраняет текущий выбор если он в новом списке."""
           current = self._combo.currentText()
           with block_signals(self._combo):
               self._combo.clear()
               self._combo.addItems(items)
           if current in items:
               with block_signals(self._combo):
                   self._combo.setCurrentText(current)

       def set_value(self, value: str) -> None:
           """Установить выбранный item; эмитит currentTextChanged → value_changed."""
           self._combo.setCurrentText(str(value))

       def set_value_silent(self, value: str) -> None:
           """Установить выбор без эмита value_changed (синхронизация из модели)."""
           with block_signals(self._combo):
               self._combo.setCurrentText(str(value))

       def get_value(self) -> str:
           """Текущий выбранный текст."""
           return self._combo.currentText()

       def set_enabled(self, enabled: bool) -> None:
           """Включить или отключить только ComboBox (метка остаётся видимой)."""
           self._combo.setEnabled(enabled)

       def on_changed(self, callback: Callable[[str], None]) -> None:
           """Подписка на смену выбора; callback получает str."""
           self._combo.currentTextChanged.connect(callback)

       def on_finished(self, callback: Callable[[str], None]) -> None:
           """Заглушка контракта: для combo 'запись' идёт сразу в on_changed."""
           pass

       def show_error(self, message: str) -> None:
           """Показать предупреждение об ошибке записи."""
           QMessageBox.warning(self, "Ошибка", message)
   ```

**Acceptance criteria:**
- [ ] `python -c "from multiprocess_framework.modules.frontend_module.components.combo.view import ComboView; print('ok')"` — без ImportError (требует QApplication для import не нужен)
- [ ] `ComboView` имеет атрибут класса `value_changed = Signal(str)` — проверить через inspection
- [ ] `ruff check multiprocess_framework/modules/frontend_module/components/combo/view.py` — 0 ошибок
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — регрессия 0 FAILED

**Out of scope:** не добавлять поиск/фильтрацию в QComboBox; не делать editable combo; placeholder — не
реализуется как пустой первый item в этой задаче (это для presenter).

**Edge cases:**
- `block_signals` импортируется из `base.infrastructure.signal_utils` — подтверждено по `checkbox/view.py`.
- `QComboBox` — проверить что он присутствует в `core/qt_imports.py` (там же откуда checkbox импортирует QCheckBox). Если нет — добавить импорт `from PySide6.QtWidgets import QComboBox`.

**Dependencies:** Task 1.5.1

---

## Task 1.5.3 — combo/presenter.py (ComboPresenter dual-mode)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** создать `ComboPresenter` по образцу `CheckboxPresenter` — dual-mode write для `str` значения с `form_ctx` / legacy путём

**Context:** Паттерн CheckboxPresenter перенесён на str-тип. Отличия:
(а) `_on_changed(self, value: str)` вместо `bool`;
(б) `_on_external_change` — `str(value)` cast вместо `bool(value)`;
(в) `_sync_from_model` — `str(self._sync.read())`;
(г) `attach_view` — вызывает `view.set_items(items)` перед attach если items известны из
    Literal-аргументов. Items получаются из `SchemaTrait` или передаются как параметр.
(д) `ComboPresenter.__init__` принимает `items: list[str] | None = None` — список вариантов.
    Если `None` — ожидается что caller заполнит items через `view.set_items()` напрямую.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/components/combo/presenter.py` — создать

**Steps:**

1. Создать `presenter.py` по образцу `checkbox/presenter.py`.

2. Класс `ComboPresenter`:
   ```python
   class ComboPresenter:
       def __init__(
           self,
           binding: IFieldBinding,
           adapter: IRegisterPort,
           view_config: ComboViewConfig | None = None,
           current_access_level: int = 0,
           hooks: ControlHooks | None = None,
           items: list[str] | None = None,
           *,
           form_ctx: "FormContext | None" = None,
       ) -> None:
   ```

3. Инициализация аналогично CheckboxPresenter:
   - `self._binding`, `self._hooks`, `self._view_config`, `self._form_ctx` — сохранить
   - `self._items = items or []` — список допустимых вариантов
   - `SchemaTrait`, `SyncTrait`, `AccessTrait` — аналогично CheckboxPresenter
   - `self._view: Optional[IControlView[str]] = None`

4. Метод `attach_view(self, view: IControlView[str])`:
   - Вызвать `view.set_items(self._items)` если `_items` непустой и `view` имеет `set_items`
   - Вызвать `view.setup(label, tooltip, enabled)`
   - Подписаться `view.on_changed(self._on_changed)`
   - `self._sync.subscribe(self._on_external_change)`
   - `self._sync_from_model()`

5. Метод `_on_changed(self, value: str)` — dual-mode write:
   ```python
   def _on_changed(self, value: str) -> None:
       if not self._access.can_modify():
           emit_access_denied(...)
           self._sync_from_model()
           return
       if self._form_ctx is not None:
           old_value = self._sync.read()
           ok = self._form_ctx.write(
               self._binding.register_name,
               self._binding.field_name,
               value,
               old_value,
           )
           err = None if ok else "write failed"
       else:
           ok, err = self._sync.write(value)
       # обработка ok/err аналогично CheckboxPresenter
   ```

6. Методы `_on_external_change`, `_sync_from_model`, `set_access_level`, `set_access_context`,
   `refresh_metadata` — аналогично CheckboxPresenter с заменой `bool` → `str`.

**Acceptance criteria:**
- [ ] `python -c "from multiprocess_framework.modules.frontend_module.components.combo.presenter import ComboPresenter; print('ok')"` — без ImportError
- [ ] `ComboPresenter(binding, adapter, items=["a","b"])` — инстанциируется без Qt (нет Qt-зависимостей в presenter)
- [ ] `ruff check multiprocess_framework/modules/frontend_module/components/combo/presenter.py` — 0 ошибок
- [ ] `ruff format --check ...` — 0 ошибок

**Out of scope:** не добавлять поиск по items в presenter; не добавлять multi-select; не реализовывать `refresh_items()` (reload items из RM) — техдолг для Track 4.

**Edge cases:**
- `SyncTrait.read()` может вернуть не-str (например `int` если Literal[1,2,3]). Всегда делать `str(value)` cast в `_sync_from_model` и `_on_external_change`.
- `view.set_items` — проверить что у `IControlView` нет этого метода в интерфейсе (вероятно нет). Вызывать через `hasattr(view, "set_items")` guard.

**Dependencies:** Tasks 1.5.1, 1.5.2

---

## Task 1.5.4 — combo/facade.py (ComboControl.create)

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** создать `ComboControl.create(rm, binding, view_config, items, *, form_ctx=None)` по образцу `CheckboxControl.create`

**Context:** Facade собирает `RegisterAdapter` + `ComboPresenter` + `ComboView` и возвращает
`ComboControlResult(widget, presenter)`. Паттерн полностью аналогичен `CheckboxControl.create`.
`items` — обязательный параметр (список строк для QComboBox).

**Файлы:**
- `multiprocess_framework/modules/frontend_module/components/combo/facade.py` — создать
- `multiprocess_framework/modules/frontend_module/components/combo/__init__.py` — обновить экспорты

**Steps:**

1. Создать `facade.py`:
   ```python
   # -*- coding: utf-8 -*-
   """
   ComboControl — фасад для создания выпадающего списка с привязкой к регистру.

   Пример::
       result = ComboControl.create(
           rm,
           BindingConfig(register_name="config", field_name="mode"),
           ComboViewConfig(),
           items=["auto", "manual", "off"],
       )
       layout.addWidget(result.widget)
   """
   from __future__ import annotations
   from dataclasses import dataclass
   from typing import TYPE_CHECKING, List, Optional
   from multiprocess_framework.modules.frontend_module.components.base import RegisterAdapter
   from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
   from multiprocess_framework.modules.frontend_module.components.base.control_hooks import ControlHooks
   from multiprocess_framework.modules.frontend_module.components.base.interfaces import RegistersManagerLike
   from multiprocess_framework.modules.frontend_module.components.combo.config import ComboViewConfig
   from multiprocess_framework.modules.frontend_module.components.combo.presenter import ComboPresenter
   from multiprocess_framework.modules.frontend_module.components.combo.view import ComboView
   from multiprocess_framework.modules.frontend_module.core.qt_imports import QWidget

   if TYPE_CHECKING:
       from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext


   @dataclass
   class ComboControlResult:
       """Итог фабрики: готовый виджет и presenter."""
       widget: QWidget
       presenter: ComboPresenter


   class ComboControl:
       """Статическая фабрика: собирает RegisterAdapter, ComboPresenter и ComboView."""

       @staticmethod
       def create(
           registers_manager: Optional[RegistersManagerLike],
           binding: BindingConfig,
           view_config: ComboViewConfig | None = None,
           current_access_level: int = 0,
           hooks: ControlHooks | None = None,
           items: List[str] | None = None,
           *,
           form_ctx: "FormContext | None" = None,
       ) -> ComboControlResult:
           """
           Создать выпадающий список, привязанный к полю регистра.

           Args:
               items: Список строковых вариантов. Если None — ожидаются items из Literal-типа поля.
               form_ctx: Production-путь (передан): write через ActionBus (undo/redo, IPC bridge).
                   Legacy-путь (None): прямая запись через RegisterAdapter.
           """
           view_config = view_config or ComboViewConfig()
           effective_items = items or (view_config.items or [])
           adapter = RegisterAdapter(registers_manager)
           presenter = ComboPresenter(
               binding, adapter, view_config, current_access_level, hooks=hooks,
               items=effective_items, form_ctx=form_ctx,
           )
           view = ComboView()
           presenter.attach_view(view)
           return ComboControlResult(widget=view, presenter=presenter)
   ```

2. Обновить `combo/__init__.py` — добавить полные экспорты:
   ```python
   from multiprocess_framework.modules.frontend_module.components.combo.config import ComboViewConfig
   from multiprocess_framework.modules.frontend_module.components.combo.facade import (
       ComboControl,
       ComboControlResult,
   )
   from multiprocess_framework.modules.frontend_module.components.combo.presenter import ComboPresenter
   from multiprocess_framework.modules.frontend_module.components.combo.view import ComboView

   __all__ = [
       "ComboViewConfig",
       "ComboView",
       "ComboPresenter",
       "ComboControl",
       "ComboControlResult",
   ]
   ```

**Acceptance criteria:**
- [ ] `python -c "from multiprocess_framework.modules.frontend_module.components.combo import ComboControl, ComboControlResult, ComboPresenter, ComboView, ComboViewConfig; print('ok')"` — без ImportError
- [ ] `ruff check multiprocess_framework/modules/frontend_module/components/combo/` — 0 ошибок
- [ ] `ruff format --check multiprocess_framework/modules/frontend_module/components/combo/` — 0 ошибок
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — регрессия 0 FAILED

**Out of scope:** не добавлять `ComboRegister` (django-style descriptor) — не нужен сейчас; не добавлять `defaults.py`.

**Edge cases:**
- `items=None` + `view_config.items=None` → `effective_items = []` → `view.set_items([])` — combo пустой, это ОК (caller настроит items через `result.presenter._items`).
- `RegisterAdapter` — импортируется из `base` как в CheckboxControl.create (строка 20 checkbox/facade.py).

**Dependencies:** Tasks 1.5.1, 1.5.2, 1.5.3

---

## Task 1.5.5 — unit-тесты ComboControl (test_combo_v2.py)

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** написать 5-7 unit-тестов по образцу `test_checkbox_v2.py`, покрывающих presenter без Qt, Signal, facade smoke

**Context:** Паттерн фейков из `test_checkbox_v2.py` с заменой `bool` → `str`. Тесты должны покрывать:
presenter write, external sync, items init, Signal(str), facade create, access-denied.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/tests/test_combo_v2.py` — создать новый файл

**Steps:**

1. Создать фейки аналогично `test_checkbox_v2.py`:
   - `_FakeRegister` с полем `mode: str = "auto"`
   - `_FakeRegistersManager` с регистром `"config"`, полем `"mode"`
   - `_FakeStrView` (аналог `_FakeBoolView`) — реализует `IControlView[str]` без Qt:
     `setup/set_value/set_value_silent/get_value/set_enabled/on_changed/on_finished/show_error/user_select(value)`

2. Тест `test_combo_presenter_write_on_change`:
   - `ComboPresenter(BindingConfig("config","mode"), adapter, items=["auto","manual","off"])`, `_FakeStrView`
   - `view.user_select("manual")`
   - Assert: `rm.get_register("config").mode == "manual"`

3. Тест `test_combo_external_sync_updates_view`:
   - Presenter + view attached
   - `rm.set_field_value("config", "mode", "off")`
   - Assert: `view.value == "off"`

4. Тест `test_combo_items_set_on_attach_view`:
   - `ComboPresenter(binding, adapter, items=["a","b","c"])`
   - `attach_view(fake_view)`
   - Assert: `fake_view.items == ["a","b","c"]` (если `_FakeStrView` хранит items после `set_items`)

5. Тест `test_combo_access_denied_no_write`:
   - `ComboPresenter(BindingConfig("config","mode", access_level=5), adapter, current_access_level=0)`
   - `view.user_select("manual")`
   - Assert: `rm.get_register("config").mode == "auto"` (не изменилось)
   - Assert: `view.enabled_flag is False`

6. Тест `test_combo_value_changed_signal_emits_str` (требует qapp):
   - `ComboView()`, `combo.set_items(["x","y"])`
   - `received = []; view.value_changed.connect(lambda v: received.append(v))`
   - `view.set_value("y")`
   - Assert: `received == ["y"]`

7. Тест `test_combo_control_facade_create_returns_widget_and_presenter` (требует qapp):
   - `ComboControl.create(rm, BindingConfig("config","mode"), items=["auto","manual"])`
   - Assert: `result.widget is not None`, `result.presenter is not None`

**Acceptance criteria:**
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_combo_v2.py -v` — 0 FAILED
- [ ] Минимум 5 тестов PASSED (7 желательно)
- [ ] `ruff check multiprocess_framework/modules/frontend_module/tests/test_combo_v2.py` — 0 ошибок
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — регрессия 0 FAILED

**Out of scope:** не тестировать form_ctx в этом файле — это Task 1.5.7.

**Edge cases:**
- `_FakeStrView.set_items` — добавить метод `set_items(items)` который сохраняет `self.items = items` для проверки в тестах.
- Тест Signal требует `qapp` fixture (Qt event loop).

**Dependencies:** Tasks 1.5.1, 1.5.2, 1.5.3, 1.5.4

---

## Task 1.5.6 — _build_literal_binding_aware + form_ctx kwarg + dispatch _KIND_LITERAL

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** создать `_build_literal_binding_aware()` в factory.py, добавить `form_ctx` kwarg в `_build_literal` и dispatch для `_KIND_LITERAL` в `CardsFieldFactory.create`

**Context:** `_build_literal` (строки 373-391 factory.py) создаёт `QComboBox` напрямую без binding.
Нужно добавить binding-aware путь через `ComboControl.create`. Items берутся из `get_args(Literal[...])`.

**Ключевой нюанс:** `_build_literal` уже извлекает items из типа через `get_args(t)`:
```python
t = _unwrap_optional(field_info.field_type)
items = list(get_args(t))
```
В `_build_literal_binding_aware` нужно передать эти items в `ComboControl.create`.

**Файлы:**
- `multiprocess_prototype/frontend/forms/factory.py` — изменить

**Steps:**

1. Прочитать актуальные строки 373-391 factory.py перед правкой.

2. Добавить `_build_literal_binding_aware` после `_build_color3_binding_aware`:
   ```python
   def _build_literal_binding_aware(
       field_info: FieldInfo,
       form_ctx: FormContext,
       parent: QWidget | None = None,
   ) -> FieldEditor:
       """ComboControl через FormContext.write — binding-aware путь для Literal["a","b","c"].

       Items берутся из Literal-аргументов типа поля.
       Coalescing, undo/redo, IPC bridge — автоматически через ActionBus.
       """
       from typing import get_args
       from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
       from multiprocess_framework.modules.frontend_module.components.combo import (
           ComboControl,
           ComboViewConfig,
       )

       binding = BindingConfig(
           field_info.plugin_name or "",
           field_info.field_name or "",
       )
       t = _unwrap_optional(field_info.field_type)
       items = [str(x) for x in get_args(t)]

       result = ComboControl.create(
           form_ctx.registers_manager,
           binding,
           ComboViewConfig(label=field_info.title),
           current_access_level=form_ctx.access_level,
           items=items,
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

3. Обновить `_build_literal` — добавить `form_ctx` kwarg и dispatch:
   ```python
   def _build_literal(
       field_info: FieldInfo,
       parent: QWidget | None = None,
       *,
       form_ctx: FormContext | None = None,
   ) -> FieldEditor:
       """QComboBox для Literal["a","b","c"] (legacy) или ComboControl (binding-aware)."""
       if form_ctx is not None:
           return _build_literal_binding_aware(field_info, form_ctx, parent)
       # Legacy: raw QComboBox без binding
       ...  # существующий код без изменений
   ```

4. Добавить dispatch в `CardsFieldFactory.create`:
   ```python
   if kind == _KIND_LITERAL and builder is _build_literal:
       return _build_literal(field_info, parent, form_ctx=form_ctx)
   ```
   Вставить после `_KIND_COLOR3` dispatch.

5. Обновить docstring `CardsFieldFactory.create` — упомянуть literal dispatch через ComboControl.

**Acceptance criteria:**
- [ ] `grep -n "_build_literal_binding_aware" multiprocess_prototype/frontend/forms/factory.py` — есть определение и вызов
- [ ] `grep -n "_KIND_LITERAL" multiprocess_prototype/frontend/forms/factory.py` — dispatch в `CardsFieldFactory.create` добавлен
- [ ] `_build_literal(field_info, form_ctx=mock_ctx)` → `_build_literal_binding_aware` → `ComboControl.create`
- [ ] `_build_literal(field_info)` без form_ctx → legacy QComboBox (без регрессии)
- [ ] `ruff check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок
- [ ] `ruff format --check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок

**Out of scope:** не менять `_build_color3`, не трогать `_build_bool`/`_build_int`/`_build_float`.

**Edge cases:**
- `Literal[1, 2, 3]` (int items, не str) — `get_args` вернёт `(1, 2, 3)` → `[str(x) for x in ...]` даст `["1","2","3"]`. Это ОК — ComboControl работает со строками, write обратно передаст str в RM.
- `_unwrap_optional` — функция уже используется в `_build_literal` (строка 376) — импорт есть.

**Dependencies:** Tasks 1.5.1-1.5.4 (ComboControl готов)

---

## Task 1.5.7 — Тесты form_ctx для ComboControl (test_combo_form_ctx.py)

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** написать 4 теста по образцу `test_spinbox_form_ctx.py`, покрывающих write через form_ctx, undo, legacy и access guard для ComboControl

**Context:** Паттерн идентичен `test_spinbox_form_ctx.py` с заменой числового поля на строковое.
Отличия: `_FakeRegister.mode: str = "auto"`, `_FakeRegistersManager._meta` для `("config","mode")`,
`ComboControl.create` с `items=["auto","manual","off"]`.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/tests/test_combo_form_ctx.py` — создать новый файл

**Steps:**

1. Создать `test_combo_form_ctx.py` по образцу `test_spinbox_form_ctx.py`.

2. Адаптировать фейки:
   - `_FakeRegister` — `mode: str = "auto"`
   - `_FakeRegistersManager` — регистр `"config"`, поле `"mode"`, meta с `{"description": "Режим"}`
   - `_FakeActionBuilder.field_set_timed` — принимает str new/old (не float)
   - Остальные фейки и fixtures — без изменений

3. Тест `test_combo_write_via_form_ctx`:
   - `ComboControl.create(fake_rm, BindingConfig("config","mode"), items=["auto","manual","off"], current_access_level=0, form_ctx=form_ctx)`
   - `presenter._on_changed("manual")`
   - Assert: `fake_rm.get_register("config").mode == "manual"`
   - Assert: `bus_with_handler.last_action() is not None`

4. Тест `test_combo_undo_restores_view` (требует qapp):
   - write("manual") → undo() → RM="auto" → `widget.get_value()=="auto"`

5. Тест `test_combo_legacy_path_no_form_ctx` (требует qapp):
   - `ComboControl.create(...)` без form_ctx
   - `presenter._on_changed("off")`
   - Assert: `fake_rm.get_register("config").mode == "off"`

6. Тест `test_combo_access_level_guard` (требует qapp):
   - `BindingConfig("config","mode", access_level=3)`, `current_access_level=0`
   - Assert: `presenter._access.can_modify() is False`
   - `presenter._on_changed("off")` → RM не изменился
   - `presenter.set_access_level(3)` → `presenter._access.can_modify() is True`

**Acceptance criteria:**
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_combo_form_ctx.py -v` — 0 FAILED
- [ ] Минимум 4 теста PASSED
- [ ] `ruff check multiprocess_framework/modules/frontend_module/tests/test_combo_form_ctx.py` — 0 ошибок
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — регрессия 0 FAILED

**Out of scope:** не тестировать items-init в этом файле (это в test_combo_v2.py).

**Edge cases:**
- `bus_with_handler.undo()` возвращает `None` если стек пуст — `assert undone is not None` как в spinbox-тестах.
- `DeprecationWarning` при `set_access_level` — обернуть в `warnings.catch_warnings()`.

**Dependencies:** Tasks 1.5.1-1.5.6

---

## Acceptance вся фаза (Track 1.4 + 1.5)

- [ ] `CompoundNumericControl.create(..., *, form_ctx=None)` — kwarg добавлен, backward-совместим
- [ ] `_build_color3(field_info, form_ctx=form_ctx)` → `_build_color3_binding_aware` → `CompoundNumericControl.create(form_ctx=form_ctx)`
- [ ] `_build_color3(field_info)` без form_ctx — legacy inline (3 raw QSpinBox), без ColorTripletWidget
- [ ] `ColorTripletWidget` удалён: файл `color_picker.py` не существует, импорт в factory.py отсутствует
- [ ] `_KIND_COLOR3` dispatch добавлен в `CardsFieldFactory.create`
- [ ] `ComboControl` существует в FW — пакет `combo/` с config, view, presenter, facade, `__init__`
- [ ] `ComboControl.create(..., *, form_ctx=None)` — kwarg keyword-only
- [ ] `_build_literal(field_info, form_ctx=form_ctx)` → `_build_literal_binding_aware` → `ComboControl.create`
- [ ] `_build_literal(field_info)` без form_ctx — legacy QComboBox (без регрессии)
- [ ] `_KIND_LITERAL` dispatch добавлен в `CardsFieldFactory.create`
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_compound_form_ctx.py -v` — 4 PASSED
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_combo_v2.py -v` — минимум 5 PASSED
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_combo_form_ctx.py -v` — 4 PASSED
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — регрессия 0 FAILED
- [ ] `ruff check` по всем изменённым файлам — 0 ошибок
- [ ] `python scripts/validate.py` — зелёный
- [ ] `python scripts/run_framework_tests.py` — зелёный
- [ ] Техдолги #9 и #10 из rollout-finish.md — CLOSED

---

## Шаблон commit messages

**Два отдельных коммита** (Compound и Combo независимы).

**Коммит 1 — Compound + color3:**
```
feat(frontend): CompoundNumericControl vertical slice — form_ctx + _build_color3_binding_aware

- CompoundNumericControl.create: form_ctx kwarg + TYPE_CHECKING + docstring
- factory._build_color3: kwarg form_ctx, dispatch на _build_color3_binding_aware (CompoundNumericConfig)
- factory._build_color3_binding_aware: CompoundNumericConfig(R/G/B labels, view_type=spinbox, 0-255)
- CardsFieldFactory.create: dispatch для _KIND_COLOR3 с form_ctx
- ColorTripletWidget удалён: color_picker.py deleted, импорт удалён из factory.py
- test_compound_form_ctx.py: 4 теста (write sub-control, undo, legacy, access guard)

Why: закрывает техдолг #9 (ColorTripletWidget 62 LOC); color3 теперь идёт через
     CompoundNumericControl с ActionBus как все остальные numeric-поля
Layer: mixed
Refs: plans/frontend-widgets-cleanup/track-1-4-1-5-compound-combo.md, plans/frontend-widgets-cleanup/rollout-finish.md
Risk: low — NumericControl.create уже принимает form_ctx; только facade-правка + удаление legacy
Tested: frontend/compound_form_ctx/4 passed, frontend/all/green, validate.py/green
```

**Коммит 2 — Combo (новый компонент):**
```
feat(frontend): ComboControl — новый FW компонент + _build_literal_binding_aware

- combo/__init__.py + combo/config.py: ComboViewConfig(BaseControlConfig) с items/placeholder
- combo/view.py: ComboView(QWidget), value_changed=Signal(str), full IControlView[str] contract
- combo/presenter.py: ComboPresenter — dual-mode write (form_ctx vs SyncTrait), items init
- combo/facade.py: ComboControl.create(rm, binding, view_config, items, *, form_ctx=None)
- factory._build_literal: kwarg form_ctx, dispatch на _build_literal_binding_aware
- factory._build_literal_binding_aware: ComboControl.create с items из Literal args
- CardsFieldFactory.create: dispatch для _KIND_LITERAL с form_ctx
- test_combo_v2.py: 7 тестов (presenter, sync, items, access, Signal, facade)
- test_combo_form_ctx.py: 4 теста (write, undo, legacy, access guard)

Why: закрывает техдолг #10 (нет combo/ в FW); Literal-поля теперь идут через ActionBus
Layer: mixed
Refs: plans/frontend-widgets-cleanup/track-1-4-1-5-compound-combo.md, plans/frontend-widgets-cleanup/rollout-finish.md
Risk: medium — новый компонент с нуля, паттерн Checkbox применён к str-типу
Tested: frontend/combo_v2/7 passed, frontend/combo_form_ctx/4 passed, frontend/all/green, validate.py/green
```

---

## Verification команды

```powershell
# 1. Тесты Compound form_ctx
pytest multiprocess_framework/modules/frontend_module/tests/test_compound_form_ctx.py -v

# 2. Тесты Combo unit
pytest multiprocess_framework/modules/frontend_module/tests/test_combo_v2.py -v

# 3. Тесты Combo form_ctx
pytest multiprocess_framework/modules/frontend_module/tests/test_combo_form_ctx.py -v

# 4. Регрессия FW frontend
pytest multiprocess_framework/modules/frontend_module/tests/ -v

# 5. Ruff FW компоненты
ruff check `
  multiprocess_framework/modules/frontend_module/components/compound/facade.py `
  multiprocess_framework/modules/frontend_module/components/combo/

# 6. Ruff factory
ruff check multiprocess_prototype/frontend/forms/factory.py
ruff format --check multiprocess_prototype/frontend/forms/factory.py

# 7. ColorTripletWidget полностью удалён
Select-String -Pattern "ColorTripletWidget" -Path multiprocess_prototype/ -Recurse
# Ожидается: 0 результатов

# 8. _build_color3_binding_aware в factory
Select-String -Pattern "_build_color3_binding_aware" multiprocess_prototype/frontend/forms/factory.py

# 9. _build_literal_binding_aware в factory
Select-String -Pattern "_build_literal_binding_aware" multiprocess_prototype/frontend/forms/factory.py

# 10. _KIND_COLOR3 и _KIND_LITERAL dispatch в CardsFieldFactory
Select-String -Pattern "_KIND_COLOR3|_KIND_LITERAL" multiprocess_prototype/frontend/forms/factory.py

# 11. Проверить что combo/__init__.py экспортирует все 5 символов
python -c "from multiprocess_framework.modules.frontend_module.components.combo import ComboControl, ComboControlResult, ComboPresenter, ComboView, ComboViewConfig; print('ok')"

# 12. Общая валидация
python scripts/validate.py
python scripts/run_framework_tests.py
```

---

## Риски и ограничения

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| `CompoundNumericControl.create` — `NumericControl.create` не принимает `form_ctx` (Task 1.3.1 не выполнен) | Низкая | Проверить через grep до начала 1.4.1; если не выполнено — блокер |
| `BindingConfig(index=i)` в compound sub-controls — `RegisterAdapter` может не поддерживать indexed write в `_FakeRegistersManager` для тестов | Средняя | В тестах 1.4.4 использовать простое поле без index если RM не поддерживает; проверить как `SyncTrait.write` обрабатывает `index` kwarg перед написанием тестов |
| `LabeledNumericGroupView.get_value()` / `set_value_silent()` — может быть не реализован для compound result в `_build_color3_binding_aware` lambda | Средняя | getter через `lambda: tuple(r.widget.get_value() for r in result.results)` — работает если `r.widget` это `LabeledNumericGroupView`. Проверить тип `result.results[i].widget` |
| `QComboBox` отсутствует в `core/qt_imports.py` | Средняя | Проверить `core/qt_imports.py` перед созданием view.py; если нет — добавить `from PySide6.QtWidgets import QComboBox` напрямую |
| `IControlView[str].set_items` — метод не в интерфейсе, `attach_view` в presenter принимает `IControlView[str]` | Средняя | Вызывать через `hasattr(view, "set_items")` guard в presenter; view-протокол не нарушается |
| `SyncTrait.read()` возвращает non-str для Literal[1,2,3] (int values) | Высокая | Всегда `str()` cast в presenter; items тоже `str(x)` в `_build_literal_binding_aware` — прописано в Steps |
| `ComboView.set_value` эмитит `value_changed` (через `currentTextChanged`) что вызывает двойной write при `set_value_silent` | Средняя | `set_value_silent` использует `block_signals` — это предотвращает двойной emit; убедиться что `set_value_silent` корректно блокирует сигналы (паттерн из CheckboxView и SpinBoxValueView) |
| `_build_color3` legacy inline — `QHBoxLayout`, `QSpinBox` уже импортированы в factory.py | Низкая | Проверить импорты factory.py; если нет — добавить в blok локальных импортов внутри функции |
| Track 1.4 и 1.5 коммитятся в одну ветку — конфликты в factory.py если делать параллельно | Низкая | Делать последовательно: сначала Track 1.4 (коммит), затем Track 1.5 (коммит) |
