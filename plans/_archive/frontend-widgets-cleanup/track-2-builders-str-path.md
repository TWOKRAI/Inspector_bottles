# Plan: Track 2.5-2.8 — Factory builders str/text/path + unsupported (thin binding wrapper)

- **Slug:** frontend-widgets-track-2-str-path
- **Дата:** 2026-05-16
- **Статус:** DONE (2026-05-18, реализация в `f5634ec`: thin binding wrappers `_build_str_short`/`_build_str_long`/`_build_path` через `form_ctx.write`, `test_str_short_form_ctx.py` + `test_str_long_form_ctx.py` + `test_path_form_ctx.py`)
- **Ветка:** refactor/frontend-widgets-cleanup
- **Родительский план:** [`rollout-finish.md`](rollout-finish.md), секция «Track 2» (строки 163-175)
- **Верхнеуровневая карта:** [`plan.md`](plan.md)

---

## Зачем

Tracks 2.1-2.4 подключили str/text/path к FW-компонентам (SpinBox, Numeric, Compound, Combo). Tracks 2.5-2.7 — последние три builder'а без FW-компонентов: `_build_str_short`, `_build_str_long`, `_build_path`. Согласно rollout-finish.md (строки 248-258, секция «Что НЕ делаем»), **FW-компоненты для str/text/path — отдельная задача, вне scope текущей фазы**. Здесь делается минимум: **thin binding wrapper** прямо в factory.py — подписка сигнала Qt-виджета на `FormContext.write` через lambda без создания presenter или facade. Track 2.8 (`_build_unsupported`) — только добавление kwarg `form_ctx=None` для единообразия сигнатуры; реального binding нет (readonly QLabel).

Все четыре задачи объединяются в **один коммит** — это thin glue уровня 10-15 строк на builder.

---

## Ключевые факты из анализа кода

| Что | Факт |
|-----|------|
| `_build_str_short` (factory.py строки 727-746) | QLineEdit, `change_signal=le.textChanged`; placeholder из `meta.info`; нет form_ctx kwarg |
| `_build_str_long` (строки 749-764) | QPlainTextEdit с `setReadOnly(True)`, `setFixedHeight(60)`, `change_signal=te.textChanged`; нет form_ctx kwarg |
| `_build_path` (строки 767-780) | QLineEdit идентично str_short; полный picker отложен на Phase 10B; нет form_ctx kwarg |
| `_build_unsupported` (строки 783-797) | disabled QLabel, `change_signal=None`; нет form_ctx kwarg |
| `FormContext.write` сигнатура | `(register_name: str, field_name: str, new_value: Any, old_value: Any) -> bool` |
| `register_name` и `field_name` | берутся из `field_info.plugin_name` и `field_info.field_name` аналогично `_build_bool_binding_aware` |
| Binding-aware bool образец | `_build_bool_binding_aware` (строки 219-265): BindingConfig + CheckboxControl → change_signal=None |
| Диспетч в CardsFieldFactory.create | строки 858-874: явные `if kind == _KIND_X and builder is _build_X` проверки. str/path аналогично добавляются |
| Сигнал str_short / path | `le.editingFinished` (Signal без аргументов, срабатывает при Enter/LostFocus) — предпочтительнее `textChanged` (слишком частит) |
| Сигнал str_long | `QPlainTextEdit.textChanged` (Signal без аргументов, нет `editingFinished` у QPlainTextEdit) |
| old_value tracking | берётся из `le.text()` / `te.toPlainText()` непосредственно **до** write; реализуется через lambda с nonlocal `_last` или capture `le` в closure |

### Почему thin wrapper, а не FW-компонент

FW-компоненты (CheckboxControl, SpinBoxControl и т.д.) реализуют presenter с `_write`, `SyncTrait`, `DebounceTrait`, `AccessTrait` и тестовой базой. Создавать StringControl с таким же уровнем инфраструктуры — нецелесообразно до того, как будет понятна финальная UX (однострочный input vs contenteditable, валидация regex, placeholder, markdown-preview и т.д.). Поэтому на этой фазе binding встраивается в factory напрямую: 5-6 строк lambda, никаких новых модулей.

### Решение по undo round-trip в тестах

**Undo round-trip НЕ тестируется** для str/path builders. Причина: undo-путь требует `_FakeActionBus.undo()` → RM notify → подписчик вызывает `setter` на виджете. В thin wrapper нет subscriber-регистрации на RM (в отличие от presenter, который подписывается через `SyncTrait.attach`). Без этой подписки undo может попасть в RM, но виджет не обновится — это известное ограничение thin wrapper, которое будет устранено при создании StringControl в будущей задаче. Тестировать это сейчас означало бы тестировать ожидаемое **отсутствие** поведения, что создаёт ложные ожидания. Достаточно трёх тестов: write через form_ctx, legacy-путь, корректное эмитирование.

---

## Порядок выполнения

Все четыре задачи в одном PR / одном коммите. Логический порядок:

### Phase 1: Thin wrappers (задачи 2.5, 2.6, 2.7)

- Task 2.5: `_build_str_short_binding_aware` + kwarg в `_build_str_short` + dispatch [PENDING]
- Task 2.6: `_build_str_long_binding_aware` + kwarg в `_build_str_long` + dispatch [PENDING]
- Task 2.7: `_build_path_binding_aware` + kwarg в `_build_path` + dispatch [PENDING]

### Phase 2: Unsupported сигнатура (задача 2.8)

- Task 2.8: kwarg `form_ctx=None` в `_build_unsupported` + dispatch-stub [PENDING]

### Phase 3: Тесты (входят в тот же коммит)

- Task 2.5T: 3 теста в `test_str_short_form_ctx.py` [PENDING]
- Task 2.6T: 3 теста в `test_str_long_form_ctx.py` [PENDING]
- Task 2.7T: 3 теста в `test_path_form_ctx.py` [PENDING]

---

## Task 2.5 — _build_str_short_binding_aware + dispatch

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** добавить thin binding wrapper для QLineEdit (str_short) с подпиской `editingFinished` на `FormContext.write`

**Context:** `_build_str_short` (factory.py строки 727-746) создаёт QLineEdit с `change_signal=le.textChanged`. В binding-aware режиме нужно: (a) подписать `le.editingFinished` на `form_ctx.write` через lambda — не `textChanged`, чтобы write не срабатывал на каждую нажатую клавишу; (b) вернуть `FieldEditor` с `change_signal=None` — чтобы `RegisterView._on_editor_changed` не делал двойной write (как в `_build_bool_binding_aware` строка 264). Никакой FW-компонент, BindingConfig, presenter — не нужны. Только QLineEdit + lambda.

**Файлы:**
- `multiprocess_prototype/frontend/forms/factory.py` — изменить

**Steps:**

1. Прочитать актуальное состояние factory.py строки 727-746 (`_build_str_short`) и 855-874 (`CardsFieldFactory.create` dispatch) перед правками.

2. Добавить функцию `_build_str_short_binding_aware` сразу после `_build_str_short` (перед `_build_str_long`):
   ```python
   def _build_str_short_binding_aware(
       field_info: FieldInfo,
       form_ctx: FormContext,
       parent: QWidget | None = None,
   ) -> FieldEditor:
       """QLineEdit для короткой строки с прямой подпиской на FormContext.write.

       NOTE: thin wrapper — нет FW-компонента, нет presenter, нет undo-subscribe.
       Undo попадает в RM, но виджет не обновляется автоматически (ограничение
       текущей фазы; устраняется при создании StringControl в будущей задаче).
       """
       le = QLineEdit(parent)
       default = _safe_default(field_info, "")
       le.setText(str(default))

       meta = field_info.meta
       if meta and meta.info:
           le.setPlaceholderText(meta.info)

       register_name = field_info.plugin_name or ""
       field_name = field_info.field_name or ""

       def _on_editing_finished() -> None:
           new_value = le.text()
           # old_value берём из RM через RegistersManager если доступен,
           # иначе передаём пустую строку (ActionBus coalescing по new_value достаточен).
           old_value = ""
           try:
               reg = form_ctx.registers_manager.get_register(register_name)
               if reg is not None:
                   raw = getattr(reg, field_name, None)
                   old_value = str(raw) if raw is not None else ""
           except Exception:
               pass
           form_ctx.write(register_name, field_name, new_value, old_value)

       le.editingFinished.connect(_on_editing_finished)

       label = _make_label(field_info)
       # change_signal=None: binding-aware путь пишет через _on_editing_finished →
       # form_ctx.write; RegisterView НЕ должен дублировать write.
       return FieldEditor(
           field_info=field_info,
           widget=le,
           getter=le.text,
           setter=lambda v: le.setText(str(v)),
           change_signal=None,  # type: ignore[arg-type]
           label=label,
       )
   ```

3. Изменить сигнатуру `_build_str_short`:
   ```python
   def _build_str_short(
       field_info: FieldInfo,
       parent: QWidget | None = None,
       form_ctx: FormContext | None = None,
   ) -> FieldEditor:
       """QLineEdit для короткой строки (binding-aware если form_ctx передан)."""
       if form_ctx is not None:
           return _build_str_short_binding_aware(field_info, form_ctx, parent)
       # Legacy путь — QLineEdit без binding-aware моста.
       ...  # остальной текущий код без изменений
   ```

4. В `CardsFieldFactory.create` добавить dispatch для str_short аналогично существующим (после строки `if kind == _KIND_LITERAL and builder is _build_literal:`):
   ```python
   if kind == _KIND_STR_SHORT and builder is _build_str_short:
       return _build_str_short(field_info, parent, form_ctx)
   if kind == _KIND_STR_LONG and builder is _build_str_long:
       return _build_str_long(field_info, parent, form_ctx)
   if kind == _KIND_PATH and builder is _build_path:
       return _build_path(field_info, parent, form_ctx)
   ```
   (три dispatcha добавляются сразу — строки для str_short, str_long, path вместе)

5. Проверить что `_KIND_STR_SHORT`, `_KIND_STR_LONG`, `_KIND_PATH` константы уже определены в начале файла (они там есть — это строки с `_KIND_*`). Не добавлять новые.

**Acceptance criteria:**
- [ ] `_build_str_short_binding_aware` существует в factory.py
- [ ] `_build_str_short(field_info, form_ctx=None)` — legacy путь работает без form_ctx (QLineEdit с textChanged)
- [ ] `_build_str_short(field_info, form_ctx=ctx)` — вызывает `_build_str_short_binding_aware`, change_signal=None
- [ ] `le.editingFinished` подключён в binding-aware пути; `le.textChanged` — НЕ подключён напрямую к form_ctx.write
- [ ] `ruff check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок

**Out of scope:** не создавать StringControl FW-компонент. Не добавлять undo-subscriber. Не мигрировать callers (Track 3). Не трогать str_long, path, unsupported — они в отдельных tasks этого же коммита.

**Edge cases:**
- `field_info.plugin_name` или `field_info.field_name` могут быть `None` — защита через `or ""` уже в шаге 2.
- `form_ctx.registers_manager.get_register(register_name)` может вернуть `None` или бросить если регистр не зарегистрирован — защита через `try/except Exception: pass` и fallback `old_value = ""`.
- `le.editingFinished` срабатывает при Enter и при потере фокуса. Если пользователь нажал Escape — значение откатилось к предыдущему, `editingFinished` не срабатывает. Это корректное поведение.

**Dependencies:** нет (не требует FW-компонента)

---

## Task 2.6 — _build_str_long_binding_aware + dispatch

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** добавить thin binding wrapper для QPlainTextEdit (str_long) с подпиской `textChanged` на `FormContext.write`

**Context:** `_build_str_long` (factory.py строки 749-764) создаёт `QPlainTextEdit` с `setReadOnly(True)` и `setFixedHeight(60)`. Ключевое отличие от str_short: у `QPlainTextEdit` **нет сигнала `editingFinished`**. Единственный доступный сигнал для отслеживания изменений — `textChanged` (Signal без аргументов, значение берётся через `te.toPlainText()`). Это означает: write срабатывает на каждый символ. Это принято как допустимое ограничение thin wrapper для текстовых полей (coalescing в ActionBus смягчает нагрузку). Если str_long используется только для readonly — binding-aware режим имеет смысл только когда `setReadOnly(False)`. Однако оставить возможность: если caller передал `form_ctx`, значит поле редактируемое в его контексте.

**Файлы:**
- `multiprocess_prototype/frontend/forms/factory.py` — изменить

**Steps:**

1. Добавить функцию `_build_str_long_binding_aware` сразу после `_build_str_long` (перед `_build_path`):
   ```python
   def _build_str_long_binding_aware(
       field_info: FieldInfo,
       form_ctx: FormContext,
       parent: QWidget | None = None,
   ) -> FieldEditor:
       """QPlainTextEdit с прямой подпиской textChanged на FormContext.write.

       NOTE: thin wrapper — нет editingFinished у QPlainTextEdit, write на каждый символ.
       ActionBus coalescing смягчает нагрузку. setReadOnly(False) в этом режиме —
       ответственность caller'а.
       NOTE: undo-subscribe отсутствует (ограничение thin wrapper, устраняется в StringControl).
       """
       te = QPlainTextEdit(parent)
       default = _safe_default(field_info, "")
       te.setPlainText(str(default))
       te.setFixedHeight(60)
       # В binding-aware режиме не ставим setReadOnly(True) — caller ожидает редактирование.

       register_name = field_info.plugin_name or ""
       field_name = field_info.field_name or ""

       def _on_text_changed() -> None:
           new_value = te.toPlainText()
           old_value = ""
           try:
               reg = form_ctx.registers_manager.get_register(register_name)
               if reg is not None:
                   raw = getattr(reg, field_name, None)
                   old_value = str(raw) if raw is not None else ""
           except Exception:
               pass
           form_ctx.write(register_name, field_name, new_value, old_value)

       te.textChanged.connect(_on_text_changed)

       label = _make_label(field_info)
       return FieldEditor(
           field_info=field_info,
           widget=te,
           getter=te.toPlainText,
           setter=lambda v: te.setPlainText(str(v)),
           change_signal=None,  # type: ignore[arg-type]
           label=label,
       )
   ```

2. Изменить сигнатуру `_build_str_long` аналогично 2.5:
   ```python
   def _build_str_long(
       field_info: FieldInfo,
       parent: QWidget | None = None,
       form_ctx: FormContext | None = None,
   ) -> FieldEditor:
       """QPlainTextEdit для длинной строки (binding-aware если form_ctx передан)."""
       if form_ctx is not None:
           return _build_str_long_binding_aware(field_info, form_ctx, parent)
       # Legacy путь — QPlainTextEdit readonly без binding-aware моста.
       te = QPlainTextEdit(parent)
       ...  # остальной текущий код без изменений
   ```

3. Dispatch в `CardsFieldFactory.create` добавлен в Task 2.5 (шаг 4) — не дублировать.

**Acceptance criteria:**
- [ ] `_build_str_long_binding_aware` существует в factory.py
- [ ] Legacy путь: `_build_str_long(field_info)` → QPlainTextEdit с `setReadOnly(True)`, `change_signal=te.textChanged`
- [ ] Binding-aware путь: `_build_str_long(field_info, form_ctx=ctx)` → QPlainTextEdit без setReadOnly(True), `change_signal=None`
- [ ] `te.textChanged` подключён в binding-aware пути к `_on_text_changed`
- [ ] `ruff check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок

**Out of scope:** не добавлять `editingFinished` (его нет у QPlainTextEdit). Не менять высоту виджета (60px остаётся). Dispatch str_long добавлен в Task 2.5 шаг 4.

**Edge cases:**
- `te.textChanged` срабатывает при каждом изменении, включая программный `te.setPlainText(v)` в setter. Если setter вызывается извне (RegisterView загружает значения) — это создаст write-loop. Защита: в `_on_text_changed` проверять не совпадает ли `new_value` с текущим значением RM. Альтернативно: использовать `blockSignals(True)` в setter перед `setPlainText` и `blockSignals(False)` после. **Реализовать второй вариант** (blockSignals) — это надёжнее и не требует обращения к RM. Обновить setter в FieldEditor: `lambda v: (te.blockSignals(True), te.setPlainText(str(v)), te.blockSignals(False))`.

**Dependencies:** нет. Dispatch добавлен в Task 2.5.

---

## Task 2.7 — _build_path_binding_aware + dispatch

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** добавить thin binding wrapper для QLineEdit (path) с подпиской `editingFinished` на `FormContext.write`

**Context:** `_build_path` (factory.py строки 767-780) идентичен `_build_str_short` по структуре: QLineEdit, placeholder нет, default конвертируется через `.as_posix()` если это `Path`. Разница: тип данных — строковое представление пути. Binding-aware подход — точно такой же как `_build_str_short_binding_aware`: `editingFinished` → `form_ctx.write`. Полный file-picker диалог отложен на Phase 10B и **не добавляется здесь**.

**Файлы:**
- `multiprocess_prototype/frontend/forms/factory.py` — изменить

**Steps:**

1. Добавить функцию `_build_path_binding_aware` сразу после `_build_path` (перед `_build_unsupported`):
   ```python
   def _build_path_binding_aware(
       field_info: FieldInfo,
       form_ctx: FormContext,
       parent: QWidget | None = None,
   ) -> FieldEditor:
       """QLineEdit для Path с прямой подпиской editingFinished на FormContext.write.

       NOTE: thin wrapper — полный picker (QFileDialog) отложен на Phase 10B.
       NOTE: write возвращает str; преобразование в Path — ответственность handler'а в RM.
       NOTE: undo-subscribe отсутствует (ограничение thin wrapper).
       """
       le = QLineEdit(parent)
       default = _safe_default(field_info, "")
       le.setText(default.as_posix() if isinstance(default, Path) else str(default))

       register_name = field_info.plugin_name or ""
       field_name = field_info.field_name or ""

       def _on_editing_finished() -> None:
           new_value = le.text()
           old_value = ""
           try:
               reg = form_ctx.registers_manager.get_register(register_name)
               if reg is not None:
                   raw = getattr(reg, field_name, None)
                   old_value = str(raw) if raw is not None else ""
           except Exception:
               pass
           form_ctx.write(register_name, field_name, new_value, old_value)

       le.editingFinished.connect(_on_editing_finished)

       label = _make_label(field_info)
       return FieldEditor(
           field_info=field_info,
           widget=le,
           getter=lambda: le.text(),
           setter=lambda v: le.setText(str(v)),
           change_signal=None,  # type: ignore[arg-type]
           label=label,
       )
   ```

2. Изменить сигнатуру `_build_path`:
   ```python
   def _build_path(
       field_info: FieldInfo,
       parent: QWidget | None = None,
       form_ctx: FormContext | None = None,
   ) -> FieldEditor:
       """QLineEdit для Path (binding-aware если form_ctx передан; picker — Phase 10B)."""
       if form_ctx is not None:
           return _build_path_binding_aware(field_info, form_ctx, parent)
       # Legacy путь — QLineEdit без binding-aware моста.
       ...  # остальной текущий код без изменений
   ```

3. Dispatch в `CardsFieldFactory.create` добавлен в Task 2.5 (шаг 4) — не дублировать.

**Acceptance criteria:**
- [ ] `_build_path_binding_aware` существует в factory.py
- [ ] Legacy путь: `_build_path(field_info)` → QLineEdit с `change_signal=le.textChanged` (без изменений)
- [ ] Binding-aware путь: `_build_path(field_info, form_ctx=ctx)` → QLineEdit, `change_signal=None`, `editingFinished` подключён
- [ ] `ruff check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок

**Out of scope:** не добавлять QFileDialog. Не валидировать path-строку. Dispatch добавлен в Task 2.5.

**Edge cases:**
- `default` может быть `pathlib.Path` — конвертация `.as_posix()` уже в legacy-пути, копируем без изменений.
- RM-handler получит `str` (не `Path`) — это задокументировано в NOTE. Если handler ожидает `Path`, пусть сам делает `Path(value)`. Не добавлять конвертацию здесь.

**Dependencies:** нет. Dispatch добавлен в Task 2.5.

---

## Task 2.8 — _build_unsupported: kwarg form_ctx=None для единообразия

**Level:** Junior (Haiku, normal)
**Assignee:** developer
**Goal:** добавить kwarg `form_ctx: FormContext | None = None` в `_build_unsupported` и stub-dispatch в `CardsFieldFactory.create` — без реального binding

**Context:** `_build_unsupported` (factory.py строки 783-797) возвращает disabled QLabel для неподдерживаемых типов. Никакого write-пути нет и быть не должно — это readonly. Цель задачи: единообразие сигнатур всех builder'ов, чтобы `CardsFieldFactory.create` мог вызывать `builder(field_info, parent, form_ctx)` без проверки per-builder. Реальный binding не добавляется.

**Файлы:**
- `multiprocess_prototype/frontend/forms/factory.py` — изменить

**Steps:**

1. Изменить сигнатуру `_build_unsupported`:
   ```python
   def _build_unsupported(
       field_info: FieldInfo,
       parent: QWidget | None = None,
       form_ctx: FormContext | None = None,  # noqa: ARG001 — зарезервирован для единообразия
   ) -> FieldEditor:
       """Disabled QLabel для неподдерживаемых типов. form_ctx игнорируется (readonly)."""
       ...  # тело без изменений
   ```

2. В `CardsFieldFactory.create` добавить dispatch для unsupported — **опционально**: только если принято решение унифицировать финальный fallback. Если `return builder(field_info, parent)` в конце достаточно — не добавлять отдельный `if kind == _KIND_UNSUPPORTED`. Предпочтительнее: оставить `return builder(field_info, parent)` как fallback, а для unsupported изменить финальный вызов на `builder(field_info, parent)` — это уже покрывает `_build_unsupported` с новым kwarg-дефолтом.

   **Конкретно:** финальная строка `return builder(field_info, parent)` заменяется на:
   ```python
   # Fallback: builders без binding-aware пути (unsupported и переопределённые через register_type)
   return builder(field_info, parent)
   ```
   Это не меняет поведение — `_build_unsupported` принимает `form_ctx=None` по умолчанию.

3. Обновить docstring `_build_unsupported` — добавить примечание что `form_ctx` зарезервирован, но не используется.

**Acceptance criteria:**
- [ ] `_build_unsupported` принимает `form_ctx: FormContext | None = None` без ошибок импорта
- [ ] `_build_unsupported(field_info)` — legacy вызов без изменений работает
- [ ] `_build_unsupported(field_info, form_ctx=some_ctx)` — возвращает то же (disabled QLabel), form_ctx игнорируется
- [ ] `ruff check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок

**Out of scope:** не создавать FW-компонент для unsupported. Не добавлять write-path. Не добавлять visible indicator что тип не поддерживается (это UX-задача).

**Edge cases:** `# noqa: ARG001` может потребоваться если ruff включил `flake8-unused-arguments`. Проверить конфигурацию ruff в `pyproject.toml` — если ARG001 не включён, noqa не нужен.

**Dependencies:** нет

---

## Task 2.5T — Тесты для _build_str_short_binding_aware

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** написать 3 теста проверяющих write через form_ctx, legacy-путь и корректность эмитирования для _build_str_short

**Context:** паттерн тестов — аналог `test_spinbox_form_ctx.py` (Track 1.1). Для QLineEdit нет QApplication в unit-тестах, если не attach виджет к экрану. Использовать `qapp` fixture из pytest-qt. Триггер write — `le.editingFinished.emit()` (не setText, не реальный ввод). `_FakeActionBus` и `_FakeActionBuilder` — копировать из существующих тестовых файлов (аналог из `test_form_context_write.py` или `test_checkbox_v2.py`). Undo round-trip не тестируется (см. раздел «Решение по undo round-trip»).

**Файлы:**
- `multiprocess_prototype/frontend/forms/tests/test_str_short_form_ctx.py` — создать новый файл (или в `multiprocess_framework/modules/frontend_module/tests/` если factory-тесты там)

> **NOTE разработчику:** перед созданием файла прочитать где находятся существующие factory-тесты (`multiprocess_prototype/frontend/forms/tests/` или `multiprocess_framework/...`). Тесты factory.py помещать туда же.

**Steps:**

1. Найти директорию с тестами factory.py: `Select-String -Path "multiprocess_prototype/frontend/forms/tests/" -Pattern "_build_str"` или проверить наличие директории `multiprocess_prototype/frontend/forms/tests/`.

2. Скопировать `_FakeRegistersManager`, `_FakeActionBuilder`, `_FakeActionBus` из ближайшего существующего теста factory или form_context.

3. Написать тест `test_str_short_write_via_form_ctx` (требует `qapp`):
   - Создать `field_info` с `plugin_name="test_reg"`, `field_name="label"`, `default="hello"`
   - Создать `FormContext(rm, bus, _FakeActionBuilder())`
   - Вызвать `_build_str_short(field_info, form_ctx=ctx)` → получить `editor`
   - Вызвать `editor.widget.editingFinished.emit()`
   - Assert: `bus.last_action is not None` (action попал в ActionBus)
   - Assert: `editor.change_signal is None` (binding-aware путь не дублирует write)

4. Написать тест `test_str_short_legacy_path_no_form_ctx` (требует `qapp`):
   - `_build_str_short(field_info)` (без form_ctx)
   - Assert: `editor.change_signal is not None` (legacy путь — textChanged подключён)
   - Assert: `editor.widget` — это QLineEdit

5. Написать тест `test_str_short_emits_correct_value` (требует `qapp`):
   - `_build_str_short(field_info, form_ctx=ctx)`
   - `editor.widget.setText("new_value")`
   - `editor.widget.editingFinished.emit()`
   - Assert: `bus.last_action.new_value == "new_value"` (проверить что в action записан правильный текст)

**Acceptance criteria:**
- [ ] `pytest multiprocess_prototype/frontend/forms/tests/test_str_short_form_ctx.py -v` — 3 теста PASSED
- [ ] `ruff check ...test_str_short_form_ctx.py` — 0 ошибок
- [ ] Регрессия factory-тестов PASSED

**Out of scope:** не тестировать undo round-trip. Не тестировать placeholder. Не тестировать access-level (FW-компонента нет).

**Edge cases:** `QLineEdit.editingFinished` — Signal без аргументов. `.emit()` вызывается без параметров. Если `bus.last_action` — это `_FieldSetAction` объект, доступ к `new_value` зависит от реализации `_FakeActionBuilder.field_set_timed`. Проверить структуру action в `_FakeActionBuilder` перед написанием assert.

**Dependencies:** Task 2.5

---

## Task 2.6T — Тесты для _build_str_long_binding_aware

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** написать 3 теста для _build_str_long аналогично 2.5T

**Context:** Триггер write — `te.textChanged.emit()` (или `te.setPlainText("new")` — это тоже испускает `textChanged`). Важный нюанс: setter использует `blockSignals(True/False)` — проверить что это не мешает тесту. В тесте при вызове `te.setPlainText` через setter — write не должен срабатывать. При вызове `te.setPlainText` напрямую — срабатывает. Legacy путь: QPlainTextEdit с `setReadOnly(True)`.

**Файлы:**
- `multiprocess_prototype/frontend/forms/tests/test_str_long_form_ctx.py` — создать

**Steps:**

1. Тест `test_str_long_write_via_form_ctx` (требует `qapp`):
   - Создать editor через `_build_str_long(field_info, form_ctx=ctx)`
   - Напрямую вызвать `editor.widget.setPlainText("new text")` (минуя setter — без blockSignals)
   - Assert: `bus.last_action is not None`
   - Assert: `editor.change_signal is None`

2. Тест `test_str_long_setter_no_write` (требует `qapp`):
   - Через `editor.setter("via setter")` — write НЕ должен вызываться (blockSignals)
   - Assert: `bus.last_action is None` или action_count не изменился

3. Тест `test_str_long_legacy_path_no_form_ctx` (требует `qapp`):
   - `_build_str_long(field_info)` без form_ctx
   - Assert: `editor.widget.isReadOnly() == True`
   - Assert: `editor.change_signal is not None` (legacy textChanged)

**Acceptance criteria:**
- [ ] `pytest ...test_str_long_form_ctx.py -v` — 3 теста PASSED
- [ ] `ruff check ...test_str_long_form_ctx.py` — 0 ошибок

**Out of scope:** не тестировать undo. Не тестировать многострочный ввод (достаточно простого текста).

**Edge cases:** `te.textChanged` срабатывает при `setPlainText` как из кода, так и из UI. Блокировка через `blockSignals` в setter должна предотвратить write-loop, но тест это верифицирует явно.

**Dependencies:** Task 2.6

---

## Task 2.7T — Тесты для _build_path_binding_aware

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** написать 3 теста для _build_path аналогично 2.5T (editingFinished, legacy, correct value)

**Context:** Паттерн идентичен Task 2.5T. Основное отличие: default может быть `pathlib.Path` — проверить что `le.text()` содержит строку (posix-путь).

**Файлы:**
- `multiprocess_prototype/frontend/forms/tests/test_path_form_ctx.py` — создать

**Steps:**

1. Тест `test_path_write_via_form_ctx` (требует `qapp`):
   - `field_info` с Path-default: `default=Path("/some/path")`
   - `_build_path(field_info, form_ctx=ctx)`
   - `editor.widget.editingFinished.emit()`
   - Assert: `bus.last_action is not None`

2. Тест `test_path_legacy_path_no_form_ctx` (требует `qapp`):
   - `_build_path(field_info)` без form_ctx
   - Assert: `editor.change_signal is not None`
   - Assert: `editor.widget.text()` содержит строку пути

3. Тест `test_path_emits_str_value` (требует `qapp`):
   - `editor.widget.setText("/new/path")`
   - `editor.widget.editingFinished.emit()`
   - Assert: action.new_value == "/new/path"

**Acceptance criteria:**
- [ ] `pytest ...test_path_form_ctx.py -v` — 3 теста PASSED
- [ ] `ruff check ...test_path_form_ctx.py` — 0 ошибок

**Out of scope:** не тестировать file picker. Не тестировать валидацию пути.

**Edge cases:** `Path.as_posix()` на Windows возвращает forward-slash путь. Тест должен работать кроссплатформенно — использовать `posixpath` или просто проверять `str` без зависимости от OS-слеша.

**Dependencies:** Task 2.7

---

## Acceptance вся Track 2.5-2.8

- [ ] `_build_str_short(field_info, form_ctx=ctx)` → FieldEditor с `change_signal=None`, `editingFinished` подключён
- [ ] `_build_str_short(field_info)` → FieldEditor с `change_signal=le.textChanged` (legacy без изменений)
- [ ] `_build_str_long(field_info, form_ctx=ctx)` → FieldEditor с `change_signal=None`, `textChanged` подключён, не readonly
- [ ] `_build_str_long(field_info)` → FieldEditor с `change_signal=te.textChanged`, `isReadOnly=True` (legacy без изменений)
- [ ] `_build_path(field_info, form_ctx=ctx)` → FieldEditor с `change_signal=None`, `editingFinished` подключён
- [ ] `_build_path(field_info)` → FieldEditor с `change_signal=le.textChanged` (legacy без изменений)
- [ ] `_build_unsupported(field_info, form_ctx=None)` — принимает kwarg, поведение не изменилось
- [ ] `CardsFieldFactory.create(field_info, parent, form_ctx=ctx)` — dispatch работает для всех 4 kinds
- [ ] `pytest multiprocess_prototype/frontend/forms/tests/test_str_short_form_ctx.py -v` — 3 PASSED
- [ ] `pytest multiprocess_prototype/frontend/forms/tests/test_str_long_form_ctx.py -v` — 3 PASSED
- [ ] `pytest multiprocess_prototype/frontend/forms/tests/test_path_form_ctx.py -v` — 3 PASSED
- [ ] `ruff check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок
- [ ] `ruff format --check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок
- [ ] `python scripts/validate.py` — зелёный
- [ ] `python scripts/run_framework_tests.py` — зелёный

---

## Шаблон commit message

```
feat(frontend): Track 2.5-2.8 — thin binding wrappers str/path builders

- _build_str_short_binding_aware: QLineEdit + editingFinished → form_ctx.write
- _build_str_long_binding_aware: QPlainTextEdit + textChanged → form_ctx.write; setter blockSignals
- _build_path_binding_aware: QLineEdit + editingFinished → form_ctx.write (picker Phase 10B)
- _build_unsupported: добавлен kwarg form_ctx=None для единообразия сигнатуры
- CardsFieldFactory.create: dispatch для _KIND_STR_SHORT, _KIND_STR_LONG, _KIND_PATH
- test_str_short_form_ctx.py: 3 теста (write, legacy, correct value)
- test_str_long_form_ctx.py: 3 теста (write, setter no-write, legacy)
- test_path_form_ctx.py: 3 теста (write, legacy, str value)

Why: закрытие Track 2 без FW-компонентов — thin lambda binding прямо в factory;
     str/text/path остаются сырым Qt (StringControl — отдельная задача вне scope)
Layer: prototype
Refs: plans/frontend-widgets-cleanup/track-2-builders-str-path.md, plans/frontend-widgets-cleanup/rollout-finish.md
Risk: low — только factory.py; legacy callers без form_ctx не затронуты
Reversible: yes
Tested: frontend/str_short/3 passed, frontend/str_long/3 passed, frontend/path/3 passed
```

---

## Verification команды

```powershell
# 1. Новые тесты str_short
pytest multiprocess_prototype/frontend/forms/tests/test_str_short_form_ctx.py -v

# 2. Новые тесты str_long
pytest multiprocess_prototype/frontend/forms/tests/test_str_long_form_ctx.py -v

# 3. Новые тесты path
pytest multiprocess_prototype/frontend/forms/tests/test_path_form_ctx.py -v

# 4. Регрессия factory тестов
pytest multiprocess_prototype/frontend/forms/tests/ -v

# 5. Ruff factory.py
ruff check multiprocess_prototype/frontend/forms/factory.py
ruff format --check multiprocess_prototype/frontend/forms/factory.py

# 6. Проверить наличие всех binding-aware функций в factory
Select-String -Pattern "_build_str_short_binding_aware|_build_str_long_binding_aware|_build_path_binding_aware" `
  multiprocess_prototype/frontend/forms/factory.py

# 7. Проверить dispatch в CardsFieldFactory.create
Select-String -Pattern "_KIND_STR_SHORT|_KIND_STR_LONG|_KIND_PATH" `
  multiprocess_prototype/frontend/forms/factory.py

# 8. Общая валидация
python scripts/validate.py
python scripts/run_framework_tests.py
```

---

## Риски и ограничения

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| `te.textChanged` + `te.setPlainText` в setter = write-loop | Высокая | `blockSignals(True/False)` в setter (шаг 2 Task 2.6) — тест 2.6T это верифицирует |
| `le.editingFinished` не срабатывает при программном `setText` | Низкая | Это ожидаемое поведение; setter не должен триггерить write |
| `form_ctx.registers_manager.get_register` может бросить на несуществующем регистре | Средняя | `try/except Exception: pass` с fallback `old_value=""` во всех трёх wrappers |
| `# noqa: ARG001` не нужен если ruff не включает ARG001 | Низкая | Проверить `pyproject.toml` перед добавлением noqa |
| Путь к тестам factory — неизвестен заранее | Средняя | Developer читает существующие тесты factory перед созданием новых файлов |
| old_value из RM может не совпасть с фактическим значением виджета если setter вызывался в обход RM | Низкая | Для thin wrapper это допустимо; FW-presenter решит это правильно через SyncTrait.read |
