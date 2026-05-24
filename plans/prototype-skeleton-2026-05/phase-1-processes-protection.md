# Phase 1 — Защита системных процессов

> **Master plan**: [plan.md](plan.md)
> **Branch**: `feat/processes-protection`
> **Дней**: 1
> **Зависимости**: Phase 0
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-1-processes-protection.md, plans/prototype-skeleton-2026-05/plan.md`

## Цель

В ProcessesTab нельзя удалить/остановить GUI и orchestrator.

## Файлы

- `multiprocess_prototype/frontend/widgets/tabs/processes/_panels.py` — `AllProcessesPanel`
- `multiprocess_prototype/frontend/widgets/tabs/processes/presenter.py` — `ProcessesPresenter`
- Process-схема (data_schema) — добавить `protected: bool = False`

## Шаги

1. В blueprint для `gui` и `orchestrator` (process_manager) выставить `protected: true`.
2. Presenter: `can_delete(name) → not protected`. View disable кнопок «Удалить»/«Остановить» для protected.
3. Action-handler — early return + toast «системный процесс защищён».

## Acceptance

- На GUI и orchestrator кнопки disabled с тултипом.
- Остальные процессы управляются как раньше.
- 3-5 unit-тестов.

---

## Декомпозиция на задачи

### Task 1.1 — Поле `protected` в ProcessInfo и метод `is_protected` в Presenter

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Добавить поле `protected: bool = False` в `ProcessInfo` и метод `is_protected(name: str) -> bool` в `ProcessesPresenter`, считывающий значение из topology-dict по ключу `"protected"`.

**Context:** Сейчас `ProcessInfo` — чистый dataclass без флага защиты. Presenter читает процессы из `ctx.config["topology"]["processes"]` или `ctx.extras["topology"]["processes"]`. Оба пути возвращают dicts с ключами `process_name`, `plugins` и т.п. — достаточно добавить чтение `protected` при маппинге. Метод `is_protected` в Presenter даёт единственную точку проверки для tab и panels.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/processes/data.py` — добавить поле `protected: bool = False` в `ProcessInfo`
- `multiprocess_prototype/frontend/widgets/tabs/processes/presenter.py` — в `get_processes()` при создании `ProcessInfo` читать `proc_dict.get("protected", False)` (ветка dict) и `getattr(proc_dict, "protected", False)` (ветка Pydantic); добавить метод `is_protected(name: str) -> bool`

**Steps:**
1. В `data.py`: в `@dataclass ProcessInfo` добавить поле `protected: bool = False` после `frame_count`.
2. В `presenter.py`, метод `get_processes()`, ветка `isinstance(proc_dict, dict)`: при создании `ProcessInfo(...)` добавить `protected=proc_dict.get("protected", False)`.
3. Там же, ветка `else` (Pydantic-объект): `protected=getattr(proc_dict, "protected", False)`.
4. Добавить метод `is_protected(self, name: str) -> bool` — вызывает `get_process_by_name(name)` и возвращает `bool(proc.protected) if proc else False`.

**Acceptance criteria:**
- [x] `ProcessInfo` instantiates с `protected=True` без ошибок
- [x] `presenter.is_protected("gui")` возвращает `True` когда topology содержит `{"process_name": "gui", "protected": true, ...}`
- [x] `presenter.is_protected("camera_0")` возвращает `False` для обычного процесса
- [x] `presenter.is_protected("nonexistent")` возвращает `False` без исключений

**Out of scope:** YAML-файлы topology не трогать — protected выставляется только в тестовых fixtures Task 1.1, а в YAML — в Task 1.2.

**Refs:** plans/prototype-skeleton-2026-05/phase-1-processes-protection.md, plans/prototype-skeleton-2026-05/plan.md

**Module contract:** impl-only

**Status:** ✅ Done (commit `22b144e`)

---

### Task 1.2 — Флаг `protected: true` в topology YAML + защита кнопок в Tab

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Прописать `protected: true` для `gui` во всех активных topology YAML; в `ProcessesTab._update_buttons_state()` и `_on_button_action()` блокировать кнопки «Удалить»/«Остановить» для protected-процессов с тултипом.

**Context:** В topology YAML (все файлы кроме `archive/`) процесс `gui` объявлен без поля `protected`. После Task 1.1 presenter умеет читать этот флаг — нужно выставить его в данных и применить в tab. `process_manager`/`orchestrator` не присутствует в topology YAML (это инфраструктурный процесс фреймворка) — защищать только `gui`. В `_update_buttons_state()` сейчас только проверка `has_selection`; нужно дополнить проверкой `self._presenter.is_protected(self._selected_process)`. В `_on_button_action()` action `"delete"` и `"stop"` — добавить early return с `QMessageBox.warning` или `QToolTip`.

**Files:**
- `multiprocess_prototype/backend/topology/hello_world.yaml` — добавить `protected: true` к процессу `gui`
- `multiprocess_prototype/backend/topology/inspection_basic.yaml` — то же
- `multiprocess_prototype/backend/topology/inspection_full.yaml` — то же
- `multiprocess_prototype/backend/topology/multi_camera.yaml` — то же
- `multiprocess_prototype/backend/topology/pilot_widgets.yaml` — то же
- `multiprocess_prototype/backend/topology/region_pipeline.yaml` — то же
- `multiprocess_prototype/frontend/widgets/tabs/processes/tab.py` — изменить `_update_buttons_state()` и `_on_button_action()`

**Steps:**
1. В каждом активном YAML (6 файлов, исключая `archive/`) найти запись `process_name: gui` и добавить строку `protected: true` сразу после `process_name`.
2. В `tab.py`, метод `_update_buttons_state()`: после `has_selection = self._selected_process is not None` добавить `is_protected = has_selection and self._presenter.is_protected(self._selected_process)`. Кнопку `_btn_delete` enabled только если `has_selection and not is_protected`; `_btn_stop` — то же. `_btn_start` оставить enabled при `has_selection` (запуск остановленного protected — не запрещён). Для disabled кнопок выставить `setToolTip("Системный процесс защищён от изменений")`, для обычных — `setToolTip("")`.
3. В `_on_button_action()` для `action_id in ("delete", "stop")` добавить guard: `if self._presenter.is_protected(self._selected_process): return` (кнопки уже disabled — guard на случай programmatic вызова).

**Acceptance criteria:**
- [x] После выбора процесса `gui` в nav: `_btn_delete.isEnabled() == False`, `_btn_stop.isEnabled() == False`, `_btn_start.isEnabled() == True`
- [x] `_btn_delete.toolTip()` содержит «Системный процесс» для `gui`
- [x] После выбора `camera_0`: `_btn_delete.isEnabled() == True`, `_btn_stop.isEnabled() == True`
- [x] `_on_button_action("delete")` для `gui` не вызывает `command_sender.send_command` (early return)
- [x] Все 6 YAML содержат `protected: true` для `gui`

**Out of scope:** Карточки в `SingleProcessPanel` (кнопки Start/Stop на карточке) — в Task 1.2 не трогать, это Task 1.3. Topology `archive/` не трогать.

**Refs:** plans/prototype-skeleton-2026-05/phase-1-processes-protection.md, plans/prototype-skeleton-2026-05/plan.md

**Module contract:** impl-only

**Status:** ✅ Done (commit `e0ba4e8`, acceptance проверены smoke-check'ом; Qt-проверки в Task 1.3)

---

### Task 1.3 — Тесты защиты + disable кнопок на карточке SingleProcessPanel

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Покрыть новую логику защиты unit-тестами (≥5 тестов) и отключить кнопки «Остановить»/action `stop` на карточке `SingleProcessPanel` для protected-процессов.

**Context:** Два независимых действия объединены в одну задачу, т.к. оба небольшие и связаны: карточка в `SingleProcessPanel._build_cards_page()` строит actions жёстко (`CardAction("stop", "Остановить")`), без учёта protected; и это нужно протестировать в том же файле. Тест-стиль проекта: pure Python presenter-тесты через `unittest.mock.MagicMock`, qt-тесты через `qtbot`. Все тесты кладутся в `tests/test_processes_tab.py` (расширяем существующий файл, не создаём новый).

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/processes/_panels.py` — в `SingleProcessPanel._build_cards_page()` передавать только разрешённые actions исходя из `protected`; при `protected=True` исключить `CardAction("stop", ...)` из списка
- `multiprocess_prototype/frontend/widgets/tabs/processes/tests/test_processes_tab.py` — добавить тест-класс `TestProtectedProcesses` в конец файла

**Steps:**
1. В `_panels.py`, `SingleProcessPanel._build_cards_page()`: получить `proc = self._presenter.get_process_by_name(self._process_name)`; если `proc.protected`, строить `actions` без `CardAction("stop", "Остановить")` — только start и restart (или вообще без кнопок управления, на усмотрение в рамках 5 LOC).
2. В `test_processes_tab.py` добавить `class TestProtectedProcesses:` с тестами:
   - `test_is_protected_true` — topology с `protected: true` для `gui`, проверить `presenter.is_protected("gui") == True`
   - `test_is_protected_false_for_regular` — `presenter.is_protected("camera_0") == False`
   - `test_is_protected_missing_key` — topology без поля `protected` → `False`
   - `test_buttons_disabled_for_protected(qtbot)` — создать tab с topology где `gui.protected=true`, выбрать `gui` в nav, проверить `_btn_delete.isEnabled() == False` и `_btn_stop.isEnabled() == False`
   - `test_buttons_enabled_for_unprotected(qtbot)` — `camera_0` выбран → кнопки enabled
   - `test_toolbar_stop_skips_protected` — `_on_toolbar_action("stop_all")` не шлёт команду для protected процесса

**Acceptance criteria:**
- [x] `pytest multiprocess_prototype/frontend/widgets/tabs/processes/tests/` — все тесты зелёные (включая существующие)
- [x] `TestProtectedProcesses` содержит ≥5 тестов, все проходят
- [x] `SingleProcessPanel` для `gui` не отображает кнопку «Остановить» (карточка строится без `stop` action)
- [x] Нет импортов `multiprocess_prototype.*` из framework-модулей (слоевое правило не нарушено)

**Status:** ✅ Done (commits: f6c9b40, 6a2741c, <fix-reviewer>)

**Out of scope:** `_on_toolbar_action` уже в tab.py — если legacy stop_all итерирует `self._cards`, добавить guard `if not self._presenter.is_protected(name)` там же. Интеграционные тесты с реальным запуском процессов не нужны.

**Edge cases:**
- topology без поля `protected` → `False` (backward-compat)
- topology с `protected: false` явно → `False`
- `is_protected` при `selected_process=None` → `False` (не должно падать)

**Dependencies:** Task 1.1, Task 1.2

**Refs:** plans/prototype-skeleton-2026-05/phase-1-processes-protection.md, plans/prototype-skeleton-2026-05/plan.md

**Module contract:** impl-only
