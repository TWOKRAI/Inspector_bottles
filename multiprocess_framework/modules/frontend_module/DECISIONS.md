# `frontend_module` — Архитектурные решения

PySide6-фреймворк виджетов с привязкой к `data_schema_module` (`SchemaBase` + `FieldMeta` + `FieldRouting`). Каждое решение зафиксировано как **ADR** в глобальном `multiprocess_framework/DECISIONS.md`.

> **Этот файл — индекс**, а не дубль. Каждая запись ниже ссылается на полный текст в глобальном `DECISIONS.md`.

---

## Реестр

| ADR | Тема | Глобальный текст |
|-----|------|------------------|
| ADR-033 | `frontend_module` и `shared_registers` — фундамент UI-фреймворка | `../../DECISIONS.md#adr-033` |
| ADR-034 | `FrontendManager` — единая точка входа (`BaseManager`) | `../../DECISIONS.md#adr-034` |
| ADR-035 | `FrontendRegistersBridge` — связь frontend с backend через регистры | `../../DECISIONS.md#adr-035` |
| ADR-036 | Конфигурация frontend — hot-reload без перезапуска | `../../DECISIONS.md#adr-036` |
| ADR-037 | Рефакторинг `frontend_module` и прототипа (2026-03-18) | `../../DECISIONS.md#adr-037` |
| ADR-042 | `ProcessModule` как `IRouterLike` для `FrontendManager` | `../../DECISIONS.md#adr-042` |
| ADR-043 | Унифицированные конфиги frontend на `SchemaBase` + `FieldMeta` | `../../DECISIONS.md#adr-043` |
| ADR-044 | Реорганизация `components/` и паттерн «конфиг рядом с виджетом» | `../../DECISIONS.md#adr-044` |
| ADR-053 | Прототип — один `GuiProcess`, импорты регистров, `FrontendManager` runtime | `../../DECISIONS.md#adr-053` |
| ADR-084 | `FrontendAppContext` — явный контекст вкладок без слияния слоёв | `../../DECISIONS.md#adr-084` |
| ADR-090 | `frontend/coordinators`, границы виджет / Presenter / `managers` | `../../DECISIONS.md#adr-090` |
| ADR-095 | `StructuredTwoLevelTreeWidget` — группа → строки | `../../DECISIONS.md#adr-095` |
| ADR-097 | Touch-клавиатура — проброс из `FrontendConfig`, делегат по колонкам | `../../DECISIONS.md#adr-097` |

---

## Краткая суть (без дублирования полного текста)

**1. Конфиг рядом с виджетом (ADR-044).** Каждый виджет в `components/<name>/` имеет свой `config.py` с `SchemaBase`-наследником. Конфиг не лежит отдельно в `configs/` — это нарушает принцип «модуль = одна папка».

**2. Виджет ↔ регистр (ADR-035).** Виджет связывается с полем регистра через `FieldRouting.channel` + `FieldMeta`. `FrontendRegistersBridge` подписывается на изменения регистра и обновляет UI; обратно — через `set_field_value()` в `RegistersManager`.

**3. `FrontendManager` — `BaseManager` (ADR-034).** Точка входа в подсистему фронтенда из процесса. Управляет окнами, виджетами, привязкой к регистрам.

**4. Координаторы (ADR-090).** `frontend/coordinators/` — слой между виджетом, Presenter и managers. Виджет не знает про Router/IPC — координатор делегирует действия в backend.

**5. Hot-reload конфигов (ADR-036).** Изменение `FrontendConfig` через `ConfigManager.subscribe()` пересобирает виджеты без перезапуска процесса.

---

## Где искать детали

- Архитектура виджетов — `README.md` модуля.
- Cookbook — `WIDGET_COOKBOOK.md` модуля (примеры компонентов).
- Полный текст ADR — глобальный `multiprocess_framework/DECISIONS.md`.
- Дорожная карта — `multiprocess_framework/docs/FRONTEND_COMMAND_LAUNCHER_ROADMAP.md`.

---

## Локальные решения (FE-серия)

> Записи FE-серии охватывают тему RBAC/Auth-интеграции в frontend_module (PR1 Group C).
> Глобальный индекс — `multiprocess_framework/DECISIONS.md` (обновляется через `python -m scripts.sync`).

### FE-001: Расширение `AccessContext` — именованные permissions + role_name (2026-05-11)

**Контекст.** `AccessContext` хранил только числовой `level` + булевые флаги. Для RBAC нужны именованные права.

**Решение.** Добавлены поля `permissions: frozenset[str]` и `role_name: str` после существующих полей (`level, bypass_readonly, show_hidden`) — позиционные вызовы `AccessContext(5, True, True)` сохраняются без изменений. `frozenset` выбран как immutable + hashable. Сериализация через `to_dict()` / `from_dict()`: permissions → sorted list[str] (детерминизм).

**Backward compat.** `from_dict({})` без ключей permissions/role_name → дефолтные значения. Конструктор без новых полей работает. Существующие тесты не тронуты.

**Альтернативы.** `list[str]` — нет, не hashable. `set[str]` — нет, mutable. Отдельный класс RBAC-контекста — избыточно для PR1.

---

### FE-002: `AccessTrait` двухосевая модель view/edit (2026-05-11)

**Контекст.** Старый `AccessTrait` знал только `can_modify()` через числовой level. RBAC требует отдельно `can_view()` и `can_modify()`.

**Решение.** Добавлены параметры `required_view_permission` и `required_edit_permission`. Логика:
- `can_view()`: если perm задан → `ctx.has_permission(perm)`, иначе `True`.
- `can_modify()`: coherence invariant `edit ⇒ view` (нет view → нет edit); если edit_perm задан → permission check; иначе legacy `ctx.level >= N OR ctx.bypass_readonly`.

**Backward compat.** Первый позиционный аргумент → `legacy_required_level`. Kwarg `required_level=N` → `DeprecationWarning` + работает. `update(int)` → `DeprecationWarning` + создаёт минимальный `AccessContext(level=N)`. `update(AccessContext)` → новый путь без warning. `set_required_level()` — сохранён.

**Coherence invariant.** `can_modify() → can_view()` — enforced в коде: если `can_view() == False`, `can_modify()` возвращает `False` немедленно.

---

### FE-003: Централизация access policy в `BaseConfigurableWidget._apply_access` (2026-05-11)

**Контекст.** До PR1 каждый виджет сам решал что делать при смене уровня доступа. Нет единого места для `setVisible/setEnabled/readOnly+QSS`.

**Решение.** Добавлен метод `_apply_access()` в `BaseConfigurableWidget`. Логика: `can_view==False` → `setVisible(False)`; `can_view==True` → `setVisible(True)`, `setEnabled(can_modify())`, `setProperty("readOnly", not can_modify())` + QSS repolish через `style().unpolish/polish`. Метод защищён guard'ом `if not hasattr(self, "_trait") or self._trait is None`.

`_update_access_level()` сохранён как deprecated alias с `DeprecationWarning`, внутри обновляет trait через legacy путь и вызывает `_apply_access()`.

**Почему repolish.** QSS-селектор `[readOnly="true"]` читается только при repolish — без него смена свойства не отражается в стилях.

---

### FE-004: GUI-контракт request/response для дискретных команд (2026-06-07)

**Контекст.** GUI слал команды бэкенду fire-and-forget и не знал результат (активация рецепта «молча» падала или успевала — UI не отличал). Транспорт request/response уже существовал (ADR-005, correlation_id), но GUI-сторона его не использовала.

**Решение.** Дискретные команды GUI→PM (активация рецепта, start/stop/restart, replace_blueprint) идут **request/response** — GUI узнаёт реальный результат. Высокочастотный **field-write остаётся fire-and-forget** (request на каждую правку слайдера = блокировка). Контракт потоков: `request()` выполняется на **worker-потоке** (`RequestRunner` поверх `QThreadPool`, паттерн `DataReceiverBridge`), результат маршалится в **main-thread сигналом** (AutoConnection) — никакого прямого доступа к виджетам с воркера. Timeout щедрый (30s); слепое ожидание уберёт lifecycle-прогресс поверх того же канала (`request(on_progress=...)`).

**Реализация.** `CommandSender.request_command/request_system_command` + `IRequestingProcess` (framework, `deae8b91`); `RequestRunner` + `ProcessManagerProxy.*_async(on_result)` (prototype, `e9e29f71`); presenter активации рецепта (`c4894133`). Авто-reply транспортом по `request_id` даёт паритет с fire-and-forget (no-op без correlation).

**Альтернативы.** `request()` из main-thread — отвергнуто (фриз UI). Request для field-write — отвергнуто (блокировка hot-path). Модальный диалог результата — отвергнуто (`c4894133` non-modal, не рвёт поток работы).
