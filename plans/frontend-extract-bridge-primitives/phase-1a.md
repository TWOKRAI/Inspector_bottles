# Фаза 1A — Вынос созревших элементов + техгигиена

- **Родительский план:** [`plan.md`](plan.md)
- **Статус:** READY — можно стартовать сейчас, не зависит от пилота вкладок
- **Содержание:** A1 (bridge → fw), A2 (primitives → fw), B2 (EntityTreeWidget), B3 (README), C1/C2/C3 (тесты менеджеров)

---

## Порядок задач внутри фазы

```
A1 ║ A2  →  B2 ║ B3 ║ C1 ║ C2 ║ C3   (после готовности bridge/ и primitives/ во fw)
```

A1 и A2 — параллельно, файлов не пересекают.
B2, B3, C1, C2, C3 — параллельно, после завершения A1+A2.

---

## Task A1 — Вынос `bridge/` подпакета во framework

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** скопировать 6 файлов `bridge/` из прототипа в `frontend_module/bridge/`,
исправить единственную прото-ссылку (`GuiProcess` → Protocol/Any) и добавить
re-export в прото-`__init__.py` для обратной совместимости.
**Context:** шесть файлов — pure Python без зависимостей от прото; единственный
грязный edge — `TYPE_CHECKING` lazy import `GuiProcess` в `command_sender.py`.
После переноса все 42 точки использования в прото работают через re-export.
**Module contract:** new-full (новый подпакет ≥3 файлов с публичным API)

**Files:**
- `multiprocess_framework/modules/frontend_module/bridge/__init__.py` — создать
- `multiprocess_framework/modules/frontend_module/bridge/wire_protocol.py` — создать
- `multiprocess_framework/modules/frontend_module/bridge/diff_engine.py` — создать
- `multiprocess_framework/modules/frontend_module/bridge/system_commands.py` — создать
- `multiprocess_framework/modules/frontend_module/bridge/wire_monitor.py` — создать
- `multiprocess_framework/modules/frontend_module/bridge/command_sender.py` — создать
- `multiprocess_framework/modules/frontend_module/bridge/command_validator.py` — создать
- `multiprocess_framework/modules/frontend_module/bridge/README.md` — создать (contract-first)
- `multiprocess_prototype/frontend/bridge/__init__.py` — добавить re-export из fw

**Steps:**
<!-- K2: Step 2 с созданием _GuiProcessLike удалён — используем существующий IProcess (строки 17-24 command_sender.py) -->
1. Скопировать `wire_protocol.py`, `diff_engine.py`, `system_commands.py`,
   `wire_monitor.py`, `command_validator.py` дословно (без правок — нет зависимостей).
2. Скопировать `command_sender.py`; удалить `TYPE_CHECKING` импорт
   `from ..process import GuiProcess` (строки ~14-16); заменить аннотацию
   `"GuiProcess | IProcess"` (строка ~38) на просто `IProcess`.
   Существующий `IProcess` (строки 17-24, Protocol с двумя аргументами
   `send_message(target: str, msg: dict[str, Any]) -> None`) остаётся без изменений
   и реэкспортируется вместе с файлом.
3. Создать `frontend_module/bridge/__init__.py` с `__all__` — реэкспортирует все
   публичные символы из 6 модулей (те же, что сейчас в прото-`bridge/__init__.py`,
   кроме `DataReceiverBridge` — он не переносится).
4. Создать `bridge/README.md` — назначение подпакета, список публичных классов,
   stability marker (`partial` → `contract` после тестов C1-C3).
5. В прото-`bridge/__init__.py`: заменить прямые импорты из `.wire_protocol`,
   `.diff_engine` и т.д. на импорты из
   `multiprocess_framework.modules.frontend_module.bridge.*`;
   сохранить строку `from ..bridge_impl import DataReceiverBridge` и
   `from .command_catalog import ...`, `from .topology_bridge import ...` (они остаются
   в прото).
5.5. **[K1]** В прототипе заменить КАЖДЫЙ из 6 оригинальных файлов на однострочный
   re-export shim — так все 17 потребителей, импортирующих напрямую из подмодулей
   (`from multiprocess_prototype.frontend.bridge.command_sender import CommandSender`),
   продолжат работать:
   ```python
   """Re-export из framework (Phase 1, A1)."""
   from multiprocess_framework.modules.frontend_module.bridge.command_sender import *  # noqa: F401, F403
   from multiprocess_framework.modules.frontend_module.bridge.command_sender import __all__  # noqa: F401
   ```
   Применить аналогично к `wire_protocol.py`, `diff_engine.py`, `system_commands.py`,
   `wire_monitor.py`, `command_validator.py`. После замены в каждом файле не должно
   остаться определений классов/функций — только re-export.
6. Прогнать существующие тесты в `bridge/tests/` — все должны пройти без правки
   (импортируют из `multiprocess_prototype.frontend.bridge`, что теперь re-export).

**Acceptance criteria:**
- [ ] `python -c "from multiprocess_framework.modules.frontend_module.bridge import WireConfig, CommandSender, WireStatusMonitor"` без ошибок
- [ ] `python -c "from multiprocess_prototype.frontend.bridge import WireConfig, CommandSender"` без ошибок (re-export работает)
- [ ] `python -c "from multiprocess_prototype.frontend.bridge.command_sender import CommandSender"` без ошибок (прямой импорт из подмодуля работает)
- [ ] `grep -c "^class\|^def " multiprocess_prototype/frontend/bridge/command_sender.py` возвращает `0` (только re-export, без определений)
- [ ] То же проверить для остальных 5 shim-файлов: `wire_protocol.py`, `diff_engine.py`, `system_commands.py`, `wire_monitor.py`, `command_validator.py`
- [ ] `python scripts/run_framework_tests.py` зелёный (все прото-тесты bridge/)
- [ ] `mcp__sentrux__check_rules` — 0 новых нарушений boundary `framework → prototype`
- [ ] `make check` (ruff + pyright + bandit) зелёный

**Out of scope:**
- Не переносить `command_catalog.py`, `topology_bridge.py` (зависимости от прото)
- Не удалять и не переименовывать файлы в `multiprocess_prototype/frontend/bridge/` (только заменять содержимое на shims)
- Не менять публичный API (сигнатуры классов и функций)
- Не создавать тесты для новых файлов (это Task C1)

**Edge cases:**
- `system_commands.py` использует `TYPE_CHECKING: from .wire_protocol import WireConfig` —
  после копирования в один пакет этот относительный импорт корректен, проверить.
- `wire_monitor.py` зависит от `command_sender.py` (проверить граф импортов внутри
  подпакета перед копированием).

**Dependencies:** нет (первый в цепочке)

---

## Task A2 — Вынос primitive-виджетов во framework

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** перенести 4 primitive-виджета из `multiprocess_prototype/frontend/widgets/primitives/`
в `multiprocess_framework/modules/frontend_module/components/primitives/` и добавить
re-export в прото-`__init__.py`.
**Context:** виджеты — pure PySide6, 0 зависимостей от прото-пакета.
<!-- K3: директория widgets/primitives/ во фреймворке НЕ существует. Реальные framework-primitives
     живут в components/primitives/ (control_label.py, numeric_line_edit.py, styled_slider.py,
     value_bridge.py). Целевой путь исправлен с widgets/primitives/ → components/primitives/ -->
Директория `components/primitives/` во фреймворке уже существует (содержит
`control_label.py`, `numeric_line_edit.py`, `styled_slider.py`, `value_bridge.py`);
нужно дополнить её 4 новыми виджетами.
**Module contract:** public-api-change (расширение существующего подпакета)

**Files:**
- `multiprocess_framework/modules/frontend_module/components/primitives/status_indicator.py` — создать
- `multiprocess_framework/modules/frontend_module/components/primitives/entity_card.py` — создать
- `multiprocess_framework/modules/frontend_module/components/primitives/crud_table.py` — создать
- `multiprocess_framework/modules/frontend_module/components/primitives/master_detail.py` — создать
- `multiprocess_framework/modules/frontend_module/components/primitives/__init__.py` — обновить (добавить 4 новых символа в `__all__`)
- `multiprocess_prototype/frontend/widgets/primitives/__init__.py` — обновить (добавить re-export из fw для 4 символов)

**Steps:**
1. Скопировать 4 файла дословно (нет зависимостей, нет правок).
2. Обновить `frontend_module/components/primitives/__init__.py`:
   добавить импорты и символы в `__all__`:
   `StatusIndicator`, `EntityCard`, `CardAction`, `CrudTable`, `MasterDetailLayout`.
   **Замечание:** если 4 переносимых виджета (UI-карточки, таблицы) семантически
   конфликтуют с существующими control-primitives (control_label, slider, numeric_input) —
   escalate в teamlead для решения, нужна ли отдельная директория. Решение
   зафиксировать в ADR (локальный `DECISIONS.md` или отдельный ADR в `DECISIONS.md` фреймворка).
3. Обновить прото-`__init__.py`: для 4 перенесённых символов сделать re-export из
   `multiprocess_framework.modules.frontend_module.components.primitives`:
   ```python
   # re-export перенесённых primitives из фреймворка
   from multiprocess_framework.modules.frontend_module.components.primitives import (
       StatusIndicator,
       EntityCard,
       CardAction,
       CrudTable,
       MasterDetailLayout,
   )
   ```
   Остальные символы (ActionToolbar, SlotSelector и т.д.) остаются локальными.
4. Убедиться, что `from multiprocess_prototype.frontend.widgets.primitives import
   StatusIndicator` продолжает работать.

**Acceptance criteria:**
- [ ] `python -c "from multiprocess_framework.modules.frontend_module.components.primitives import StatusIndicator, EntityCard, CrudTable, MasterDetailLayout"` без ошибок
- [ ] `python -c "from multiprocess_prototype.frontend.widgets.primitives import StatusIndicator"` без ошибок (re-export)
- [ ] `make check` зелёный
- [ ] Существующие тесты `test_primitives_batch1.py`, `test_primitives_batch2.py` зелёные

**Out of scope:**
- Не переносить ActionToolbar, SlotSelector, SectionedForm, SideNavLayout, StandardTabLayout,
  DiffScrollTabLayout, TreeNavWidget (они в активной разработке или зависимы)
- Не удалять исходные файлы из прото

**Edge cases:**
- Проверить, что `entity_card.py` экспортирует `CardAction` — он нужен в `__init__.py`.
- Если выявлен семантический конфликт типов primitives — см. замечание в Step 2.

**Dependencies:** нет (параллельно с A1)

---

## Task B2 — Устранение дублирования в `EntityTreeWidget`

**Level:** Junior (developer, normal thinking)
**Assignee:** developer
**Goal:** извлечь приватный метод `_build_level_row` из дублирующихся
`_build_parent_row` и `_build_child_row` в `entity_tree_widget.py`.
**Context:** 554-строчный файл. Методы строки 218-258 и 260-303 идентичны на 80%.
Рефакторинг устраняет divergence-риск при будущих изменениях UI-формата строк.
**Module contract:** impl-only

**Files:**
- `multiprocess_framework/modules/frontend_module/widgets/entity_editor/entity_tree_widget.py`

**Steps:**
1. Создать приватный метод `_build_level_row`:
   ```python
   def _build_level_row(
       self,
       level,           # EntityLevel (parent_level или child_level из конфига)
       display_key: str,
       role_type: str,          # "parent" | "child"
       data: dict,
       *,
       role_parent: str,
       role_child: str | None = None,
   ) -> list[QStandardItem]:
   ```
   Внутри — общая логика создания `name_item`, `val_item`, `comment_item`, `summary_item`.
2. В `_build_parent_row` — делегировать `_build_level_row` с `role_type="parent"`,
   `role_child=None`.
3. В `_build_child_row` — делегировать `_build_level_row` с `role_type="child"`,
   передать `parent_key` как `role_parent`, `child_key` как `role_child`.
4. Убедиться, что тесты, использующие tree widget, не упали (тест в
   `tests/test_base_tree_nav_tab.py` или аналог).

**Acceptance criteria:**
- [ ] `entity_tree_widget.py` уменьшился на 25-35 строк
- [ ] `_build_parent_row` и `_build_child_row` вызывают `_build_level_row` (нет дублирования)
- [ ] `python scripts/run_framework_tests.py` зелёный
- [ ] `make check` зелёный

**Out of scope:**
- Не менять публичный API `entity_tree_widget.py`
- Не рефакторить другие методы файла
- Не добавлять тесты (уже есть)

**Edge cases:**
- Убедиться, что в `_build_parent_row` иконка не зависит от `child_key` (в parent_row
  его нет) — в общем методе параметр `role_child` = `None`, `setData` для `ROLE_CHILD`
  вызывается только если не None.

**Dependencies:** нет (v3 — было «B1», но `entity_tree_widget.py` не правится пилотом
вкладок и не входит в zone hot-conflict; B2 может идти параллельно с A1/A2).

---

## Task B3 — README для подпакетов `frontend_module`

**Level:** Junior (Haiku, normal thinking)
**Assignee:** docs-writer
**Goal:** создать минимальные README (≤1 экрана) для 6 подпакетов, у которых его нет.
**Context:** из 13 подпакетов верхнего уровня только `components/` имеет README.
Этап 8 STATUS.md — «Финальная документация». Минимальный README: назначение +
ключевые публичные символы + ссылка на корневой README.
**Module contract:** n/a (только документация)

**Files (создать):**
- `multiprocess_framework/modules/frontend_module/application/README.md`
- `multiprocess_framework/modules/frontend_module/widgets/README.md`
- `multiprocess_framework/modules/frontend_module/managers/README.md`
- `multiprocess_framework/modules/frontend_module/core/README.md`
- `multiprocess_framework/modules/frontend_module/schemas/README.md`
- `multiprocess_framework/modules/frontend_module/configs/README.md`

**Steps:**
<!-- T4: список подпакетов без README может измениться после A1 и A2 -->
0. Перед началом — повторный glob по подпакетам `frontend_module` и проверка наличия
   `README.md`. После A1 `bridge/` уже получит README (создаётся там — не дублировать).
   После A2 `components/primitives/` может получить README (уточнить у исполнителя A2).
   Актуализировать список файлов для создания.
1. Прочитать `__init__.py` каждого подпакета — определить публичные символы.
2. Для каждого создать README по шаблону:
   ```markdown
   # <имя> — <назначение одной строкой>

   ## Ключевые символы
   - `ClassName` — что делает
   ...

   ## Stability
   partial | contract | lite

   → Корневой README: `../../README.md`
   ```
3. Не включать в README внутренние (`_*`) классы.

**Acceptance criteria:**
- [ ] Все 6 файлов созданы
- [ ] Каждый README ≤ 30 строк
- [ ] `make check` не ломается (ruff не проверяет .md)

**Out of scope:**
- Не создавать README для `bridge/` (создан в A1) и `components/` (уже есть)
- Не писать ADR (это task tech-writer)
- Не обновлять корневой README модуля

**Dependencies:** A1 (bridge/README.md создаётся там; B3 не дублирует его)

---

## Task C1 — Unit-тесты `FrontendManager`

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** tester
**Goal:** покрыть `application/frontend_manager.py` на ≥60% unit-тестами
с моком Qt и зависимостей фреймворка.
**Context:** FrontendManager — самый критичный класс модуля (223 LOC): initialize,
run_app, shutdown_app, config hot-reload через подписку. Сейчас 0 тестов. Этап 7
STATUS.md.
**Module contract:** impl-only (только тесты)

**Files:**
- `multiprocess_framework/modules/frontend_module/tests/test_frontend_manager.py` — создать

**Steps:**
1. Определить стратегию мокирования:
   - `QApplication` — мок через `pytest-qt` (`qtbot`) или `unittest.mock.patch`
   - `WindowManager` — мок-объект с `show/close/register`
   - `ThreadManager` — мок-объект
   - `FrontendRegistersBridge` — мок
   - `BaseManager.initialize` — patch
2. Тест-кейсы:
   - `test_initialize_sets_managers` — после `initialize()` атрибуты заполнены
   - `test_run_app_calls_window_manager` — `run_app()` вызывает `window_manager.show_main()`
   - `test_shutdown_app_calls_cleanup` — `shutdown_app()` вызывает teardown-методы
   - `test_config_hotreload_emits_signal` — подписка на config_module, изменение
     конфига → emit `config_changed`
   - `test_initialize_without_process` — инициализация без process не бросает
3. Формат тестов: `pytest`, given/when/then комментарии.

**Acceptance criteria:**
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_frontend_manager.py -v` — все тесты зелёные
- [ ] Coverage `application/frontend_manager.py` ≥ 60% (`pytest --cov`)
- [ ] Нет импортов из `multiprocess_prototype` в тестовом файле
- [ ] `make check` зелёный

**Out of scope:**
- Не тестировать `WindowManager`, `ThemeManager` здесь (это C2/C3)
- Не тестировать реальный Qt event loop (только мок)

**Edge cases:**
- `FrontendManager` наследует `BaseManager` + `ObservableMixin` — моки должны учитывать
  MRO и то, что `initialize()` вызывает `super().initialize()`

**Dependencies:** A1, A2 (bridge/ и primitives/ должны быть во фреймворке; B1 не требуется — менеджеры уже используют qt_imports)

---

## Task C2 — Unit-тесты `WindowManager`

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** tester
**Goal:** покрыть `application/window_manager.py` на ≥60% unit-тестами.
**Context:** WindowManager — реестр окон (221 LOC): register, show, close,
fullscreen, access_level, cursor. Сейчас 0 тестов.
**Module contract:** impl-only (только тесты)

**Files:**
- `multiprocess_framework/modules/frontend_module/tests/test_window_manager_unit.py` — создать
  (NB: `test_window_registry.py` уже есть — это другой класс, не дублировать)

**Steps:**
1. Стратегия мокирования:
   - `QObject.__init__` — pytest-qt `qapp` fixture (нужен реальный `QApplication`)
   - Окна — мок-объекты с `show()`, `hide()`, `showFullScreen()`
   - `WindowRegistry` — использовать реальный (он не Qt)
2. Тест-кейсы:
   - `test_register_window` — `register()` добавляет в реестр
   - `test_show_registered_window` — `show_window(name)` вызывает `window.show()`
   - `test_close_all` — `close_all()` вызывает `hide()` на всех окнах
   - `test_access_level_restricts_visibility` — при `access_level < required` окно
     не показывается
   - `test_show_unknown_window_raises` — `show_window("unknown")` → ValueError или
     warning (проверить по коду)
   - `test_config_get_dict` — хелпер `_config_get` с dict и dot-notation
3. Формат: `pytest`, given/when/then.

**Acceptance criteria:**
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_window_manager_unit.py -v` — зелёный
- [ ] Coverage `application/window_manager.py` ≥ 60%
- [ ] `make check` зелёный

**Out of scope:**
- Не тестировать `WindowRegistry` — уже есть `test_window_registry.py`
- Не тестировать реальный fullscreen (только мок)

**Edge cases:**
- `WindowManager(QObject)` требует `QApplication` до инициализации — fixture `qapp`
  из pytest-qt обязательна.

**Dependencies:** A1, A2 (не B1 — менеджеры уже используют qt_imports независимо)

---

## Task C3 — Unit-тесты `ThemeManager`

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** tester
**Goal:** покрыть `managers/theme_manager.py` на ≥60% unit-тестами с файловой
изоляцией через `tmp_path`.
**Context:** ThemeManager (273 LOC): загрузка QSS, модульные темы (папка с
несколькими .qss), CSS-переменные (`@var` плейсхолдеры), hot-reload,
`variables.yaml`. Сейчас 0 тестов.
**Module contract:** impl-only (только тесты)

**Files:**
- `multiprocess_framework/modules/frontend_module/tests/test_theme_manager.py` — создать

**Steps:**
1. Стратегия: `tmp_path` для создания фиктивных `.qss` и `variables.yaml`.
   Мок `QApplication.instance().setStyleSheet` (или реальный `qapp` fixture).
2. Тест-кейсы:
   - `test_load_single_file_theme` — файл `styles/dark.qss` → `load_theme("dark")`
     вызывает `setStyleSheet`
   - `test_load_modular_theme` — папка `styles/themes/dark/*.qss` — файлы
     конкатенируются по алфавиту
   - `test_resolve_qss_variables` — `@bg_deep` заменяется на значение из словаря
   - `test_variables_from_yaml` — `variables.yaml` в папке темы подхватывается
   - `test_switch_theme` — `switch_theme("light")` → другой QSS применяется
   - `test_hot_reload` — повторный `load_theme()` → `setStyleSheet` вызван снова
   - `test_missing_theme_raises` — `load_theme("nonexistent")` → FileNotFoundError
     или warning (проверить по коду)
3. Формат: `pytest`, given/when/then.

**Acceptance criteria:**
- [ ] `pytest multiprocess_framework/modules/frontend_module/tests/test_theme_manager.py -v` — зелёный
- [ ] Coverage `managers/theme_manager.py` ≥ 60%
- [ ] `make check` зелёный

**Out of scope:**
- Не тестировать реальный рендеринг Qt (только применение QSS)
- Не создавать реальные темы в `styles/` — только через `tmp_path`

**Edge cases:**
- `ThemeManager` использует `yaml` — убедиться, что `pyyaml` есть в dev-зависимостях
  (скорее всего есть, но проверить).
- Если `QApplication` не инициализирован, `setStyleSheet` может не работать —
  нужна `qapp` fixture.

**Dependencies:** A1, A2 (не B1 — менеджеры уже используют qt_imports независимо)

---

## Локальные риски Фазы 1A

1. **Re-export loop risk (A1):** fw-bridge не должен импортировать из прото.
   Mitigation: проверить через `mcp__sentrux__check_rules` после A1.

2. **GuiProcess Protocol (A1):** неправильная замена сломает pyright.
   Mitigation: не создавать новый Protocol — использовать существующий `IProcess`
   (`send_message(target: str, msg: dict[str, Any]) -> None`). Убрать только
   `TYPE_CHECKING` import `GuiProcess` и заменить аннотацию `"GuiProcess | IProcess"` → `IProcess`.

3. **Тесты bridge в прото (A1):** 9 тестовых файлов работают через re-export.
   Mitigation: явно прогнать все 9 в шаге 6 A1.

4. **primitives: неполный __all__ (A2):** `CardAction` должен быть в re-export.
   Mitigation: явно перечислен в Steps A2. Целевая директория — `components/primitives/`,
   не `widgets/primitives/` (которая не существует во фреймворке).

5. **pytest-qt для C1-C3:** нужна `qapp` fixture в `conftest.py`.
   Mitigation: добавить локально, не ломать существующие тесты.

6. **Параллельное A1||A2:** файловых конфликтов нет.

---

## Локальный acceptance Фазы 1A

См. также общий блок в [`plan.md`](plan.md#фаза-1a).

- [ ] A1: `from multiprocess_framework.modules.frontend_module.bridge import WireConfig, CommandSender, WireStatusMonitor, CommandValidator` работает
- [ ] A1: `from multiprocess_prototype.frontend.bridge import WireConfig` работает (re-export)
- [ ] A2: `from multiprocess_framework.modules.frontend_module.components.primitives import StatusIndicator, EntityCard, CrudTable, MasterDetailLayout` работает
- [ ] A2: `from multiprocess_prototype.frontend.widgets.primitives import StatusIndicator` работает (re-export)
- [ ] B2: `entity_tree_widget.py` уменьшился на 25-35 строк, дублирование устранено
- [ ] B3: 6 README созданы, каждый ≤30 строк
- [ ] C1+C2+C3: Coverage ≥60% по каждому из трёх менеджеров
- [ ] Smoke-test: 6 мигрированных вкладок (recipes, processes, services, plugins, pipeline, displays) открываются без ошибок
- [ ] `make gate` зелёный
- [ ] `mcp__sentrux__check_rules` — 0 новых нарушений
