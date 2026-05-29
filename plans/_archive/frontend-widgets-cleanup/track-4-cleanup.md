# Plan: Track 4 — Финальная волна cleanup

- **Slug:** frontend-widgets-track-4-cleanup
- **Дата:** 2026-05-16
- **Статус:** DONE (2026-05-16)
- **Ветка:** refactor/frontend-widgets-cleanup
- **Родительский план:** [`rollout-finish.md`](rollout-finish.md), секция «Track 4» (строки 271-329)
- **Верхнеуровневая карта:** [`plan.md`](plan.md)

---

## Зачем

Tracks 1+2+3 дали FW-компонентам поддержку `form_ctx`, перестроили factory-builder'ы и мигрировали всех callers. Track 4 — **финальная уборка**: удаление мёртвого backward-compat кода, который после этих изменений гарантированно не нужен в production-пути. Цель — прийти к состоянию «dual-mode в presenters отсутствует, re-export FieldInfo удалён, deprecated property process_name удалён».

**Gating:** Track 4 **запрещён** к началу, пока не выполнен чекпойнт (см. раздел ниже).

---

## Чекпойнт перед стартом Track 4

Перед первой задачей Director / TeamLead обязан выполнить следующую проверку вручную:

```powershell
# 1. Все 5 callers передают form_ctx — grep по сигнатурам RegisterView(
git grep "RegisterView(" -- multiprocess_prototype/

# 2. В factory нет form_ctx=None в binding-aware ветке
git grep "form_ctx=None" -- multiprocess_prototype/frontend/forms/factory.py

# 3. Все 8 builders в factory имеют binding-aware path (ищем form_ctx kwarg)
git grep "form_ctx" -- multiprocess_prototype/frontend/forms/factory.py

# 4. Тесты зелёные
pytest multiprocess_framework/modules/frontend_module/tests/ -q
pytest multiprocess_prototype/frontend/forms/tests/ -q
```

**Условия пропуска:** если хотя бы один из grep выдаёт неожиданный результат (caller без form_ctx в binding-aware пути, или factory с form_ctx=None в не-non-plugin ветке) — фиксить в Track 3 перед продолжением.

---

## Ключевые факты из анализа кода

### Dual-mode в presenters (4.1/4.2)

Три presenter'а содержат `if self._form_ctx is not None` guard:
- `checkbox/presenter.py:131` — в `_on_changed`
- `numeric/presenter.py:186` — в `_write`
- `combo/presenter.py:138` — в `_on_changed`

SpinBox, Slider и Compound **не имеют** собственного `_write` с dual-mode — они наследники `NumericPresenter` без override. Таким образом, единственные кандидаты на удаление — три файла выше.

**Критический вопрос о `_examples/`:** `_examples/checkbox/adapter.py`, `_examples/numeric/adapter.py` и `_examples/compound_numeric/adapter.py` вызывают `CheckboxControl.create(...)` и `NumericControl.create(...)` **без `form_ctx`** (параметр не передаётся). Это означает, что после удаления dual-mode в presenter'ах эти examples будут создавать контролы с `form_ctx=None`, что **сломает** их при попытке write (AttributeError или ошибка runtime). Однако `_examples/` — демо-адаптеры, не production-код. Решение: **оставить legacy путь через `SyncTrait.write` только в `_examples/`-specific entry-point**, либо пометить `_examples/` как «без write-поддержки» (read-only demo). Самый безопасный вариант — оставить legacy ветку в presenter'ах **с явным TODO**, но поднять assertion/warning если `form_ctx is None` в не-examples контексте. Ниже — конкретное решение в Task 4.1.

**`default_factories.py`:** `_create_slider` и `_create_checkbox` тоже вызывают `Control.create` без `form_ctx`. Это FW-внутренняя WidgetRegistry (не production-binding-path), используется в tab-template. Аналогично `_examples/` — не передаёт form_ctx → нужен тот же подход.

**Итоговое решение по dual-mode:** НЕ удалять ветку `else: self._sync.write(...)` полностью. Вместо этого:
1. Добавить `DeprecationWarning` (или логируемый WARNING) в legacy-ветку, чтобы в production сразу видно если форм-контекст не передан.
2. Задокументировать что legacy путь — только для `_examples/` и FW unit-тестов без Qt.
3. Оставить ветку `else` нетронутой структурно, но пометить явно: `# LEGACY: только для _examples/ и FW unit-тестов`.

Это называется «мягкое удаление dual-mode»: API не ломается, но все неожиданные обращения к legacy-пути становятся заметными.

### FieldInfo re-export (4.3)

`multiprocess_prototype/registers/field_info.py` — файл из 12 строк, re-export из FW.

**Callers в прототипе** (16 мест):
- Продакшн-код: `factory.py`, `form_builder.py`, `field_editor.py`, `register_view.py`, `yaml_io.py`, `settings/system/presenter.py`
- Тесты: `test_table_builder.py`, `test_str_short_form_ctx.py`, `test_str_long_form_ctx.py`, `test_register_view_signals.py`, `test_register_view.py`, `test_path_form_ctx.py`, `test_factory.py`, `test_form_builder.py` (2 вхождения), `test_inspector.py`

Итого: **6 продакшн-файлов + 10 тест-файлов = 16 файлов, 17 строк импорта**.

**Решение:** mass-rename **возможен** — все пути однотипны, замена механическая. Паттерн поиска: `from multiprocess_prototype.registers.field_info import` → `from multiprocess_framework.modules.registers_module.core.field_info import`. После замены файл `field_info.py` удаляется.

### ResolvedCommand.process_name property (4.4)

`command_catalog.py:51-56` — backward-compat property. Callers (production):
- `topology_bridge.py:270` — `resolved.process_name` в `send_action_command` вызове (одиночный target, не fan-out)
- `command_catalog.py:206` — `(pc.process_name,) if pc.process_name else ()` при построении process_names
- `command_catalog.py:248` — аналогично

**Тестовые callers** (оставить на потом — see below):
- `test_topology_bridge.py:34` — `MockResolvedCommand.process_name` (мок-класс, отдельный dataclass)
- `test_topology_bridge_v2.py:32` — `MockResolvedCommand.process_name` (другой мок, без `process_names` property!)
- `test_command_catalog.py` — множество `result.process_name == ...` assertions (backward-compat тесты)

**Для `topology_bridge.py:270`:** это **singleton send** (action-команда, один target), допустимо заменить на `resolved.process_names[0]` или итерацию.

**Для `command_catalog.py:206,248`:** здесь `pc` — это `PluginCommands` dataclass (строка 60), у которого тоже есть поле `process_name: str` — это **другой** `process_name`, не deprecated property в `ResolvedCommand`. Этот трогать не нужно.

**`test_topology_bridge_v2.py:MockResolvedCommand`:** не имеет `process_names` property (в отличие от `test_topology_bridge.py` где есть). После удаления `ResolvedCommand.process_name` bridge вызовет `resolved.process_names` — но mock не имеет этого атрибута. Это Task 4.6 из backlog.

### value_changed Signal (4.5)

Все 4 view-класса уже имеют `value_changed: Signal`:
- `checkbox/view.py:40` — `Signal(bool)` ✓
- `combo/view.py:29` — `Signal(str)` ✓
- `slider/view.py:33` — `Signal(float)` ✓
- `spinbox/view.py:25` — `Signal(float)` ✓

**Task 4.5 — только verification, никаких изменений кода.**

---

## Задачи

### Task 4.1 — Мягкое удаление dual-mode в FW presenters

**Уровень:** Middle (Sonnet, normal thinking)
**Исполнитель:** developer
**Цель:** пометить legacy-ветку в трёх presenter'ах deprecation-warning'ом, задокументировать что `form_ctx=None` допустим только в `_examples/` и FW unit-тестах.

**Контекст:** dual-mode нельзя полностью вырезать потому что `_examples/` и `default_factories.py` вызывают `XxxControl.create` без `form_ctx`. Вместо breaking change — logging.warning + явный комментарий. Это сигнализирует о проблеме в dev, не ломает prod.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/components/checkbox/presenter.py` — `_on_changed`, блок `else`
- `multiprocess_framework/modules/frontend_module/components/numeric/presenter.py` — `_write`, блок `else`
- `multiprocess_framework/modules/frontend_module/components/combo/presenter.py` — `_on_changed`, блок `else`

**Шаги:**
1. В каждом из трёх файлов найти блок `else: # Legacy путь...`.
2. Добавить в начало блока `else` вызов `import warnings; warnings.warn(...)` с текстом: `"[deprecated] form_ctx=None в {ClassName}._on_changed/write — legacy путь только для _examples/ и FW unit-тестов. Передай form_ctx в production-коде."` + `DeprecationWarning`.
3. Обновить комментарий с `# Legacy путь: прямая запись...` на `# LEGACY ONLY: _examples/ и FW unit-тесты. В production form_ctx обязателен.`
4. В `__init__` каждого presenter'а добавить в docstring строку: `form_ctx: обязателен в production. None допустим только в _examples/ и FW unit-тестах (без ActionBus).`

**Acceptance criteria:**
- [ ] Три файла изменены — в `else`-ветке есть `warnings.warn(..., DeprecationWarning)`
- [ ] Существующие тесты без `form_ctx` (например `test_checkbox_v2.py`, `test_controls_v2_hooks.py`) проходят — они ожидают warning, либо warning не ломает тест
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/ -v` — зелёный (возможны `PytestUnraisableExceptionWarning` — это ок, но тесты не падают)
- [ ] В `_examples/checkbox/adapter.py` и `_examples/numeric/adapter.py` предупреждение будет при write — это ожидаемо

**Out of scope:** полное удаление `else`-ветки, изменение `_examples/` адаптеров, изменение `default_factories.py`.

**Edge cases:** Если `warnings` уже импортирован в файле — использовать тот же import, не дублировать.

---

### Task 4.2 — Mass-rename FieldInfo re-export

**Уровень:** Middle (Sonnet, normal thinking)
**Исполнитель:** developer
**Цель:** удалить `multiprocess_prototype/registers/field_info.py` и заменить все 16 import-строк прямым путём к FW.

**Контекст:** файл `field_info.py` в прототипе — legacy shim из 12 строк. После переноса всех импортов на FW-канонический путь — удалить. Это уменьшит «prototype → framework» косвенную зависимость через посредника.

**Файлы:**
- `multiprocess_prototype/registers/field_info.py` — удалить
- `multiprocess_prototype/frontend/forms/factory.py` — правка импорта
- `multiprocess_prototype/frontend/forms/form_builder.py` — правка импорта
- `multiprocess_prototype/frontend/forms/field_editor.py` — правка импорта
- `multiprocess_prototype/frontend/forms/register_view.py` — правка импорта
- `multiprocess_prototype/frontend/widgets/tabs/settings/yaml_io.py` — правка импорта
- `multiprocess_prototype/frontend/widgets/tabs/settings/system/presenter.py` — правка импорта
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_inspector.py` — правка импорта
- `multiprocess_prototype/frontend/forms/tests/test_table_builder.py` — правка импорта
- `multiprocess_prototype/frontend/forms/tests/test_str_short_form_ctx.py` — правка импорта
- `multiprocess_prototype/frontend/forms/tests/test_str_long_form_ctx.py` — правка импорта
- `multiprocess_prototype/frontend/forms/tests/test_register_view_signals.py` — правка импорта
- `multiprocess_prototype/frontend/forms/tests/test_register_view.py` — правка импорта
- `multiprocess_prototype/frontend/forms/tests/test_path_form_ctx.py` — правка импорта
- `multiprocess_prototype/frontend/forms/tests/test_factory.py` — правка импорта
- `multiprocess_prototype/frontend/forms/tests/test_form_builder.py` — два вхождения

**Шаги:**
1. В каждом файле из списка заменить строку `from multiprocess_prototype.registers.field_info import FieldInfo` на `from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo`.
2. Там где импортируется `extract_fields` дополнительно — аналогично (`yaml_io.py`, `test_form_builder.py`).
3. Удалить файл `multiprocess_prototype/registers/field_info.py`.
4. Проверить: нет ли в `multiprocess_prototype/registers/__init__.py` re-export'а `FieldInfo` — если есть, удалить.

**Acceptance criteria:**
- [ ] `git grep "from multiprocess_prototype.registers.field_info"` — 0 результатов
- [ ] `multiprocess_prototype/registers/field_info.py` не существует
- [ ] `pytest multiprocess_prototype/frontend/forms/tests/ -v` — зелёный
- [ ] `pytest multiprocess_prototype/frontend/widgets/tabs/ -v -k "test_inspector or test_yaml"` — зелёный
- [ ] `python scripts/validate.py` — без новых ошибок

**Out of scope:** изменение API самого `FieldInfo` или `extract_fields`, трогать `registers/__init__.py` если там нет re-export'а.

**Edge cases:** `field_editor.py` и `form_builder.py` используют `TYPE_CHECKING` guard — проверить что замена импорта в обоих блоках корректна (в `if TYPE_CHECKING:` и вне него).

---

### Task 4.3 — Удаление ResolvedCommand.process_name + fix callers

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** удалить deprecated property `ResolvedCommand.process_name` и починить единственный production-caller в `topology_bridge.py:270`.

**Контекст:** property добавлен как backward-compat shim в прошлом рефакторинге (multi-target fan-out, commit d67ca70). После Track 3 все field-command вызовы идут через `resolved.process_names` цикл. Осталось только одно место с `process_name` в production — строка 270 `topology_bridge.py` (action-command). Тесты bridge тоже тестируют backward-compat — часть этих тестов придётся обновить.

**ВАЖНО:** не путать `ResolvedCommand.process_name` (property в `command_catalog.py:51`) с `PluginCommands.process_name` (поле dataclass `command_catalog.py:64`) и с `ProcessDiff.process_name` (поле `diff_engine.py:17`). Последние два — **не трогать**.

**Файлы:**
- `multiprocess_prototype/frontend/bridge/command_catalog.py` — удалить property `process_name` (строки 50-56)
- `multiprocess_prototype/frontend/bridge/topology_bridge.py:270` — заменить на `process_names[0]` или цикл
- `multiprocess_prototype/frontend/bridge/tests/test_topology_bridge.py` — обновить backward-compat тесты (строки 481-496)
- `multiprocess_prototype/frontend/bridge/tests/test_topology_bridge_v2.py` — обновить `MockResolvedCommand` (строки 30-34): добавить `process_names: tuple[str, ...]` property по аналогии с `test_topology_bridge.py` (Task 4.6 из backlog — включить сюда)
- `multiprocess_prototype/frontend/bridge/tests/test_command_catalog.py` — решить судьбу `result.process_name == ...` assertions

**Шаги:**
1. В `command_catalog.py` удалить property `process_name` (строки 50-56) и обновить docstring класса `ResolvedCommand`.
2. В `topology_bridge.py:270` заменить `resolved.process_name` на `resolved.process_names[0] if resolved.process_names else ""` (action-команда = один target; если пустой tuple — не отправлять).
3. В `test_topology_bridge.py` найти тесты `test_process_name_backward_compat` и `test_process_name_empty` (строки 480-496) — удалить или преобразовать в тест что атрибута `process_name` больше нет (`assert not hasattr(cmd, "process_name")`).
4. В `test_topology_bridge_v2.py` обновить `MockResolvedCommand` (строка 30-35): заменить поле `process_name: str` на `process_names: tuple[str, ...]`; добавить helper-метод `process_name_first` или просто использовать `process_names[0]` в тестах где это нужно. Проверить все тестовые ассерты в этом файле на `process_name`.
5. В `test_command_catalog.py` решить: строки с `result.process_name == "..."` — либо удалить backward-compat тесты, либо добавить проверку `result.process_names[0] == "..."` как замену. Тесты на строках 219, 228, 256, 350, 352, 417, 438, 448, 467 требуют внимания.

**Acceptance criteria:**
- [ ] `git grep "ResolvedCommand.*process_name\|resolved\.process_name"` в `command_catalog.py` — 0 результатов для property definition
- [ ] `git grep "resolved\.process_name"` во всём репо — 0 результатов
- [ ] `pytest multiprocess_prototype/frontend/bridge/tests/ -v` — зелёный
- [ ] `python scripts/validate.py` — без новых ошибок

**Out of scope:** трогать `PluginCommands.process_name`, `ProcessDiff.process_name`, или любые другие `process_name` поля не в `ResolvedCommand`.

**Edge cases:** строка `topology_bridge.py:270` — action-команда. Если `resolved.process_names` пуст (что теоретически возможно при некорректном каталоге), команду нужно не отправлять, а вернуть `False` с логом.

**Dependencies:** Task 4.3 должна идти после (или совместно с) проверкой чекпойнта.

---

### Task 4.4 — Verification value_changed Signal + итоговая проверка

**Уровень:** Junior (Haiku, normal)
**Исполнитель:** docs-writer
**Цель:** подтвердить что все 4 view-класса имеют `value_changed: Signal`, обновить чеклисты в плане, составить финальный acceptance-отчёт.

**Контекст:** по анализу кода все 4 signal уже существуют. Это верификационная задача, не имплементационная. Параллельно — финальный smoke-тест всей фазы.

**Файлы (только чтение + отчёт):**
- `multiprocess_framework/modules/frontend_module/components/checkbox/view.py` — проверить `value_changed = Signal(bool)`
- `multiprocess_framework/modules/frontend_module/components/combo/view.py` — `Signal(str)`
- `multiprocess_framework/modules/frontend_module/components/slider/view.py` — `Signal(float)`
- `multiprocess_framework/modules/frontend_module/components/spinbox/view.py` — `Signal(float)`
- `plans/frontend-widgets-cleanup/track-4-cleanup.md` — проставить `[x]` в чеклисте Acceptance

**Шаги:**
1. Для каждого из 4 view-файлов grep `value_changed` — зафиксировать тип сигнала.
2. Запустить финальные тесты: `pytest multiprocess_framework/modules/frontend_module/tests/ -q` и `pytest multiprocess_prototype/frontend/ -q` — зафиксировать результат.
3. Обновить чеклисты `[x]` в `rollout-finish.md` для пунктов, закрытых Track 4.
4. Занести в `track-4-cleanup.md` финальный статус (DONE) и результаты верификации.

**Acceptance criteria:**
- [ ] Все 4 `value_changed: Signal(...)` подтверждены grep'ом
- [ ] Финальные тесты зелёные (задокументировано количество passed/failed)
- [ ] Чеклисты в `rollout-finish.md` обновлены
- [ ] Статус плана обновлён в `track-4-cleanup.md`

**Out of scope:** любые правки кода view-файлов.

---

## Порядок выполнения

```
Чекпойнт (Director/TeamLead) — git grep проверки
           ↓
Task 4.1 (dual-mode deprecation warning) — можно параллельно с 4.2
Task 4.2 (FieldInfo mass-rename)         ┘
           ↓
Task 4.3 (process_name deletion + tests)
           ↓
Task 4.4 (verification + план обновить)
```

Task 4.1 и 4.2 независимы — их можно выполнять параллельно или последовательно. Task 4.3 зависит от стабильного состояния тестов (лучше после 4.1 чтобы убедиться что warning'и не ломают тесты). Task 4.4 — только после 4.1+4.2+4.3.

---

## Коммит-стратегия (2-3 коммита)

**Коммит 1 — после Tasks 4.1 + 4.2:**
```
refactor(frontend): dual-mode deprecated + FieldInfo re-export removed

- Checkbox/Numeric/ComboPresenter: DeprecationWarning в legacy else-ветке
- multiprocess_prototype/registers/field_info.py удалён
- 16 файлов (6 prod + 10 tests) переведены на FW canonical import

Why: после миграции всех callers (Track 3) form_ctx=None — легаси,
     только для _examples/. Re-export был временным shim, теперь не нужен.
Layer: mixed
Refs: plans/frontend-widgets-cleanup/track-4-cleanup.md
```

**Коммит 2 — после Task 4.3:**
```
refactor(bridge): ResolvedCommand.process_name deprecated property removed

- command_catalog.py: property process_name удалён из ResolvedCommand
- topology_bridge.py:270: send_action_command → process_names[0] with guard
- test_topology_bridge.py: backward-compat тесты обновлены/удалены
- test_topology_bridge_v2.py: MockResolvedCommand → process_names tuple
- test_command_catalog.py: process_name assertions → process_names[0]

Why: шим добавлен при введении multi-target fan-out, все callers
     мигрированы, держать deprecated API нет смысла.
Layer: prototype
Refs: plans/frontend-widgets-cleanup/track-4-cleanup.md
```

**Коммит 3 — после Task 4.4 (опциональный, только если есть реальные правки в чеклистах):**
```
docs(plans): Track 4 DONE — финальная верификация widgets cleanup

- rollout-finish.md: чеклисты Track 4 закрыты
- track-4-cleanup.md: статус → DONE, результаты тестов

Why: фиксирует завершение рефакторинга для трассируемости.
Layer: docs
Refs: plans/frontend-widgets-cleanup/track-4-cleanup.md
```

---

## Risks & Митигация

### R1 — `_examples/` и `default_factories.py` сломаются при записи (HIGH → LOW после Task 4.1)

`_examples/checkbox/adapter.py`, `_examples/numeric/adapter.py`, `default_factories.py` вызывают `XxxControl.create` без `form_ctx`. После Task 4.1 они получат `DeprecationWarning` при write, но не упадут. **Если же задачу 4.1 пропустить и сразу удалять ветку `else`** — эти файлы упадут с `AttributeError` при попытке write.

**Митигация:** строго соблюдать решение о мягком удалении (warning вместо hard delete).

### R2 — test_topology_bridge_v2.py MockResolvedCommand не имеет process_names (MEDIUM)

`MockResolvedCommand` в v2-тестах содержит только `process_name: str`, без `process_names: tuple[str, ...]`. После удаления property из `ResolvedCommand` — мок не сломается (он свой класс), но `topology_bridge.py:270` при тесте через v2 будет вызывать `resolved.process_names` который в моке отсутствует → `AttributeError`.

**Митигация:** Task 4.3 шаг 4 явно обновляет `MockResolvedCommand` в v2 добавлением `process_names` property.

### R3 — Mass-rename FieldInfo пропустит файл (LOW)

16 файлов — всё одинаковый паттерн. Риск: `TYPE_CHECKING` блок в `field_editor.py` или `register_view.py` — импорт внутри guard'а. Замена должна идти **внутри** `if TYPE_CHECKING:` блока, не добавлять новый top-level import.

**Митигация:** Task 4.2 явно упоминает это в Edge cases. Acceptance criterion на `git grep` после выполнения.

### R4 — test_command_catalog.py: много тестов на process_name (MEDIUM)

9 тест-строк в `test_command_catalog.py` проверяют `result.process_name`. После удаления property — тесты упадут. Надо либо удалить backward-compat тесты, либо заменить на `process_names[0]`.

**Митигация:** Task 4.3 шаг 5 явно перечисляет строки (219, 228, 256, 350, 352, 417, 438, 448, 467) и требует их обновления.

### R5 — FormContext.write(targets=...) backlog (LOW, INFO)

Task 4.8 из rollout-finish.md — явный API `FormContext.write(targets=...)` — **остаётся в backlog**. Никаких действий в Track 4. Если потребуется — отдельный план.

---

## Acceptance (вся фаза Track 4)

- [x] `git grep "if self._form_ctx is not None"` в трёх presenter'ах → ветка присутствует, содержит `DeprecationWarning`
- [x] `git grep "from multiprocess_prototype.registers.field_info"` → 0 результатов
- [x] `multiprocess_prototype/registers/field_info.py` не существует
- [x] `git grep "resolved\.process_name"` во всём репо → 0 результатов
- [x] `ResolvedCommand` в `command_catalog.py` — нет property `process_name`
- [x] Все 4 view-класса имеют `value_changed: Signal(...)` (верифицировано)
- [x] `pytest multiprocess_framework/modules/frontend_module/tests/ -q` — 220 passed (2 pre-existing fail не связаны с Track 4)
- [x] `pytest multiprocess_prototype/frontend/ -q` — 1163 passed (1 pre-existing fail)
- [x] `python scripts/validate.py` — зелёный
- [ ] `mcp__sentrux__check_rules` — не запускался (нет изменений архитектурных границ)

---

## Backlog (явные out of scope)

- **4.8 FormContext.write(targets=...)** — явный API для multi-target write. Оставить как отдельный issue/план.
- **Полное удаление `else`-ветки в presenter'ах** — возможно после рефакторинга `_examples/` на form_ctx или перевода их в read-only режим. Отдельная задача.
- **`default_factories.py` migration** — WidgetRegistry создаёт контролы без form_ctx. Рассмотреть в контексте constructor-refactor, не здесь.
