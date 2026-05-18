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
├── base_tree_nav_tab.py        # NEW — QWidget-шаблон + view
├── current_page_stack.py       # без изменений
├── mvp_pattern.py              # без изменений
└── tab_layouts/                # NEW каталог
    ├── __init__.py
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
- [ ] **3.2** Создать `framework/.../widgets/tabs/base_tree_nav_tab.py`:
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
- [ ] **3.3** Сигналы наружу: `section_changed(key: str)`,
      `section_dirty_changed(key: str, dirty: bool)`,
      `section_data_saved(key: str, data: dict)`.
- [ ] **3.4** Параметр `show_toggle: bool = True` в `RegisterView.__init__`
      (замена `system/section.py:87` хака с `_toggle.hide()`).
- [ ] **3.5** **Acceptance:**
      - [ ] `BaseTreeNavTab` не импортирует ничего app-specific
      - [ ] Smoke-тест: создать `BaseTreeNavTab` с 2 фейковыми секциями,
            переключение работает

## Phase 4 — Миграция SettingsTab → BaseTreeNavTab

**Цель:** `SettingsTab` = ~80 LOC декларации, всё остальное работает как раньше.

- [ ] **4.1** Переписать `SettingsTab` как наследника `BaseTreeNavTab`:
      ```python
      class SettingsTab(BaseTreeNavTab):
          settings_saved = Signal(dict)
          dirty_changed = Signal(bool)

          def __init__(self, ctx: AppContext, parent=None):
              super().__init__(
                  title="Настройки",
                  sections=_build_settings_sections(ctx),
                  ctx=ctx,
                  layout_factory=DiffScrollTabLayout,
                  parent=parent,
              )
              # проброс сигналов из system_settings в публичные сигналы таба
              self.section_dirty_changed.connect(self._on_section_dirty)
              self.section_data_saved.connect(self._on_section_saved)
      ```
- [ ] **4.2** Вынести `_build_settings_sections(ctx)` в
      `settings/_sections.py` — декларация всех 9 секций как `SectionSpec`.
- [ ] **4.3** Удалить из `SettingsTab` все 5 `add_X_page()` методов,
      `register_action_page()`, `set_undo_enabled/set_redo_enabled`,
      `select_tree_key`, `create_admin_panel` — всё в base class или
      в `_sections.py`.
- [ ] **4.4** Удалить из `SettingsPresenter` — переделать в тонкую обёртку
      над `TreeNavTabPresenter` (если вообще останется отдельным классом).
- [ ] **4.5** Сохранить публичный API `SettingsTab`:
      `reload()`, `save()`, `is_dirty()`, `field_editors()`, `view_mode()`
      — для backward-compat (но пометить как deprecated).
- [ ] **4.6** **Acceptance:**
      - [ ] `settings/tab.py` < 100 LOC
      - [ ] Все тесты `test_settings_tab.py` зелёные
      - [ ] Все admin тесты (67) зелёные
      - [ ] Smoke: `python multiprocess_prototype/run.py` — Settings
            работает идентично

## Phase 5 — Разделение section-as-view и presenter

**Цель:** Section не создаёт presenter в своём __init__ → их можно подменять.

- [ ] **5.1** Извлечь `SystemSettingsPresenter` из `SystemSection.__init__`.
      Section возвращает View Protocol-методы; presenter создаётся через
      фабрику в `SectionSpec.factory` или отдельным `SectionSpec.presenter_factory`.
- [ ] **5.2** То же для `AppearancePresenter`, `HistoryPresenter`
      (опционально, для единообразия).
- [ ] **5.3** **Acceptance:**
      - [ ] Тестам можно подсунуть mock-presenter в Section
      - [ ] Зелёные все тесты Settings

## Phase 6 — Унификация DiffScroll/Standard + Recipes pilot

**Цель:** один общий каркас для двух layout-стратегий, pilot Recipes.

- [ ] **6.1** Перенести `DiffScrollTabLayout` + `StandardTabLayout` →
      `framework/.../widgets/tabs/tab_layouts/`. Сохранить objectName
      (QSS не трогаем).
- [ ] **6.2** Выделить общую базу `_AbstractColumnarTabLayout(QWidget)`:
      action-колонка + nav + content + undo/redo. Конкретные классы
      переопределяют:
      - тип скролла (диф vs обычный)
      - тип nav-виджета (по умолчанию None — конкретный таб задаёт)
- [ ] **6.3** **Pilot Recipes:** переписать `RecipesTab` через
      `BaseTreeNavTab` (с `StandardTabLayout` как layout_factory).
      Сравнить LOC: до vs после.
- [ ] **6.4** ADR: «DiffScroll vs Standard layout — критерии выбора».
- [ ] **6.5** **Acceptance:**
      - [ ] Все тесты `test_recipes_tab.py` зелёные
      - [ ] LOC в `recipes/tab.py` уменьшился на ≥30%
      - [ ] Smoke: Recipes работает идентично

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
| 6 | +200 / −300 | 6-7 | High | **TeamLead** | 6h |
| 7 | −60 | 4 | Low | Developer + Docs | 2h |
| | | | | **Итого** | **~26h** |

**Итого:** ~1100 строк добавится, ~970 удалится. SettingsTab.py:
**434 → ~80 LOC**. Recipes готов к миграции «бесплатно» после Phase 6.

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
