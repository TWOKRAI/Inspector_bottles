# Plan: Track 1.1 + 2.1 — Vertical slice SpinBoxControl + _build_int (form_ctx)

- **Slug:** frontend-widgets-track-1-1-spinbox
- **Дата:** 2026-05-15
- **Статус:** DRAFT
- **Ветка:** refactor/frontend-widgets-cleanup
- **Родительский план:** [`rollout-finish.md`](rollout-finish.md), секции «Track 1» (1.1) и «Track 2» (2.1)
- **Верхнеуровневая карта:** [`plan.md`](plan.md)

---

## Зачем

Track 0 полностью закрыл пилот CheckboxControl: round-trip тест, fan-out smoke, access-level guard, docstring и README. Следующий шаг — тиражировать этот паттерн на `SpinBoxControl`. Согласно принципу **vertical slice** (rollout-finish.md, строки 30-37): FW facade (`form_ctx` kwarg в `SpinBoxControl.create`) + factory builder (`_build_int_binding_aware` в `factory.py`) + тесты — один коммит. Track 1.1 и Task 2.1 объединяются и не разбиваются на два PR.

Ключевое отличие от Checkbox: SpinBox является тонкой обёрткой над `NumericPresenter`, write-логика живёт в `NumericPresenter._write()` через `SyncTrait.write()`, а не в самом `SpinBoxPresenter`. Поэтому dual-mode (`form_ctx.write` vs `SyncTrait.write`) добавляется в `NumericPresenter`, а `SpinBoxPresenter` остаётся тонким наследником без изменений логики. View (`SpinBoxValueView`) уже имеет `value_changed = Signal(float)` — добавлять ничего не нужно.

---

## Ключевые факты из анализа кода

| Что | Факт |
|-----|------|
| `SpinBoxValueView.value_changed` | Уже есть: `Signal(float)`. Задача 1.1.1 (добавить сигнал) **отпадает** |
| Write-механизм | `NumericPresenter._write()` → `self._sync.write(storage_value)` (через `SyncTrait → RegisterAdapter → rm.set_field_value`). form_ctx не подключён |
| Архитектура | `SpinBoxPresenter` наследует `NumericPresenter` полностью; сам не переопределяет `_write`, `_on_changing`, `_on_finished` |
| `SpinBoxControl.create` | Принимает `legacy_context` (старый), `hooks`, но **не** `form_ctx`. Нет `TYPE_CHECKING`-импорта `FormContext` |
| `_build_int` в factory | Создаёт raw `QSpinBox` напрямую (37 строк). Нет `form_ctx` kwarg |
| Тип сигнала | `Signal(float)` — SpinBox в FW работает с `float` даже для int-полей (QDoubleSpinBox с `set_validator_int()` → 0 decimals). В factory legacy-путь — raw `QSpinBox` с `int` |
| Тип данных при write | `storage_value: float` (через `ValueTransformer.to_storage()`). `form_ctx.write()` получит `float`; callers (FieldSetHandler) должны быть к этому готовы — проверить |

---

## Порядок выполнения

### Phase 1: Framework — NumericPresenter + SpinBoxControl facade (задачи 1.1.1, 1.1.2)

- Task 1.1.1: Dual-mode write в `NumericPresenter` — `form_ctx` kwarg + `_write` разветвление [PENDING]
- Task 1.1.2: `form_ctx` kwarg в `SpinBoxControl.create` — пробросить через `SpinBoxPresenter` в `NumericPresenter` [PENDING]

### Phase 2: Prototype — factory builder (задача 1.1.3)

- Task 1.1.3: `_build_int_binding_aware` в `factory.py` + kwarg `form_ctx` в `_build_int` [PENDING]

### Phase 3: Тесты (задача 1.1.4)

- Task 1.1.4: 4-5 тестов для SpinBox с form_ctx [PENDING]

---

## Task 1.1.1 — Dual-mode write в NumericPresenter

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** добавить `form_ctx: FormContext | None = None` в `NumericPresenter.__init__` и разветвить `_write()` на form_ctx-путь vs legacy-путь

**Context:** `SpinBoxPresenter` наследует `NumericPresenter` без переопределений — вся write-логика сосредоточена в `NumericPresenter._write()`. Это единственное место где нужно внедрить dual-mode. Аналог: `CheckboxPresenter._on_changed()` в `checkbox/presenter.py` (строки 131-143). Важно: `form_ctx.write()` ожидает `old_value` — его нужно получить через `self._sync.read()` до записи, аналогично Checkbox. Тип `storage_value` — `float`; `form_ctx.write` принимает `Any`, это нормально.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/components/numeric/presenter.py` — изменить

**Steps:**
1. Добавить в начало файла в блок `TYPE_CHECKING`:
   ```python
   if TYPE_CHECKING:
       from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext
   ```
2. В `NumericPresenter.__init__` добавить kwarg `form_ctx: "FormContext | None" = None` — последним именованным параметром. Сохранить в `self._form_ctx = form_ctx`.
3. В `_write(self, storage_value: float)` заменить тело на dual-mode:
   ```python
   def _write(self, storage_value: float) -> None:
       if self._form_ctx is not None:
           # Новый путь: write через ActionBus (coalescing, undo/redo, IPC bridge).
           old_value = self._sync.read()
           ok = self._form_ctx.write(
               self._binding.register_name,
               self._binding.field_name,
               storage_value,
               old_value,
           )
           err = None if ok else "write failed"
       else:
           # Legacy путь: прямая запись через SyncTrait → RegisterAdapter → rm.
           ok, err = self._sync.write(storage_value)
       if not ok:
           msg = err or "write failed"
           emit_write_rejected(self._hooks, self._binding, self._control_kind, msg, storage_value)
           self._sync_from_model()
           if err and self._view is not None:
               self._view.show_error(err)
       else:
           emit_write_committed(self._hooks, self._binding, self._control_kind, storage_value)
           if self._legacy:
               self._legacy.notify_after_write(storage_value)
   ```
4. Убедиться что `self._binding` доступен в `NumericPresenter` (он хранится в `self._binding = binding`, строка в коде). Если нет — добавить.
5. Проверить импорт `BindingConfig` — он уже есть через `from ... import BindingConfig`.

**Acceptance criteria:**
- [ ] `ruff check multiprocess_framework/modules/frontend_module/components/numeric/presenter.py` — 0 ошибок
- [ ] `ruff format --check ...presenter.py` — 0 ошибок
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — все существующие тесты PASSED (регрессия)
- [ ] `form_ctx` kwarg присутствует в сигнатуре `NumericPresenter.__init__`
- [ ] `self._form_ctx` хранится в `__init__`

**Out of scope:** не трогать `SliderPresenter`, `SliderControl` — это Track 1.2. Не удалять legacy-путь — он остаётся для non-plugin callers.

**Edge cases:**
- `self._sync.read()` может вернуть `None` (поле не инициализировано в RM). В Checkbox это обрабатывается как `bool(None) = False`. Для числового поля: передать `None` как `old_value` в `form_ctx.write()` — это допустимо (ActionBus обработает).
- `_on_changing` использует debounce → `_write` вызывается через lambda. Замыкание захватывает `storage_value` — это не изменится при внедрении form_ctx.

**Dependencies:** нет

---

## Task 1.1.2 — form_ctx kwarg в SpinBoxControl.create и SpinBoxPresenter

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** пробросить `form_ctx` через `SpinBoxControl.create` → `SpinBoxPresenter.__init__` → `NumericPresenter.__init__`

**Context:** `SpinBoxPresenter` — тонкий наследник `NumericPresenter` (40 строк, только `__init__` с `super().__init__(..., control_kind="spinbox")`). `SpinBoxControl.create` — статическая фабрика (87 строк), создаёт `SpinBoxPresenter`. Нужно добавить kwarg `form_ctx` в обоих местах с проксированием вниз. Паттерн — точно как в `CheckboxControl.create` (строки 51-58 facade.py) с `TYPE_CHECKING` импортом.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/components/spinbox/presenter.py` — добавить `form_ctx` kwarg в `__init__`, пробросить в `super().__init__`
- `multiprocess_framework/modules/frontend_module/components/spinbox/facade.py` — добавить `form_ctx` kwarg в `SpinBoxControl.create`, добавить `TYPE_CHECKING` импорт, пробросить в `SpinBoxPresenter`

**Steps:**
1. В `spinbox/presenter.py`:
   - Добавить в топ файла блок `TYPE_CHECKING` с импортом `FormContext` (по аналогии с `checkbox/presenter.py`)
   - В `SpinBoxPresenter.__init__` добавить kwarg `form_ctx: "FormContext | None" = None` — последним именованным параметром
   - В вызове `super().__init__(...)` добавить `form_ctx=form_ctx`

2. В `spinbox/facade.py`:
   - Добавить `from typing import TYPE_CHECKING` (если нет) и блок `if TYPE_CHECKING: from ...form_context import FormContext`
   - В `SpinBoxControl.create` добавить kwarg `form_ctx: "FormContext | None" = None` — последним именованным параметром (после `hooks`)
   - В вызове `SpinBoxPresenter(...)` добавить `form_ctx=form_ctx`
   - Добавить в docstring `create` секцию для `form_ctx` — по аналогии с расширенным docstring в `checkbox/facade.py` (строки 71-83): production-путь, legacy-путь, рекомендация

**Acceptance criteria:**
- [ ] `SpinBoxControl.create(rm, binding, view_config, current_access_level=0, hooks=None, form_ctx=None)` — сигнатура корректна
- [ ] `ruff check multiprocess_framework/modules/frontend_module/components/spinbox/` — 0 ошибок
- [ ] `python -c "from multiprocess_framework.modules.frontend_module.components.spinbox import SpinBoxControl; print('ok')"` — без ImportError
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — все существующие тесты PASSED

**Out of scope:** не трогать `SpinBoxConfig`, `SpinBoxValueView`, `group/` — они не меняются в этом task.

**Edge cases:** `legacy_context` параметр в `SpinBoxPresenter.__init__` уже есть — убедиться что `form_ctx` добавляется **отдельно**, не заменяет `legacy_context`.

**Dependencies:** Task 1.1.1 (NumericPresenter должен принять form_ctx)

---

## Task 1.1.3 — _build_int_binding_aware в factory.py + form_ctx kwarg в _build_int

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** создать `_build_int_binding_aware()` в `factory.py` по образцу `_build_bool_binding_aware` и добавить kwarg `form_ctx` в `_build_int` с разветвлением

**Context:** текущий `_build_int` (строки 307-343 factory.py) создаёт raw `QSpinBox` напрямую. Нужно добавить binding-aware путь через `SpinBoxControl.create(..., form_ctx=form_ctx)`. Паттерн — точно `_build_bool_binding_aware` (строки 220-266). Нюанс: `SpinBoxControl` использует `SpinBoxConfig` (не `SpinBoxViewConfig` — такого нет, конфиг называется `SpinBoxConfig`). Второй нюанс: в factory `FieldInfo` хранит `min_value`, `max_value`, `unit` — их нужно передать в `SpinBoxConfig(min_val=, max_val=)`. Третий нюанс: `FieldEditor.change_signal=None` для binding-aware пути (как в `_build_bool_binding_aware` строка 264) — иначе двойной write.

**Файлы:**
- `multiprocess_prototype/frontend/forms/factory.py` — изменить

**Steps:**
1. Прочитать актуальное состояние `factory.py` строки 307-343 (`_build_int`) и 220-266 (`_build_bool_binding_aware`) перед внесением правок.

2. Добавить функцию `_build_int_binding_aware` сразу после `_build_bool_binding_aware` (примерно перед `_build_literal`):
   ```python
   def _build_int_binding_aware(
       field_info: FieldInfo,
       form_ctx: FormContext,
       parent: QWidget | None = None,
   ) -> FieldEditor:
       """SpinBoxControl через FormContext.write — binding-aware путь.

       Coalescing, undo/redo, IPC bridge — автоматически через ActionBus.
       """
       from multiprocess_framework.modules.frontend_module.components.base.config import (
           BindingConfig,
       )
       from multiprocess_framework.modules.frontend_module.components.spinbox import (
           SpinBoxControl,
           SpinBoxConfig,
       )

       binding = BindingConfig(
           field_info.plugin_name or "",
           field_info.field_name or "",
       )
       view_config = SpinBoxConfig(
           label=field_info.title,
           min_val=float(field_info.min_value) if field_info.min_value is not None else None,
           max_val=float(field_info.max_value) if field_info.max_value is not None else None,
       )

       result = SpinBoxControl.create(
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

3. Изменить сигнатуру `_build_int`:
   ```python
   def _build_int(
       field_info: FieldInfo,
       parent: QWidget | None = None,
       *,
       form_ctx: FormContext | None = None,
   ) -> FieldEditor:
       """QSpinBox для int (legacy) или SpinBoxControl (binding-aware, если form_ctx передан)."""
       if form_ctx is not None:
           return _build_int_binding_aware(field_info, form_ctx, parent)
       # Legacy путь — raw QSpinBox без binding-aware моста.
       ...  # остальной текущий код без изменений
   ```

4. Проверить что `SpinBoxConfig` экспортируется из `multiprocess_framework.modules.frontend_module.components.spinbox` (проверить `__init__.py` пакета).

5. Проверить что `get_value` и `set_value_silent` существуют на объекте `result.widget` (это `LabeledNumericGroup` — проверить его interface через `group/labeled_numeric_factory.py`).

**Acceptance criteria:**
- [ ] `grep -n "form_ctx" multiprocess_prototype/frontend/forms/factory.py` показывает `_build_int` и `_build_int_binding_aware`
- [ ] `_build_int(field_info, form_ctx=None)` — legacy путь работает (QSpinBox создаётся)
- [ ] `_build_int(field_info, form_ctx=form_ctx)` — вызывает `_build_int_binding_aware`
- [ ] `ruff check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок
- [ ] `ruff format --check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок

**Out of scope:** не трогать `_build_float`, `_build_literal`, другие builders. Не мигрировать callers — это Track 3.

**Edge cases:**
- `field_info.unit` — суффикс. В legacy-пути он ставится через `spin.setSuffix(f" {unit}")`. В binding-aware пути `SpinBoxConfig` не имеет поля `suffix` — суффикс приходит через `FieldMeta` в RM. Убедиться что `FieldMeta.unit` прокидывается в RM или добавить в docstring NOTE что unit в binding-aware пути берётся из метаданных регистра, а не из `SpinBoxConfig`.
- `result.widget` — это `LabeledNumericGroup`, не `SpinBoxValueView`. Методы `get_value` / `set_value_silent` должны быть на этом виджете. Если их нет — нужно делегировать через `result.widget.value_view.get_value`. Проверить `group/` перед написанием.

**Dependencies:** Task 1.1.2 (SpinBoxControl.create принимает form_ctx)

---

## Task 1.1.4 — Тесты: SpinBoxControl с form_ctx

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** написать 4-5 тестов, покрывающих write через form_ctx, undo, legacy-путь и access-level guard для SpinBoxControl

**Context:** паттерн тестов — аналог `test_checkbox_v2.py` + `test_form_context_integration.py` (Track 0). SpinBox работает без QApplication в unit-тестах (presenter без Qt, faker RM). Для Qt-smoke нужен `qapp` fixture. Ключевое отличие: write идёт с debounce (100ms) через `DebounceTrait`. В тестах debounce нужно либо форсировать (`presenter._debounce.flush()` если есть), либо вызывать `presenter._on_finished(value)` напрямую (он вызывает `_debounce.cancel()` + немедленный `_write`). Использовать `_on_finished` как основной триггер в тестах.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/tests/test_spinbox_form_ctx.py` — создать новый файл

**Steps:**
1. Создать файл `test_spinbox_form_ctx.py` в `multiprocess_framework/modules/frontend_module/tests/`.

2. Скопировать фейки из `test_checkbox_v2.py` или `test_controls_v2_base.py`: `_FakeRegistersManager` (subscribe/unsubscribe/get_register/get_field_metadata/set_field_value). Адаптировать для числового поля `speed` в регистре `motor` с `{"min": 0, "max": 1000, "description": "Скорость"}`.

3. Скопировать фейки FormContext из `test_form_context_write.py`: `_FakeActionBuilder`, `_FakeActionBus` (записывает последний action, поддерживает `undo()`).

4. Написать тест `test_spinbox_write_via_form_ctx`:
   - Создать `FormContext(rm, bus, _FakeActionBuilder)`
   - `SpinBoxControl.create(rm, BindingConfig("motor", "speed"), SpinBoxConfig(), current_access_level=0, form_ctx=form_ctx)`
   - Вызвать `presenter._on_finished(42.0)` (имитация Enter/LostFocus)
   - Assert: `bus.last_action is not None` (action попал в bus)
   - Assert: `rm.get_register("motor").speed.value == 42.0`

5. Написать тест `test_spinbox_undo_restores_view`:
   - Аналогично Task 0.1 для Checkbox (round-trip через undo)
   - Требует `qapp` fixture (SpinBoxPresenter attach_view подключает Qt view)
   - `presenter._on_finished(100.0)` → `bus.undo()` → rm вернулся к 0.0 → подписчик → `view.set_value_silent(0.0)` → `view.get_value() == 0.0`

6. Написать тест `test_spinbox_legacy_path_no_form_ctx`:
   - Создать без form_ctx: `SpinBoxControl.create(rm, binding, SpinBoxConfig())`
   - `presenter._on_finished(55.0)`
   - Assert: `rm.get_register("motor").speed.value == 55.0` (прямая запись через SyncTrait)
   - Assert: `bus` не использован (можно просто не передавать bus вообще)

7. Написать тест `test_spinbox_access_level_guard`:
   - `SpinBoxControl.create(rm, BindingConfig("motor", "speed", access_level=5), SpinBoxConfig(), current_access_level=0, form_ctx=form_ctx)`
   - Требует `qapp` для attach_view
   - Assert: `result.widget` — spinbox disabled (`result.widget.value_view.set_enabled` вызван с False), либо `result.presenter.set_access_level(0)` → `presenter._access.can_modify() == False`
   - `presenter._on_finished(99.0)` → `rm.get_register("motor").speed.value != 99.0` (write заблокирован)

8. (Опционально) Написать тест `test_spinbox_debounce_skipped_on_finished`:
   - `presenter._on_changing(10.0)` → debounce запланирован, write ещё не произошёл
   - `presenter._on_finished(20.0)` → debounce отменён, write немедленно с 20.0
   - Assert: `rm.get_register("motor").speed.value == 20.0`

**Acceptance criteria:**
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_spinbox_form_ctx.py -v` — 0 FAILED
- [ ] Минимум 4 теста PASSED (write via form_ctx, undo, legacy, access guard)
- [ ] `ruff check multiprocess_framework/modules/frontend_module/tests/test_spinbox_form_ctx.py` — 0 ошибок
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — все существующие тесты PASSED (регрессия не сломана)

**Out of scope:** не проверять fan-out multi-target (это Track 0.2); не проверять touch-keyboard; не тестировать debounce timeout (только cancel через _on_finished)

**Edge cases:**
- `DebounceTrait` использует `QTimer` внутри. В headless-тестах (без QApplication) `_on_changing` с debounce может упасть. Использовать только `_on_finished` в тестах без `qapp`, и с `qapp` для round-trip.
- `_FakeActionBus.undo()` должен вызвать `rm.set_field_value(register, field, old_value)` — для этого `_FakeFieldSetHandler` должен знать register/field/old_value. Скопировать реализацию из `test_form_context_integration.py` (Task 0.1) или из `test_form_context_write.py`.

**Dependencies:** Tasks 1.1.1, 1.1.2, 1.1.3

---

## Acceptance вся Track 1.1

- [ ] `SpinBoxControl.create(..., form_ctx=None)` — kwarg добавлен, backward-совместим
- [ ] `NumericPresenter._write()` — dual-mode: form_ctx.write vs SyncTrait.write
- [ ] `_build_int(field_info, form_ctx=form_ctx)` → `_build_int_binding_aware` → `SpinBoxControl.create(form_ctx=form_ctx)`
- [ ] `_build_int(field_info)` (без form_ctx) — legacy QSpinBox путь работает без изменений
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_spinbox_form_ctx.py -v` — 4+ тестов PASSED
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — регрессия 0 FAILED
- [ ] `pytest multiprocess_prototype/frontend/forms/tests/ -v` — регрессия 0 FAILED (если есть)
- [ ] `ruff check multiprocess_framework/modules/frontend_module/components/numeric/presenter.py multiprocess_framework/modules/frontend_module/components/spinbox/presenter.py multiprocess_framework/modules/frontend_module/components/spinbox/facade.py multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок
- [ ] `python scripts/validate.py` — зелёный
- [ ] `python scripts/run_framework_tests.py` — зелёный
- [ ] Техдолг #8 из rollout-finish.md частично закрыт (`value_changed: Signal` в SpinBoxValueView — уже был, не нужен)

---

## Шаблон commit message

```
feat(frontend): SpinBox vertical slice — form_ctx + _build_int binding-aware

- NumericPresenter._write: dual-mode (form_ctx.write vs SyncTrait.write)
- SpinBoxPresenter.__init__: form_ctx kwarg → super().__init__
- SpinBoxControl.create: form_ctx kwarg + TYPE_CHECKING импорт + docstring
- factory._build_int: kwarg form_ctx, разветвление на _build_int_binding_aware
- factory._build_int_binding_aware: SpinBoxControl.create с form_ctx
- test_spinbox_form_ctx.py: 4 теста (write, undo, legacy, access guard)

Why: тиражирование паттерна CheckboxControl на SpinBox — первый numeric
     vertical slice; один коммит (FW facade + factory builder + тесты)
Layer: mixed
Refs: plans/frontend-widgets-cleanup/track-1-1-spinbox.md, plans/frontend-widgets-cleanup/rollout-finish.md
Risk: low — dual-mode изолирован в NumericPresenter._write; legacy путь не тронут
Tested: frontend/spinbox_form_ctx/4 passed, frontend/all/green, validate.py/green
```

---

## Verification команды

```powershell
# 1. Новые тесты SpinBox form_ctx
pytest multiprocess_framework/modules/frontend_module/tests/test_spinbox_form_ctx.py -v

# 2. Регрессия FW frontend тестов
pytest multiprocess_framework/modules/frontend_module/tests/ -v

# 3. Ruff все изменённые FW файлы
ruff check `
  multiprocess_framework/modules/frontend_module/components/numeric/presenter.py `
  multiprocess_framework/modules/frontend_module/components/spinbox/presenter.py `
  multiprocess_framework/modules/frontend_module/components/spinbox/facade.py

# 4. Ruff factory
ruff check multiprocess_prototype/frontend/forms/factory.py
ruff format --check multiprocess_prototype/frontend/forms/factory.py

# 5. Проверить что _build_int принимает form_ctx
Select-String -Pattern "form_ctx" multiprocess_prototype/frontend/forms/factory.py

# 6. Проверить что NumericPresenter._write dual-mode
Select-String -Pattern "_form_ctx" multiprocess_framework/modules/frontend_module/components/numeric/presenter.py

# 7. Общая валидация
python scripts/validate.py
python scripts/run_framework_tests.py
```

---

## Риски и ограничения

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| `result.widget` у SpinBoxControl — `LabeledNumericGroup`, а не SpinBoxValueView; методы `get_value`/`set_value_silent` могут отсутствовать на верхнем виджете | Средняя | Перед Task 1.1.3 прочитать `group/labeled_numeric_factory.py` и `group/labeled_numeric_group.py` и убедиться в наличии методов; если отсутствуют — делегировать через `result.widget.value_view` |
| `DebounceTrait` требует QApplication для `QTimer` | Средняя | В тестах без `qapp` использовать только `_on_finished`, не `_on_changing` |
| `SpinBoxConfig` не имеет поля `suffix`/`unit` — единица измерения потеряется в binding-aware пути | Низкая | unit берётся из FieldMeta в RM автоматически через `ValueTransformer.to_ui` или `SchemaTrait`; в NOTE в docstring указать это явно |
| Тип `float` в `form_ctx.write(storage_value: float)` — `FieldSetHandler` ожидает `int` для int-полей | Низкая | Проверить `FieldSetHandler.apply` — если нужен int-cast, добавить `int(storage_value)` перед передачей в form_ctx.write |
| `SpinBoxConfig` не экспортируется из `spinbox/__init__.py` | Низкая | Проверить `__init__.py` пакета перед шагом импорта в factory |
