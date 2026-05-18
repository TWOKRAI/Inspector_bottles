---
date: 2026-05-18
topic: tab-template-extraction Phase 3 done, ready for Phase 4
machine: Windows
branch: refactor/tab-template
---

## Session goal

Phase 3 плана `plans/tab-template-extraction/plan.md` — дать инструмент
(`BaseTreeNavTab` + публичный API `DiffScrollTabLayout`) для миграции
SettingsTab в Phase 4. На Phase 3 Settings НЕ мигрируем — все существующие
тесты остаются зелёными.

## Done — Phase 3 закрыта

**Commit `845df32`** — `feat(framework): TabLayoutProtocol + публичный API DiffScrollTabLayout — Phase 3.1`
- `tab_layout_protocol.py` — структурный Protocol для layout-виджетов (set_title, set_action/nav/content_widget, enable_undo_redo, register_inner_scrolls, connect_stack, refresh_after_page_change).
- `DiffScrollTabLayout`:
  - `refresh_after_page_change(role: "content" | "action")` — публичный аналог трюка widgetResizable toggle + update master range.
  - `connect_stack(stack: QStackedWidget, role)` — авто-подписка `currentChanged → refresh`.
  - `set_content_widget()` теперь ставит ChildAdded event filter на content-виджет → автоматически подхватывает вложенные `QScrollArea` при `addWidget` страниц.

**Commit `9974771`** — `feat(forms): RegisterView(show_toggle) — Phase 3.4`
- `RegisterView.__init__(... show_toggle: bool = True)` — отключает встроенный тумблер режима, но `_toggle` объект существует (set_mode работает).
- `SystemSection.__init__`: убран хак `self._register_view._toggle.hide()`, заменён на `show_toggle=False`.

**Commit `547437f`** — `feat(framework): BaseTreeNavTab + nav_tree_utils — Phase 3.2/3.3`
- `base_tree_nav_tab.py` (~270 LOC) — QWidget-каркас. `__init__(*, title, sections, ctx, layout_factory, bus_change_subscriber, parent)`.
  - Сигналы: `section_changed(str)`, `section_dirty_changed(str, bool)`, `section_data_saved(str, dict)`.
  - Hooks для подкласса: `_tree_object_name()`, `_make_presenter()`, `populate()`.
  - Циклом по `list[SectionSpec]` создаёт content/action страницы (lazy=True → откладывает фабрику до активации).
  - `_attach_section()` подписывается на `SectionWithEvents` (dirty/saved/bus) через `isinstance` + `getattr`.
  - `create_lazy_section(key)` — дефолтная фабрика через `SectionSpec`, подкласс может переопределить.
- `nav_tree_utils.py` (~165 LOC) — `build_nav_tree`, `build_nav_tree_from_specs` (поддержка произвольной вложенности), `collapse_other_branches`, `find_tree_item`, `select_tree_key`. Перенесено из prototype/_nav_tree.py.
- `prototype/.../_nav_tree.py` — реэкспорты для backward-compat.

**Commit `9ce2a2b`** — `fix(framework): post-review fixups Phase 3` (после ревью)
- `tab_layout_protocol.py:connect_stack(stack: QStackedWidget)` — точный тип для pyright-strict.
- `test_diff_scroll_tab_layout_public_api.py`: `assert > initial_count` (было `>=` — пропускало бы регрессию автоподхвата).
- `diff_scroll_tab_layout.py`: убрана обманчивая проверка `id(child) not in _redirected` в ChildAdded handler (защита от дублей живёт в `_install_wheel_redirect` по `id(viewport)`, child≠viewport).

**Tests:** 128 settings + 267 framework passed (2 pre-existing failed `test_controls_v2_hooks`) + 18 новых = 18 ✅
- `test_base_tree_nav_tab.py` — 10 pytest-qt тестов (builds_with_two_sections, signal_emits_on_navigation, dirty/data_saved proxied, lazy_creation_on_navigation, bus_change_subscriber, tree_object_name_overridable, no_layout_factory_raises, populate_navigates_to_first)
- `test_register_view_show_toggle.py` — 3 теста (default visible, false hides, set_mode still works)
- `test_diff_scroll_tab_layout_public_api.py` — 5 тестов (refresh_content/action, connect_stack_content/action, set_content_widget_auto_picks_inner_scrolls)

## Key decisions made

- **TabLayoutProtocol** — отдельный модуль `tab_layout_protocol.py`, не внутри `base_tree_nav_tab.py`. Причина: импортируется без Qt-зависимостей BaseTreeNavTab и переиспользуется в type hints концретных табов. Совместимость с DiffScrollTabLayout — структурная (Protocol + runtime_checkable).
- **ChildAdded event filter в set_content_widget** — установлен на сам content-виджет (QStackedWidget). При `addWidget(page)` ChildAdded приходит на reparenting, handler идёт `findChildren(QAbstractScrollArea)` и подключает их к мастер-скроллу. Альтернатива (явный `register_inner_scrolls` снаружи) оставлена как публичный метод для тестов и краевых случаев.
- **nav_tree_utils.py перенесён в framework** — `build_nav_tree_from_specs(specs: list[SectionSpec])` строит дерево с произвольной вложенностью (два прохода: top-level, потом children по parent_key). Старый `build_nav_tree(sections, admin_children)` оставлен в framework для legacy-API Settings, а в prototype `_nav_tree.py` остался как реэкспорт — тесты Settings продолжают импортировать те же символы из старого пути.
- **populate() отдельно от __init__** — `BaseTreeNavTab.__init__` строит UI, `populate()` навигирует к первой top-level секции. Это даёт подклассу (Settings в Phase 4) выполнить дополнительную настройку (подписка на bus) между конструированием и первой навигацией.
- **`_MockLayoutWrapper` в тестах** — QWidget-обёртка вокруг `MagicMock(spec=TabLayoutProtocol)`. Делегирует addWidget/setLayout в реальный QWidget, остальные вызовы — в mock. Без неё `main_layout.addWidget(mock)` падает (mock не QWidget).
- **post-review fixups отдельным коммитом** — три non-blocking замечания ревьюера сведены в `9ce2a2b` (типы Protocol, строгий assert, чистка ChildAdded). #4 (try/except вокруг factory) и #5 (`# type: ignore` на `addWidget(self._layout)`) — намеренно оставлены на Phase 4.

## What did NOT work

- **MagicMock как QWidget** в первой версии тестов `test_base_tree_nav_tab.py` — `main_layout.addWidget(mock)` падает с `TypeError: addWidget(self, w: QWidget): argument 1 has unexpected type 'MagicMock'`. Решение: `_MockLayoutWrapper(QWidget)` который делегирует TabLayoutProtocol-методы в mock через `__getattr__`.
- **`_redirect_nested_wheels` синхронность** — ChildAdded приходит в момент `setParent()`, до завершения конструктора child. В тестах используем `QApplication.processEvents()` после `stack.addWidget(page)`, иначе ассерт `len(_scroll_areas) > initial_count` падает rare-race.
- **`# type: ignore[arg-type]` на `main_layout.addWidget(self._layout)`** — `TabLayoutProtocol` это Protocol, не QWidget; pyright справедливо ругается. Решение в Phase 4: либо добавить наследование `Protocol + QWidget`, либо `cast(QWidget, self._layout)`. Намеренно оставлено как техдолг.

## Next step — Phase 4

**Phase 4 — Миграция SettingsTab → BaseTreeNavTab** (4-6h, Medium-High, Developer + Tester по плану). Конкретно:

1. **4.2** — создать `multiprocess_prototype/frontend/widgets/tabs/settings/_sections.py`:
   `_build_settings_sections(ctx: AppContext) -> list[SectionSpec[AppContext]]`. Описать все 9 секций декларативно:
   - `admin_dashboard` (top-level), `users`/`roles`/`sessions`/`audit_log` (parent_key="admin_dashboard", lazy=True)
   - `system_settings`, `interface_settings`, `appearance`, `history` (top-level)
   - Фабрики: `SystemSection.create_for(ctx)`, `AppearanceSection.create_for(...)` и т.п. — нужно понять, нужны ли им specific параметры (AppearanceSection: theme_manager + presets_manager — придётся обернуть в lambda ctx: AppearanceSection(create_theme_manager(), ThemePresetsManager())).

2. **4.1** — переписать `SettingsTab` как наследника `BaseTreeNavTab`:
   ```python
   class SettingsTab(BaseTreeNavTab):
       settings_saved = Signal(dict)
       dirty_changed = Signal(bool)
       def __init__(self, ctx, parent=None):
           super().__init__(
               title="Настройки",
               sections=_build_settings_sections(ctx),
               ctx=ctx,
               layout_factory=lambda: DiffScrollTabLayout(
                   title="Настройки", action_width=160, nav_width=230),
               bus_change_subscriber=lambda cb: (ctx.action_bus() and ctx.action_bus().add_change_callback(cb)),
               parent=parent)
           self.section_dirty_changed.connect(self._on_section_dirty)
           self.section_data_saved.connect(self._on_section_saved)
           self.populate()
       def _tree_object_name(self) -> str: return "SettingsTreeNav"
   ```

3. **4.3** — удалить из `SettingsTab`:
   - 5 методов `add_*_page()` (admin_dashboard, system_settings, interface_settings, appearance, history) — циклом строит BaseTreeNavTab.
   - `register_action_page()` — в BaseTreeNavTab._attach_section.
   - `set_undo_enabled/set_redo_enabled` — BaseTreeNavTab.enable_undo_redo + presenter подписан на bus.
   - `select_tree_key` — в BaseTreeNavTab.
   - `create_lazy_section` с if/elif — заменить на SectionSpec(lazy=True) с фабриками.
   - `_setup_ui()` — в BaseTreeNavTab.__init__.

4. **4.4** — `SettingsPresenter` оставить тонкой обёрткой над `TreeNavTabPresenter` (override `_make_presenter()` в SettingsTab). populate() уйдёт в base, останется только `on_bus_change`. Цель плана: 98 → <80 LOC.

5. **4.5** — сохранить публичный API `SettingsTab.reload()`, `save()`, `is_dirty()`, `field_editors()`, `view_mode()` — делегация через `self.section("system_settings")`. Пометить `field_editors`/`view_mode` как deprecated (используются только тестами).

6. **4.6 Acceptance:**
   - `settings/tab.py` < 100 LOC (сейчас 434)
   - Все тесты `test_settings_tab.py` (22) + admin (67) зелёные
   - Smoke через qt-mcp: `QT_MCP_PROBE=1 python multiprocess_prototype/run.py`, `qt_snapshot(max_depth=4)` после миграции → сравнить с `baseline-phase2.md` (виджет-дерево должно совпадать).

### Подводные камни Phase 4

- **AppearanceSection требует theme_manager + presets_manager** — фабрика-замыкание: `lambda ctx: AppearanceSection(create_theme_manager(), ThemePresetsManager())`. ctx тут не нужен, но сигнатура `SectionSpec.factory: Callable[[TCtx], SectionProtocol]` — придётся принимать ctx и игнорировать.
- **AdminDashboard.navigate_to сигнал** — текущий `_navigate_to_admin_section` хук в SettingsTab; в Phase 4 это через `section.section_changed` или явная подписка после создания. Либо AdminDashboard реализует `SectionWithEvents` и эмитит свой кастомный сигнал, который SettingsTab перехватывает.
- **HistorySection.presenter.refresh подписка на bus** — `SectionWithEvents.bus_change_callback()` должен вернуть `section.presenter.refresh`. Аналогично для SystemSection (`on_bus_undo_redo_sync`). Проверь — может, нужно сделать обёртку BaseTreeNavTab чтобы подписывать **список** callback-ов на bus, не один.
- **Backward-compat для тестов**: `self._view = section.register_view` (tab.py:218) — в Phase 4 удалить, тесты переписать через `tab.section("system_settings").register_view`. Но это Phase 7.1 по плану. На Phase 4 — оставить как алиас.
- **`# type: ignore[arg-type]` на `addWidget(self._layout)`** — попутно убрать в Phase 4 (см. замечание #5 ревьюера).
- **try/except вокруг factory** в `_attach_section` (замечание #4 ревьюера) — добавить в Phase 4, реальные секции грузят YAML/БД и могут падать.

Стартовать в новом чате командой:

```
Продолжаем plans/tab-template-extraction/plan.md, ветка refactor/tab-template.
Phase 0-3 закрыты (последний коммит 9ce2a2b). Делай Phase 4 через developer +
tester. Цель — SettingsTab(BaseTreeNavTab), tab.py 434→<100 LOC, presenter
98→<80 LOC, все 22 теста test_settings_tab.py + 67 admin зелёные. Baseline UI
для финальной сверки через qt-mcp — plans/tab-template-extraction/baseline-phase2.md.
Подробности и подводные камни — workspace/handoffs/2026-05-18_tab-template-phase3.md
```

## Files changed

**Commits на ветке `refactor/tab-template` (база Phase 2 = 2868dc1):**

```
9ce2a2b fix(framework): post-review fixups Phase 3 — типы Protocol, строгий assert, чистка ChildAdded
547437f feat(framework): BaseTreeNavTab + nav_tree_utils — Phase 3.2/3.3
9974771 feat(forms): RegisterView(show_toggle) — Phase 3.4
845df32 feat(framework): TabLayoutProtocol + публичный API DiffScrollTabLayout — Phase 3.1
```

**Файлы (Phase 3 cumulative):**

Создано:
- `multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layout_protocol.py` (~70 LOC)
- `multiprocess_framework/modules/frontend_module/widgets/tabs/base_tree_nav_tab.py` (~270 LOC)
- `multiprocess_framework/modules/frontend_module/widgets/tabs/nav_tree_utils.py` (~165 LOC)
- `multiprocess_framework/modules/frontend_module/tests/test_base_tree_nav_tab.py` (~330 LOC, 10 тестов)
- `multiprocess_framework/modules/frontend_module/tests/test_register_view_show_toggle.py` (~65 LOC, 3 теста)
- `multiprocess_prototype/frontend/widgets/primitives/tests/test_diff_scroll_tab_layout_public_api.py` (~115 LOC, 5 тестов)

Изменено:
- `multiprocess_prototype/frontend/widgets/primitives/diff_scroll_tab_layout.py` — +refresh_after_page_change, +connect_stack, +ChildAdded eventFilter
- `multiprocess_prototype/frontend/forms/register_view.py` — +show_toggle parameter
- `multiprocess_prototype/frontend/widgets/tabs/settings/system/section.py` — `show_toggle=False` вместо `_toggle.hide()`
- `multiprocess_prototype/frontend/widgets/tabs/settings/_nav_tree.py` — реэкспорт из framework
- `multiprocess_framework/modules/frontend_module/widgets/tabs/__init__.py` — +BaseTreeNavTab, +TabLayoutProtocol
- `plans/tab-template-extraction/plan.md` — чекбоксы 3.1-3.5 [x]
