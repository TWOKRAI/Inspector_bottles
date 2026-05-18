---
date: 2026-05-18
topic: tab-template-extraction Phase 5 done, ready for Phase 6
machine: Windows
branch: refactor/tab-template
---

## Session goal

Phase 5 плана `plans/tab-template-extraction/plan.md` — декаплинг
section/presenter. Цель: добавить `SectionSpec.presenter_factory`, вытащить
создание `SystemSettingsPresenter`/`AppearancePresenter`/`HistoryPresenter`
из `__init__` секций, чтобы тестам можно было подсунуть mock-presenter.

## Done — Phase 5 закрыта

**Commit `9c59a2a`** — `refactor(forms): декаплинг section/presenter — Phase 5`
- `section_spec.py`: новое поле `presenter_factory: Callable[[TCtx,
  "SectionProtocol"], object] | None = None` на frozen dataclass.
- `base_tree_nav_tab.py`: новый метод `_apply_presenter_factory(section, key)`
  ищет spec по `key`, через `getattr` проверяет `set_presenter` (чтобы не
  ломать `_SectionAdapter` без setter'а), вызывает
  `presenter_factory(self._ctx, section)` → `section.set_presenter(presenter)`.
  Вызывается в `_attach_section` **ПЕРЕД** `_connect_section_events` —
  порядок критичен, т.к. `bus_change_callback()` лезет к
  `self._presenter` секции.
- `system/section.py`: `__init__` без presenter (`self._presenter:
  SystemSettingsPresenter | None = None`). Новый `set_presenter()`:
  inject + `sync_editors_to_cfg()` + подключение callback'ов
  `on_dirty_changed`/`on_settings_saved` + `editor.change_signal →
  on_field_changed` + `register_view.field_changed →
  on_field_changed_action_bus`. Слоты кнопок (`_on_save_clicked`,
  `_on_reset_clicked`) — guard `if self._presenter is not None`.
  `bus_change_callback()` возвращает `None` если presenter не inject'ен.
- `appearance/section.py`: то же + **breaking change**:
  `AppearanceSection.__init__` теперь БЕЗ аргументов `theme_manager`/
  `presets_manager` — они создаются в `_appearance_presenter_factory`.
  Слоты-врапперы `_on_theme_selected` / `_on_var_changed` с guard'ами.
  `set_presenter()` вызывает `presenter.initialize()` (загрузка таблицы тем).
- `history/section.py`: то же. `on_activated()` и `bus_change_callback()`
  с guard'ами. `set_presenter()` без вызова initialize (нет такого метода).
- `_sections.py`: 3 новые фабрики `_system/_appearance/_history_presenter_factory`.
  `_appearance_factory(ctx)` теперь `return AppearanceSection()` без аргументов.
  В `build_settings_sections` обновлены 3 SectionSpec — добавлено поле
  `presenter_factory=...`.

**Commit `2cc0db7`** — `fix(forms): post-review fixups Phase 5 — dirty при
запуске, инкапсуляция` (после reviewer iter 1 CHANGES REQUESTED)
- **Fix 1 (баг):** `SystemSettingsPresenter.__init__` больше НЕ вызывает
  `sync_editors_to_cfg()`. В первой версии Phase 5 вызывался дважды:
  один раз из `__init__` (безвредно — сигналы ещё не подключены), второй
  раз из `set_presenter()` ПОСЛЕ подключения `editor.change_signal` —
  второй вызов эмитил `change_signal` → `on_field_changed()` →
  `_set_dirty(True)`, и при запуске приложения кнопки «Сохранить»/
  «Сбросить» уже enabled. Теперь sync вызывается один раз в `set_presenter`
  **ДО** подключения сигналов.
- **Fix 2 (инкапсуляция):** `_sync_editors_to_cfg` переименован в
  `sync_editors_to_cfg` (публичный). `SystemSection` больше не лезет в
  приватный API презентера — это нарушало декаплинг, ради которого
  Phase 5 и делалась. Все 3 вызова обновлены (`def`, `reload()`,
  `set_presenter()`).
- **Fix 3 (типы):** `SectionSpec.presenter_factory` типизирован
  `Callable[[TCtx, "SectionProtocol"], object] | None` вместо
  `Callable[[TCtx, object], object] | None`.
- **Fix 4 (типы фабрик в _sections.py):** ПРОПУЩЕН — потенциальный
  циклический импорт (нужно импортировать `SystemSection` в `_sections.py`
  для `isinstance`-narrowing). По спеке reviewer'а это nice-to-have,
  «если порождает цикл — оставь как есть».

**Tests (после `2cc0db7`):**
- `multiprocess_prototype/.../settings/` — 128 passed, 0 failed
- `multiprocess_framework/.../frontend_module/tests/` — 267 passed,
  2 pre-existing fail (`test_controls_v2_hooks.py::test_*_rejected_hook` —
  baseline регрессия, не Phase 5)

## Reviewer verdict — APPROVED (iter 2 of 2)

Iter 1 → CHANGES REQUESTED (4 issue). Iter 2 → APPROVED после `2cc0db7`.
> «Ветка `refactor/tab-template` Phase 5 готова к мержу. Блокеров нет,
> можно переходить к Phase 6 (миграция Recipes).»

Доверие к 128 passed: иначе говоря — тесты с моками используют
`schema_to_field_infos=[]`, цикл sync пуст, поведение «нет sync в
presenter.__init__» не затронуло тесты.

## Key decisions made

- **`presenter_factory` опционален, проверка через `getattr(section,
  "set_presenter", None)`** — `_SectionAdapter` (для admin-панелей) не
  имеет setter'а; `_apply_presenter_factory` молча игнорирует.
- **Порядок в `_attach_section`:** register_section → apply_presenter_factory
  → _connect_section_events. Зашит в коде, задокументирован в docstring
  `_attach_section`.
- **`AppearanceSection.__init__` breaking change** — потерял аргументы
  `theme_manager`/`presets_manager`. Это допустимо в пределах одного
  коммита (фабрика `_appearance_factory` обновлена синхронно). В
  тестах прямых вызовов с этими аргументами нет (developer проверил).
- **`SystemSettingsPresenter.sync_editors_to_cfg` теперь публичный** —
  расширение API ради декаплинга. Альтернатива (initialize-паттерн как
  у AppearancePresenter) — потребовала бы большего рефактора presenter'а,
  отложено.
- **`SettingsPresenter` пока пустой** — после Phase 5 он всё ещё только
  `__init__` с `_ctx`. Возможно, после Phase 6 (Recipes pilot)
  выяснится, что он не нужен — но это решение Phase 7.

## What did NOT work / отложено

- **Fix 4 типизации фабрик** (`object` → конкретный класс) — циклический
  импорт. Допустимый компромисс.
- **Smoke через qt-mcp** — снова не запущен (как и в Phase 4). Архитектурно
  ничего не должно сломаться, но запустить `python multiprocess_prototype/run.py`
  перед стартом Phase 6 настоятельно рекомендуется.
- **Тест с реальным mock-presenter** — план писал «Тестам можно подсунуть
  mock-presenter». Архитектурно это теперь возможно, но **нового теста с
  использованием `SectionSpec.presenter_factory=lambda...: MockSysPresenter()`
  не написано**. Реальная польза Phase 5 проявится в Phase 6, когда Recipes
  будет тестироваться этим паттерном.

## LOC delta

- Phase 5 (9c59a2a): +208 / -73 = **+135 net** (план прогнозировал +20).
- Post-review (2cc0db7): мелкие изменения, +/- 10 строк.
- Перерасход: guard-слоты в кнопках (`if self._presenter is None: return`)
  во всех 3 секциях + публичный setter с docstring.

## Files changed (Phase 5 cumulative)

```
2cc0db7 fix(forms): post-review fixups Phase 5 — dirty при запуске, инкапсуляция
9c59a2a refactor(forms): декаплинг section/presenter — Phase 5
```

Изменено:
- `multiprocess_framework/modules/frontend_module/widgets/tabs/section_spec.py`
- `multiprocess_framework/modules/frontend_module/widgets/tabs/base_tree_nav_tab.py`
- `multiprocess_prototype/frontend/widgets/tabs/settings/system/section.py`
- `multiprocess_prototype/frontend/widgets/tabs/settings/system/presenter.py`
- `multiprocess_prototype/frontend/widgets/tabs/settings/appearance/section.py`
- `multiprocess_prototype/frontend/widgets/tabs/settings/history/section.py`
- `multiprocess_prototype/frontend/widgets/tabs/settings/_sections.py`
- `plans/tab-template-extraction/plan.md` (чекбоксы 5.1-5.4)

## Next step — Phase 6 (TeamLead, 6h)

**Phase 6 — Унификация DiffScroll/Standard + Recipes pilot**. Это
сложная и важная фаза (план оценивает TeamLead, не Developer).

### Текущее состояние Recipes (предварительный recon)

- `multiprocess_prototype/frontend/widgets/tabs/recipes/tab.py` — **302 LOC**
- `multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py` — 125 LOC
- `multiprocess_prototype/frontend/widgets/tabs/recipes/recipe_io.py` — 95 LOC
- `multiprocess_prototype/frontend/widgets/primitives/standard_tab_layout.py` — 375 LOC

Recipes не использует tree-навигацию — у него **список** (выбор активного
рецепта) + редактор. Это другая семантика по сравнению с Settings (где
дерево секций). Перед стартом нужно прочитать `recipes/tab.py` и
понять, насколько `BaseTreeNavTab` вообще применим — может,
нужен ещё `BaseListNavTab` (общий с `BaseTreeNavTab` через `_AbstractColumnarTabLayout`).

### Подзадачи (по плану)

1. **6.1** Перенести `DiffScrollTabLayout` (`multiprocess_prototype/.../primitives/`)
   и `StandardTabLayout` (тот же путь) → `multiprocess_framework/.../widgets/tabs/tab_layouts/`.
   Сохранить objectName (QSS не трогаем — пользователь чувствителен к UX).
2. **6.2** Выделить общую базу `_AbstractColumnarTabLayout(QWidget)`:
   action-колонка + nav + content + undo/redo. Конкретные классы
   переопределяют:
   - тип скролла (диф vs обычный)
   - тип nav-виджета (по умолчанию None — конкретный таб задаёт)
3. **6.3 Pilot Recipes:** переписать `RecipesTab` через `BaseTreeNavTab` (или
   новую базу `BaseListNavTab` если придётся) с `StandardTabLayout` как
   `layout_factory`. Сравнить LOC: до vs после.
4. **6.4** ADR-127 (предположительно): «DiffScroll vs Standard layout —
   критерии выбора».
5. **6.5 Acceptance:**
   - [ ] Все тесты `test_recipes_tab.py` зелёные
   - [ ] LOC в `recipes/tab.py` уменьшился на ≥30%
   - [ ] Smoke: Recipes работает идентично (qt-mcp или ручной запуск)

### Подводные камни Phase 6

- **Перенос layout'ов в framework** ломает импорты в prototype.
  `DiffScrollTabLayout` импортируется из 3+ мест (settings/tab.py,
  возможно recipes/tab.py, тесты). После переноса — фасадный реэкспорт
  в `multiprocess_prototype/frontend/widgets/primitives/__init__.py` для
  backward-compat (как делали в Phase 4 с `_nav_tree.py`).
- **QSS чувствителен к objectName.** В `BaseTreeNavTab` уже есть
  `_tree_object_name()` hook. Для layout'ов нужно сохранить все имена
  (`SettingsTreeNav`, корневой groupBox, action panel и т.д.).
  Базовая `_AbstractColumnarTabLayout` должна оставить subclass'ам
  гибкость переименовать.
- **Recipes — не tree, а список.** `BaseTreeNavTab.__init__` ожидает
  `sections: list[SectionSpec]` и строит QTreeWidget. Если у Recipes
  плоский список рецептов (без иерархии) — это **просто tree без
  parent_key**, и должно работать. Но если рецепты — динамический набор
  (CRUD: пользователь добавляет/удаляет), а не статичная декларация —
  нужен `BaseListNavTab` с runtime-добавлением секций. Скорее всего
  второе — рецепты как сущности данных, не как секции UI.
- **StandardTabLayout не подписан на ActionBus** (в отличие от
  DiffScrollTabLayout). После переноса в framework решить: подписка
  через общую базу или только в DiffScroll-subclass.
- **Один уровень PR.** Phase 6 = TeamLead, 6h. Может не уложиться в
  одну сессию — план может быть разбит на 6a (перенос layout'ов
  + общая база) и 6b (Recipes pilot). Решает Director.

### Стартовать в новом чате командой:

```
Продолжаем plans/tab-template-extraction/plan.md, ветка refactor/tab-template.
Phase 0-5 закрыты (последние коммиты 9c59a2a, 2cc0db7, и docs-коммит плана).
Делай Phase 6 через teamlead (это High сложность по плану — TeamLead, 6h).
Цель — унификация DiffScroll/Standard layout'ов в framework + pilot
RecipesTab через BaseTreeNavTab. Подробности и подводные камни —
workspace/handoffs/2026-05-18_tab-template-phase5.md
```
