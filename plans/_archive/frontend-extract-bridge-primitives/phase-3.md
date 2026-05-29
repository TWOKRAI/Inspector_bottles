# Фаза 3 — Реструктуризация пакетов (отложено)

- **Родительский план:** [`plan.md`](plan.md)
- **Статус:** PENDING — стартует после стабилизации прото (≥2 спринта после Фазы 2)
- **Содержание:** 3.1 (BaseWidget+auth), 3.2 (contracts/), 3.3 (core → runtime/utils), 3.4 (windows влить), 3.5 (scaffold CLI)

Самый рискованный этап — механическое перемещение 13 пакетов в 7.
Требует: прото заморожен на рефакторинг, все тесты зелёные, sentrux baseline снят.

---

## Целевая иерархия пакетов

```
frontend_module/
  runtime/        # из application/ + core/(runtime: qt_thread_guard, registers_bridge, app_context, routed_command)
  contracts/      # из schemas/ + configs/ + forms/ + interfaces.py
  components/     # без изменений
  widgets/        # + windows/ влить (loading_window → widgets/windows/)
  managers/       # без изменений
  utils/          # из core/(utility: diagnostics, prefs_store, action_binding, schema_config)
  tests/
```

---

## Порядок задач внутри фазы

```
3.1  →  3.2  →  3.3  →  3.4  →  3.5    (последовательно)
```

---

## Task 3.1 — Миграция auth_source + AccessTrait из `BaseConfigurableWidget` в `BaseWidget`

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** объединить два базовых виджета. `BaseWidget[TModel]` получает фичу
`auth_source` + `_wire_auth_source` + `_apply_access`. `BaseConfigurableWidget`
помечается deprecated.
**Context:** `BaseConfigurableWidget` (393 LOC) реализует `auth_source` + AccessTrait.
Единственный прото-потребитель — `permission_gate.py`. Дублирование с `BaseWidget`
накапливает расхождения. Аудит: `tests/test_base_widget_auth_source.py` уже
тестирует auth-поведение на `BaseWidget` — значит идея уже была, нужно завершить.
**Module contract:** public-api-change

**Files:**
- `multiprocess_framework/modules/frontend_module/widgets/base_widget/base_widget.py`
- `multiprocess_framework/modules/frontend_module/core/base_configurable_widget.py`
- `multiprocess_prototype/frontend/widgets/access/permission_gate.py`
- `multiprocess_framework/modules/frontend_module/tests/test_base_widget_auth_source.py` — расширить

**Steps:**
1. Изучить `_wire_auth_source`, `_on_auth_context_changed`, `_apply_access` в `BaseConfigurableWidget`.
2. Проверить `test_base_widget_auth_source.py` — какие методы уже тестируются на `BaseWidget`.
3. Перенести auth-логику как mixin или прямое расширение `BaseWidget`:
   - `_wire_auth_source(auth_source: Any) -> None`
   - `_on_auth_context_changed(ctx: Any) -> None`
   - `_apply_access() -> None`
   - параметр `auth_source` в `__init__`
4. Мигрировать `permission_gate.py` — убрать наследование от `BaseConfigurableWidget`,
   использовать `BaseWidget` с `auth_source`.
5. Пометить `BaseConfigurableWidget` deprecated: `warnings.warn(..., DeprecationWarning)`.
6. Расширить `test_base_widget_auth_source.py` — покрыть полный цикл auth-поведения.

**Acceptance criteria:**
- [ ] `BaseWidget` принимает параметр `auth_source` в `__init__`
- [ ] `permission_gate.py` использует `BaseWidget` (не `BaseConfigurableWidget`)
- [ ] `test_base_widget_auth_source.py` — все тесты зелёные
- [ ] `BaseConfigurableWidget` помечен `@deprecated`
- [ ] `make check` зелёный

**Out of scope:**
- Не удалять `BaseConfigurableWidget` (Фаза 3 только deprecated-маркировка)
- Не мигрировать другие потребители `BaseConfigurableWidget` (если они появились)

**Edge cases:**
- `BaseWidget` может быть generic `BaseWidget[TModel]` — параметр `auth_source`
  должен добавиться без ломающего изменения сигнатуры.
- MRO: если `BaseWidget` наследует несколько mix-ins — проверить порядок `super().__init__`.

**Dependencies:** зависит от завершения Фазы 2
**Module contract:** public-api-change

---

## Task 3.2 — Объединение `schemas/` + `configs/` + `forms/` + `interfaces.py` → `contracts/`

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** под одной крышей `contracts/` — все типы границ модуля.
Уменьшение шума на top-level с 13 до 10 пакетов.
**Context:** `schemas/` (3 файла, ~340 LOC), `configs/` (3 файла, ~75 LOC),
`forms/` (1 файл, ~110 LOC), `interfaces.py` (~200 LOC) — логически одна зона.
**Module contract:** public-api-change

**Files:**
- `multiprocess_framework/modules/frontend_module/contracts/` — создать пакет
- `multiprocess_framework/modules/frontend_module/schemas/` — оставить как re-export shim
- `multiprocess_framework/modules/frontend_module/configs/` — оставить как re-export shim
- `multiprocess_framework/modules/frontend_module/forms/` — оставить как re-export shim
- `multiprocess_framework/modules/frontend_module/interfaces.py` — оставить как re-export shim
- `multiprocess_framework/modules/frontend_module/__init__.py` — обновить публичный API

**Steps:**
1. Создать `contracts/` с `__init__.py` — реэкспортирует все публичные символы.
2. Переместить файлы в `contracts/`:
   - `schemas/register_binding.py`, `schemas/widget_descriptor.py` (deprecated) → `contracts/`
   - `configs/frontend_manager_config.py`, `configs/thread_manager_config.py`,
     `configs/window_manager_config.py` → `contracts/`
   - `forms/form_config.py` → `contracts/`
   - `interfaces.py` → `contracts/interfaces.py`
3. Старые пути оставить как re-export shims с `DeprecationWarning`.
4. Обновить `__init__.py` модуля — публичный API переключить на `contracts/`.
5. Добавить ADR о структуре `contracts/` в `frontend_module/DECISIONS.md`.

**Acceptance criteria:**
- [ ] `from multiprocess_framework.modules.frontend_module.contracts import FrontendManagerConfig` работает
- [ ] `from multiprocess_framework.modules.frontend_module.configs import FrontendManagerConfig` работает с `DeprecationWarning`
- [ ] `from multiprocess_framework.modules.frontend_module.interfaces import IFrontendManager` работает с `DeprecationWarning`
- [ ] Прото не сломан (re-exports работают)
- [ ] `make check` зелёный

**Out of scope:**
- Не удалять старые shim-пакеты (только deprecated)
- Не мигрировать потребителей в прото (они работают через re-export)

**Edge cases:**
- `widget_descriptor.py` уже помечен deprecated в Task 2.1 — перенести его в
  `contracts/_deprecated/` внутри `contracts/`, чтобы не смешивать с живыми типами.
- Проверить, что `__init__.py` contracts не создаёт циклических импортов с `core/`.

**Dependencies:** Task 3.1 (BaseWidget должен быть стабилен до реструктуризации contracts)
**Module contract:** public-api-change

---

## Task 3.3 — Разделение `core/` → `runtime/` + `utils/`

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** самое масштабное изменение Фазы 3. `core/` (15 файлов, ~1498 LOC)
разбивается на два пакета по семантике: `runtime/` (Qt-зависимые) и `utils/` (чистые утилиты).
**Context:** `core/` смешивает runtime-зависимые компоненты (qt_thread_guard, app_context,
registers_bridge) с чистыми утилитами (diagnostics, prefs_store, action_binding).
Разделение улучшает тестируемость — `utils/` тестируется без Qt.
**Module contract:** public-api-change

**Files (core/ — 15 файлов, ~1498 LOC):**

В **`runtime/`** (Qt-зависимые):
- `qt_imports.py`, `qt_thread_guard.py`, `registers_bridge.py` (если есть),
  `app_context.py`, `routed_command.py`
- Из `application/` влить: `frontend_manager.py`, `window_manager.py`,
  `thread_manager.py`, `process_attached_frontend.py`

В **`utils/`** (чистые утилиты):
- `diagnostics.py`, `prefs_store.py`, `action_binding.py`, `schema_config.py`

В **`_deprecated/`** (если Фазы 1-2 не удалили):
- `widget_registry.py`, `layout_composer.py`, `default_factories.py`,
  `base_configurable_widget.py`

**Steps:**
<!-- V6: добавить sentrux baseline без него "0 новых циклов" не проверяемо -->
0. Запустить `mcp__sentrux__session_start` и сохранить baseline перед любыми изменениями.
1. Проверить актуальный список файлов в `core/` перед началом (к моменту Фазы 3
   состав может измениться после Фаз 1-2).
2. Создать `runtime/` и `utils/` с `__init__.py`.
3. Переместить файлы группами — обновить внутренние импорты.
4. Оставить `core/__init__.py` как re-export shim с `DeprecationWarning` на все символы.
5. Обновить `tests/` — импорты теперь из `runtime/` и `utils/`.
6. Обновить документацию: `README.md` (обоих пакетов), `STATUS.md`, `DECISIONS.md`.
7. `mcp__sentrux__dsm` — проверить 0 новых циклов.
8. Запустить `mcp__sentrux__session_end` для delta-отчёта. Сохранить результат в
   `docs/refactors/2026-XX_phase3_dsm_delta.md` (имя файла уточнить по дате выполнения).

**Acceptance criteria:**
- [ ] `from multiprocess_framework.modules.frontend_module.runtime import FrontendManager` работает
- [ ] `from multiprocess_framework.modules.frontend_module.utils import diagnostics` работает
- [ ] `from multiprocess_framework.modules.frontend_module.core import FrontendManager` работает с `DeprecationWarning`
- [ ] `mcp__sentrux__dsm`: 0 новых циклов
- [ ] Все тесты зелёные

**Out of scope:**
- Не удалять `core/` — только re-export shim
- Не переименовывать публичные классы

**Edge cases:**
- `qt_imports.py` сам по себе является "реэкспортом" Qt — если его переместить в `runtime/`,
  нужно убедиться, что все файлы внутри `runtime/` и `utils/` импортируют из нового пути.
- `prefs_store.py` после Task 2.2 принимает `configure(organization)` — при переносе
  в `utils/` проверить, что прото-вызов `configure("Inspector")` находит новый путь.

**Dependencies:** Tasks 3.1, 3.2 должны быть завершены
**Module contract:** public-api-change

---

## Task 3.4 — Влить `windows/` в `widgets/windows/`

**Level:** Junior (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** один файл `LoadingWindow` в отдельном top-level пакете `windows/` — неоправданно.
Влить в `widgets/windows/`. Уменьшение пакетов с 13 до 12.
**Context:** `windows/loading_window.py` — единственный файл в пакете. Прямых потребителей
в прото нет (прото использует `MainWindow` через `frontend/windows/main_window.py`,
не через framework). Перемещение — чисто структурное.
**Module contract:** public-api-change

**Files:**
- `multiprocess_framework/modules/frontend_module/windows/loading_window.py` — переместить
- `multiprocess_framework/modules/frontend_module/widgets/windows/` — создать подпакет
- `multiprocess_framework/modules/frontend_module/widgets/windows/__init__.py` — создать
- `multiprocess_framework/modules/frontend_module/windows/__init__.py` — превратить в re-export shim
- `multiprocess_framework/modules/frontend_module/widgets/__init__.py` — добавить re-export LoadingWindow

**Steps:**
1. Создать `widgets/windows/` с `__init__.py`.
2. Переместить `loading_window.py` в `widgets/windows/loading_window.py`.
3. Обновить `widgets/windows/__init__.py`:
   ```python
   from .loading_window import LoadingWindow
   __all__ = ["LoadingWindow"]
   ```
4. Старый `windows/__init__.py` — re-export shim:
   ```python
   import warnings
   warnings.warn("frontend_module.windows is deprecated, use frontend_module.widgets.windows", DeprecationWarning, stacklevel=2)
   from multiprocess_framework.modules.frontend_module.widgets.windows import LoadingWindow
   __all__ = ["LoadingWindow"]
   ```
5. `make check` + тесты.

**Acceptance criteria:**
- [ ] `from multiprocess_framework.modules.frontend_module.widgets.windows import LoadingWindow` работает
- [ ] `from multiprocess_framework.modules.frontend_module.windows import LoadingWindow` работает с `DeprecationWarning`
- [ ] `make check` зелёный

**Out of scope:**
- Не трогать прото `frontend/windows/main_window.py` — это другой пакет
- Не создавать дополнительные окна

**Edge cases:**
- `windows/__init__.py` re-export shim не должен вызывать circular import —
  проверить что `widgets/windows/` не импортирует из `windows/`.

**Dependencies:** Task 3.3 (разделение core/) должно быть завершено для чистоты импортов
**Module contract:** public-api-change

---

## Task 3.5 — Scaffold CLI: `python -m frontend_module.scaffold`

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** снизить boilerplate первого виджета. CLI генерирует 4-5 файлов из
`widgets/_template/` с переименованием классов под переданное имя.
**Context:** `widgets/_template/` содержит 5 файлов: `model.py`, `panel_widget.py`,
`presenter.py`, `schemas.py`, `__init__.py` — полный skeleton MVP-виджета.
Сейчас копирование ручное. Scaffold CLI делает это за секунды.
**Module contract:** new-lite (новый публичный single-file модуль)

**Files:**
- `multiprocess_framework/modules/frontend_module/scaffold/__main__.py` — создать
- `multiprocess_framework/modules/frontend_module/scaffold/__init__.py` — создать
- `multiprocess_framework/modules/frontend_module/scaffold/templates/` — создать
  (перенести из `widgets/_template/` с `.tmpl`-расширением или использовать `jinja2`-minimal)
- `multiprocess_framework/modules/frontend_module/docs/WIDGET_COOKBOOK.md` — создать/обновить

**Steps:**
1. Изучить `widgets/_template/` — список файлов, паттерны именования классов
   (`TemplateWidget`, `TemplatePresenter`, `TemplateModel`, `TemplateSchemas`).
2. Определить стратегию шаблонизации: простой `str.replace("Template", PascalCase(name))`
   без внешних зависимостей (Jinja2 — опционально если уже есть в dev-deps).
3. Реализовать `__main__.py`:
   ```
   python -m frontend_module.scaffold my_widget --target path/to/widgets/
   ```
   Аргументы:
   - `widget_name` — имя в snake_case, конвертируется в PascalCase
   - `--target` — целевая директория (дефолт: `./widgets/`)
   - `--dry-run` — показать что будет создано без записи
4. Генерация: создать папку `my_widget/`, скопировать 5 шаблонных файлов с заменой
   `Template` → `MyWidget` в именах классов и импортах.
5. Написать тест: `test_scaffold_creates_files` — вызов через `subprocess` или прямой
   вызов функций, проверить что 5 файлов созданы с правильными именами.
6. Обновить `WIDGET_COOKBOOK.md`: раздел "Быстрый старт через scaffold".

**Acceptance criteria:**
- [ ] `python -m frontend_module.scaffold demo_widget --dry-run` выводит список 5 файлов без ошибок
- [ ] `python -m frontend_module.scaffold demo_widget --target /tmp/test_scaffold/` создаёт 5 файлов
- [ ] В `DemoWidget/presenter.py` класс называется `DemoWidgetPresenter` (не `TemplatePresenter`)
- [ ] `test_scaffold_creates_files` проходит
- [ ] `WIDGET_COOKBOOK.md` содержит раздел scaffold

**Out of scope:**
- Не добавлять Jinja2 в зависимости если не нужен (str.replace достаточен)
- Не генерировать тесты (только 5 боевых файлов)
- Не делать интерактивный режим (wizard)

**Edge cases:**
- `widget_name` может прийти в CamelCase или snake_case — нормализовать оба варианта.
- Целевая директория уже существует — спросить или падать с ошибкой (не молча перезаписывать).

**Dependencies:** Tasks 3.1–3.4 должны быть завершены (scaffold должен генерировать
виджеты под новую структуру пакетов)
**Module contract:** new-lite

---

## Локальные риски Фазы 3

1. **Самое масштабное изменение (3.3):** 15 файлов core/, ~1498 LOC. Высокий риск
   сломать импорты. Mitigation: сначала re-export shim, потом потребители.

2. **Scope drift Фазы 3:** состав `core/` к моменту выполнения изменится после
   Фаз 1-2. Teamlead обязан пересмотреть список файлов перед стартом Task 3.3.

3. **Scaffold зависимости (3.5):** scaffold генерирует под новую структуру пакетов —
   нельзя стартовать до 3.1-3.4.
