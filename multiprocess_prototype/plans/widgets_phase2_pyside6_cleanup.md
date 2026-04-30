# План: Phase 2 — Полный переход на PySide6 + уборка follow-up после widgets-reorg

**Дата:** 2026-04-27
**Статус:** DRAFT
**Область:** `multiprocess_prototype/` + `App/` + тесты
**Предшественник:** `widgets_reorganization.md` (завершён, ветка `feat/widgets-reorg`, 8 коммитов)

---

## Контекст и факты (по аудиту от 2026-04-27)

### Что уже есть

- **Production v3 уже на PySide6.** 31 файл с импортами `from PySide6...`, **0 файлов с `from PyQt5`** в `multiprocess_prototype/`.
- Центральный shim `multiprocess_framework/modules/frontend_module/core/qt_imports.py` — на PySide6, docstring декларирует завершение «Phase 2, Wave 5: transitional aliases удалены».
- `qt_imports.py` импортируется в **132 файлах** (138 import-строк).
- В venv `projects/Inspector_bottles/.venv/` установлен **PySide6 6.10.3, PyQt5 отсутствует**.

### Что не убрано (расхождения)

1. **Тесты v3 декларируют PyQt5**, хотя его нет в venv:
   - `tests/test_recipes_integration.py:19` — `pytest.importorskip("PyQt5", ...)` → тест **всегда скипается**
   - `tests/unit/test_recipes_register_presenter.py:15` — то же
   - `tests/unit/test_auto_layout.py:18-22` — `sys.modules["PyQt5"] = MagicMock()` → ставит MagicMock на несуществующий модуль (no-op в текущем venv)
   - `tests/unit/test_region_per_camera.py:70` — комментарий «(только при наличии PyQt5)»
   - 4-5 файлов с docstring «без PyQt5» / «требуется PyQt5»

2. **Комментарии в production-коде упоминают PyQt5:**
   - `frontend/managers/window_manager.py:13` — «PyQt5 импортируется только для аннотаций»
   - `frontend/widgets/__init__.py:8` — docstring «не требовать PyQt5 в окружении»
   - `frontend/widgets/recipes/recipes_widget/__init__.py:7` — «без PyQt5»
   - `frontend/widgets/recipes/recipes_widget/auto_save.py:3` — «тестируется без PyQt5»

3. **pytest config неполон:**
   - `pyproject.toml` `testpaths` не включает `multiprocess_prototype/tests/` — тесты v3 не собираются по умолчанию.
   - Нет `qt_api = "pyside6"` → pytest-qt warning «Unknown config option: qt_api».
   - `pytest-qt` возможно не установлен (требуется проверка).

4. **Папка `App/`** — 61 файл с `from PyQt5`:
   - `App/main_app.py`, `App/UI/Components/*` (12 файлов), `App/UI/Windows/*` (10 файлов), `App/UI/Widgets/*` (8 файлов).
   - **НЕ импортируется** из `multiprocess_prototype/` (`grep -rn "from App\." | grep -v /App/` = 0).
   - **НЕ запускается** в текущем venv (PyQt5 нет).
   - Старая версия приложения, изолирована.

5. **Ручной запуск MainWindow падает на `backend`:**
   - `frontend/managers/display_router.py:16` — `from backend.routing.frame_router_setup import ...`
   - `backend/` существует в `multiprocess_prototype/backend/`, но не находится из cwd ``.
   - Этот баг **есть и на baseline `widgets-reorg-start`** — не наш регресс, но блокирует ручной smoke `python -c "import MainWindow"`.

6. **Структурный долг от widgets-reorg (из ревью 2026-04-27):**
   - `tabs_setting/` плоский, дублирует доменные группы (`recipes/` ↔ `tabs_setting/recipes_tab/`).
   - `_base/` подчёркнут как приватный, но используется 5 доменами.
   - Доменные `__init__.py` пустые — внешние импорты двухуровневые.
   - План реорганизации остался в `multiprocess_prototype/plans/`.

---

## Цели

1. **«Только PySide6 везде»** — убрать все упоминания PyQt5 из v3 (production + тесты + комментарии).
2. **Корректная конфигурация pytest** — v3-тесты в testpaths, `qt_api = pyside6`, скипы тестов работают по реальному критерию (PySide6 vs no-Qt).
3. **Решение по `App/`** — деприкейт-стратегия (переезд в `_archive/` или удаление).
4. **Closing the loop по widgets-reorg** — устранить структурный долг (5-7 пунктов).
5. **Документация** — CLAUDE.md проекта актуальна, план реорганизации перенесён в `docs/refactors/`.

**Не цели:**
- Полная миграция `App/` на PySide6 (это отдельная фаза, если решим оживить).
- Расщепление виджетов на `core/`+`qt/` (большая архитектурная фаза).
- Решение `backend.routing` импорт-проблемы (отдельный план — связан с тем как запускается v3 runtime).

---

## Декомпозиция на задачи

### Phase A — PySide6 cleanup в v3 (низкий риск, 2-3 часа)

#### Task 2.1 — Тесты v3: PyQt5 → PySide6

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** Убрать все `importorskip("PyQt5")` и `sys.modules["PyQt5"] = MagicMock`. Тесты должны проходить или скипаться по реальному критерию (PySide6).

**Файлы:**
- `tests/test_recipes_integration.py:19` — `importorskip("PyQt5")` → `importorskip("PySide6")` (или просто убрать — PySide6 теперь в venv)
- `tests/unit/test_recipes_register_presenter.py:15` — то же
- `tests/unit/test_auto_layout.py:18-22` — удалить блок `sys.modules["PyQt5"] = MagicMock()`. Если тест требует Qt — добавить `pytest.importorskip("PySide6")`. Если pure-Python — переписать без моков.
- `tests/unit/test_region_per_camera.py:70` — обновить комментарий

**Шаги:**
1. Прочитать каждый тест, понять реальную зависимость от Qt
2. Заменить `PyQt5` → `PySide6` в `importorskip` и `sys.modules`
3. Прогнать `pytest multiprocess_prototype/tests` — проверить, что число passed/failed/errors не ухудшилось vs baseline

**Критерии приёмки:**
- [ ] `grep -rn "PyQt5" multiprocess_prototype/tests --include="*.py"` возвращает 0 (только новые упоминания PySide6 или комментарии без PyQt5)
- [ ] pytest на v3 не хуже baseline (1034 passed, 21 failed, 17 errors на момент 2026-04-27)
- [ ] Тесты, которые должны выполняться с PySide6 — выполняются (не скипаются молча)

#### Task 2.2 — Production-код: убрать упоминания PyQt5 в комментариях/docstrings

**Уровень:** Junior (Haiku, normal)
**Исполнитель:** docs-writer
**Цель:** Документация в коде соответствует реальности.

**Файлы:**
- `frontend/managers/window_manager.py:13`
- `frontend/widgets/__init__.py:8`
- `frontend/widgets/recipes/recipes_widget/__init__.py:7`
- `frontend/widgets/recipes/recipes_widget/auto_save.py:3`
- (плюс grep на остальные)

**Шаги:**
1. `grep -rn "PyQt5" multiprocess_prototype/frontend --include="*.py"` — список
2. Каждое упоминание: `PyQt5` → `PySide6` (и проверить смысл — возможно нужно переформулировать)

**Критерии приёмки:**
- [ ] `grep -rn "PyQt5" multiprocess_prototype/frontend --include="*.py"` = 0

#### Task 2.3 — pytest config

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer

**Файлы:** `pyproject.toml` (корень Inspector_bottles)

**Шаги:**
1. Добавить в `[tool.pytest.ini_options]`:
   ```
   qt_api = "pyside6"
   testpaths = [
       ...,  # существующие
       "multiprocess_prototype/tests",
   ]
   ```
2. Установить `pytest-qt` если ещё нет: `uv add --dev pytest-qt` (или эквивалент)
3. Прогнать `pytest` без аргументов — все тесты должны коллектиться

**Критерии приёмки:**
- [ ] `pytest` без аргументов собирает v3-тесты
- [ ] Warning «Unknown config option: qt_api» исчезает
- [ ] Не хуже baseline по passed/failed

---

### Phase B — Решение по `App/` (требует обсуждения с пользователем)

#### Task 2.4 — Status-аудит `App/`

**Уровень:** Senior (Opus)
**Исполнитель:** teamlead
**Цель:** Зафиксировать решение по `App/` — удалить, архивировать, или мигрировать.

**Шаги:**
1. Прочитать `App/main_app.py` и `App/__init__.py` — какова роль приложения
2. Прочитать `App/docs/README.md` (если есть)
3. Проверить git history — когда последний раз менялось содержимое `App/`
4. Проверить нет ли скрытых пользователей (через `App/UI/Components/<X>` без префикса `App.`)
5. Сформулировать **рекомендацию пользователю** в `App/STATUS.md` — три варианта (delete / archive / migrate) с pros/cons

**Критерии приёмки:**
- [ ] `App/STATUS.md` создан с рекомендацией
- [ ] Решение принято пользователем

#### Task 2.5 — Реализация выбранного решения по `App/`

**Уровень:** зависит от решения
**Исполнитель:** developer (delete/archive) или teamlead (migrate)

**Сценарии:**
- **Delete:** `git rm -r App/` + чистка ссылок в README/CLAUDE.md (если есть)
- **Archive:** `git mv App/ _archive/App/` (на уровне )
- **Migrate:** отдельный план, не в этой фазе

---

### Phase C — Closing the loop по widgets-reorg (5-7 часов суммарно)

#### Task 2.6 — Перенос плана в `docs/refactors/`

**Уровень:** Junior (Haiku)
**Исполнитель:** docs-writer

**Шаги:**
1. `mkdir -p docs/refactors`
2. `git mv multiprocess_prototype/plans/widgets_reorganization.md docs/refactors/2026-04_widgets_reorg.md`
3. То же для этого плана (когда будет завершён): `widgets_phase2_pyside6_cleanup.md` → `docs/refactors/2026-04_widgets_phase2.md`
4. Добавить header «STATUS: COMPLETED 2026-04-27» в перенесённые файлы

**Критерии приёмки:**
- [ ] `multiprocess_prototype/plans/` пуст или содержит только активные планы
- [ ] `docs/refactors/` содержит исторические планы

#### Task 2.7 — Обновить CLAUDE.md проекта

**Уровень:** Middle (Sonnet)
**Исполнитель:** docs-writer

**Файлы:** `projects/Inspector_bottles/CLAUDE.md`

**Шаги:**
1. Добавить в раздел «Архитектура» подраздел про `frontend/widgets/` структуру (домены)
2. Сослаться на `docs/refactors/2026-04_widgets_reorg.md`
3. Обновить упоминания «PyQt5 → PySide6 (Phase 2)» — теперь Phase 2 завершена

**Критерии приёмки:**
- [ ] CLAUDE.md описывает текущую структуру widgets/
- [ ] Phase-status PySide6 актуален

#### Task 2.8 — `_base/` → `base/`

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer

**Шаги:**
1. `git mv frontend/widgets/_base frontend/widgets/base`
2. Поиск и замена `from .._base` → `from ..base`, `from ..._base` → `from ...base` (через grep + sed или Edit)
3. Финальный grep: `grep -rn "_base" widgets/` = 0
4. Smoke-test

**Критерии приёмки:**
- [ ] `_base/` отсутствует, `base/` на месте
- [ ] Все sibling-импорты обновлены
- [ ] pytest не хуже

#### Task 2.9 — Доменные `__init__.py` с lazy реэкспортами

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Внешние импорты `from ..chrome import AppHeaderWidget` вместо `from ..chrome.app_header import AppHeaderWidget`.

**Файлы:**
- `chrome/__init__.py` — реэкспорты `AppHeaderWidget`, `CollapsibleSidePanel`, `WatchdogOverlay`, `RecordingIndicator`, `ViewModeToggle`, `SearchFilterBar`, `apply_filter`
- `sources/__init__.py` — `SimWebcamWidget`, `HikvisionCameraMvpWidget`, `DisplayWindow`
- `recipes/__init__.py` — `RegisterRecipePanelWidget`, `AppRecipePanelWidget`, `SettingsProfilePanelWidget`, `RecipesSlotButtonsPanel`
- `processing/__init__.py` — `ProcessingPanelWidget`, `PostProcessingPanelWidget`, `CroppedRegionsPanelWidget`
- `settings/__init__.py` — `SettingsContainerWidget`

Использовать lazy `__getattr__` pattern (как в `widgets/__init__.py`), чтобы не тащить Qt в pure-Python тесты.

**Шаги:**
1. Для каждого пакета прочитать его `__init__.py` и собрать список публичных экспортов
2. Создать lazy-стили реэкспорты в группирующем `__init__.py`
3. (Опционально) Обновить внешних импортёров: `from ..chrome.app_header` → `from ..chrome` — но только если становится короче и понятнее. Не делать массово.

**Критерии приёмки:**
- [ ] `from multiprocess_prototype.frontend.widgets.chrome import AppHeaderWidget` работает
- [ ] Тесты не сломаны
- [ ] `import widgets.chrome` без Qt не валится (lazy)

#### Task 2.10 — Решение по `tabs_setting/` (большая задача — обсудить отдельно)

**Уровень:** Senior+ (Opus)
**Исполнитель:** обсуждение → план

**Цель:** Устранить дубликат «домен ↔ tabs_setting/X_tab/».

**Подход:** написать ADR в `multiprocess_framework/DECISIONS.md` с тремя вариантами:
- (A) Затянуть `tabs_setting/X_tab/` в соответствующий домен
- (B) Переименовать `tabs_setting/` → `tabs_registry/` + минимизировать содержимое
- (C) Оставить как есть (зафиксировать как осознанный выбор)

Решение пользователя → отдельный план реорганизации.

---

### Phase D — Опционально (если будет время)

#### Task 2.11 — Расщепление виджетов на `core/`+`qt/`

Подготовка к переходу на pure-Python тесты для всех presenters. Большая фаза, отдельный план.

#### Task 2.12 — Решение по `backend` импорту в `display_router.py`

`from backend.routing...` падает. Понять, чей это backend (v3 или старый prototype), починить sys.path. Не Qt-задача, но блокирует ручной smoke MainWindow.

---

## Acceptance criteria всей фазы 2

- [ ] `grep -rn "PyQt5" multiprocess_prototype --include="*.py"` = 0
- [ ] `pytest` без аргументов собирает v3-тесты, baseline по passed/failed сохранён
- [ ] `pytest-qt` warning исчезает
- [ ] Решение по `App/` принято и реализовано
- [ ] CLAUDE.md актуален
- [ ] План `widgets_reorganization.md` перенесён в `docs/refactors/`
- [ ] `_base/` переименован в `base/`
- [ ] Доменные `__init__.py` имеют lazy реэкспорты

---

## Порядок выполнения

```
Phase A (PySide6 cleanup, ~3ч):
  Task 2.1 → Task 2.2 → Task 2.3
Phase B (App/ decision):
  Task 2.4 (аудит) → ОБСУЖДЕНИЕ → Task 2.5 (реализация)
Phase C (closing the loop, ~5ч):
  Task 2.6 → Task 2.7 → Task 2.8 → Task 2.9 → Task 2.10 (только аудит, реализация — отдельная фаза)
```

Параллелизм: Phase A и Phase B независимы, можно идти параллельно. Phase C ждёт Phase A (тесты должны быть в рабочем состоянии перед `_base/` → `base/`).

---

## Риски

1. **Task 2.3 (testpaths v3):** добавление v3-тестов в общий pytest может выявить ранее скрытые регрессии. Mitigation — сначала прогнать pytest на v3 отдельно (как сделано 2026-04-27), зафиксировать baseline.
2. **Task 2.8 (`_base/` → `base/`):** обновление 9+ импортов плюс `_base/__init__.py`. Стандартный риск рефакторинга — sibling-импорты внутри пакетов. Mitigation — используем те же грепы, что в widgets-reorg.
3. **Task 2.9 (lazy реэкспорты):** некорректный lazy может сломать импорт-цикл. Mitigation — копировать pattern из `widgets/__init__.py`, тестировать каждый домен отдельно.
4. **App/ decision:** если App/ окажется нужным — затягивает фазу. Mitigation — зафиксировать как `archive` (минимально-инвазивно), миграция отдельной фазой.

---

## Связанные документы

- Завершённый план: `multiprocess_prototype/plans/widgets_reorganization.md`
- Аудит виджетов: `multiprocess_prototype/docs/widgets_audit.md` (ссылка из коммита `09de52d`)
- Memory: `feedback_worktree_overkill.md` (урок про worktree из widgets-reorg)
