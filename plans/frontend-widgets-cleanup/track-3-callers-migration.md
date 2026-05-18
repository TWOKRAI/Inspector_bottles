# Plan: Track 3 — Callers migration на FormContext

- **Slug:** frontend-widgets-track-3-callers
- **Дата:** 2026-05-16
- **Статус:** DONE (2026-05-18, реализация в `f5634ec`: form_ctx прокинут через form_builder/register_view/field_editor, callers PluginsTab/ServicesTab/InspectorPanel/SystemSection/yaml_io передают form_ctx)
- **Ветка:** refactor/frontend-widgets-cleanup
- **Родительский план:** [`rollout-finish.md`](rollout-finish.md), секция «Track 3» (строки 179-203)
- **Верхнеуровневая карта:** [`plan.md`](plan.md)

---

## Зачем

Tracks 1 и 2 дали FW-компонентам и factory-builder'ам поддержку `form_ctx` kwarg. Track 3 закрывает цепочку: все **callers** (виджеты, которые вызывают `RegisterView` или `CardsFieldFactory.create`) должны явно передавать `form_ctx` — полный `FormContext` для plugin-bindable форм или `None` для GUI-локальных настроек.

После Track 3:
- `ServicesTab` рендерит поля сервисов через binding-aware путь (ActionBus коммиты, undo/redo).
- `NodeInspectorPanel` использует `form_ctx` для chain-runner-узлов pipeline; для UI-control-узлов — `None`.
- `SystemSection` (SettingsSystem) явно передаёт `form_ctx=None`, двойная подписка устранена (если была).
- `build_form_for_register` / `build_table_for_register` в `form_builder.py` принимают `form_ctx` и пробрасывают в `CardsFieldFactory.create`.
- `yaml_io` не изменяется (нет связи с form_ctx).
- `PluginsTab._build_form_ctx` расширяет whitelist со специфических плагинов на **все** плагины с registers (пилотный whitelist был только для `robot_control`/`pilot_widgets`).

---

## Ключевые факты из анализа кода

### RegisterView (`forms/register_view.py`)

`RegisterView.__init__` уже принимает `form_ctx: FormContext | None = None` (строка 66) и пробрасывает в `CardsFieldFactory.create(fi, form_ctx=form_ctx)` (строка 78). **Фундамент готов — Task 3.0 (RegisterView kwarg) из первоначальной постановки не нужен.**

### PluginsTab (`tabs/plugins/tab.py`) — **DONE, но неполный**

Форм-контекст уже передаётся (`RegisterView(fields, form_ctx=form_ctx)`, строка 95). Однако `_build_form_ctx` (строка 119-133) имеет **pilot whitelist**: только `robot_control` и `pilot_widgets` получают полный FormContext, все остальные плагины с registers — `None`. Нужно убрать whitelist и вернуть `self._ctx.form_context()` безусловно для всех плагинов с registers. Это финализация DONE-статуса.

### ServicesTab (`tabs/services/tab.py`) — требует миграции

`RegisterView(fields)` вызывается без `form_ctx` (строка 110). `_build_service_page` не имеет доступа к `FormContext`. Нужно: (a) добавить `_build_form_ctx()` метод аналогично PluginsTab, (b) передать `form_ctx` в `RegisterView`.

### NodeInspectorPanel (`tabs/pipeline/inspector/inspector_panel.py`) — требует миграции с оговоркой

Панель вызывает `CardsFieldFactory.create(field_info, parent=self._params_widget)` напрямую в `_try_build_cards_editors` (строка 188), минуя `RegisterView`. Не передаёт `form_ctx`. Ситуация нетривиальная: `NodeInspectorPanel` обслуживает **разные типы узлов** pipeline — одни связаны с plugin (chain runners, получают полный `FormContext`), другие — UI-control-узлы без plugin binding (form_ctx=None). Логика выбора: если `process_name` соответствует процессу с plugin registers — передавать `form_ctx`, иначе `None`. `AppContext` доступен через `self._ctx` (задаётся через `set_context`).

### SystemSection (`tabs/settings/system/section.py`) — form_ctx=None, двойная подписка

`RegisterView` создаётся без `form_ctx` (строка 71-75) — это **правильно** (GUI-локальные настройки). `form_ctx=None` нужно указать **явно** (self-documenting). Двойная подписка: строки 90-94 подключают `editor.change_signal.connect(self._presenter.on_field_changed)` **для каждого editor** по-отдельности — плюс ещё `self._register_view.field_changed.connect(self._presenter.on_field_changed_action_bus)` (строка 93). Это не двойная запись в ActionBus (два разных метода presenter'а), но первая подписка (`editor.change_signal`) вызывает другой обработчик. Нужно **проверить** во время реализации что `on_field_changed` и `on_field_changed_action_bus` не создают двойную запись в RM/ActionBus — если создают, удалить первую подписку.

### form_builder.py (`forms/form_builder.py`) — требует добавления kwarg

`build_form_for_register` и `build_table_for_register` создают editors через `CardsFieldFactory.create(fi)` без `form_ctx` (строки 66 и 149). Нужно добавить kwarg `form_ctx: FormContext | None = None` в обе функции и пробросить в `CardsFieldFactory.create(fi, form_ctx=form_ctx)`.

### yaml_io — без изменений

`yaml_io` выполняет только чтение/запись YAML. `form_ctx` не используется. Задача пропускается.

---

## Порядок выполнения

### Phase 1: Фундамент (Task 3.1)

- Task 3.1: form_builder — добавить kwarg `form_ctx` [PENDING]

### Phase 2: Plugin-callers (Tasks 3.2, 3.3)

- Task 3.2: ServicesTab — form_ctx для всех service-плагинов [PENDING]
- Task 3.3: PluginsTab — финализация: убрать pilot whitelist [PENDING]

### Phase 3: Специальные callers (Tasks 3.4, 3.5)

- Task 3.4: NodeInspectorPanel — условный form_ctx по типу узла [PENDING]
- Task 3.5: SystemSection — явный form_ctx=None + аудит двойной подписки [PENDING]

---

## Task 3.1 — form_builder: добавить kwarg form_ctx

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** добавить `form_ctx: FormContext | None = None` в `build_form_for_register` и `build_table_for_register`, пробросить в `CardsFieldFactory.create`

**Context:** `form_builder.py` — standalone функции для построения cards/table без `RegisterView`. Используются в нескольких местах прототипа как альтернатива `RegisterView`. После добавления kwarg callers смогут опционально передавать `form_ctx`, не ломая существующих вызовов без него.

**Файлы:**
- `multiprocess_prototype/frontend/forms/form_builder.py` — изменить обе функции

**Steps:**

1. Прочитать актуальное состояние `form_builder.py` полностью перед правками.

2. В `build_form_for_register` добавить kwarg:
   ```python
   def build_form_for_register(
       fields: list[FieldInfo],
       *,
       editors: dict[str, FieldEditor] | None = None,
       parent: QWidget | None = None,
       group_by_category: bool = True,
       category_titles: dict[str, str] | None = None,
       form_ctx: FormContext | None = None,      # ← добавить
   ) -> tuple[QWidget, dict[str, FieldEditor]]:
   ```
   Импорт `FormContext` добавить в блок `if TYPE_CHECKING` (или прямой импорт — смотреть по существующему паттерну в файле; в `register_view.py` используется прямой импорт).

3. Изменить строку создания editors (текущая: `editors[key] = CardsFieldFactory.create(fi)`):
   ```python
   editors[key] = CardsFieldFactory.create(fi, form_ctx=form_ctx)
   ```

4. Аналогично в `build_table_for_register` — тот же kwarg и тот же проброс.

5. Обновить docstring обеих функций: добавить `form_ctx` в раздел Аргументы с пояснением «передаётся в CardsFieldFactory.create; если None — legacy путь без binding».

6. Проверить `__init__.py` (`forms/__init__.py`) — `build_form_for_register` и `build_table_for_register` уже реэкспортируются, изменение сигнатуры не требует правки `__init__.py`.

**Acceptance criteria:**
- [ ] `build_form_for_register(..., form_ctx=None)` — вызов без form_ctx не меняет поведение
- [ ] `build_form_for_register(..., form_ctx=ctx)` — editors создаются через `CardsFieldFactory.create(fi, form_ctx=ctx)`
- [ ] Аналогично для `build_table_for_register`
- [ ] `ruff check multiprocess_prototype/frontend/forms/form_builder.py` — 0 ошибок
- [ ] Все существующие callers `build_form_for_register` компилируются без изменений (backward-compat через default None)

**Out of scope:** не менять shared-editors-режим (когда `editors` передаётся извне). Не создавать тесты (достаточно smoke через существующие тесты RegisterView). Не трогать `yaml_io`.

**Edge cases:**
- В `build_form_for_register` editors могут быть переданы **извне** (shared mode). В этом случае `form_ctx` игнорируется — уже созданные editors не перестраиваются. Это корректное поведение; добавить NOTE в docstring.
- Импорт `FormContext` должен быть совместим с TYPE_CHECKING если используется только в аннотациях.

**Dependencies:** нет (RegisterView уже передаёт form_ctx в factory — Task 3.1 симметрично добавляет тот же kwarg в standalone-функции)

---

## Task 3.2 — ServicesTab: form_ctx для всех service-плагинов

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** передать полный `FormContext` в `RegisterView` для каждой страницы сервиса в `ServicesTab`

**Context:** `ServicesTab._build_service_page` создаёт `RegisterView(fields)` без `form_ctx` (строка 110). Сервисы — это plugin-bindable объекты (аналог PluginsTab). Нужно получить `FormContext` из `AppContext` и передавать его в каждый `RegisterView`. Паттерн — точная копия из `PluginsTab._build_form_ctx` без pilot-whitelist.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/services/tab.py` — изменить

**Steps:**

1. Прочитать актуальное состояние файла перед правками.

2. Добавить метод `_build_form_ctx` в `ServicesTab`:
   ```python
   def _build_form_ctx(self) -> FormContext | None:
       """Собрать FormContext для binding-aware RegisterView.

       Возвращает None если ActionBus или RegistersManager недоступны.
       """
       return self._ctx.form_context()
   ```
   Добавить импорт: `from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext` (или из `multiprocess_prototype.frontend.forms` если там реэкспортируется).

3. В `_build_service_page` передать form_ctx в RegisterView:
   ```python
   form_ctx = self._build_form_ctx()
   view = RegisterView(fields, form_ctx=form_ctx)
   ```

4. Убедиться что `_on_field_changed` **не** дублирует write — при `form_ctx` is not None binding-aware builder пишет напрямую через `form_ctx.write`, а `field_changed` signal от RegisterView тоже будет вызывать `_on_field_changed` → `bus.execute`. Проверить механизм: в RegisterView `_on_editor_changed` эмитит `field_changed` только если `editor.change_signal is not None` — binding-aware builders возвращают `change_signal=None`. Значит `field_changed` не будет эмититься для binding-aware полей. Подтвердить это при чтении кода. Если поведение иное — добавить guard в `_on_field_changed` аналогично PluginsTab.

5. Добавить импорт `FormContext` в секцию импортов файла.

**Acceptance criteria:**
- [ ] `RegisterView(fields, form_ctx=form_ctx)` — form_ctx передаётся в каждой странице сервиса
- [ ] `_build_form_ctx()` возвращает `FormContext | None` без исключений при `ctx.action_bus() is None`
- [ ] Нет двойной записи в ActionBus (binding-aware поля: только через form_ctx.write; legacy поля: через field_changed → bus.execute)
- [ ] `ruff check multiprocess_prototype/frontend/widgets/tabs/services/tab.py` — 0 ошибок

**Out of scope:** не добавлять тесты ServicesTab (нет существующих, рефакторинг). Не менять кнопки «Запустить/Остановить/Перезапуск». Не трогать permission guards.

**Edge cases:**
- `self._ctx.form_context()` — метод может отсутствовать в `AppContext` если не был добавлен в Track 0. Проверить `AppContext` перед реализацией; если нет — добавить делегирующий метод аналогично PluginsTab.
- Если `fields` пустой список — `RegisterView([])` с `form_ctx` нормально создаётся (пустая форма).

**Dependencies:** Task 3.1 (form_builder готов); независим от Task 3.3-3.5

---

## Task 3.3 — PluginsTab: финализация pilot whitelist → all plugins

**Level:** Junior (Haiku, normal)
**Assignee:** developer
**Goal:** убрать pilot whitelist в `PluginsTab._build_form_ctx` — все плагины с registers получают полный FormContext

**Context:** `_build_form_ctx` (строка 119-133) возвращает `None` для всех плагинов кроме `robot_control`/`pilot_widgets`. Это pilot-ограничение из Track 0. После завершения Track 2 (все builders binding-aware) — ограничение снять. Изменение минимальное: убрать if-guard и возвращать `self._ctx.form_context()` безусловно.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/plugins/tab.py` — изменить только `_build_form_ctx`

**Steps:**

1. Найти метод `_build_form_ctx` (строки 119-133).

2. Заменить тело метода:
   ```python
   def _build_form_ctx(self, plugin_name: str) -> FormContext | None:
       """Собрать FormContext для binding-aware RegisterView.

       После завершения Track 2 — form_ctx передаётся для всех плагинов с registers.

       Returns:
           FormContext если доступен ActionBus и RM, иначе None.
       """
       return self._ctx.form_context()
   ```
   Параметр `plugin_name` сохраняется в сигнатуре (используется в caller'е для других целей — не ломать сигнатуру). Если параметр не используется нигде кроме whitelist — добавить `# noqa: ARG002` или удалить из сигнатуры если caller не передаёт.

3. Удалить строки pilot-комментария («Phase 2.0 pilot: whitelist плагинов»).

4. Обновить комментарий в `_on_plugin_selected` (строка 99, где упоминается Phase 2.0 pilot):
   ```python
   # Track 3.3: form_ctx передаётся для всех плагинов с registers.
   form_ctx = self._build_form_ctx(plugin_name)
   ```

**Acceptance criteria:**
- [ ] `_build_form_ctx` не содержит whitelist `robot_control`/`pilot_widgets`
- [ ] `_build_form_ctx("любой_плагин")` возвращает `FormContext | None` (зависит от AppContext)
- [ ] `ruff check multiprocess_prototype/frontend/widgets/tabs/plugins/tab.py` — 0 ошибок

**Out of scope:** не трогать `_on_plugin_selected` логику выбора RegisterView vs PluginInfoCard. Не добавлять тесты.

**Edge cases:**
- `self._ctx.form_context()` может вернуть `None` если ActionBus не инициализирован при старте. Это корректно — RegisterView с `form_ctx=None` работает через legacy путь.

**Dependencies:** Track 2 полностью завершён (все builders binding-aware)

---

## Task 3.4 — NodeInspectorPanel: условный form_ctx по типу узла

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** передать `form_ctx` в `CardsFieldFactory.create` внутри `_try_build_cards_editors` — полный для plugin-узлов, None для UI-control-узлов

**Context:** `NodeInspectorPanel._try_build_cards_editors` (строки 163-211) вызывает `CardsFieldFactory.create(field_info, parent=self._params_widget)` без `form_ctx`. Панель обслуживает разные типы узлов pipeline. Нетривиальность: не все узлы имеют plugin binding. Решение — условный form_ctx: если `AppContext` доступен и `RegistersManager` нашёл поля для процесса — считать узел plugin-bound → передавать `form_ctx`. Если поля нашлись только через fallback (params dict) — UI-control-узел → `form_ctx=None`.

Дополнительно: панель использует собственный `QFormLayout` вместо `RegisterView`. Это означает что двойной write невозможен через `RegisterView._on_editor_changed` — все сигналы подключаются вручную в `_try_build_cards_editors`. Нужно убедиться что при binding-aware editors (`change_signal=None`) сигнал `editor.change_signal.connect(...)` в строках 203-206 НЕ подключается (т.к. `change_signal is None`). Проверить существующую guard: `if editor.change_signal is not None:` (строка 202) — она уже есть, всё корректно.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py` — изменить `_try_build_cards_editors`

**Steps:**

1. Прочитать актуальное состояние файла полностью перед правками.

2. В `_try_build_cards_editors` добавить получение `form_ctx`:
   ```python
   def _try_build_cards_editors(
       self,
       process_name: str,
       params: dict[str, Any] | None,
   ) -> bool:
       if self._ctx is None:
           return False

       rm = self._ctx.registers_manager()
       if rm is None:
           return False

       fields = rm.get_fields(process_name)
       if not fields:
           return False

       # Получить form_ctx — для plugin-bound узлов передаём полный контекст.
       # Если form_context() недоступен — fallback на legacy путь (form_ctx=None).
       form_ctx = self._ctx.form_context()  # ← добавить

       from multiprocess_prototype.frontend.forms.factory import CardsFieldFactory

       for field_info in fields:
           editor = CardsFieldFactory.create(
               field_info,
               parent=self._params_widget,
               form_ctx=form_ctx,  # ← добавить kwarg
           )
           ...  # остальной код без изменений
   ```

3. Убедиться что guard `if editor.change_signal is not None:` (строка 202) остаётся — она корректно блокирует двойное подключение для binding-aware editors.

4. Добавить импорт `FormContext` в секцию TYPE_CHECKING (только для аннотации если нужна).

5. Проверить `AppContext.form_context()` — метод должен существовать. Если нет — см. edge cases.

**Acceptance criteria:**
- [ ] `CardsFieldFactory.create` вызывается с `form_ctx` kwarg в `_try_build_cards_editors`
- [ ] Для узлов где `form_context()` вернул `None` — editors создаются в legacy режиме (без binding)
- [ ] Guard `if editor.change_signal is not None:` — сохранена, не дублирует write для binding-aware editors
- [ ] `ruff check inspector_panel.py` — 0 ошибок

**Out of scope:** не рефакторить `NodeInspectorPanel` на использование `RegisterView` вместо `QFormLayout` (это отдельная задача архитектуры). Не добавлять тесты. Не менять fallback QLineEdit-режим.

**Edge cases:**
- `AppContext.form_context()` — если метод отсутствует, добавить в `AppContext` делегирующий метод (аналог PluginsTab). Перед реализацией прочитать `multiprocess_prototype/frontend/app_context.py` и убедиться в наличии метода.
- `process_name` может соответствовать процессу без plugin registers (UI-control). В этом случае `rm.get_fields(process_name)` вернёт пустой список → `return False` → fallback QLineEdit. form_ctx в этом случае не используется.
- `form_ctx` может быть `None` если ActionBus не инициализирован. `CardsFieldFactory.create(field_info, form_ctx=None)` → legacy путь. Поведение идентично текущему.

**Dependencies:** Task 3.1 (form_builder готов). Независим от 3.2, 3.3, 3.5.

---

## Task 3.5 — SystemSection: явный form_ctx=None + аудит двойной подписки

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** явно передать `form_ctx=None` в `RegisterView` в `SystemSection`; проверить и при необходимости устранить двойную подписку `editor.change_signal`

**Context:** `SystemSection.__init__` (строки 71-75) создаёт `RegisterView(field_infos, ...)` без `form_ctx` — это неявный None. Нужно сделать явным для self-documenting. Строки 90-94 подключают `editor.change_signal.connect(self._presenter.on_field_changed)` для каждого editor + `self._register_view.field_changed.connect(self._presenter.on_field_changed_action_bus)`. Это **потенциальная** двойная запись: оба сигнала могут привести к записи одного изменения дважды. Аудит при реализации обязателен.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/settings/system/section.py` — изменить

**Steps:**

1. Прочитать актуальное состояние файла полностью перед правками.

2. Изменить создание `RegisterView` — добавить явный kwarg:
   ```python
   self._register_view = RegisterView(
       field_infos,
       initial_mode=initial_mode,
       category_titles=_SECTION_TITLES,
       form_ctx=None,  # GUI-локальные настройки: binding-aware путь не используется
   )
   ```

3. Аудит двойной подписки (строки 90-94):
   - `editor.change_signal.connect(self._presenter.on_field_changed)` — вызывает `SystemSettingsPresenter.on_field_changed`
   - `self._register_view.field_changed.connect(self._presenter.on_field_changed_action_bus)` — вызывает `on_field_changed_action_bus`

   Прочитать `SystemSettingsPresenter` (`tabs/settings/system/presenter.py`) и определить:
   - Что делает `on_field_changed` — пишет в RM? в ActionBus?
   - Что делает `on_field_changed_action_bus` — пишет в ActionBus?

   Если оба метода пишут в одно место — **удалить первую подписку** (через `editor.change_signal`) и оставить только `field_changed → on_field_changed_action_bus`. Если методы делают разное (например, один обновляет UI/validation, другой записывает в RM) — обе подписки оставить, но добавить комментарий поясняющий зачем.

4. Если первая подписка (цикл по editors) удаляется — убедиться что `set_dirty_indicator` / `show_validation_error` вызываются через `on_field_changed_action_bus` или другой обработчик.

5. Добавить комментарий к `form_ctx=None`:
   ```python
   # form_ctx=None: SettingsSystem не использует plugin binding.
   # Поля GUI-локальные (тема, i18n, режим отображения).
   # Legacy путь: editor.change_signal → presenter.on_field_changed_action_bus.
   ```

**Acceptance criteria:**
- [ ] `RegisterView(..., form_ctx=None)` — явный kwarg присутствует в коде
- [ ] Двойная подписка отсутствует (или обоснована комментарием если намеренная)
- [ ] `SystemSettingsPresenter` читает изменения ровно один раз на событие
- [ ] `ruff check section.py` — 0 ошибок

**Out of scope:** не рефакторить `SystemSettingsPresenter`. Не мигрировать SystemSection на plugin binding (GUI-локальное состояние — legacy путь навсегда по решению rollout-finish.md). Не добавлять тесты.

**Edge cases:**
- Если `on_field_changed` используется для dirty-флага/валидации а `on_field_changed_action_bus` для записи — оба нужны. Удаление первого сломает UX. Убедиться в правильности решения через чтение presenter'а **перед** удалением.
- После удаления цикла `for editor in self._register_view.editors().values()` — убедиться что build_ui корректно вызывается до того как editors заполнены (порядок __init__ не нарушен).

**Dependencies:** нет (независимая задача)

---

## Acceptance вся Track 3

- [ ] `RegisterView` создаётся с явным `form_ctx` (полным или `None`) во всех 4 caller'ах: ServicesTab, PluginsTab, SystemSection, NodeInspectorPanel (через factory)
- [ ] `build_form_for_register` и `build_table_for_register` принимают `form_ctx: FormContext | None = None`
- [ ] `PluginsTab._build_form_ctx` без pilot whitelist — возвращает `self._ctx.form_context()` для всех плагинов
- [ ] `ServicesTab._build_service_page` передаёт `form_ctx` в `RegisterView`
- [ ] `NodeInspectorPanel._try_build_cards_editors` передаёт `form_ctx` в `CardsFieldFactory.create`
- [ ] `SystemSection` — явный `form_ctx=None`; двойная подписка отсутствует или обоснована
- [ ] `yaml_io` — не изменён (нет связи с form_ctx)
- [ ] `grep -r "CardsFieldFactory.create" multiprocess_prototype/` — все вызовы либо передают `form_ctx`, либо это standalone-утилиты где legacy путь намеренный
- [ ] `grep "form_ctx=None" multiprocess_prototype/frontend/widgets/tabs/settings/` — только SystemSection (self-documenting)
- [ ] `pytest multiprocess_prototype/frontend/` — все существующие тесты PASSED (регрессия)
- [ ] `python scripts/validate.py` — зелёный
- [ ] `python multiprocess_prototype/run.py` — стартует (manual smoke)

---

## Commit messages (2 коммита)

### Коммит 1: Фундамент (form_builder)

```
refactor(frontend): Track 3.1 — form_builder kwarg form_ctx

- build_form_for_register: добавлен form_ctx: FormContext | None = None
- build_table_for_register: аналогично; проброс в CardsFieldFactory.create
- backward-compat: все существующие callers без изменений (default None)

Why: form_builder — standalone-альтернатива RegisterView; должна поддерживать
     тот же binding-aware путь для будущих callers без RegisterView
Layer: prototype
Refs: plans/frontend-widgets-cleanup/track-3-callers-migration.md
Risk: low — только добавление kwarg, legacy путь не изменён
Reversible: yes
```

### Коммит 2: Caller migrations

```
refactor(frontend): Track 3.2-3.5 — callers migration на FormContext

- ServicesTab: RegisterView получает form_ctx для всех service-плагинов
- PluginsTab: убран pilot whitelist (_build_form_ctx → все плагины)
- NodeInspectorPanel: CardsFieldFactory.create получает form_ctx
- SystemSection: явный form_ctx=None + аудит двойной подписки
- yaml_io: без изменений (read-only YAML, form_ctx не нужен)

Why: завершение цепочки Track 3 — все callers явно декларируют отношение
     к FormContext; plugin-callers получают binding-aware путь,
     GUI-локальные — legacy (form_ctx=None навсегда)
Layer: prototype
Refs: plans/frontend-widgets-cleanup/track-3-callers-migration.md, plans/frontend-widgets-cleanup/rollout-finish.md
Risk: medium — ServicesTab и NodeInspectorPanel изменяют поведение записи
     (legacy field_changed → ActionBus vs form_ctx.write); smoke-тест обязателен
Reversible: yes
Tested: frontend/regression passed
```

---

## Verification команды

```powershell
# 1. Проверить form_builder сигнатуры
Select-String -Pattern "form_ctx" `
  multiprocess_prototype/frontend/forms/form_builder.py

# 2. Проверить что все RegisterView() и CardsFieldFactory.create() в callers имеют form_ctx
Select-String -Pattern "RegisterView\(" `
  multiprocess_prototype/frontend/widgets/tabs/services/tab.py, `
  multiprocess_prototype/frontend/widgets/tabs/plugins/tab.py, `
  multiprocess_prototype/frontend/widgets/tabs/settings/system/section.py

# 3. Проверить CardsFieldFactory.create в inspector
Select-String -Pattern "CardsFieldFactory.create" `
  multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py

# 4. Проверить что pilot whitelist удалён из PluginsTab
Select-String -Pattern "robot_control|pilot_widgets" `
  multiprocess_prototype/frontend/widgets/tabs/plugins/tab.py

# 5. Проверить явный form_ctx=None в SystemSection
Select-String -Pattern "form_ctx=None" `
  multiprocess_prototype/frontend/widgets/tabs/settings/system/section.py

# 6. Ruff check всех изменённых файлов
ruff check `
  multiprocess_prototype/frontend/forms/form_builder.py `
  multiprocess_prototype/frontend/widgets/tabs/services/tab.py `
  multiprocess_prototype/frontend/widgets/tabs/plugins/tab.py `
  multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py `
  multiprocess_prototype/frontend/widgets/tabs/settings/system/section.py

# 7. Регрессия frontend тестов
pytest multiprocess_prototype/frontend/ -v

# 8. Общая валидация
python scripts/validate.py
python scripts/run_framework_tests.py
```

---

## Риски и ограничения

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| **ServicesTab двойной write** — `field_changed` Signal + `form_ctx.write` оба пишут в ActionBus | Средняя | Убедиться что binding-aware builders возвращают `change_signal=None` → RegisterView не эмитит `field_changed` для этих полей. Проверить при реализации Task 3.2 шаг 4. |
| **NodeInspectorPanel** — `AppContext.form_context()` метод может отсутствовать | Средняя | Читать `app_context.py` перед Task 3.4; если нет — добавить делегирующий метод. |
| **SystemSection двойная подписка** — удаление `on_field_changed` сломает dirty-флаг или валидацию | Средняя | Читать `SystemSettingsPresenter` **до** удаления подписки. Только если оба метода делают одно — удалять. |
| **PluginsTab pilot whitelist** — плагины без RegistersManager-регистрации получат form_ctx и упадут | Низкая | `_ctx.form_context()` возвращает None если RM недоступен; RegisterView корректно обрабатывает form_ctx=None. |
| **NodeInspectorPanel** — узлы без registers (UI-control) получат form_ctx=None → legacy путь | Нет риска | `rm.get_fields(process_name)` пустой → return False → fallback QLineEdit; form_ctx не задействован. |
| **form_builder shared-editors-режим** — если editors переданы извне, новый form_ctx kwarg игнорируется | Осознанное ограничение | Документировано в docstring. Shared-editors создаются caller'ом до вызова builder; если нужен form_ctx — создавать editors через RegisterView, не через standalone-функции. |
