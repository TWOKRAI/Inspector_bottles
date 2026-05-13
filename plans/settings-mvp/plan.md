---
Slug: settings-mvp
Дата: 2026-05-13
Статус: IN_PROGRESS
Ветка: refactor/settings-mvp
Автор: Director (Opus)
---

# Рефакторинг Settings Tab → модульная MVP-архитектура

## Context

Вкладка Settings (~3900 LOC, 18 файлов) работает, но имеет архитектурные проблемы:
- **tab.py (749 LOC)** — монолит: навигация, стекинг, history, undo/redo, field sync, save/reset
- **theme_editor_section.py (869 LOC)** — монолит: вся логика тем + UI в одном файле
- **Нет MVP** — логика в слотах виджетов; все другие табы уже на MVP
- Дублирование паттернов в admin-панелях

**Цели:**
1. Модульная структура: каждая подвкладка = папка, ни один файл >400 LOC
2. MVP с использованием **существующих** framework-классов (`TabPresenterBase`, `TabViewProtocol`)
3. Вынос переиспользуемых компонентов в `multiprocess_framework/modules/frontend_module/`
4. Образцовая архитектура для последующего рефакторинга Recipes

## Текущая оценка

| Аспект | Оценка | Комментарий |
|--------|--------|-------------|
| Модульность | 6/10 | Admin хорошо разбита, но tab.py и theme — монолиты |
| MVP | 2/10 | Нет presenter, нет Protocol, логика в view |
| Тестируемость | 5/10 | Есть тесты, но всё через Qt (нет pure-Python тестов) |
| DRY | 6/10 | 15-20% дублирования в admin-панелях |
| Навигация | 5/10 | tab.py надо листать 750 строк чтобы разобраться |

## Что уже есть во фреймворке (ПЕРЕИСПОЛЬЗОВАТЬ, не дублировать)

| Класс | Файл | Что даёт |
|-------|------|----------|
| `TabPresenterBase[TView, TUi]` | `frontend_module/widgets/tabs/mvp_pattern.py` | `_view`, `_rm`, `_ui` хранилище |
| `TabViewProtocol` | там же | Маркер Protocol для view |
| `BaseTab` | `frontend_module/widgets/tabs/tab_widget.py` | `on_tab_selected/deselected` хуки |
| `MvpTabBase` | `frontend_module/widgets/tabs/mvp_facade.py` | MVP lifecycle на базе BaseWidget |
| `BaseWidget[TModel]` | `frontend_module/widgets/base_widget/base_widget.py` | Полный MVP lifecycle |

## Framework vs Prototype split

| Компонент | Куда | Обоснование |
|-----------|------|-------------|
| `_CurrentPageStack` | **framework** `frontend_module/widgets/tabs/` | Чистая layout-утилита, zero app logic |
| `SectionProtocol` | **framework** `frontend_module/widgets/tabs/` | Единый контракт секции для любого таба с навигацией |
| `BaseSectionPresenter` | **framework** `frontend_module/widgets/tabs/` | Расширение `TabPresenterBase` для секций (on_activated/deactivated, action_buttons) |
| `BaseAdminPanel` | **prototype** `settings/administration/` | Зависит от AuthContext — app-specific |
| `DiffScrollTabLayout` | **prototype** (пока) | Имеет TYPE_CHECKING coupling с ActionBus; вынос — future work после устранения |

## Целевая структура

```
settings/
├── __init__.py                      # re-export SettingsTab (без изменений API)
├── tab.py                           # ~200 LOC — тонкая оболочка: layout + делегация presenter
├── presenter.py                     # ~150 LOC — навигация, реестр секций, undo/redo координация
├── view.py                          # ~40 LOC — SettingsView Protocol (extends TabViewProtocol)
├── _nav_tree.py                     # ~80 LOC — tree helpers (из tab.py), _CurrentPageStack → re-export из framework
├── yaml_io.py                       # без изменений (98 LOC)
│
├── system/                          # «Настройки системы»
│   ├── __init__.py
│   ├── section.py                   # ~150 LOC — QWidget, обёртка RegisterView
│   ├── presenter.py                 # ~180 LOC — load/save/validate/dirty/field sync
│   └── view.py                      # ~30 LOC — SystemSettingsView Protocol
│
├── interface/                       # «Настройка интерфейса»
│   ├── __init__.py
│   └── section.py                   # ~81 LOC (перенос, без MVP — слишком прост)
│
├── appearance/                      # «Оформление» (разбивка 869-LOC монолита)
│   ├── __init__.py
│   ├── section.py                   # ~120 LOC — контейнер, компоновка виджетов
│   ├── presenter.py                 # ~200 LOC — CRUD тем, логика редактирования
│   ├── view.py                      # ~40 LOC — AppearanceView Protocol
│   ├── themes_table.py              # ~150 LOC — таблица тем (QTableWidget)
│   ├── vars_editor.py               # ~250 LOC — TreeNav + таблица переменных
│   └── inline_color_editor.py       # ~100 LOC — inline color dialog с API open/close/signal
│
├── history/                         # «История» (извлечение из tab.py)
│   ├── __init__.py
│   ├── section.py                   # ~120 LOC — QWidget: таблица + кнопки
│   ├── presenter.py                 # ~150 LOC — bus queries, CSV export, undo/redo
│   └── view.py                      # ~30 LOC — HistoryView Protocol
│
├── administration/                  # «Администрация» (DRY + минимальные изменения)
│   ├── __init__.py
│   ├── _base_panel.py               # NEW ~120 LOC — BaseAdminPanel (table/header/permissions)
│   ├── section.py                   # без изменений (158 LOC)
│   ├── dashboard.py                 # без изменений (132 LOC)
│   ├── users_panel.py               # рефакторинг на BaseAdminPanel (~340 LOC)
│   ├── user_form.py                 # без изменений (186 LOC)
│   ├── roles_panel.py               # рефакторинг на BaseAdminPanel (~220 LOC)
│   ├── permission_matrix.py         # без изменений (289 LOC)
│   ├── sessions_panel.py            # рефакторинг на BaseAdminPanel (~120 LOC)
│   ├── audit_log_panel.py           # рефакторинг на BaseAdminPanel (~380 LOC)
│   ├── _formatters.py               # без изменений (53 LOC)
│   └── tests/                       # обновление импортов
│
└── tests/
    ├── test_settings_tab.py         # обновление импортов, green-bar constraint
    ├── test_yaml_io.py              # без изменений
    ├── test_system_presenter.py     # NEW — pure-Python тесты
    ├── test_appearance_presenter.py  # NEW — pure-Python тесты
    └── test_history_presenter.py    # NEW — pure-Python тесты
```

## Правило: Framework vs Prototype — best-of-both

При переносе компонента в framework (или переиспользовании существующего framework-класса):
1. **Сравнить** реализацию в prototype и framework
2. Если prototype-версия **лучше** (удобнее API, чище код, больше edge-cases) — взять лучшее из обоих
3. Результат сохранить **во framework** (единый источник правды)
4. Prototype переключить на import из framework

Это касается: `_CurrentPageStack`, `TabPresenterBase`, `BaseTab`, и любых виджетов/утилит, которые дублируются.

## Ключевые архитектурные решения

### 1. SectionProtocol — единый контракт секции (→ framework)

```python
# frontend_module/widgets/tabs/section_protocol.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class SectionProtocol(Protocol):
    """Контракт секции для вкладок с tree-навигацией."""
    @property
    def key(self) -> str: ...
    @property 
    def title(self) -> str: ...
    def widget(self) -> QWidget: ...
    def action_buttons(self) -> list[QWidget]: ...
    def on_activated(self) -> None: ...
    def on_deactivated(self) -> None: ...
```

Это устраняет `hasattr(panel, "action_buttons")` и позволяет SettingsPresenter работать единообразно.

### 2. MVP-паттерн с framework-базой

```python
# Presenter наследует TabPresenterBase из framework
class SystemSettingsPresenter(TabPresenterBase[SystemSettingsView, None]):
    def __init__(self, *, view: SystemSettingsView, rm=None, ui=None): ...
    def save(self) -> bool: ...
    def reload(self) -> None: ...

# View — Protocol расширяющий TabViewProtocol
class SystemSettingsView(TabViewProtocol, Protocol):
    def set_editor_value(self, key: str, value: object) -> None: ...
    def get_editor_values(self) -> dict[str, object]: ...
    def set_dirty(self, dirty: bool) -> None: ...
```

### 3. Appearance: presenter владеет данными, view эмитит события

Presenter владеет `_current_vars` и `_last_saved_vars`. `vars_editor` эмитит `var_changed(name, value)` при каждом изменении. Нет batch `_flush_table_to_vars()`.

### 4. InterfaceSection — без MVP (81 LOC, одна кнопка — overengineering)

### 5. Lazy section loading — все секции создаются при первом переключении

## Фазы реализации

### Phase 0: Framework-контракты + подготовка
- [ ] **0.1** Создать `frontend_module/widgets/tabs/section_protocol.py` — SectionProtocol
- [ ] **0.2** Перенести `_CurrentPageStack` → `frontend_module/widgets/tabs/current_page_stack.py`
- [ ] **0.3** Создать `administration/_base_panel.py` — BaseAdminPanel (в prototype)
- [ ] **0.4** Прогнать все тесты — green baseline
- **Коммит**: `refactor(framework): SectionProtocol + CurrentPageStack в frontend_module`

### Phase 1: Top-level SettingsPresenter ПЕРВЫМ (по рекомендации ревьюера)

> Ревьюер [MAJOR]: «SettingsPresenter нужно делать первым — иначе каждая следующая фаза меняет tab.py как промежуточный шаг, а потом Phase 4 снова перестраивает»

- [ ] **1.1** Создать `settings/view.py` — SettingsView Protocol
- [ ] **1.2** Создать `settings/presenter.py` — навигация, реестр SectionProtocol, undo/redo координация
- [ ] **1.3** Извлечь tree helpers → `settings/_nav_tree.py` (re-export CurrentPageStack из framework)
- [ ] **1.4** Рефакторинг `tab.py` → тонкая оболочка, делегация presenter'у
- [ ] **1.5** Green-bar: все 10 тестов `test_settings_tab.py` проходят
- **Коммит**: `refactor(prototype): SettingsPresenter + View Protocol`

### Phase 2: Извлечение History (минимальная связность)
- [ ] **2.1** Создать `history/view.py` — HistoryView Protocol
- [ ] **2.2** Создать `history/presenter.py` — bus queries, CSV export, undo/redo state
- [ ] **2.3** Создать `history/section.py` — таблица + кнопки, implements SectionProtocol
- [ ] **2.4** Зарегистрировать HistorySection через SettingsPresenter
- [ ] **2.5** Тесты: `test_history_presenter.py` + green-bar существующих
- **Коммит**: `refactor(prototype): History секция с MVP`

### Phase 3: Извлечение System Settings
- [ ] **3.1** Создать `system/view.py` — SystemSettingsView Protocol
- [ ] **3.2** Создать `system/presenter.py` — load/save/validate/dirty/field sync
- [ ] **3.3** Создать `system/section.py` — обёртка RegisterView, implements SectionProtocol
- [ ] **3.4** Зарегистрировать через SettingsPresenter, удалить код из tab.py
- [ ] **3.5** Тесты: `test_system_presenter.py` + green-bar
- **Коммит**: `refactor(prototype): System Settings секция с MVP`

### Phase 4: Разбивка ThemeEditorSection (869 LOC → 6 файлов)
- [ ] **4.1** Создать `appearance/view.py` — AppearanceView Protocol
- [ ] **4.2** Создать `appearance/presenter.py` — CRUD тем, owner `_current_vars`/`_last_saved_vars`
- [ ] **4.3** Создать `appearance/inline_color_editor.py` — API: `open(table, row, color)`, `close()`, `color_changed` signal
- [ ] **4.4** Создать `appearance/themes_table.py` — таблица тем
- [ ] **4.5** Создать `appearance/vars_editor.py` — TreeNav + таблица + var_changed signal
- [ ] **4.6** Создать `appearance/section.py` — компоновка, implements SectionProtocol
- [ ] **4.7** Удалить `theme_editor_section.py`
- [ ] **4.8** Тесты: `test_appearance_presenter.py` + green-bar
- **Коммит**: `refactor(prototype): Appearance секция — разбивка монолита`

### Phase 5: Перенос interface + DRY admin-панелей
- [ ] **5.1** Перенести `interface_section.py` → `interface/section.py` (без MVP)
- [ ] **5.2** Рефакторинг `users_panel.py` → наследование BaseAdminPanel
- [ ] **5.3** Рефакторинг `sessions_panel.py` → наследование BaseAdminPanel
- [ ] **5.4** Рефакторинг `audit_log_panel.py` → наследование BaseAdminPanel
- [ ] **5.5** Green-bar всех admin тестов
- **Коммит**: `refactor(prototype): DRY admin-панелей через BaseAdminPanel`

### Phase 6: Финализация
- [ ] **6.1** Обновить все `__init__.py`
- [ ] **6.2** Полный прогон тестов + проверка запуска `run.py`
- [ ] **6.3** Финальный коммит

## Обратная совместимость (green-bar constraint)

На **каждой фазе** обязательно:
- Все существующие тесты `test_settings_tab.py` проходят зелёным
- Все admin тесты проходят
- `settings/__init__.py` экспортирует `SettingsTab` с тем же API
- Конструктор `(ctx: AppContext, parent=None)` и `create(ctx)` — без изменений
- Сигналы: `settings_saved`, `dirty_changed` — без изменений

## Верификация

1. **Тесты:** `python -m pytest multiprocess_prototype/frontend/widgets/tabs/settings/tests/ -v`
2. **Admin тесты:** `python -m pytest multiprocess_prototype/frontend/widgets/tabs/settings/administration/tests/ -v`
3. **Framework тесты:** `python -m pytest multiprocess_framework/modules/frontend_module/tests/ -v`
4. **Запуск прототипа:** `python multiprocess_prototype/run.py` — Settings открывается, навигация работает
5. **Проверка LOC:** ни один файл не превышает 400 LOC
6. **Проверка MVP:** каждый presenter импортируется без Qt

## Ожидаемый результат

| Метрика | До | После |
|---------|-----|-------|
| Макс. файл | 869 LOC | <400 LOC |
| MVP coverage | 0 секций | 4 секции (settings, system, appearance, history) |
| Pure-Python тесты | 0 | ~280 LOC (3 файла) |
| Файлов | 18 | ~30 (каждый сфокусирован) |
| tab.py | 749 LOC | ~200 LOC |
| Дублирование admin | 15-20% | <5% |
| Framework контракты | 0 section-level | +2 (SectionProtocol, CurrentPageStack) |

## Учтённые замечания ревьюера

| # | Severity | Замечание | Решение |
|---|----------|-----------|---------|
| 1 | CRITICAL | Framework split не определён | Phase 0 — SectionProtocol + CurrentPageStack в framework |
| 2 | MAJOR | SettingsPresenter должен быть Phase 1 | Переставлен — Phase 1 |
| 3 | MAJOR | Нет SectionProtocol | Добавлен в Phase 0 как framework-контракт |
| 4 | MAJOR | color_editor API | Переименован в `inline_color_editor.py`, API: open/close/signal |
| 5 | MAJOR | _flush_table_to_vars sync | Presenter владеет данными, vars_editor эмитит var_changed |
| 6 | MINOR | DiffScrollTabLayout coupling | Зафиксировано как future work |
| 7 | MINOR | Phase 5 не конкретна | Уточнена: CRUD vs read-only — разные подклассы BaseAdminPanel |
| 8 | MINOR | Green-bar constraint | Добавлен на каждой фазе |
| 9 | SUGGESTION | Lazy section loading | Принято — все секции лениво |
| 10 | SUGGESTION | Interface не нуждается в MVP | Принято — только перенос в папку |
| 11 | SUGGESTION | ADR отсутствует | Зафиксировать в DECISIONS.md при первом коммите |
