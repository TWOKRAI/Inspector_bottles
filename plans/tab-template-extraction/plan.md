---
Slug: tab-template-extraction
Дата: 2026-05-18
Статус: DRAFT
Ветка: refactor/tab-template
Автор: Director (Opus)
Baseline: 0775d01 (diff-scroll polish, refactor/frontend-widgets-cleanup)
---

# Рефакторинг шаблона вкладки с tree-навигацией

## Контекст

После закрытия `settings-mvp` (DONE) вкладка Settings получила правильный
MVP-каркас:
- `SectionProtocol` (framework) — единый контракт секции
- `TabPresenterBase` (framework) — общая база презентера
- `CurrentPageStack` (framework) — фикс sizeHint для QStackedWidget
- `DiffScrollTabLayout` (prototype) — UI-скелет с диф-скроллом
- `SettingsTab` + `SettingsPresenter` + `SettingsView` — оркестрация секций

Связка работает, баги диф-скролла зафиксированы baseline-коммитом `0775d01`.

**Но шаблон не готов к переиспользованию для других вкладок (Recipes, ...):**
1. `SettingsTab.add_X_page()` методов — 5 шт., каждый = копипаст
2. `SettingsPresenter.populate()` жёстко знает имена секций Settings
3. `SettingsTab` лезет в `_diff_layout._content_scroll`, `_update_master_range`
   — приватный API чужого виджета
4. `SystemSection` лезет в `RegisterView._toggle.hide()` — то же
5. Tab подписывает callback'и через `presenter.on_settings_saved = lambda` —
   не через сигналы
6. `DiffScrollTabLayout` и `StandardTabLayout` живут параллельно с 60% общего

Без рефакторинга миграция Recipes на «шаблон Settings» = копирование 700+ LOC
с локальными правками.

## Цель

Превратить связку `DiffScrollTabLayout + SettingsTab + SettingsPresenter +
SectionProtocol` в **переиспользуемый шаблон вкладки с tree-навигацией**.
Новая вкладка (например Recipes) = ~50 LOC декларации `SectionSpec` без
копирования tab.py/presenter.py.

## Текущая оценка

| Аспект | Оценка | Комментарий |
|--------|--------|-------------|
| Архитектурный фундамент (MVP, Protocol) | 8/10 | SectionProtocol + TabPresenterBase — правильно |
| Шаблонизируемость | 4/10 | Жёсткая привязка `add_X_page` в presenter |
| Инкапсуляция DiffScrollTabLayout | 5/10 | Settings лезет в `_content_scroll`, `_update_master_range` |
| DRY (vs StandardTabLayout) | 4/10 | Два параллельных шаблона с 60% общего |
| Тестируемость | 7/10 | Pure-Python тесты пресентеров есть |
| Документированность | 8/10 | Хорошие docstrings, ASCII-схемы |
| Совместимость с тестами | 7/10 | `_view = section.register_view` — техдолг |

**Итог:** фундамент здоровый, **шаблонизация недоделана**.

## Конкретные дефекты (с файлами и строками)

### 🔴 Кровотечения инкапсуляции

1. **`settings/tab.py:418-433`** — `_on_content_page_changed` /
   `_on_action_page_changed` лезут в приватные атрибуты
   `_diff_layout._content_scroll`, `_diff_layout._action_scroll`,
   `_diff_layout._update_master_range()`.

2. **`settings/tab.py:160-163, 300-301`** — ручной вызов
   `_diff_layout.register_inner_scrolls(widget)` после каждого `addWidget`.
   Должно происходить автоматически.

3. **`system/section.py:87`** — `self._register_view._toggle.hide()` —
   доступ к приватному полю `RegisterView`.

### 🟡 Жёсткая привязка имён секций

4. **`settings/tab.py:187-260`** — 5 методов
   (`add_admin_dashboard_page`, `add_system_settings_page`,
   `add_interface_settings_page`, `add_appearance_page`, `add_history_page`),
   каждый — импорт + создание + `register_action_page` + `add_content_page` +
   `register_section`. Копипаст для каждой секции.

5. **`settings/presenter.py:29-42, 113-117`** — `_TOP_SECTIONS`,
   `_ADMIN_CHILDREN` зашиты как модульные константы; `populate()` вызывает
   `view.add_system_settings_page()` и т.д. по конкретным именам.

6. **`settings/tab.py:262-301`** — `create_admin_panel()` — `if/elif/elif`
   по строковому ключу с 4 импортами внутри.

### 🟡 Нарушения событийной модели

7. **`settings/tab.py:203-204`** — Tab присваивает атрибуты презентера:
   ```python
   section.presenter.on_settings_saved = lambda data: self.settings_saved.emit(data)
   section.presenter.on_dirty_changed = lambda dirty: self.dirty_changed.emit(dirty)
   ```
   Должно быть через Qt Signal на SectionProtocol.

8. **3 места знают про undo/redo:** `DiffScrollTabLayout.enable_undo_redo`,
   `SettingsPresenter._refresh_undo_redo`, `SettingsTab.set_undo_enabled/set_redo_enabled`.
   Хватило бы одного (Layout уже подписан на bus).

### 🟡 Прочее

9. **`settings/tab.py:142-153`** — view-метод `register_action_page` строит
   QWidget внутри. Должен быть чистой билд-функцией.

10. **`settings/tab.py:218`** — `self._view = section.register_view` для
    backward-compat с тестами (комментарий это явно говорит).

11. **`SettingsTab.field_editors()`, `view_mode()`** — публичные методы для
    тестов, делегируют в `SystemSection`. Техдолг.

## Целевая структура

```
multiprocess_framework/modules/frontend_module/widgets/tabs/
├── section_protocol.py         # ESCALATED: добавить опц. сигналы
├── section_spec.py             # NEW — декларация секции
├── tree_nav_presenter.py       # NEW — обобщённый TreeNavTabPresenter
├── base_columnar_tab.py        # NEW Phase 6b — nav-агностичная база (QWidget)
├── base_tree_nav_tab.py        # REFACTORED Phase 6b — теперь BaseColumnarTab подкласс
├── base_list_nav_tab.py        # NEW Phase 6c — динамический CRUD-список
├── current_page_stack.py       # без изменений
├── mvp_pattern.py              # без изменений
└── tab_layouts/                # NEW каталог (Phase 6a)
    ├── __init__.py
    ├── _abstract_columnar.py   # NEW Phase 6a — nav-агностичная база layout'а
    ├── diff_scroll_layout.py   # MOVED из prototype, инкапсуляция чище
    └── standard_layout.py      # MOVED из prototype

multiprocess_prototype/frontend/widgets/tabs/settings/
├── tab.py                      # 434 → ~80 LOC (декларация SectionSpec)
├── system/                     # без больших изменений
├── appearance/                 # без больших изменений
├── history/                    # без больших изменений
├── administration/             # без больших изменений
└── interface/                  # без больших изменений
```

## Стратегия: 7 фаз

```
Phase 0: Подготовка (baseline + ветка + ADR)
    ↓
Phase 1: SectionSpec + расширение SectionProtocol (сигналы)
    ↓
Phase 2: TreeNavTabPresenter (универсальный, в framework)
    ↓
Phase 3: BaseTreeNavTab (Qt-шаблон + публичный API DiffScrollTabLayout)
    ↓
Phase 4: Миграция SettingsTab → BaseTreeNavTab (green-bar)
    ↓
Phase 5: Разделение section-as-view и presenter (опционально)
    ↓
Phase 6: Унификация DiffScroll/Standard + Recipes pilot
    ↓
Phase 7: Очистка техдолгов + документация
```

---

## Phase 0 — Подготовка

- [x] **0.1** Закоммитить uncommitted полировку диф-скролла → baseline
      (коммит `0775d01` на `refactor/frontend-widgets-cleanup`)
- [x] **0.2** Создать ветку `refactor/tab-template` из baseline
- [x] **0.3** Зафиксировать sentrux baseline:
      `mcp__sentrux__session_start` сохранён — `quality_signal=7183`
      (modularity=5107, acyclicity=10000, depth=6667, equality=6223,
      redundancy=9024). MCP-вариант sentrux не поддерживает именованные
      теги — baseline хранится в текущей сессии sentrux и сравнится
      через `session_end` в Phase 7.3.
- [x] **0.4** ADR в `multiprocess_framework/DECISIONS.md` —
      [ADR-126](../multiprocess_framework/DECISIONS.md#adr-126-шаблон-вкладки-с-tree-навигацией-sectionspec-treenavtabpresenter-basetreenavtab):
      «Шаблон вкладки с tree-навигацией — `SectionSpec` +
      `TreeNavTabPresenter` + `BaseTreeNavTab`». TOC обновлён через
      `python -m scripts.sync`, `scripts/validate.py` зелёный.
- [x] **0.5** План сохранён (`032f6a0`), ADR закоммичен отдельным
      коммитом `docs(adr): ADR-126`.

## Phase 1 — `SectionSpec` + сигналы в `SectionProtocol`

**Цель:** заменить `add_X_page()` методы на декларацию через dataclass.

- [x] **1.1** Создать `framework/.../widgets/tabs/section_spec.py`:
      `@dataclass(frozen=True) SectionSpec[TCtx]` с полями `key`, `title`,
      `factory`, `parent_key=None`, `lazy=False`. Generic-параметр `TCtx`
      позволяет таблу типизировать контекст (например, `SectionSpec[AppContext]`)
      без того, чтобы framework знал о прототипе.
- [x] **1.2** Расширить `section_protocol.py`:
      - Базовый `SectionProtocol` без изменений (все существующие секции
        остаются совместимыми).
      - Новый `SectionWithEvents(Protocol)` — опциональный mixin с
        `section_dirty_changed: SignalInstance | None`,
        `section_data_saved: SignalInstance | None` и
        `bus_change_callback() -> Callable[[], None] | None`. Помечен
        `@runtime_checkable` — `BaseTreeNavTab` проверяет через `isinstance`.
- [x] **1.3** Pure-Python тесты `test_section_spec.py` — 14 тестов
      (импорт без Qt, фасадные реэкспорты, frozen dataclass, иерархия по
      `parent_key`, runtime_checkable проверка, совместимость с
      существующими `SystemSection` / `AppearanceSection` / `HistorySection`).
- [x] **1.4** **Acceptance:**
      - [x] `SectionSpec` импортируется без Qt (зафиксировано тестом
            `test_section_spec_module_imports_without_qt` и
            `test_section_protocol_module_imports_without_qt`).
      - [x] Существующие секции (`SystemSection`, `AppearanceSection`,
            `HistorySection`) продолжают удовлетворять `SectionProtocol`
            (тест `test_existing_settings_sections_satisfy_section_protocol`).
      - [x] Тесты `test_settings_tab.py` (22) и весь `settings/` (128) зелёные.
            Framework `frontend_module/tests/` (236 passed, 2 failed — те же
            `test_controls_v2_hooks.py::test_*_rejected_hook` падали и на
            baseline `0b24bd5`, не связаны с этим PR).

## Phase 2 — `TreeNavTabPresenter`

**Цель:** обобщённый презентер, в который Settings передаёт `list[SectionSpec]`.

- [x] **2.1** Создан `framework/.../widgets/tabs/tree_nav_presenter.py`:
      `TreeNavTabPresenter(TabPresenterBase[TView, TUi])` — pure-Python база
      с реестром секций, ленивыми узлами, навигацией. Не привязан к
      Settings (sections передаются подклассом через `populate()` или
      вызовом `register_section()`). На Phase 2 контракт «sections: list[SectionSpec]»
      не реализован напрямую — он появится в Phase 3 (`BaseTreeNavTab`),
      пока SettingsPresenter использует явные `view.add_X_page()` вызовы.
- [x] **2.2** `SettingsPresenter` теперь наследует `TreeNavTabPresenter`.
      В нём остались только app-specific: константы `_TOP_SECTIONS` /
      `_ADMIN_CHILDREN`, `populate()` через view-методы, `on_bus_change()`
      с доступом к `ctx.action_bus()`. Универсальный код (реестр секций,
      ленивые узлы, навигация) живёт в базе. Алиас `notify_admin_panel_created`
      удалён, `tab.py:create_admin_panel` переименован в `create_lazy_section`.
- [x] **2.3** Pure-Python тесты `test_tree_nav_presenter.py` — 18 тестов
      на фейковом view (без Qt): реестр секций, регистрация content/action
      страниц, переключение через `on_tree_item_changed`, lifecycle
      `on_activated`/`on_deactivated`, навигация, ленивая инициализация
      секций через `create_lazy_section`, robustness при исключениях.
- [x] **2.4** **Acceptance:**
      - [x] `TreeNavTabPresenter` — pure-Python (тест
            `test_tree_nav_presenter_module_imports_without_qt`).
      - [~] `SettingsPresenter` = 98 LOC (было 256, цель плана <80).
            Финальное сжатие до <80 LOC — Phase 4.4 (после миграции на
            `BaseTreeNavTab`, когда `populate()` уйдёт в базу, а константы
            переедут в `settings/_sections.py`).
      - [x] Зелёные тесты: `test_settings_tab.py` (22), весь `settings/` (128),
            новый `test_tree_nav_presenter.py` (18), `test_section_spec.py` (14).

## Phase 3 — `BaseTreeNavTab` + чистый публичный API DiffScrollLayout

**Цель:** превратить `SettingsTab._setup_ui()` в переиспользуемый базовый класс.

- [x] **3.1** Сделать публичный API `DiffScrollTabLayout`:
      - `refresh_after_page_change(stack: QStackedWidget)` (вместо
        `_content_scroll.setWidgetResizable(False/True)` снаружи)
      - `connect_stack(stack: QStackedWidget, role: 'content'|'action')` —
        автоматически вешает `currentChanged → refresh`
      - `register_inner_scrolls` остаётся, но **дополнительно** вызывается
        автоматически на `installEventFilter(ChildAdded)` корневого виджета
        контент-стека
- [x] **3.2** Создать `framework/.../widgets/tabs/base_tree_nav_tab.py`:
      `BaseTreeNavTab(QWidget)` — реализует `TreeNavTabView` Protocol.
      Принимает:
      ```python
      def __init__(self,
                   *,
                   title: str,
                   sections: list[SectionSpec],
                   ctx: AppCtx,
                   layout_factory: Callable[[], _AbstractColumnarTabLayout]
                       = DiffScrollTabLayout,
                   parent: QWidget | None = None) -> None: ...
      ```
      Делает циклом по `sections` всё, что сейчас делают 5
      `add_X_page()` методов.
- [x] **3.3** Сигналы наружу: `section_changed(key: str)`,
      `section_dirty_changed(key: str, dirty: bool)`,
      `section_data_saved(key: str, data: dict)`.
- [x] **3.4** Параметр `show_toggle: bool = True` в `RegisterView.__init__`
      (замена `system/section.py:87` хака с `_toggle.hide()`).
- [x] **3.5** **Acceptance:**
      - [x] `BaseTreeNavTab` не импортирует ничего app-specific
      - [x] Smoke-тест: создать `BaseTreeNavTab` с 2 фейковыми секциями,
            переключение работает

## Phase 4 — Миграция SettingsTab → BaseTreeNavTab

**Цель:** `SettingsTab` = ~80 LOC декларации, всё остальное работает как раньше.

- [x] **4.1** `SettingsTab` теперь наследник `BaseTreeNavTab` (коммит
      `ffa6f92`). `__init__` вызывает `super().__init__()` с
      `build_settings_sections(ctx)` и `_layout_factory`, подключает
      `section_dirty_changed` / `section_data_saved` к локальным слотам
      ретрансляции, после `populate()` подписывает `AdminDashboard.navigate_to`
      → `presenter.navigate_to`.
- [x] **4.2** `multiprocess_prototype/.../settings/_sections.py` создан
      (228 LOC): `build_settings_sections(ctx)` возвращает 9
      `SectionSpec[AppContext]`. Адаптер `_SectionAdapter` оборачивает
      виджеты без полного `SectionProtocol` (`AdminDashboard`,
      `UsersPanel`/`RolesPanel`/`SessionsPanel`/`AuditLogPanel`). Lazy admin
      панели создаются через фабрику spec при первой активации.
- [x] **4.3** Удалены из `SettingsTab`: 5 `add_*_page()` методов,
      `register_action_page`, `add_content_page`, `build_nav_tree`,
      `select_tree_key`, `create_lazy_section`, `set_undo_enabled` /
      `set_redo_enabled`, `_setup_ui` — всё в `BaseTreeNavTab` /
      `TreeNavTabPresenter` или в `_sections.py`. Старый файл
      `settings/_nav_tree.py` сохранён как реэкспорт для тестов admin.
- [x] **4.4** `SettingsPresenter` — 38 LOC (post-review `ce68349`).
      Только `__init__` с `_ctx` ради точки расширения Phase 5.
      `on_bus_change()` удалён в `ce68349` (дублировал
      `DiffScrollTabLayout._refresh_undo_redo`, который подписывается на
      bus сам в `enable_undo_redo()`).
- [x] **4.5** Публичный API сохранён: `reload()`, `save()`, `is_dirty()`,
      `field_editors()`, `view_mode()` — делегируют в
      `presenter.section("system_settings")`. Все 5 методов помечены
      `DeprecationWarning` (post-review `ce68349`), будут удалены в
      Phase 7.1. `tab._view = sys_sec.register_view` сохранён для теста
      `test_view_mode_toggle_persists_to_prefs` — тоже техдолг Phase 7.1.
- [x] **4.6** **Acceptance:**
      - [~] `settings/tab.py` = 114 LOC (target <100; +14 LOC заняты
            deprecation warnings + helper `_warn`/`_sys` — уйдут в Phase 7.1
            вместе с backward-compat блоком; чистая декларация = 65 LOC).
      - [x] `settings/presenter.py` = 38 LOC (<80) ✓
      - [x] Все тесты `test_settings_tab.py` (12 функций, parametrize → 22)
            и settings (128 passed) зелёные.
      - [x] Все admin тесты (67 passed) зелёные.
      - [x] Framework: 267 passed, 2 pre-existing baseline fail
            (`test_controls_v2_hooks::test_*_rejected_hook` — не связаны).
      - [ ] Smoke `python multiprocess_prototype/run.py` через qt-mcp —
            отложено до Phase 5 (или ручной запуск пользователя).

## Phase 5 — Разделение section-as-view и presenter

**Цель:** Section не создаёт presenter в своём __init__ → их можно подменять.
**Статус: DONE** (коммиты `9c59a2a` + `2cc0db7`, 2026-05-18, reviewer APPROVED)

- [x] **5.1** Извлечь `SystemSettingsPresenter` из `SystemSection.__init__`.
      `SectionSpec.presenter_factory: Callable[[TCtx, "SectionProtocol"], object] | None`.
      `BaseTreeNavTab._apply_presenter_factory` вызывается ПЕРЕД
      `_connect_section_events` (порядок критичен для `bus_change_callback`).
      Section получает presenter через `set_presenter()` setter.
- [x] **5.2** То же для `AppearancePresenter`, `HistoryPresenter`. Бонус:
      `AppearanceSection()` теперь без аргументов `theme_manager`/`presets_manager`
      — они создаются в `_appearance_presenter_factory`.
- [x] **5.3** **Acceptance:**
      - [x] Тестам можно подсунуть mock-presenter в Section через
            `SectionSpec(..., presenter_factory=lambda ctx, sec: MockPresenter(...))`.
      - [x] Зелёные тесты Settings (128 passed), framework (267 passed,
            2 pre-existing fail в `test_controls_v2_hooks`).
- [x] **5.4** Post-review fixups (коммит `2cc0db7`):
      - Двойной `_sync_editors_to_cfg` → один вызов в `set_presenter` ДО
        подключения `editor.change_signal` (фикс dirty=True при запуске).
      - `_sync_editors_to_cfg` → публичный `sync_editors_to_cfg` (декаплинг).
      - `presenter_factory` типизирован `Callable[[TCtx, SectionProtocol], object]`.

## Phase 6 — Унификация DiffScroll/Standard + иерархия Tab + Recipes pilot

**Разбита на три независимых PR (6a → 6b → 6c) по итогам recon (2026-05-18, пересмотрено 2026-05-18).**
Причины split и смена 6b/6c: см. раздел «Phase 6 — Recon-заметки» ниже.

---

### Phase 6a — Унификация layout'ов + перенос в framework

**Цель:** добавить `_AbstractColumnarTabLayout` как общую базу,
перенести оба layout'а в `framework/.../widgets/tabs/tab_layouts/`,
обеспечить backward-compat реэкспорт из prototype.

**Уровень: Senior+ (TeamLead, Opus). Отдельный PR.**

- [x] **6a.1** Добавить общую базу `_AbstractColumnarTabLayout(QWidget)` в
      `multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layouts/_abstract_columnar.py`.
      Содержит: action-колонку (top/bottom), `enable_undo_redo`, интерфейсные
      методы `set_content_widget / set_title` (abstract).
      **Ключевое:** `set_nav_widget(widget: QWidget)` принимает произвольный
      виджет — база не знает про конкретный тип nav (QListWidget, QTreeWidget
      или что-либо ещё). Реализации (DiffScroll / Standard) могут уточнять
      тип, но контракт базы — `QWidget`.
      `StandardTabLayout` реализует sub-nav (QListWidget) + QScrollArea;
      `DiffScrollTabLayout` — дифференциальный мастер-скролл + QGroupBox.
- [x] **6a.2** Переместить `DiffScrollTabLayout` →
      `multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layouts/diff_scroll_layout.py`.
      Сохранить все objectName: `DiffScrollActions`, `DiffScrollNavGroup`,
      `DiffScrollNav`, `DiffScrollContent`, `DiffScrollMaster`,
      `DiffScrollUndo`, `DiffScrollRedo`.
- [x] **6a.3** Переместить `StandardTabLayout` →
      `multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layouts/standard_layout.py`.
      Сохранить objectName: `StandardTabActionColumn`, `StandardTabSubNav`,
      `StandardTabScroll`. Добавить реализации методов `set_title`,
      `set_action_widget`, `set_nav_widget`, `register_inner_scrolls`,
      `connect_stack`, `refresh_after_page_change`
      (для полного соответствия `TabLayoutProtocol`).
- [x] **6a.4** Создать
      `multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layouts/__init__.py`
      с реэкспортом `DiffScrollTabLayout`, `StandardTabLayout`,
      `_AbstractColumnarTabLayout`.
- [x] **6a.5** Backward-compat реэкспорт в
      `multiprocess_prototype/frontend/widgets/primitives/__init__.py`:
      удалить прямые импорты из `diff_scroll_tab_layout.py` /
      `standard_tab_layout.py`, добавить импорт из
      `multiprocess_framework.modules.frontend_module.widgets.tabs.tab_layouts`.
      Физические файлы `primitives/diff_scroll_tab_layout.py` и
      `primitives/standard_tab_layout.py` заменить тонкими реэкспортами
      (один import-from + `__all__`), чтобы прямые импорты типа
      `from ...primitives.diff_scroll_tab_layout import DiffScrollTabLayout`
      продолжали работать (это делает `settings/tab.py`).
- [x] **6a.6** Обновить `multiprocess_prototype/frontend/widgets/tabs/settings/tab.py`:
      импорт `DiffScrollTabLayout` остаётся через backward-compat файл
      `primitives/diff_scroll_tab_layout.py` — решение TeamLead: не ломать
      git blame на settings/tab.py ради косметического изменения импорта.
- [x] **6a.7** ADR-127: «DiffScroll vs Standard layout — критерии выбора.
      Размещение в framework. `_AbstractColumnarTabLayout` как nav-агностичная база».
      Добавить в `multiprocess_framework/DECISIONS.md`,
      запустить `python -m scripts.sync`.
- [x] **6a.8** **Acceptance:**
      - [x] `StandardTabLayout` удовлетворяет `TabLayoutProtocol` (runtime check через `isinstance`)
      - [x] `DiffScrollTabLayout` удовлетворяет `TabLayoutProtocol` (runtime check)
      - [x] `_AbstractColumnarTabLayout.set_nav_widget` принимает `QWidget` — тест с mock-виджетом
      - [x] Тесты `test_standard_tab_layout.py` (23 тестов) зелёные
      - [x] Тесты settings (128) зелёные
      - [x] Framework тесты (267) зелёные (+ 2 pre-existing fail)
      - [x] LOC в `primitives/diff_scroll_tab_layout.py` = 3 (только реэкспорт)
      - [x] LOC в `primitives/standard_tab_layout.py` = 3 (только реэкспорт)
      - Коммит: `541009f`

---

### Phase 6b — Рефакторинг иерархии Tab: BaseColumnarTab + BaseTreeNavTab(BaseColumnarTab)

**Цель:** вытащить из `BaseTreeNavTab` nav-агностичный слой `BaseColumnarTab(QWidget)`,
который держит layout + nav-слот + content_stack + сигналы, но не знает про `SectionSpec`.
`BaseTreeNavTab` становится подклассом, добавляющим tree-навигацию по `list[SectionSpec]`.
Settings продолжает работать **без изменений**.

**Уровень: Senior+ (TeamLead, Opus). Отдельный PR. Зависит от 6a.**

- [x] **6b.1** Создать
      `multiprocess_framework/modules/frontend_module/widgets/tabs/base_columnar_tab.py`.

      **Публичный API `BaseColumnarTab(QWidget)`:**
      ```
      __init__(title, ctx, layout_factory=DiffScrollTabLayout, parent=None)
      self._tab_layout          # экземпляр layout'а (TabLayoutProtocol)
      self._content_stack       # QStackedWidget — общий для всех типов nav

      # Абстрактные хуки — подкласс обязан реализовать:
      _build_nav_widget() -> QWidget   # вернуть QTreeWidget / QListWidget / любой QWidget
      _on_nav_changed(key: str) -> None  # реагировать на смену выбора

      # Helpers:
      register_content_widget(key: str, widget: QWidget) -> int  # → index в content_stack
      select_key(key: str) -> None   # переключить content_stack на ключ

      # Сигналы:
      section_changed = Signal(str)   # имя «section» сохранено для backward-compat
      ```
      Базовый `__init__` вызывает `_build_nav_widget()`, передаёт результат в
      `self._tab_layout.set_nav_widget(...)`, строит `QVBoxLayout(self)`.

- [x] **6b.2** Переписать `BaseTreeNavTab` как подкласс `BaseColumnarTab`:
      - `__init__(*, title, sections: list[SectionSpec], ctx, layout_factory, ...)` —
        передаёт `title, ctx, layout_factory` в `super().__init__`, сохраняет `sections`.
      - `_build_nav_widget()` → строит и возвращает `QTreeWidget`, заполняет по `SectionSpec`
        через `build_nav_tree_from_specs`.
      - `_on_nav_changed(key)` → находит `SectionSpec`, инициализирует через factory,
        регистрирует в `content_stack`, вызывает `presenter_factory`.
      - `_attach_section`, `_apply_presenter_factory`, `_connect_section_events`,
        `create_lazy_section`, `populate` — всё SectionSpec-related остаётся здесь.
      - `TreeNavTabPresenter` остаётся без изменений (он — деталь `BaseTreeNavTab`).

- [x] **6b.3** Обновить
      `multiprocess_framework/modules/frontend_module/widgets/tabs/__init__.py`:
      добавить реэкспорт `BaseColumnarTab` рядом с `BaseTreeNavTab`.

- [x] **6b.4** Тест `test_base_columnar_tab.py` в
      `multiprocess_framework/modules/frontend_module/tests/`:
      - Конкретная минимальная реализация `_ConcreteColumnarTab(_build_nav_widget → QLabel,
        _on_nav_changed → записать вызов)`.
      - Тест: `register_content_widget` добавляет виджет в стек.
      - Тест: `select_key` переключает индекс стека.
      - Тест: `section_changed` эмитится при вызове `_on_nav_changed` через слот.
      - Тест: `layout_factory=None` → `RuntimeError` (унаследованное поведение).

- [x] **6b.5** **Acceptance:**
      - [x] `SettingsTab` (наследует `BaseTreeNavTab(BaseColumnarTab)`) — 128 тестов зелёные
      - [x] Settings (128 тестов) зелёные — **нет регресса**
      - [x] Framework тесты (2746 passed, 1 pre-existing perf fail) зелёные
      - [x] `BaseColumnarTab` импортируется из framework без app-specific зависимостей
      - [x] `issubclass(BaseTreeNavTab, BaseColumnarTab)` == `True`
      - [x] `BaseColumnarTab` не импортирует `SectionSpec`, `SectionProtocol`, `TreeNavTabPresenter`
      - Коммит: `684bdb9`

---

### Phase 6c — BaseListNavTab + Recipes pilot

**Цель:** новый `BaseListNavTab(BaseColumnarTab)` для динамических CRUD-навигаций.
Реализован в framework. `RecipesTab` переписан как pilot-consumer.

**Уровень: Senior+ (TeamLead, Opus). Отдельный PR. Зависит от 6b.**

---

#### Phase 6c — Recon (Processes / Plugins / Recipes CRUD API)

*Recon выполнен manager'ом (2026-05-18) на основе прочтения tab.py и tests/ трёх табов.*

**Табы с динамическим nav-списком:**

| Таб | Nav-виджет | Тип nav | Динамика |
|-----|-----------|---------|----------|
| `RecipesTab` | `StandardTabLayout.sub_nav` (QListWidget) | data entities (`RecipeInfo`, slot+name) | CRUD: add/delete (rename через save) |
| `ProcessesTab` | собственный `QListWidget` (без StandardTabLayout) | mix: «Все процессы» (фикс.) + имена процессов | add/delete (через TODO), readonly status |
| `PluginsTab` | `MasterDetailLayout._item_list` (QListWidget) | catalog (read-only list из registry) | нет CRUD — только фильтр+поиск |

**a) Какие CRUD-операции реально нужны:**

- `RecipesTab`: `add_item` (slot "−1" = новый), `remove_item` (delete), rename через save (не отдельная операция).
  Нет: reorder, multi-select, drag-drop.
- `ProcessesTab` (memory: workers/threads CRUD запланирован, сейчас TODO): `add_item`, `remove_item`.
  Фикс-элемент «Все процессы» — нужен параметр `header_item: str | None`.
- `PluginsTab`: CRUD нет — только read-only каталог с фильтрацией. `BaseListNavTab` не применим.

**Вывод по a:** минимум API = `add_item / remove_item / rename_item / select_item`.
Reorder и multi-select не нужны в ближайших consumer'ах — вне scope Phase 6c.

**b) Какие events наружу хочет каждый таб:**

- `RecipesTab`: `item_selected(key)`, `item_added(key)` — для sync форм.
- `ProcessesTab`: `item_selected(key)` — для update_buttons_state; `item_added`, `item_removed` — для sync nav.
- Сигналы базового класса: `item_selected(key: str)`, `item_added(key: str)`,
  `item_removed(key: str)`, `item_renamed(key: str, label: str)`.

**c) Фиксированные слоты vs неограниченный список:**

- `RecipesTab`: слоты 0..N + псевдослот −1 (новый рецепт). Семантически ограниченный набор слотов,
  но не фиксированное число. Слот −1 — это не настоящий item, а команда «создать».
- `ProcessesTab`: неограниченный список имён процессов.
- Параметр `max_items` не нужен — ограничение — ответственность Presenter'а.
  `BaseListNavTab` параметра `max_items` не добавляет.

**d) Кто отвечает за persistence:**

- `RecipesPresenter` управляет `_recipes_dir` и файлами — уже так.
- `ProcessesPresenter` управляет списком процессов через ctx.
- Шаблон `BaseListNavTab` **не знает про persistence** — только отображает items и эмитит события.
  Presenter вызывает `tab.add_item / remove_item` напрямую после своих операций.

**e) Иконка/badge возле item:**

- `RecipesTab`: нет.
- `ProcessesTab`: статус процесса (running/stopped) — желательна цветная точка или иконка.
  Но сейчас в `ProcessesTab` это не реализовано (TODO).
- `PluginsTab` (если переедет): enabled/disabled badge.
- Решение: `add_item(key, label, icon: QIcon | None = None)` — опциональная иконка.
  Реализация через `QListWidgetItem.setIcon`. Субкласс может переопределять `_make_nav_item`.

---

#### Tasks

- [ ] **6c.1** Дизайн API `BaseListNavTab` на основе recon — зафиксировать
      в docstring файла перед реализацией. TeamLead уточняет API если recon
      выявил отклонения.

      **Baseline API (может корректироваться TeamLead):**
      ```
      BaseListNavTab(BaseColumnarTab)
        __init__(*, title, ctx, layout_factory=StandardTabLayout, parent=None)

        # CRUD — вызывает Presenter после своих операций:
        add_item(key: str, label: str, icon: QIcon | None = None) -> None
        remove_item(key: str) -> None
        rename_item(key: str, label: str) -> None
        select_item(key: str) -> None

        # Хук для кастомизации item-виджета в content_stack:
        _create_item_widget(key: str) -> QWidget   # подкласс переопределяет

        # Опциональный хук для кастомного QListWidgetItem:
        _make_nav_item(key: str, label: str, icon: QIcon | None) -> QListWidgetItem

        # Сигналы:
        item_selected  = Signal(str)    # key
        item_added     = Signal(str)    # key
        item_removed   = Signal(str)    # key
        item_renamed   = Signal(str, str)  # key, new_label
      ```

      `_build_nav_widget()` → возвращает `QListWidget`.
      `_on_nav_changed(key)` → эмитит `item_selected`, переключает `content_stack`.
      `section_changed` (унаследован) алиасит `item_selected` для backward-compat.

- [ ] **6c.2** Реализовать `BaseListNavTab(BaseColumnarTab)` в файле
      `multiprocess_framework/modules/frontend_module/widgets/tabs/base_list_nav_tab.py`.
      Добавить реэкспорт в
      `multiprocess_framework/modules/frontend_module/widgets/tabs/__init__.py`.

- [ ] **6c.3** Переписать
      `multiprocess_prototype/frontend/widgets/tabs/recipes/tab.py` как
      `RecipesTab(BaseListNavTab)`.

      **Требования к результату:**
      - `recipes/tab.py` ≤ 100 LOC.
      - `RecipesTab.__init__` передаёт `layout_factory=StandardTabLayout`.
      - Переопределяет `_create_item_widget(key)` — возвращает form-виджет
        (группа «Информация о рецепте»: name_edit, desc_edit, labels).
      - `ViewModeToggle` (Cards/Table) остаётся локально в `RecipesTab` —
        это не часть шаблона (Recipes-специфика).
      - Presenter (`RecipesPresenter`) вызывает `tab.add_item / remove_item`
        через callback — persistence остаётся в Presenter.
      - Legacy-атрибуты `_on_slot_selected`, `_sync_slots` — удалить.
        Тесты переписать через новый API.

- [ ] **6c.4** Тесты:
      - `multiprocess_framework/modules/frontend_module/tests/test_base_list_nav_tab.py` —
        pure-Python (без Qt по максимуму, mock QListWidget):
        CRUD контракт (`add_item` → item в списке, `remove_item` → удалён),
        сигналы (`item_selected` эмитится), `_on_nav_changed` вызывается.
      - `multiprocess_prototype/frontend/widgets/tabs/recipes/tests/test_recipes_tab.py` —
        переписать `TestRecipesTab` через новый паттерн
        (убрать `_on_slot_selected`, `_sync_slots`, прямой `_presenter._recipes_dir`).

- [ ] **6c.5** **Acceptance:**
      - [ ] `BaseListNavTab` импортируется без app-specific зависимостей:
            `from multiprocess_framework.modules.frontend_module.widgets.tabs import BaseListNavTab`
      - [ ] `recipes/tab.py` ≤ 100 LOC
      - [ ] `test_recipes_tab.py` — все тесты зелёные (3 класса TestRecipeIO, TestRecipesPresenter, TestRecipesTab)
      - [ ] `test_base_list_nav_tab.py` — все тесты зелёные
      - [ ] Settings (128) + framework (267) тесты зелёные (нет регресса)
      - [ ] LOC delta: `base_list_nav_tab.py` ~120 LOC + `_create_item_widget` в RecipesTab
            вместо 303 LOC старого `tab.py`

---

## Phase 6 — Recon-заметки (2026-05-18, пересмотрено 2026-05-18)

### Findings из первоначального recon

**a) Recipes — list-CRUD, не tree-навигация.**

`RecipesTab` использует `StandardTabLayout(show_sub_nav=True)` в режиме
«external-content»: sub-nav — `QListWidget` с динамическими рецептами
(пользователь добавляет/удаляет через CRUD), контент — единый
`QStackedWidget{Cards, Table}`. Рецепты — data entities (`RecipeInfo`
со `slot`, `name`, `created`), не UI-секции. `SectionSpec`/`SectionProtocol`
неприменимы: у рецепта нет `action_buttons()`, нет `on_activated()`,
нет `presenter_factory`.

**b) `BaseTreeNavTab` не применим к Recipes напрямую.**

`BaseTreeNavTab.__init__` ожидает `list[SectionSpec]` — статичную
декларацию UI-секций, строит `QTreeWidget` с постоянными узлами.

**c) Overlap DiffScroll / Standard: ~40%, не 60%.**

`DiffScrollTabLayout` (463 LOC): дифференциальный скролл (мастер-скроллбар,
delta-sync, wheel redirect, eventFilter) — ~200 LOC специфичного кода.
`StandardTabLayout` (376 LOC): QScrollArea одиночный, QListWidget sub-nav,
external-content режим.

Общий код: enable_undo_redo (~40 LOC), action-колонка top/bottom (~60 LOC),
`_make_button` + `action_triggered` (~25 LOC). Итого ~125 LOC overlap.
Реальная общая база `_AbstractColumnarTabLayout` = ~100-120 LOC.

**d) Impactful imports — 3 файла.**

Прямые импорты layout'ов из prototype:
1. `settings/tab.py:12` → `from ...primitives.diff_scroll_tab_layout import DiffScrollTabLayout`
2. `recipes/tab.py:33` → `from ...primitives import StandardTabLayout`
3. `primitives/tests/test_standard_tab_layout.py:8` → `from ...primitives import StandardTabLayout`

После переноса — достаточно backward-compat реэкспортов в двух местах:
- `primitives/diff_scroll_tab_layout.py` (тонкий файл-реэкспорт)
- `primitives/__init__.py` (обновить импорт источника)

**e) `StandardTabLayout` не удовлетворяет `TabLayoutProtocol` сейчас.**

Отсутствуют: `set_title`, `set_action_widget`, `set_nav_widget`,
`register_inner_scrolls`, `connect_stack`, `refresh_after_page_change`.
Это известно из `tab_layout_protocol.py:5-6` (комментарий «любой будущий
StandardTabLayout»). Phase 6a.3 добавляет эти методы.

**f) ViewModeToggle (Cards/Table) — Recipes-специфика, не в шаблон.**

`ViewModeToggle` в `RecipesTab` управляет `QStackedWidget{Cards, Table}`
внутри единого content-виджета. Это паттерн «два вида данных одного
типа», не «дерево секций». В общий шаблон не выносить.

### Пересмотр Director'а: почему BaseListNavTab нужен

Первоначальный вывод «`BaseListNavTab` не нужен» был основан на аргументе
YAGNI — единственный потребитель `RecipesTab`. Этот аргумент некорректен
в контексте данного проекта с явной целью **constructor ethos** (memory:
`feedback_constructor_modularity.md` — «всё должно быть модульным
конструктором: подключаемым, тестируемым, компонуемым блоком»).

**Конкретные будущие consumer'ы `BaseListNavTab` — уже запланированы:**

1. **ProcessesTab** (memory: `project_processes_tab.md`) — workers/threads CRUD
   запланирован как следующая фаза. Сейчас `ProcessesTab` строит свой `QListWidget`
   вручную (tab.py ~580 LOC). Миграция на `BaseListNavTab` сократит до ~150 LOC
   декларации.

2. **PluginManagerTab / SystemTopology Phase 2** (memory:
   `project_system_topology_phase1.md`) — Phase 2 предполагает миграцию tab на
   общий шаблон. Topology nodes — это тоже динамический список.

Аналогия с `BaseTreeNavTab` (Phase 3): тогда тоже был один consumer (`SettingsTab`),
но создали базу, зная что будут другие tree-навигационные табы. Та же логика применима
к `BaseListNavTab`.

**Риск «designed for the second»** митигирован через recon 6c.0 (секция выше):
проверены реальные CRUD API трёх табов, зафиксированы общие операции
(add/remove/rename/select) и события (item_selected/added/removed/renamed),
подтверждено что PluginsTab не нужен (read-only каталог).

### Итоговый split: 6a + 6b + 6c

- **6a** (layout move + абстрактная база) — механическая но рискованная работа
  (QSS objectName, TabLayoutProtocol compliance). Отдельный PR — изолирует риск.
- **6b** (BaseColumnarTab + рефакторинг BaseTreeNavTab) — аккуратный структурный
  рефакторинг без изменения функциональности. Зависит от 6a (layout'ы в framework).
- **6c** (BaseListNavTab + Recipes pilot) — новый API + миграция consumer.
  Зависит от 6b (нужен BaseColumnarTab как база).

**Оценка 6a:** +120 (abstract base) + move ~840 LOC → framework + 2 тонких
реэкспорта = изменение ~10-12 файлов, ~3h TeamLead.
**Оценка 6b:** +200 / -150 LOC — BaseColumnarTab (~130 LOC) + рефакторинг
BaseTreeNavTab (~70 LOC новых хуков, ~150 LOC старого кода переезжает в подкласс),
4-5 файлов, ~3-4h TeamLead.
**Оценка 6c:** +250 / -200 LOC — BaseListNavTab (~120 LOC) + RecipesTab (-200 LOC,
новый ~100 LOC) + тесты (~130 LOC), 6-7 файлов, ~3-4h TeamLead.

## Phase 7 — Очистка техдолгов + документация

- [ ] **7.1** Удалить из `settings/tab.py` техдолги:
      `self._view = section.register_view`, deprecated
      `field_editors()`, `view_mode()`. Тесты переписать через прямой
      доступ к Section через `tab.section(key)`.
- [ ] **7.2** Обновить `docs/refactors/` — финальный отчёт `2026-MM_tab_template.md`.
- [ ] **7.3** `sentrux session_end` → дельта (modularity, depth, acyclicity).
- [ ] **7.4** Обновить `CONSTRUCTOR_BLUEPRINT.md` — новые контракты.
- [ ] **7.5** Закрыть план: статус `DONE`, проставить коммиты.

---

## Обратная совместимость (green-bar constraint)

На **каждой фазе** обязательно:
- Все существующие тесты `test_settings_tab.py` (22) зелёные
- Все admin тесты (67) зелёные
- Все framework-тесты зелёные
- `settings/__init__.py` экспортирует `SettingsTab` с тем же API
- Сигналы `settings_saved`, `dirty_changed` сохраняются
- После Phase 6: тесты `test_recipes_tab.py` зелёные

## Что **точно не** делаем (out of scope)

- Не трогаем `RegisterView` целиком (только параметр `show_toggle`).
- Не трогаем `ActionBus`, `AppContext`.
- Не переписываем admin-панели — они работают.
- Не вводим новые UI-фичи (тематика, layout). Только рефакторинг.
- Не убираем `CurrentPageStack` или диф-скролл — они работают, фикс
  sizeHint остаётся (baseline `0775d01`).

## Риски и митигация

| Риск | Митигация |
|------|-----------|
| Сломать тесты Settings | Green-bar на каждом коммите; pure-Python тесты пресентеров остаются |
| Расхождение sizeHint при `BaseTreeNavTab` | Smoke-тест в Phase 3.5 перед миграцией |
| Перенос `DiffScrollTabLayout` в framework сломает QSS | objectName сохраняем, QSS не трогаем |
| Decoupling section/presenter сломает callback chain | Phase 5 — отдельно, после стабилизации Phase 4 |
| Pilot Recipes покажет неудобство API | Phase 6.3 — pilot ДО массовой миграции |

## Метрики (до → после)

| Метрика | Сейчас | Цель |
|---------|--------|------|
| `settings/tab.py` LOC | 434 | <100 |
| `SettingsPresenter` LOC | 256 | <80 |
| Методы `add_X_page` в tab | 5 | 0 |
| Приватный API DiffScroll, тыкаемый снаружи | 3 атрибута | 0 |
| Параллельные layout-шаблоны | 2 (без общей базы) | 2 (общая база) |
| Recipes на новом шаблоне | — | ДА |
| Новый таб = сколько LOC декларации | ~700 | ~50-80 |

## Оценка трудоёмкости

| Phase | LOC delta | Файлов | Сложность | Уровень | Время |
|-------|-----------|--------|-----------|---------|-------|
| 0 | +ADR | 2-3 | — | Director | 0.5h |
| 1 | +150 / −0 | 2-3 | Low | Developer | 2h |
| 2 | +250 / −180 | 3-4 | Medium | Developer | 4h |
| 3 | +350 / −0 | 2-3 | High | **TeamLead** | 6h |
| 4 | +80 / −400 | 5-6 | Medium-High | Developer + Tester | 4h |
| 5 | +50 / −30 | 3 | Medium | Developer | 2h |
| 6a | +120 / −0 (move ~840) | 10-12 | High | **TeamLead** | 3h |
| 6b | +200 / −150 | 4-5 | High (refactor) | **TeamLead** | 3-4h |
| 6c | +250 / −200 | 6-7 | High | **TeamLead** | 3-4h |
| 7 | −60 | 4 | Low | Developer + Docs | 2h |
| | | | | **Итого** | **~30h** |

**Итого:** ~1450 строк добавится, ~960 удалится. SettingsTab.py:
**434 → ~80 LOC**. Recipes на `BaseListNavTab` после Phase 6c. Основание split 6→6a/6b/6c:
три независимых PR, каждый изолирует риск и может проходить review отдельно.

## Верификация перед закрытием

1. `python -m pytest multiprocess_prototype/frontend/widgets/tabs/settings/ -v`
   — все тесты Settings зелёные
2. `python -m pytest multiprocess_prototype/frontend/widgets/tabs/recipes/ -v`
   — все тесты Recipes зелёные
3. `python -m pytest multiprocess_framework/modules/frontend_module/tests/ -v`
   — все framework-тесты зелёные
4. `make gate` — ruff + mypy + bandit + pytest зелёный
5. `python multiprocess_prototype/run.py` — Settings и Recipes работают
   идентично
6. `sentrux session_end` — modularity не упал, depth не вырос
7. Метрики из таблицы выше достигнуты
