---
date: 2026-05-18
topic: tab-template-extraction Phase 0-2 + qt-mcp baseline
machine: Windows
branch: refactor/tab-template
---

## Session goal

Рефакторинг связки `DiffScrollTabLayout + SettingsTab + SettingsPresenter +
SectionProtocol` в **переиспользуемый шаблон вкладки с tree-навигацией**, чтобы
новая вкладка (Recipes/Processes/...) = ~50 LOC декларации `SectionSpec` без
копирования 700+ LOC tab.py/presenter.py. План — `plans/tab-template-extraction/plan.md`,
7 фаз, ~26ч. ADR — [ADR-126](../../multiprocess_framework/DECISIONS.md#adr-126-шаблон-вкладки-с-tree-навигацией-sectionspec-treenavtabpresenter-basetreenavtab).

## Done

**Phase 0 (commit `0b24bd5`)** — Подготовка
- Sentrux baseline зафиксирован: `quality_signal=7183` (modularity=5107,
  acyclicity=10000, depth=6667, equality=6223, redundancy=9024). MCP-вариант
  sentrux не поддерживает именованные теги — `session_start` хранится в
  сессии sentrux, сравнится через `session_end` в Phase 7.3.
- ADR-126 в `multiprocess_framework/DECISIONS.md`, TOC пересобран
  `python -m scripts.sync`, `scripts/validate.py` зелёный.

**Phase 1 (commit `86c2926`)** — `SectionSpec` + `SectionWithEvents`
- `framework/.../widgets/tabs/section_spec.py` — `@dataclass(frozen=True)
  SectionSpec[TCtx]` с полями `key`, `title`, `factory`, `parent_key=None`,
  `lazy=False`. Generic-параметр позволяет таблу типизировать контекст
  без того, чтобы framework знал `AppContext` прототипа.
- `section_protocol.py` — добавлен опциональный `@runtime_checkable`
  Protocol `SectionWithEvents` (сигналы `section_dirty_changed`,
  `section_data_saved`, метод `bus_change_callback`). Базовый
  `SectionProtocol` не тронут.
- `widgets/tabs/__init__.py` — экспорт `SectionSpec` / `SectionWithEvents`.
- 14 pure-Python тестов в
  `multiprocess_framework/modules/frontend_module/tests/test_section_spec.py`.

**Phase 2 (commit `2868dc1`)** — `TreeNavTabPresenter`
- `framework/.../widgets/tabs/tree_nav_presenter.py` — pure-Python
  `TreeNavTabPresenter(TabPresenterBase)`: реестр секций (`key →
  SectionProtocol`), индексы `content_stack`/`action_stack`, ленивые
  секции (`register_lazy_section` / `ensure_lazy_section` /
  `notify_lazy_section_created`), навигация `on_tree_item_changed`
  (lifecycle `on_activated`/`on_deactivated`), `navigate_to` через
  `view.select_tree_key`.
- `SettingsPresenter` теперь наследует `TreeNavTabPresenter`. **256 → 98 LOC.**
  Оставлено: `_TOP_SECTIONS`/`_ADMIN_CHILDREN`, `populate()` (через
  view-методы), `on_bus_change` через `ctx.action_bus()`. Удалены:
  `_switch_action_buttons`, `register_section`, `register_content_page`,
  `register_action_page`, `on_tree_item_changed`, `navigate_to`,
  `ensure_admin_panel`, алиасы `*_admin_panel`.
- `view.py:create_admin_panel` → `create_lazy_section` в Protocol.
- `tab.py:create_admin_panel` → `create_lazy_section`,
  `notify_admin_panel_created` → `notify_lazy_section_created`.
- 18 pure-Python тестов в `test_tree_nav_presenter.py`.

**qt-mcp интеграция (commit `c2aacb3`)** — Baseline + ловушки
- `multiprocess_prototype/frontend/app.py:run_gui()` — opt-in probe-блок:
  `QT_MCP_PROBE=1 → qt_mcp.probe.install()` на `localhost:9142`. Прод
  не меняется без env-флага.
- Baseline Settings таба снят через qt-mcp в `plans/tab-template-extraction/baseline-phase2.md`:
  виджет-дерево MainWindow + SettingsTab → DiffScrollTabLayout, `objectName`
  контракт для Phase 6.1.
- `.claude/mcp/qt-mcp/SETUP_GUIDE.md` + `README.md` дополнены секцией
  «Project-specific quirks» (Bash vs PowerShell в Claude Code, probe в
  дочернем `gui` процессе, время старта ≥12 сек, конфликт с pytest-qt
  по порту 9142).

**Агенты и правила (commits `ef963e2`, `d908040`)** — Учим qt-mcp + sentrux/qex
- `.rules/gui.md` — секции «Тестирование GUI» (pytest-qt для unit, qt-mcp
  для baseline/smoke) и «Семантический поиск и архитектурные метрики»
  (qex vs sentrux таблица).
- `agents/tester.md` — убран запрет «GUI widgets не тестируем»; добавлены
  правила выбора pytest-qt vs qt-mcp по типу acceptance criterion.
- `agents/debugger.md` — секция «GUI bugs — qt-mcp для live-диагностики»
  с пошаговым workflow + правило про sentrux dsm/rules для cross-module
  багов.
- `agents/reviewer.md` — в Architecture-специализацию: `/sentrux-rules`
  (проверка слоёв), `/sentrux-dsm` (циклы), baseline delta через
  `session_start`/`session_end`.

**Tests baseline (всё green):** 128 settings + 14 section_spec + 18
tree_nav_presenter = **160 passed**. 2 пре-существующих падения в
`test_controls_v2_hooks.py` (slider/checkbox rejected hook) — НЕ связаны
с этим PR, падали на baseline `0775d01`.

## What did NOT work

- **PowerShell-синтаксис `$env:QT_MCP_PROBE = "1"` в Claude Code Bash MCP** —
  падает с `command not found`. Claude Code на Windows исполняет background
  через bash, не через PowerShell. Решение: `QT_MCP_PROBE=1 python multiprocess_prototype/run.py`
  (POSIX). Записано в `.claude/mcp/qt-mcp/SETUP_GUIDE.md` секция «Project-specific quirks».

- **Многострочный `Why:` trailer в commit-сообщении** — commit-msg hook
  отклоняет, потому что парсер требует, чтобы каждая строка trailer-блока
  матчилась `^([A-Z][A-Za-z\-]*): (.+)$`. Решение: `Why:` всегда на одной
  строке. Подробно — `scripts/validate_commit/validate_commit.py:parse_message`.

- **Цель «SettingsPresenter <80 LOC»** — на Phase 2 достигнуто 98 LOC, не 80.
  Финальное сжатие отложено на Phase 4.4 (после миграции на `BaseTreeNavTab`,
  когда `populate()` уйдёт в базу, а константы переедут в
  `settings/_sections.py`). Метка в плане: `[~]` вместо `[x]` для 2.4.

- **`taskkill` с флагами `/F /FI /T` в bash MCP** — argument parser
  интерпретирует `/F` как путь. Решение: `powershell -Command "Get-Process
  python | Stop-Process -Force"` либо передавать без `/`-флагов.

- **Sentrux MCP не поддерживает именованные baseline-теги** — план плана
  просил «session_start с тегом tab-template-start», но `mcp__sentrux__session_start`
  тег не принимает (baseline хранится в текущей сессии sentrux). Это
  ограничение MCP-обёртки; CLI `sentrux session_start --label X` может
  поддерживать, но я не проверял. Записано в чекбоксе 0.3.

## Key decisions made

- **`SectionWithEvents` как отдельный Protocol**, а не опциональные поля
  в базовом `SectionProtocol`. Причина: Protocol не умеет «опциональные»
  поля с `@runtime_checkable` без поломки существующих секций. Mixin-Protocol
  позволяет `getattr(section, "bus_change_callback", None)` и не ломает
  5 существующих секций settings/.

- **`SettingsPresenter` наследует `TreeNavTabPresenter`** (не композиция).
  Причина: сохранение публичного API без алиасов — `tab.py` зовёт
  `self._presenter.register_section`/`navigate_to` напрямую, наследование
  делает это бесплатно.

- **`create_admin_panel` → `create_lazy_section`** в `view.py:Protocol` и
  `tab.py`. Причина: универсальное имя в framework, специфика «admin
  panel» — лишний термин, который не должен попасть в `BaseTreeNavTab`.
  Tests не страдают: они зовут публичный API `SettingsTab`, не presenter.

- **Baseline UI через qt-mcp в `plans/<slug>/baseline-phase2.md`** — а не
  в `docs/refactors/`. Причина: baseline — артефакт плана, живёт и умирает
  с планом. После закрытия плана `docs/refactors/2026-MM_tab_template.md`
  (Phase 7.2) подведёт итог.

- **Учить агентов через `.rules/gui.md` + точечные правки `tester.md`/
  `debugger.md`/`reviewer.md`** вместо переписывания каждого агента.
  Причина: `.rules/gui.md` загружается path-scoped когда агент работает с
  `frontend_module/` или `multiprocess_prototype/registers/` — это автоматически.

## Next step

**Phase 3 — `BaseTreeNavTab` + публичный API `DiffScrollTabLayout`.** Уровень
**TeamLead** (High complexity, ~6h по плану). Конкретно:

1. Расширить `DiffScrollTabLayout` публичным API:
   `refresh_after_page_change(stack)` (вместо `_content_scroll.setWidgetResizable`
   снаружи), `connect_stack(stack, role)` (автоподписка на `currentChanged`),
   `register_inner_scrolls` через `installEventFilter(ChildAdded)`.
2. Создать `framework/.../widgets/tabs/base_tree_nav_tab.py` — `BaseTreeNavTab(QWidget)`
   с конструктором `(title, sections, ctx, layout_factory=DiffScrollTabLayout)`.
   Циклом по `sections: list[SectionSpec]` делает то, что сейчас 5
   `add_*_page()` методов SettingsTab.
3. Сигналы наружу: `section_changed(key)`, `section_dirty_changed(key, dirty)`,
   `section_data_saved(key, data)`.
4. Параметр `RegisterView(show_toggle: bool = True)` — замена хака
   `system/section.py:87` `_toggle.hide()`.
5. Acceptance Phase 3.5: smoke-тест через qt-mcp — создать `BaseTreeNavTab`
   с 2 фейковыми секциями, проверить переключение `qt_find_widget` +
   `qt_snapshot`.

Стартовать в новом чате командой:
```
Продолжаем plans/tab-template-extraction/plan.md, ветка refactor/tab-template.
Phase 0-2 закрыты (коммиты 0b24bd5, 86c2926, 2868dc1). Делай Phase 3
через teamlead — High complexity, нужен публичный API DiffScrollTabLayout
без боли с приватными атрибутами. Baseline UI — plans/tab-template-extraction/baseline-phase2.md.
```

## Files changed

**Commits на ветке `refactor/tab-template` (база `0775d01`):**

```
d908040 docs(agents): добавить sentrux + qex в правила reviewer/debugger/gui-rules
ef963e2 docs(agents): научить tester/debugger использовать pytest-qt + qt-mcp
c2aacb3 chore(mcp): qt-mcp probe в frontend/app.py + baseline Phase 2 + project quirks в гайде
2868dc1 refactor(framework): TreeNavTabPresenter — универсальная база — Phase 2
86c2926 feat(framework): SectionSpec + SectionWithEvents — Phase 1 шаблона вкладок
0b24bd5 docs(adr): ADR-126 — шаблон вкладки с tree-навигацией
032f6a0 docs(plans): tab-template-extraction — рефакторинг шаблона вкладки с tree-навигацией
```

**Файлы (cumulative):**

Создано:
- `multiprocess_framework/modules/frontend_module/widgets/tabs/section_spec.py`
- `multiprocess_framework/modules/frontend_module/widgets/tabs/tree_nav_presenter.py`
- `multiprocess_framework/modules/frontend_module/tests/test_section_spec.py`
- `multiprocess_framework/modules/frontend_module/tests/test_tree_nav_presenter.py`
- `plans/tab-template-extraction/plan.md`
- `plans/tab-template-extraction/baseline-phase2.md`

Изменено:
- `multiprocess_framework/DECISIONS.md` (+ADR-126, sync TOC)
- `multiprocess_framework/modules/frontend_module/widgets/tabs/__init__.py` (export `SectionSpec`/`SectionWithEvents`/`TreeNavTabPresenter`)
- `multiprocess_framework/modules/frontend_module/widgets/tabs/section_protocol.py` (+ `SectionWithEvents`)
- `multiprocess_prototype/frontend/widgets/tabs/settings/presenter.py` (256 → 98 LOC)
- `multiprocess_prototype/frontend/widgets/tabs/settings/tab.py` (`create_admin_panel` → `create_lazy_section`, `notify_admin_panel_created` → `notify_lazy_section_created`)
- `multiprocess_prototype/frontend/widgets/tabs/settings/view.py` (rename `create_admin_panel`)
- `multiprocess_prototype/frontend/app.py` (+QT_MCP_PROBE probe-блок, opt-in)
- `.claude/mcp/qt-mcp/SETUP_GUIDE.md` (+«Project-specific quirks»)
- `.claude/mcp/qt-mcp/README.md` (+выжимка ловушек)
- `.rules/gui.md` (+тестирование GUI, +qex/sentrux)
- `.claude/agents/company/tester.md` (убрана отговорка про GUI; +pytest-qt/qt-mcp правила)
- `.claude/agents/company/debugger.md` (+qt-mcp workflow; +sentrux при cross-module)
- `.claude/agents/company/reviewer.md` (+sentrux в Architecture)
