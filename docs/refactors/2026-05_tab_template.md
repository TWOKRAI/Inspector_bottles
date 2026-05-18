# Рефакторинг шаблона вкладки с навигацией: `BaseColumnarTab` + иерархия

**Дата:** 2026-05-18
**Статус:** DONE
**Ветка:** `refactor/tab-template`
**Slug:** tab-template-extraction
**ADR:** ADR-126 (шаблон tree-nav), ADR-127 (DiffScroll vs Standard)
**Базовый коммит:** `0775d01` (refactor/frontend-widgets-cleanup)

---

## Контекст

До рефакторинга `SettingsTab` был монолитом (~434 LOC): 5 методов `add_X_page()` с
дублирующимся кодом, жёсткая привязка к именам секций в `SettingsPresenter`, прямой
доступ к приватным атрибутам `DiffScrollTabLayout`. Миграция любой другой вкладки
(Recipes, Processes) на аналогичный паттерн потребовала бы ~700 LOC копирования.

После 7 фаз рефакторинга сложился переиспользуемый constructor-kit: nav-агностичная
база `BaseColumnarTab`, два специализированных подкласса (`BaseTreeNavTab` /
`BaseListNavTab`), общая иерархия layout'ов в framework. `SettingsTab` сжался до
66 LOC декларации. `RecipesTab` переписан как pilot-consumer `BaseListNavTab` за
185 LOC без копирования шаблонного кода.

---

## Итоговая иерархия

```
tab_layouts/_AbstractColumnarTabLayout      <- рама (action + nav-slot + content + undo)
   ├── DiffScrollTabLayout                  (дифференциальный мастер-скролл)
   └── StandardTabLayout                    (QScrollArea + sub-nav вариант)

BaseColumnarTab(QWidget)                    <- nav-агностичная база Tab
   ├── BaseTreeNavTab(BaseColumnarTab)      <- статичный nav через list[SectionSpec]
   │      └── SettingsTab                  (9 секций, 66 LOC)
   └── BaseListNavTab(BaseColumnarTab)      <- динамический CRUD nav
          └── RecipesTab                   (list-CRUD, 185 LOC)
```

Все компоненты из `base_columnar_tab.py`, `base_tree_nav_tab.py`, `base_list_nav_tab.py`
и `tab_layouts/` находятся в `multiprocess_framework/modules/frontend_module/widgets/tabs/`.
Prototype знает только о `SettingsTab`, `RecipesTab` и своих `_sections.py`.

---

## Метрики до / после

| Метрика | До (baseline `0775d01`) | После (Phase 7) | Дельта |
|---------|------------------------|-----------------|--------|
| `settings/tab.py` LOC | 434 | 66 | -368 (-85%) |
| `SettingsPresenter` LOC | 256 | 38 | -218 (-85%) |
| Методы `add_X_page` в tab | 5 | 0 | -5 |
| Прямые обращения к приватным атрибутам layout | 3 | 0 | -3 |
| `recipes/tab.py` LOC | 303 | 185 | -118 (-39%) |
| Новая база `BaseColumnarTab` LOC (framework) | — | 188 | +188 |
| `BaseTreeNavTab` LOC (framework) | — | ~300 | +300 |
| `BaseListNavTab` LOC (framework) | — | 273 | +273 |
| Новый таб через BaseTreeNavTab (LOC декларации) | ~700 | ~50-80 | -88% |
| Cycles (acyclicity) | 0 | 0 | 0 |
| sentrux `quality_signal` | 7183 (Phase 0.3) | 7180 | -3 |
| sentrux coupling | 0.21 | 0.16 | -0.05 (улучшение) |

**Заметки к метрикам sentrux:**
- `quality_signal` практически не изменился (7183 → 7180, дельта -3): рефакторинг
  добавил новые файлы в framework (net +), удалил дублирование в prototype (net -).
  Нейтральный результат ожидаем — цель была не в rosте score, а в
  декомпозиции монолита.
- Coupling (0.21 → 0.16) улучшился: вынос layout'ов и общей базы в framework
  снизил связность внутри prototype.
- Cycles = 0 сохранены на всём протяжении рефакторинга.
- Детальные sub-метрики Phase 0.3 (modularity=5107, depth=6667 и др.) —
  MCP-сессионные данные, не воспроизводятся после закрытия сессии. Текущее значение
  через CLI: `sentrux check` → 7180. Complex functions: 43 → 44 (+1, minor).

---

## Чему учит этот рефакторинг

- **Pivot 6b/6c появился благодаря recon.** Изначально Phase 6 предполагала
  перевести `RecipesTab` на `BaseTreeNavTab`. Recon manager'а вскрыл несовместимость
  (`SectionSpec` — для статичного UI-дерева, Recipes — list-CRUD). Вместо отмены
  pilot'а — расширение иерархии. Нельзя проектировать без разведки реального кода.

- **`_AbstractColumnarTabLayout` появился для общего фрейма.** Два layout'а
  (`DiffScrollTabLayout` / `StandardTabLayout`) имели ~125 LOC общего кода
  (action-колонка, `enable_undo_redo`, `_make_button`). Вынос базы в
  `_AbstractColumnarTabLayout` дал чистый `set_nav_widget(QWidget)` как
  nav-агностичный слот — любой QWidget в роли nav.

- **Shiboken metaclass conflict с `ABC + QWidget`.** Попытка сделать
  `_AbstractColumnarTabLayout(QWidget, ABC)` привела к `TypeError: metaclass conflict`.
  PySide6 Shiboken metaclass несовместим с ABCMeta. Применён Вариант B:
  декоративный `@abstractmethod` без `ABC`-наследования, контракт закреплён
  в docstring. Принципиально: нельзя проверять abstract enforcement через
  `TypeError` при инстанциации — только через документацию и ревью.

- **`select_key()` НЕ должен вызывать `_on_nav_changed()`.** При первой попытке
  вызов `_on_nav_changed` из `select_key` создавал цепочку
  `select → setCurrentItem → currentItemChanged → _on_nav_changed → select_key`.
  Решение (Вариант B): `_on_nav_changed` вызывается только как signal handler
  (user-driven). `select_key` только переключает `content_stack`. Контракт
  зафиксирован в docstring `BaseColumnarTab`.

- **`presenter_factory` — ключ к декаплингу section / presenter.** До Phase 5
  `SystemSection` создавал свой presenter в `__init__`. После — `SectionSpec`
  несёт `presenter_factory: Callable[[ctx, section], presenter]`, вызываемый
  `BaseTreeNavTab._apply_presenter_factory`. Тесты могут подменять presenter
  без переопределения секции — реальная testability.

---

## Новые контракты в framework

Всё ниже добавлено в
`multiprocess_framework/modules/frontend_module/widgets/tabs/`:

| Контракт | Файл | Назначение |
|----------|------|-----------|
| `_AbstractColumnarTabLayout` | `tab_layouts/_abstract_columnar.py` | Рама: action-колонка + nav-слот + undo. `set_nav_widget(QWidget)` — nav-агностичный |
| `DiffScrollTabLayout` | `tab_layouts/diff_scroll_layout.py` | Мастер-скролл вариант (MOVED из prototype) |
| `StandardTabLayout` | `tab_layouts/standard_layout.py` | QScrollArea + sub-nav (MOVED + protocol compliance) |
| `BaseColumnarTab(QWidget)` | `base_columnar_tab.py` | Nav-агностичная база Tab. Хуки: `_build_nav_widget`, `_on_nav_changed`. Helpers: `register_content_widget`, `select_key`. Сигнал: `section_changed` |
| `BaseTreeNavTab(BaseColumnarTab)` | `base_tree_nav_tab.py` | Статичный nav через `list[SectionSpec]`. Используется `SettingsTab` |
| `BaseListNavTab(BaseColumnarTab)` | `base_list_nav_tab.py` | Динамический CRUD nav. API: `add_item`, `remove_item`, `rename_item`, `select_item`. Сигналы: `item_selected`, `item_added`, `item_removed`, `item_renamed` |
| `SectionSpec[TCtx]` | `section_spec.py` | Frozen dataclass для декларации секции (`key`, `title`, `factory`, `parent_key`, `lazy`, `presenter_factory`) |
| `TreeNavTabPresenter` | `tree_nav_presenter.py` | Pure-Python база presenter'а для tree-nav табов |
| `SectionWithEvents` | `section_protocol.py` | Protocol — опц. mixin c сигналами dirty/saved и `bus_change_callback` |

---

## Связанные ADR

- **ADR-126** — «Шаблон вкладки с tree-навигацией: `SectionSpec` + `TreeNavTabPresenter`
  + `BaseTreeNavTab`». Зафиксирован в `multiprocess_framework/DECISIONS.md`.
- **ADR-127** — «DiffScroll vs Standard layout — критерии выбора. Размещение в
  framework. `_AbstractColumnarTabLayout` как nav-агностичная база». Зафиксирован
  в `multiprocess_framework/DECISIONS.md`.

---

## Коммиты Phase 0-7

### Phase 0 (подготовка)
- `032f6a0` — `docs(plans): tab-template-extraction plan + ADR-126`

### Phase 1 (SectionSpec + SectionProtocol)
- (коммиты Phase 1 см. git log refactor/tab-template)

### Phase 2 (TreeNavTabPresenter)
- (коммиты Phase 2 см. git log refactor/tab-template)

### Phase 3 (BaseTreeNavTab + чистый API DiffScroll)
- (коммиты Phase 3 см. git log refactor/tab-template)

### Phase 4 (миграция SettingsTab → BaseTreeNavTab)
- `ffa6f92` — `feat(settings): migrate SettingsTab to BaseTreeNavTab`
- `ce68349` — `refactor(settings): SettingsPresenter 38 LOC, drop deprecated on_bus_change`

### Phase 5 (section-as-view / presenter decoupling)
- `9c59a2a` — `refactor(settings): presenter_factory decoupling in SectionSpec`
- `2cc0db7` — `fix(settings): post-review fixups — sync_editors, double dirty`

### Phase 6a (layout в framework)
- `541009f` — `feat(framework): _AbstractColumnarTabLayout + move DiffScroll/Standard — Phase 6a`
- `1de3267` — `fix(framework): post-review fixups 6a — ActionBus import layer, set_action_widget impl`
- `86415f4` — `docs(plans): Phase 6a done — tab-template-extraction`

### Phase 6b (BaseColumnarTab + BaseTreeNavTab refactor)
- `684bdb9` — `refactor(framework): BaseColumnarTab extracted from BaseTreeNavTab — Phase 6b`
- `28e9879` — `docs(plans): Phase 6b done — tab-template-extraction`

### Phase 6c (BaseListNavTab + RecipesTab pilot)
- `1260787` — `feat(framework): BaseListNavTab + RecipesTab pilot — Phase 6c`
- `b807b46` — `docs(plans): Phase 6c done — tab-template-extraction`

### Handoff
- `f1df446` — `docs(handoff): tab-template Phase 6 done (6a+6b+6c)`

### Phase 7 (техдолги + документация)
- `18b4b04` — `refactor(settings): drop deprecated tab API — Phase 7.1`
- (текущая сессия: отчёт 7.2, blueprint 7.4, план 7.5)

---

## Что не получилось / отложено

- **LOC `recipes/tab.py` = 185** (цель плана ≤100). Reviewer APPROVED с обоснованием:
  Recipes-специфика (Cards/Table toggle, permissions, `_on_action` handler) необразимо
  занимает ~85 LOC. Мониторить при следующих migration consumer'ов (ProcessesTab).

- **`_selection_guard` в `BaseListNavTab`** — поле объявлено как задел на будущее,
  но нигде не устанавливается в `True`. Не блокер для текущих consumer'ов.

- **Smoke `python multiprocess_prototype/run.py`** — не запущен в рамках Phase 7
  (рекомендован ручной запуск перед merge в main).

- **sentrux sub-метрики** (modularity, depth, equality) — детальные данные
  доступны только через MCP `session_start/session_end`. CLI (`sentrux gate`)
  даёт только summary quality_signal + coupling. Для следующих крупных рефакторов
  рекомендовано использовать MCP-сессию с самого начала и закрывать её в финале.
