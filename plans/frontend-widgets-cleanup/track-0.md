# Plan: Track 0 — Финализация пилота CheckboxControl

- **Slug:** frontend-widgets-track-0
- **Дата:** 2026-05-15
- **Статус:** DONE (2026-05-18, реализация в `6c2eeb1` feat(framework): form_ctx kwarg во всех FW control facades — integration tests + docstring + README)
- **Ветка:** refactor/frontend-widgets-cleanup
- **Родительский план:** [`rollout-finish.md`](rollout-finish.md), секция «Track 0»
- **Верхнеуровневая карта:** [`plan.md`](plan.md)

---

## Зачем

`widgets-arch-polish` доказал паттерн CheckboxControl + FormContext + ActionBus на уровне unit-тестов. Прежде чем тиражировать этот паттерн на 7 других builders (SpinBox, Slider, Numeric, Compound, Combo, str_short, str_long) — нужно **полностью** закрыть тестовое покрытие и документацию пилота. Три критических сценария сейчас не покрыты integration-тестами: round-trip с undo через QApplication, fan-out broadcast_flag через реальный TopologyBridge и блокировка UI по access_level. Без этих тестов риск тиражирования — высокий: ошибки в шаблоне разойдутся в 7 компонентах одновременно.

Track 0 **не меняет production-код**. Только тесты + docstring + README-секция + удаление устаревших TODO.

---

## Порядок выполнения

### Phase 1: Integration-тесты (задачи 0.1, 0.2, 0.3)

- Task 0.1: pytest-qt round-trip (View → action → undo → rollback) [DONE]
- Task 0.2: Multi-target smoke через TopologyBridge [DONE]
- Task 0.3: Access-level UI guard test [DONE]

### Phase 2: Документация и чистка (задачи 0.4, 0.5, 0.6)

- Task 0.4: Docstring параметра `form_ctx` в `CheckboxControl.create` [DONE]
- Task 0.5: README-секция «binding-aware mode» [DONE]
- Task 0.6: Чистка устаревших TODO Phase 2.6 в `factory.py` [DONE]

---

## Task 0.1 — pytest-qt round-trip: View → action → undo → rollback

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** покрыть полный цикл click→undo через реальный QApplication, реальный ActionBus и фейковый RegistersManager без моков Qt

**Context:** `test_form_context_write.py` уже покрывает `FormContext.write` на уровне unit (без Qt, без CheckboxView). Но никто не тестировал, что после `bus.undo()` подписчик (`SyncTrait`) действительно вызывает `view.set_value_silent` и CheckboxView возвращается к старому значению. Это критический сценарий для undo-stack — если сломается, пользователь видит рассинхрон UI и модели.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/tests/integration/test_form_context_integration.py` — создать (новый файл + `__init__.py` в директории)

**Steps:**
1. Создать директорию `multiprocess_framework/modules/frontend_module/tests/integration/` с файлами `__init__.py` и `test_form_context_integration.py`
2. Переиспользовать паттерн фейков из `test_form_context_write.py`: `_FakeRegistersManager` (поддерживает `subscribe`/`unsubscribe`/`set_field_value`), `_FakeActionBuilder`, `_FakeFieldSetHandler`
3. Создать fixture `qapp` (QApplication.instance() или new, паттерн из `test_checkbox_v2.py`)
4. Написать тест `test_checkbox_form_ctx_roundtrip`:
   - Построить `FormContext(rm, bus, _FakeActionBuilder)`; зарегистрировать `_FakeFieldSetHandler` в bus
   - Вызвать `CheckboxControl.create(rm, BindingConfig("robot_control", "enabled"), ..., form_ctx=form_ctx)`
   - Убедиться что начальное `view.get_value() == False` (из RM)
   - Вызвать `result.widget._checkbox.setChecked(True)` — триггерит `stateChanged` → `presenter._on_changed(True)` → `form_ctx.write` → action в bus, RM обновлён
   - Assert: `rm.get_register("robot_control").enabled is True`
   - Assert: `bus.last_action() is not None`
   - Вызвать `bus.undo()` — revert вызывает `rm.set_field_value("robot_control", "enabled", False)` → подписчики → `presenter._on_external_change(False)` → `view.set_value_silent(False)`
   - Assert: `result.widget.get_value() is False` (view синхронизирован)
   - Assert: `rm.get_register("robot_control").enabled is False`

**Acceptance criteria:**
- [x] Файл `multiprocess_framework/modules/frontend_module/tests/integration/test_form_context_integration.py` существует
- [x] `pytest multiprocess_framework/modules/frontend_module/tests/integration/test_form_context_integration.py::test_checkbox_form_ctx_roundtrip -v` — PASSED
- [x] Тест требует `qapp` fixture (аргумент), не `@pytest.mark.skip`

**Out of scope:** тест не проверяет IPC/TopologyBridge (это Task 0.2); не тестирует `on_write_rejected` callback в Qt-контексте (это уже в `test_form_context_write.py`)

**Edge cases:**
- `setChecked(True)` при уже `True` — `stateChanged` не эмитится, write не вызывается → undo stack пустой → `bus.undo()` — no-op. Тест должен стартовать с заведомо `False` начального значения
- `_FakeRegistersManager.subscribe` обязан хранить колбэки и вызывать их при `set_field_value` — это нужно для round-trip через undo

---

## Task 0.2 — Multi-target smoke: broadcast_flag через TopologyBridge

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** доказать что `broadcast_flag` (с `process_targets=("pilot_a", "pilot_b")`) вызывает `sender.send_field_command` ровно 2 раза

**Context:** `FieldRouting.process_targets` и fan-out через `for process_name in resolved.process_names` в `TopologyBridge.on_field_set` реализованы (коммит `0550f04`). Есть 5 unit-тестов fan-out в `test_topology_bridge.py`, но ни один не использует конкретное поле `broadcast_flag` из `PilotWidgetsRegisters`. Нужен smoke на реальном production-поле, а не на синтетическом мок-объекте.

**Файлы:**
- `multiprocess_prototype/frontend/bridge/tests/test_topology_bridge.py` — добавить тест в конец файла (не создавать новый файл)

**Steps:**
1. Прочитать `test_topology_bridge.py` чтобы понять паттерн mock-объектов (MockCatalog, MockCommandSender, MockValidator)
2. Добавить тест `test_broadcast_flag_fanout_through_bridge`:
   - Создать `MockCatalog` с `resolve_field_command("pilot_widgets", "broadcast_flag")` → `MockResolvedCommand` с `process_names=["pilot_a", "pilot_b"]`, `command_name="set_broadcast_flag"`
   - Создать `MockCommandSender` с записью вызовов `send_field_command` в список `calls`
   - Создать `TopologyBridge(catalog, validator, sender)`
   - Вызвать `bridge.on_field_set("pilot_widgets", "broadcast_flag", True)`
   - Assert: `len(calls) == 2`
   - Assert: `calls[0]["process_name"] == "pilot_a"`
   - Assert: `calls[1]["process_name"] == "pilot_b"`
   - Assert: `all(c["args"] == {"broadcast_flag": True} for c in calls)`
3. Использовать существующие mock-классы из файла (не дублировать)

**Acceptance criteria:**
- [x] `pytest multiprocess_prototype/frontend/bridge/tests/test_topology_bridge.py::test_broadcast_flag_fanout_through_bridge -v` — PASSED
- [x] В тесте нет импортов из `pilot_widgets/registers.py` — используются только строки-ключи `"pilot_widgets"` и `"broadcast_flag"` (изоляция слоёв)
- [x] `calls` содержит ровно 2 записи с правильными `process_name`

**Out of scope:** не тестировать реальный IPC-транспорт; не мокировать `PilotWidgetsRegisters` напрямую

**Edge cases:**
- `MockCommandSender` должен поддерживать именованный аргумент `debounce_ms` в `send_field_command` — проверить что mock-класс не падает при его передаче
- `MockValidator.validate_field_command` должен возвращать `ok=True` (иначе fan-out не дойдёт)

---

## Task 0.3 — Access-level UI guard: admin_only поле заблокировано при user_level=0

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** доказать что CheckboxControl с `access_level=5` в BindingConfig при `current_access_level=0` создаёт disabled checkbox

**Context:** поле `admin_only` в `PilotWidgetsRegisters` имеет `FieldMeta(access_level=5)`. Механизм блокировки реализован через `SchemaTrait.effective_access_level` → `AccessTrait.can_modify()` → `view.set_enabled(False)`. Но интеграционного теста, который проверяет именно `CheckboxView._checkbox.isEnabled() == False` при несоответствии уровней, нет — есть только unit-тест `AccessTrait` в `test_access_trait.py`.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/tests/integration/test_form_context_integration.py` — добавить тест в существующий файл (создан в Task 0.1)

**Steps:**
1. Добавить тест `test_checkbox_disabled_when_user_level_below_access_level` в файл из Task 0.1
2. Настроить `_FakeRegistersManager` с метаданными поля `access_level=5`:
   - метод `get_field_metadata("pilot_widgets", "admin_only")` → `{"access_level": 5}`
3. Вызвать `CheckboxControl.create(rm, BindingConfig("pilot_widgets", "admin_only", access_level=5), current_access_level=0, form_ctx=form_ctx)`
4. Assert: `result.widget._checkbox.isEnabled() is False`
5. Вызвать `result.presenter.set_access_level(5)`
6. Assert: `result.widget._checkbox.isEnabled() is True`
7. Добавить второй assert-блок: `set_access_level(4)` → `isEnabled() is False` (граничный случай: строго меньше, не равно)

**Acceptance criteria:**
- [x] `pytest multiprocess_prototype/frontend/bridge/tests/test_form_context_integration.py::test_checkbox_disabled_when_user_level_below_access_level -v` — PASSED (путь: `multiprocess_framework/modules/frontend_module/tests/integration/`)
- [x] Тест использует реальный `CheckboxView` (Qt-виджет), а не `_FakeBoolView`
- [x] Тест требует `qapp` fixture

**Out of scope:** не тестировать `required_view_permission` / `required_edit_permission` (это отдельный механизм AccessContext); не проверять `on_access_denied` callback

**Edge cases:**
- `BindingConfig(access_level=5)` и `SchemaTrait.effective_access_level` берёт `max(config_level, meta_level)`. Проверить что `access_level=5` в `BindingConfig` достаточно для блокировки при `current_access_level=0` без необходимости настраивать metadata в RM

---

## Task 0.4 — Docstring параметра `form_ctx` в `CheckboxControl.create`

**Level:** Junior (Haiku, normal) → **назначаем Middle** (следуем правилу «один уровень выше»)
**Assignee:** developer
**Goal:** расширить docstring параметра `form_ctx` в `CheckboxControl.create` — объяснить разницу путей (ActionBus vs legacy) и когда что использовать

**Context:** текущий docstring в `facade.py` строка 73-77: «form_ctx: FormContext — если передан, presenter пишет через `form_ctx.write(...)`. Если None — legacy путь через `RegisterAdapter.write`». Этого недостаточно — не объяснено ЗАЧЕМ, не описано что именно происходит в каждом пути, не указано что `None` — только для FW unit-тестов. Разработчик, копирующий паттерн на SpinBoxControl, должен понять из docstring: в production-пути `form_ctx` обязателен.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/components/checkbox/facade.py` — расширить docstring Args блока для `form_ctx`

**Steps:**
1. Прочитать текущий docstring `CheckboxControl.create` (строки 52-77)
2. Заменить блок `form_ctx:` в секции Args на расширенный (4-6 строк):
   - Путь 1 (production): «если передан — write идёт через `ActionBus` с coalescing + undo/redo + IPC bridge. Обязателен в plugin-формах (PluginsTab, InspectorPanel, ServicesTab)»
   - Путь 2 (legacy): «если `None` — прямая запись через `RegisterAdapter` → `rm.set_field_value`. Допустим только в FW unit-тестах (`_examples/`) и GUI-локальных формах без plugin binding (SettingsSystem)»
   - Явная рекомендация: «при тиражировании паттерна на новые controls (SpinBox, Slider, ...) — следуй этому контракту»

**Acceptance criteria:**
- [x] `facade.py` изменён, строки `form_ctx:` в docstring занимают не менее 4 строк
- [x] Слово «ActionBus» присутствует в docstring
- [x] Слово «legacy» или «FW unit-тест» присутствует в описании `None`-пути
- [x] `ruff check multiprocess_framework/modules/frontend_module/components/checkbox/facade.py` — 0 ошибок
- [x] `ruff format --check multiprocess_framework/modules/frontend_module/components/checkbox/facade.py` — 0 ошибок

**Out of scope:** не трогать `presenter.py`, `view.py`; не добавлять примеры кода в docstring (примеры — в README, Task 0.5)

**Edge cases:** docstring использует отступы Google-style (Args:/Returns:) — соблюдать тот же стиль, что уже в файле

---

## Task 0.5 — README: секция «binding-aware mode (form_ctx)»

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** добавить в `checkbox/README.md` секцию «Binding-aware mode» с описанием form_ctx-пути и sequence-диаграммой

**Context:** существующий `README.md` (64 строки) описывает только legacy путь. Sequence-диаграмма в секции «Поток значения» показывает `P → S → R` (presenter → SyncTrait → RegisterAdapter), но не показывает путь через FormContext + ActionBus. Разработчик, изучающий шаблон для копирования на SpinBox, не видит полного картины binding-aware пути.

**Файлы:**
- `multiprocess_framework/modules/frontend_module/components/checkbox/README.md` — добавить секцию после существующего «Поток значения»

**Steps:**
1. Прочитать весь текущий README (64 строки)
2. После секции «Поток значения» добавить новую секцию `## Binding-aware mode (form_ctx)`:
   - Краткое описание: когда передавать `form_ctx`, что происходит
   - Новую sequence-диаграмму (Mermaid):
     ```
     User → CheckboxView: клик
     CheckboxView → CheckboxPresenter: on_changed(bool)
     CheckboxPresenter → FormContext: write(register, field, new, old)
     FormContext → ActionBus: execute(action)
     ActionBus → FieldSetHandler: apply → rm.set_field_value
     rm.set_field_value → SyncTrait: subscribe callback
     SyncTrait → CheckboxPresenter: _on_external_change
     CheckboxPresenter → CheckboxView: set_value_silent
     ```
   - Примечание: «для undo: `bus.undo()` → `FieldSetHandler.revert` → тот же путь через subscribe»
   - Ссылку: «Шаблон для тиражирования: копируй `CheckboxControl.create(..., form_ctx=...)` для SpinBoxControl/SliderControl/...»
3. Обновить секцию «Тесты» — добавить ссылку на новый `integration/test_form_context_integration.py`

**Acceptance criteria:**
- [x] `README.md` содержит заголовок `## Binding-aware mode` (или `## Binding-aware mode (form_ctx)`)
- [x] README содержит Mermaid-блок с `FormContext` и `ActionBus` в тексте
- [x] README содержит упоминание undo (`bus.undo`)
- [x] README содержит слово «SpinBox» или «тиражирование» — указание что это шаблон
- [x] Файл UTF-8, нет trailing whitespace (проверить `ruff format --check` не применимо к md — визуально)

**Out of scope:** не трогать существующие секции (только добавлять); не обновлять `base/README.md`

**Edge cases:** Mermaid в GitHub рендерит `sequenceDiagram` корректно — использовать именно этот тип, не `flowchart`

---

## Task 0.6 — Чистка устаревших TODO Phase 2.6 в `factory.py`

**Level:** Junior (Haiku) → **назначаем Middle** (правило «один уровень выше»)
**Assignee:** developer
**Goal:** удалить устаревший TODO-комментарий Phase 2.6 в `_build_bool` и убедиться что остальные TODO в файле актуальны

**Context:** в `factory.py` строка 204: `# TODO Phase 2.6: re-enable DeprecationWarning when form_ctx becomes mandatory.` — этот TODO создавался для этапа 2.6 (поэтапная миграция callers). После введения параллельных треков в `rollout-finish.md` логика изменилась: form_ctx НЕ станет обязательным для legacy callers (SettingsSystem, GUI-локальные формы) — они намеренно остаются на `None`. DeprecationWarning не планируется вводить вообще. TODO устарел и вводит в заблуждение.

**Файлы:**
- `multiprocess_prototype/frontend/forms/factory.py` — только удаление/правка комментариев

**Steps:**
1. Прочитать весь файл `factory.py` (547 строк)
2. Найти все строки содержащие `TODO` через grep: `grep -n "TODO" factory.py`
3. Для каждого TODO принять решение:
   - `# TODO Phase 2.6: re-enable DeprecationWarning...` (строки ~204-207) — **удалить** полностью (4 строки комментария)
   - `# TODO (picker — Phase 10B)` в `_build_path` — **оставить** (реальный pending, не Phase 2.6)
   - Любые другие TODO — оставить если они не относятся к Phase 2.6
4. Убедиться что docstring `_build_bool` (строка 199: `"""Binding-aware CheckboxControl (form_ctx) или legacy QCheckBox."""`) по-прежнему корректен после удаления TODO

**Acceptance criteria:**
- [x] `grep -n "TODO Phase 2.6" multiprocess_prototype/frontend/forms/factory.py` → 0 строк (пустой вывод)
- [x] `grep -n "TODO" multiprocess_prototype/frontend/forms/factory.py` показывает только актуальные TODO (не Phase 2.6)
- [x] `ruff check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок
- [x] `ruff format --check multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок
- [x] Логика `_build_bool` не изменена — только комментарии

**Out of scope:** не менять логику builders; не добавлять новые TODO; не трогать `_build_bool_binding_aware`

**Edge cases:** если TODO-комментарий занимает несколько строк (как здесь — 4 строки) — удалить все строки блока целиком, не оставлять пустые строки-«призраки»

---

## Acceptance вся Track 0

- [x] Новая директория `multiprocess_framework/modules/frontend_module/tests/integration/` существует с `__init__.py`
- [x] 3 integration-теста зелёные: `test_checkbox_form_ctx_roundtrip`, `test_broadcast_flag_fanout_through_bridge`, `test_checkbox_disabled_when_user_level_below_access_level`
- [x] `pytest multiprocess_framework/modules/frontend_module/tests/integration/ -v` — 0 FAILED, 0 ERROR
- [x] `pytest multiprocess_prototype/frontend/bridge/tests/test_topology_bridge.py -v` — все существующие тесты + новый PASSED
- [x] `grep -n "TODO Phase 2.6" multiprocess_prototype/frontend/forms/factory.py` → пустой вывод
- [x] `README.md` содержит секцию `## Binding-aware mode`
- [x] `facade.py` — docstring `form_ctx` расширен (≥4 строк описания)
- [x] `ruff check multiprocess_framework/modules/frontend_module/components/checkbox/facade.py multiprocess_prototype/frontend/forms/factory.py` — 0 ошибок
- [x] `python scripts/validate.py` — зелёный
- [x] `python scripts/run_framework_tests.py` — зелёный
- [x] LOC delta: только `+` в тестах и README; production-код = 0 новых строк или `-` (удаление TODO)

---

## Шаблон commit message

```
test(frontend): Checkbox integration tests + docs — финализация пилота перед rollout

- добавлен integration/test_form_context_integration.py (2 теста: round-trip + access guard)
- добавлен test_broadcast_flag_fanout_through_bridge в test_topology_bridge.py
- расширен docstring form_ctx в CheckboxControl.create (facade.py)
- добавлена секция Binding-aware mode в checkbox/README.md
- удалён устаревший TODO Phase 2.6 из factory.py

Why: доказать пилот Checkbox перед тиражированием паттерна на остальные builders
Layer: tests
Refs: plans/frontend-widgets-cleanup/track-0.md, plans/frontend-widgets-cleanup/rollout-finish.md
Risk: low — только тесты и docs, production-код не изменён
Tested: frontend/integration/2 passed, bridge/1 passed, fw_tests/all green
```

---

## Verification команды

```powershell
# 1. Новые integration-тесты
pytest multiprocess_framework/modules/frontend_module/tests/integration/ -v

# 2. Bridge-тест fan-out
pytest multiprocess_prototype/frontend/bridge/tests/test_topology_bridge.py -v -k "broadcast_flag"

# 3. Все frontend тесты не сломались
pytest multiprocess_framework/modules/frontend_module/tests/ -v

# 4. Все bridge-тесты целы
pytest multiprocess_prototype/frontend/bridge/tests/ -v

# 5. Чистка TODO проверена
Select-String -Pattern "TODO Phase 2.6" multiprocess_prototype/frontend/forms/factory.py

# 6. Ruff
ruff check multiprocess_framework/modules/frontend_module/components/checkbox/facade.py
ruff check multiprocess_prototype/frontend/forms/factory.py
ruff format --check multiprocess_framework/modules/frontend_module/components/checkbox/facade.py
ruff format --check multiprocess_prototype/frontend/forms/factory.py

# 7. Общая валидация фреймворка
python scripts/validate.py
python scripts/run_framework_tests.py
```

---

## Риски и ограничения

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| `setChecked(True)` в тесте не триггерит `stateChanged` (CI без display) | Средняя | Использовать `QApplication` + убедиться что `stateChanged` подключён до вызова; если headless — добавить `pytest-qt` fixture `qtbot` вместо ручного QApplication |
| `AccessTrait.effective_access_level` берёт `max(binding.access_level, meta.access_level)` — нужно правильно настроить только BindingConfig без metadata в RM | Низкая | `BindingConfig(access_level=5)` достаточно — SchemaTrait читает `binding.access_level` напрямую, metadata optional |
| `MockResolvedCommand` в `test_topology_bridge.py` имеет `process_name: str` (не `process_names: list`) — Task B backlog | Средняя | Создать новый `MockResolvedCommandV2` с `process_names: list[str]` рядом со старым (не ломать существующие тесты) |
| TODO Phase 2.6 — несколько строк, неочевидные границы блока | Низкая | Grep `-A 3` чтобы увидеть весь блок перед удалением |
