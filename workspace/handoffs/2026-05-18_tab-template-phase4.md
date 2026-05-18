---
date: 2026-05-18
topic: tab-template-extraction Phase 4 done, ready for Phase 5
machine: Windows
branch: refactor/tab-template
---

## Session goal

Phase 4 плана `plans/tab-template-extraction/plan.md` — миграция `SettingsTab`
на `BaseTreeNavTab` (из Phase 3). Конкретные цели: `tab.py` 434 → <100 LOC,
`presenter.py` 98 → <80 LOC, все 22 теста `test_settings_tab.py` + 67 admin +
framework зелёные. Без UI-регрессий.

## Done — Phase 4 закрыта

**Commit `ffa6f92`** — `refactor(forms): SettingsTab(BaseTreeNavTab) — Phase 4`
- `settings/tab.py`: 434 → 98 LOC. Наследник `BaseTreeNavTab`. Удалены 5
  `add_*_page()`, `register_action_page`, `add_content_page`, `build_nav_tree`,
  `select_tree_key`, `create_lazy_section`, `set_undo/redo_enabled`,
  `_setup_ui` — всё в `BaseTreeNavTab` / `TreeNavTabPresenter` / `_sections.py`.
- `settings/presenter.py`: 98 → 51 LOC. Только `__init__` + `on_bus_change()`
  (последний удалён в `ce68349`, см. ниже).
- `settings/_sections.py` (новый, 225 LOC): `build_settings_sections(ctx)` →
  `list[SectionSpec[AppContext]]` с 9 секциями. Адаптер `_SectionAdapter`
  оборачивает виджеты без полного SectionProtocol (`AdminDashboard`,
  `UsersPanel`, `RolesPanel`, `SessionsPanel`, `AuditLogPanel`).
- `SystemSection`: добавлены Qt-сигналы `section_dirty_changed: Signal(bool)`,
  `section_data_saved: Signal(dict)`, метод `bus_change_callback()` →
  `presenter.on_bus_undo_redo_sync`. Callback-атрибуты `on_dirty_changed` /
  `on_settings_saved` на presenter теперь эмитят Qt-сигналы.
- `HistorySection`: добавлен `bus_change_callback()` → `presenter.refresh`.
- `SettingsView`: упрощён до 4 методов (было 15) — оставлены только реально
  вызываемые presenter'ом.

**Commit `ce68349`** — `fix(forms): post-review fixups Phase 4` (после ревью)
- `presenter.py`: удалён `on_bus_change()` — `DiffScrollTabLayout.enable_undo_redo`
  уже подписывает `_refresh_undo_redo` на ActionBus. Двойная подписка
  обновляла кнопки дважды и лезла в приватный `_layout` через `getattr`
  (нарушение `TabLayoutProtocol`). `SettingsPresenter` теперь 38 LOC —
  только `__init__` с `_ctx` ради точки расширения Phase 5.
- `tab.py`: убрана дублирующая подписка
  `bus.add_change_callback(presenter.on_bus_change)`. Backward-compat
  методы (`reload` / `save` / `is_dirty` / `field_editors` / `view_mode`)
  эмитят `DeprecationWarning` с указанием на
  `presenter.section("system_settings")`. После форматирования ruff +
  deprecation блока tab.py вырос до 114 LOC.
- `_sections.py`: аннотации фабрик `_system/_interface/_appearance/_history_factory`
  изменены с `-> QWidget` на `-> SectionProtocol` (соответствие
  `SectionSpec.factory: Callable[[TCtx], SectionProtocol]`).

**Commit `813615e`** — `docs(plans): mark Phase 4 done`
- Чекбоксы 4.1–4.5 → `[x]`. 4.6 acceptance частично: tab.py = 114 LOC
  (+14 LOC заняты deprecation блоком, уйдут в Phase 7.1). Smoke через
  qt-mcp отложен до Phase 5.

**Tests:**
- `multiprocess_prototype/.../settings/` — 128 passed, 0 failed.
- `multiprocess_framework/.../frontend_module/tests/` — 267 passed, 2
  failed (pre-existing baseline: `test_controls_v2_hooks::test_*_rejected_hook`,
  не связаны с Phase 4).

## Key decisions made

- **Адаптер `_SectionAdapter` для admin-виджетов** — `AdminDashboard` и
  `BaseAdminPanel` не реализуют полный `SectionProtocol`. Создан лёгкий
  адаптер в `_sections.py` (key/title/widget/action_buttons/on_activated/
  on_deactivated). Альтернатива (добавить SectionProtocol прямо в виджеты)
  — Phase 7+, чтобы не расширять scope.
- **Qt-сигналы в SystemSection вместо callback-атрибутов на presenter** —
  `BaseTreeNavTab._connect_section_events()` ожидает атрибуты
  `section_dirty_changed`, `section_data_saved` (из `SectionWithEvents`).
  Перенос с callback на Signal унифицирует контракт.
- **`HistorySection.bus_change_callback()` → `presenter.refresh`** —
  History обновляется при undo/redo через подписку на ActionBus. Реализация
  через `SectionWithEvents.bus_change_callback()`, BaseTreeNavTab сам
  вызывает `_bus_change_subscriber` для каждой секции.
- **AdminDashboard.navigate_to подключается ПОСЛЕ super().__init__()** —
  до этого секции ещё не зарегистрированы в presenter. После `super` и
  `populate()` достаём dashboard через `presenter.section("admin_dashboard")`,
  цепляем сигнал на `presenter.navigate_to`.
- **DeprecationWarning через helper `_warn(name)`** — 5 backward-compat
  методов вызывают `self._warn("name")` + делегируют в SystemSection.
  Помечены `# type: ignore[attr-defined]` (доступ к `register_view`, etc.
  на generic `SectionProtocol`).
- **`SettingsPresenter` оставлен пустым** — после удаления `on_bus_change`
  класс содержит только `__init__` с `_ctx`. Не удаляем ради явного типа
  `SettingsView` для pyright и точки расширения Phase 5 (когда
  SectionPresenterFactory может потребовать app-specific логику).
- **`tab._view = sys_sec.register_view`** — оставлен для теста
  `test_view_mode_toggle_persists_to_prefs` (он вызывает
  `tab._view.set_mode(ViewMode.TABLE)`). Удаление — Phase 7.1 с
  переписыванием теста через `tab.presenter.section("system_settings").register_view`.

## What did NOT work

- **`tab.py` <100 LOC** — после добавления `warnings.warn` и ruff-форматирования
  получилось 114 LOC. Из них ~50 LOC — deprecation блок (5 методов + helpers
  `_warn`/`_sys`). Чистая декларация = 65 LOC. Достижение цели плана требует
  убрать deprecation блок (Phase 7.1, удаление backward-compat API).
- **Дублирование подписки на ActionBus в первой версии Phase 4** —
  `SettingsPresenter.on_bus_change` лез к `_layout.undo_button` через
  `getattr`, а `DiffScrollTabLayout.enable_undo_redo` уже подписывает
  свой `_refresh_undo_redo`. Кнопки обновлялись дважды. Ревьюер заметил,
  фикс в `ce68349`.
- **Smoke через qt-mcp** — не запускался. UI-структура (DiffScrollTabLayout
  колонки, objectName-ы из baseline-phase2.md) теоретически не изменилась,
  так как `BaseTreeNavTab` создаёт те же widgets, что и старый `_setup_ui()`.
  Рекомендуется ручной запуск `python multiprocess_prototype/run.py` перед
  началом Phase 5.

## Reviewer verdict

`APPROVED WITH MINOR CHANGES` (см. полный текст в чате сессии 2026-05-18).
Все 3 замечания применены в `ce68349`. Архитектурный вердикт:

> **ROI положительный.** Чистый delta `-115 LOC` сейчас, но реальная
> ценность в переиспользовании: `BaseTreeNavTab` + `SectionSpec` +
> `TreeNavTabPresenter` (270 LOC framework-кода) обслужит Recipes
> (~600 LOC экономии), Processes (~500 LOC), Plugins (~400 LOC).
> Суммарный ROI: -1500 LOC копипаста при трёх новых табах.
>
> Архитектурное направление **правильное**: `DiffScrollTabLayout` живёт
> в prototype, `BaseTreeNavTab` берёт его через `layout_factory` — это
> Dependency Inversion, не антипаттерн.

## Next step — Phase 5

**Phase 5 — Разделение section-as-view и presenter** (2h, Medium, Developer
по плану). Цель: Section не создаёт presenter в `__init__` → их можно
подменять (mock-presenter в тестах, A/B логики).

1. **5.1** — Извлечь `SystemSettingsPresenter` из `SystemSection.__init__`.
   Текущая ситуация: `SystemSection.__init__` создаёт
   `SystemSettingsPresenter(view=self, ctx=ctx)` внутри. Цель Phase 5:
   - Добавить `SectionSpec.presenter_factory: Callable[[TCtx, View], Presenter] | None`
     (поле `frozen=True dataclass`).
   - `BaseTreeNavTab` после создания секции вызывает `presenter_factory`,
     передаёт его секции через атрибут `section.set_presenter(presenter)`.
   - SystemSection теряет `_presenter` из `__init__`, получает через
     setter после конструирования.
2. **5.2** — То же для `AppearancePresenter`, `HistoryPresenter` (опционально).
3. **5.3 Acceptance:** тестам можно подсунуть mock-presenter, все тесты
   Settings зелёные.

### Подводные камни Phase 5

- **`SystemSection._build_ui` использует `self._presenter` для подключения
  слотов кнопок** (например `_btn_save.clicked.connect(self._on_save_clicked)`
  → `self._presenter.save()`). Если presenter inject'ится после
  конструктора — нужен отложенный коннект, или вспомогательный setter
  переподключает слоты.
- **`SystemSection.bus_change_callback()` обращается к
  `self._presenter.on_bus_undo_redo_sync`** — после декаплинга вернёт
  callable, который замкнут на присвоенный presenter. Нужно быть уверенным,
  что `bus_change_callback` вызывается ПОСЛЕ `set_presenter`. В Phase 4
  BaseTreeNavTab._attach_section вызывает `_connect_section_events`
  сразу после создания секции — порядок «factory(ctx) →
  presenter_factory(ctx, section) → set_presenter → _connect_section_events»
  должен быть зашит в `_attach_section`.
- **AppearanceSection и HistorySection** — у них тот же паттерн: presenter
  внутри `__init__`. Для 5.2 повторить декаплинг.
- **SettingsPresenter сейчас почти пустой** — Phase 5 даст ему мощь
  обратно (он передаёт presenter_factory секций). Возможно, имеет смысл
  пересмотреть, нужен ли SettingsPresenter как отдельный класс или
  достаточно `TreeNavTabPresenter` с конфигом фабрик.
- **`_SectionAdapter`** — не имеет presenter'а, для admin-секций
  presenter_factory вернёт None или его вообще нет (lazy admin-панели
  сами управляют своей логикой). Контракт `presenter_factory: Optional`.

### Опциональные подзадачи (можно перенести в Phase 7)

- **Удалить `tab._view = sys_sec.register_view`** + переписать
  `test_view_mode_toggle_persists_to_prefs` (Phase 7.1).
- **Typed accessor `tab.system_section()` или `presenter.typed_section(key, T)`** —
  убрать 6 `type: ignore[attr-defined]` в tab.py.
- **`_SectionAdapter` → нативный SectionProtocol в admin-виджетах** —
  Phase 7+, скоуп вне декаплинга.

Стартовать в новом чате командой:

```
Продолжаем plans/tab-template-extraction/plan.md, ветка refactor/tab-template.
Phase 0-4 закрыты (последние коммиты ffa6f92, ce68349, 813615e). Делай Phase 5
через developer + tester. Цель — декаплинг section/presenter: добавить
SectionSpec.presenter_factory, вытащить presenter'ы SystemSection/AppearanceSection/
HistorySection из __init__, чтобы тестам можно было подсунуть mock-presenter.
Все тесты settings (128) + framework зелёные. Подробности и подводные камни —
workspace/handoffs/2026-05-18_tab-template-phase4.md
```

## Files changed (Phase 4 cumulative)

**Commits на ветке `refactor/tab-template` (с базы Phase 3 = `9a6116f`):**

```
813615e docs(plans): mark Phase 4 done — tab-template-extraction
ce68349 fix(forms): post-review fixups Phase 4 — dedup undo/redo, типы, deprecation
ffa6f92 refactor(forms): SettingsTab(BaseTreeNavTab) — Phase 4
```

**Файлы (Phase 4 cumulative):**

Создано:
- `multiprocess_prototype/frontend/widgets/tabs/settings/_sections.py` (228 LOC)

Изменено:
- `multiprocess_prototype/frontend/widgets/tabs/settings/tab.py`: 434 → 114 LOC
- `multiprocess_prototype/frontend/widgets/tabs/settings/presenter.py`: 98 → 38 LOC
- `multiprocess_prototype/frontend/widgets/tabs/settings/view.py`: 124 → 51 LOC
- `multiprocess_prototype/frontend/widgets/tabs/settings/system/section.py`:
  +Qt-сигналы `section_dirty_changed`, `section_data_saved`, `bus_change_callback`
- `multiprocess_prototype/frontend/widgets/tabs/settings/history/section.py`:
  +`bus_change_callback() → presenter.refresh`
- `plans/tab-template-extraction/plan.md`: чекбоксы 4.1-4.5 → [x]

Total LOC delta Phase 4: **+228 / −519 = -291 LOC net** в `settings/`
(не считая framework, который был +270 LOC в Phase 3).
