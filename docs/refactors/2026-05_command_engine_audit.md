# Примирение движка команд/undo — P1.1 read-only audit

- **Дата:** 2026-05-29
- **Статус:** DRAFT (read-only investigation, без правок кода)
- **Plan:** [`plans/2026-05-29_constructor-maturity/phase-1-command-engine.md`](../../plans/2026-05-29_constructor-maturity/phase-1-command-engine.md) (Task P1.1)
- **Master:** [`plans/2026-05-29_constructor-maturity/plan.md`](../../plans/2026-05-29_constructor-maturity/plan.md)
- **Ветка:** `refactor/cross-tab-architecture` (P1 ещё не стартовал; ветка `refactor/constructor-maturity` создаётся при старте P1.2)

## Preamble

Документ закрывает фактами открытый вопрос плана: **реально ли** мутации топологии
(теперь через domain-dispatch) потеряли RBAC-гейтинг и audit-лог, и кто фактически
зависит от framework `ActionBus`. Все утверждения — с `file:line`-доказательствами.

> **Ключевой переворот премисы.** План P1 исходит из того, что «рядом живут две
> системы команд/undo». По факту кода в проде работает **одна** (domain-dispatch).
> `ActionBus` в проде — осиротевший: создан, но не управляет приложением, а его
> «зрелые фичи» (audit, SQL-лог) **никогда не были подключены** — ни до, ни после
> cross-tab. Это меняет постановку с «заменить движок» на «доудалить мёртвый путь +
> решить судьбу framework-инфраструктуры вокруг него».

---

## Summary — вердикт

| Вопрос | Вердикт |
|---|---|
| Топология потеряла **RBAC**? | **Частично.** RBAC не исчез — переехал на widget/tab-уровень (`permission_gate` + `_can_edit()`). Но покрытие **неполное**: тулбар/drop/wire гейтятся, а **field-edit (`SetPluginConfig`) — нет**. |
| Топология потеряла **audit-лог**? | **Нет, потому что его не было.** `AuditWriter`/`ActionLogWriter`/`set_log_writer` в проде **не инстанцируются вообще**. P1.3 «вернуть audit» — это **новая фича**, а не восстановление регрессии. |
| Сколько живых потребителей **ActionBus** в проде? | **Ноль исполняющих.** `_legacy_action_bus` ни на что не подписан; единственный `.execute()` (roles_panel) защищён `bus is None`. |
| `Services/sql/action_log` — продукт или legacy? | **Полностью построен, в проде не подключён.** ~5 файлов протестированной, но мёртвой инфраструктуры. |
| Кто ещё завязан на ActionBus? | Только **framework-forms** (`FormContext.write → ActionBus`) — но прототип их обходит (`form_ctx=None` везде). Живёт лишь в тестах. |
| **Рекомендация** | **Вариант A** (один движок = domain-dispatch + pluggable middleware) с двумя поправками (см. ниже). |

---

## Q1. Audit-лог: кто подключает writer и что доходит до SQL

**Факт: в проде audit-путь не существует.**

- `create_action_bus(...)` в проде вызывается **без** `audit_writer` и `state_store` →
  `AuditMiddleware` не регистрируется ([`app.py:411-417`](../../multiprocess_prototype/frontend/app.py#L411-L417)).
  Сама фабрика навешивает middleware только при наличии обоих аргументов
  ([`bus_factory.py:86-91`](../../multiprocess_prototype/frontend/actions/bus_factory.py#L86-L91)).
- `bus.set_log_writer(...)` в проде **не вызывается ни разу** (grep по prod-коду — 0
  совпадений; определение — [`bus.py:123`](../../multiprocess_framework/modules/actions_module/bus.py#L123)).
- `AuditWriter` / `ActionLogWriter` / `ActionLogRepository` в `app.py` **не
  инстанцируются** (grep по `multiprocess_prototype/**/app.py` — 0 совпадений).

**Вывод:** топологические мутации не попадали в `action_log` ни ДО cross-tab, ни
сейчас — путь не был замкнут. «Потеря audit» — потеря того, чего в проде не было.

## Q2. RBAC: чем гейтятся мутации топологии сейчас

**Факт: RBAC переехал на widget-уровень, но покрытие неполное.**

Гейтится через `_can_edit()` → `has_permission("tabs.pipeline.edit")`
([`pipeline/tab.py:290-292`](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py#L290-L292)):

| Точка входа мутации | Гейт? | Источник |
|---|---|---|
| Тулбар (`delete`, `auto_layout`, `save_recipe`, `launch_recipe`) | ✅ | [`tab.py:299`](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py#L299) (+ `_MUTATING_ACTIONS` [`tab.py:68`](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py#L68)) |
| D&D плагина → `AddProcess` | ✅ | [`tab.py:334`](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py#L334) |
| Создание wire → `ConnectWire`/`BindDisplay` | ✅ | [`tab.py:343`](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py#L343) |
| **Field-edit → `SetPluginConfig`** | ❌ **НЕТ** | [`presenter.py:122-159`](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L122-L159) |

`panel.field_changed` подключён напрямую к `presenter._on_inspector_field_changed`
([`presenter.py:118`](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L118)),
который диспатчит `SetPluginConfig` без проверки `_can_edit()` — только `_suppress`
re-entry guard. Виджеты-редакторы инспектора создаются без permission-binding
([`inspector_panel.py:541-546`](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py#L541-L546)).

**Вывод (конкретная дыра):** пользователь с `tabs.pipeline.view`, но без
`tabs.pipeline.edit`, видит таб, выбирает ноду и может **изменить config-поле** —
dispatch пройдёт. Структурные мутации (add/remove/wire) при этом закрыты.

> **Остаточная неопределённость:** не проверено, не дизейблит ли инспектор поля
> на основе permission где-то ещё (в build-пути гейта нет). Закрыть до P1.3.

## Q3. Живые потребители ActionBus — inventory

**Факт: исполняющих потребителей в проде — ноль.**

| Потребитель | `rm`? | patch-undo? | coalescing? | Статус в проде |
|---|---|---|---|---|
| `_legacy_action_bus` (app.py) | да | — | — | **осиротел** — ни на что не подписан, undo приложения на domain ([`app.py:399-417`](../../multiprocess_prototype/frontend/app.py#L399-L417), [`app.py:493`](../../multiprocess_prototype/frontend/app.py#L493)) |
| `ROLE_UPDATE` (roles_panel) | да | да | нет | **мёртв** — `RolesPanel(auth_ctx, None)` ([`_sections.py:119`](../../multiprocess_prototype/frontend/widgets/tabs/settings/_sections.py#L119)) → ранний `return` при `bus is None` ([`roles_panel.py:200`](../../multiprocess_prototype/frontend/widgets/tabs/settings/administration/roles_panel.py#L200)) |
| `NODE_MOVE` | нет (GUI-only) | нет | нет | handler зарегистрирован ([`bus_factory.py:75-77`](../../multiprocess_prototype/frontend/actions/bus_factory.py#L75-L77)), но `.execute(NODE_MOVE)` в проде не зовётся |
| `RECIPE_APPLY` | да | — | — | handler зарегистрирован ([`bus_factory.py:62`](../../multiprocess_prototype/frontend/actions/bus_factory.py#L62)), `.execute(RECIPE_APPLY)` в проде не зовётся; recipe-активация идёт через domain (G.6.5) |
| `FIELD_SET` / topology handlers | да | да | да | зарегистрированы ([`bus_factory.py:61-72`](../../multiprocess_prototype/frontend/actions/bus_factory.py#L61-L72)), `.execute()` в проде не зовётся (field-edit → domain `SetPluginConfig`) |

Единственный `.execute()` в prod-коде — [`roles_panel.py:206`](../../multiprocess_prototype/frontend/widgets/tabs/settings/administration/roles_panel.py#L206),
недостижим (`bus is None`). Все прочие `bus.execute/undo/redo` — в тестах.

## Q4. Coalescing / undo_to — уникальные фичи ActionBus

- `undo_to(action_id)` ([`bus.py:380`](../../multiprocess_framework/modules/actions_module/bus.py#L380)) — **в проде не используется** (нет call-sites вне тестов). У `ProjectHistory` аналога нет.
- Coalescing ActionBus ([`bus.py:249-260`](../../multiprocess_framework/modules/actions_module/bus.py#L249-L260)) — **не используется** (шина мертва). Domain-dispatch имеет **свой** coalescing через `coalesce_key` ([`command_dispatcher.py:137-143`](../../multiprocess_prototype/adapters/dispatch/command_dispatcher.py#L137-L143)), и он **живой** (slider-burst в field-edit, [`presenter.py:158`](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L158)).

**Вывод:** фича-разрыв (`undo_to`) реален как код, но в проде не востребован → не блокер миграции.

## Q5. action_log как продукт — кто читает

- Пишущий путь: построен (`ActionLogWriter` буфер+flush+rotation [`log_writer.py`](../../Services/sql/action_log/log_writer.py)), но **не запущен** (Q1).
- Читающий путь: `ActionLogRecovery` ([`recovery.py`](../../Services/sql/action_log/recovery.py)) восстанавливает state из лога — **в проде не вызывается**. UI History-вкладка читает **domain-историю**, не `action_log` (см. Q6).

**Вывод:** `action_log` — завершённая, протестированная, **полностью неподключённая** подсистема. Требует продуктового решения: требование (комплаенс-журнал) или dead-code на удаление.

## Q6. Дубль change-callbacks — где подписан UI

- Глобальный undo/redo (Ctrl+Z/Y): `window.set_undo_controller(app_services.commands)` — **domain** ([`app.py:493`](../../multiprocess_prototype/frontend/app.py#L493)).
- History-вкладка: переведена на domain `CommandDispatcher`; фантомный `services.commands.action_bus()` (всегда None) удалён ([`history/presenter.py:11-14`](../../multiprocess_prototype/frontend/widgets/tabs/settings/history/presenter.py#L11-L14)).
- `CommandDispatcherOrchestrator.add_change_callback` ([`command_dispatcher.py:210`](../../multiprocess_prototype/adapters/dispatch/command_dispatcher.py#L210)) структурно зеркалит ActionBus → удовлетворяет framework `UndoRedoController`.

**Вывод:** двойной подписки нет. UI единообразно слушает domain.

---

## Скрытая связка: framework-forms ⟷ ActionBus

`FormContext.write` жёстко завязан на `ActionBus` в своём «production-пути»
([`frontend_module/forms/form_context.py:51-98`](../../multiprocess_framework/modules/frontend_module/forms/form_context.py#L51-L98)),
и вокруг него построены framework-компоненты (combo/checkbox/spinbox/slider/numeric).
**Но прототип этот путь обходит** — `form_ctx=None` везде:

- [`inspector_panel.py:539`](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py#L539) («Пока — None (legacy путь)»)
- [`plugins/_sections.py:214`](../../multiprocess_prototype/frontend/widgets/tabs/plugins/_sections.py#L214)
- [`settings/system/section.py:95`](../../multiprocess_prototype/frontend/widgets/tabs/settings/system/section.py#L95)

**Следствие для P1.4/P2:** убийство ActionBus оставляет framework-forms на мёртвом
движке. Варианты: (a) перенаправить `FormContext` на domain-dispatch — но `write`
это generic field-set, а domain ждёт typed-команды (это уже **P2**: domain-driven
Inspector, `FieldMeta`); (b) оставить framework-forms by design на узком ActionBus-слое.
**P1 и P2 связаны через вопрос форм** — порядок «P1 → P2» это учитывает.

---

## Сравнение движков (для решения)

| | domain-dispatch | framework ActionBus |
|---|---|---|
| Типобезопасность | **typed** `ProjectCommand` (pyright) | stringly-typed `action_type` + dict-патчи |
| Undo-модель | **snapshot** (before/after) — корректен, не рассинхронится | patch-undo (ручные forward/backward) — экономнее, **хрупок** |
| Чистота | `Project.apply()` pure → events | `handler.apply(action, rm)` — завязка на GUI-backend `rm` |
| Интеграция | SSOT, EventBus, cross-tab | в проде не подключён |
| Зрелые фичи | базовый undo/redo/coalesce | RBAC-hook, audit-hook, SQL-persist, `undo_to` — **все не обкатаны** |
| К framework | завязан на app-specific `Project` | **уже generic, уже во framework** |

---

## Рекомендация: вариант A + 2 поправки

**A — один движок editor-домена = domain-dispatch + pluggable middleware.** ActionBus
не «замещается» (он уже не правит приложением) — доудаляется мёртвый путь, а его
ценные идеи (auth pre-hook, audit post-hook) переносятся как **переиспользуемые
middleware** поверх dispatch.

**Поправка 1 — расщепить P1.3.**
RBAC не «восстанавливать срочно». Сначала закрыть Q2-дыру: добавить `_can_edit()`-гейт
на field-edit путь (`SetPluginConfig`) — это узкий точечный фикс, а не «возврат RBAC».
Системно — pre-dispatch middleware (P1.2) как единая точка авторизации всех команд.

**Поправка 2 — audit как продуктовое решение, не как регрессия.**
До P1.3 ответить: журнал всех действий — требование (комплаенс) или нет?
- **Да** → P1.3 поднимает `AuditMiddleware` (post-dispatch) + замыкает `action_log`. Это **новая фича**.
- **Нет** → удалить `Services/sql/action_log` + audit middleware целиком (самый чистый выигрыш по dead-code во всём рефакторинге).

---

## Долгосрочно: domain-dispatch как единственный движок — это лучший подход?

**Да — как фундамент editor-домена.** Snapshot-undo + typed commands + pure
`apply→events` дают корректность и типобезопасность, которых patch-undo ActionBus
структурно не даёт; движок уже SSOT и интегрирован с EventBus/cross-tab.

**Но «лучший вообще» выполняется только при трёх условиях:**
1. dispatch получает **pluggable middleware** (P1.2) — иначе теряется расширяемость
   (auth/audit), которую обещал ActionBus, и «один движок» = регресс по возможностям.
2. сознательно решён вопрос **framework-forms** (перенаправить `FormContext` на
   dispatch — это P2 — либо депрецировать).
3. **audit** закрыт как продуктовое решение.

**Watch-list на перспективу (не блокеры сейчас):**
- **Память snapshot-undo:** хранит полный `Project` × `max_history` (50,
  [`command_dispatcher.py:79`](../../multiprocess_prototype/adapters/dispatch/command_dispatcher.py#L79)).
  Сейчас `Project` мал — ок. При росте модели пересмотреть (structural sharing / diff-snapshot).
- **Generic vs typed для framework-reuse:** typed-команды app-specific. Выносить во
  framework (P6, по триггеру app #2) нужно **механику** (dispatch/history/middleware-контракт),
  а команды (`AddProcess`/`ConnectWire`) остаются прикладными. Это и есть «движок vs модель».

---

## Вход в P1.2–P1.4

- **P1.2** Middleware-контракт: `pre_dispatch(cmd) -> bool` / `post_dispatch(cmd, events) -> None`
  (Protocol, без логики). Симметрия `add_change_callback`, который уже есть.
- **P1.3** На dispatch: pre-hook (RBAC, закрывает Q2-дыру) + post-hook (audit — **если** Q5
  решён как требование). ActionBus-версии не трогать до P1.4.
- **P1.4** Судьба ActionBus: т.к. живых потребителей 0 (Q3), а forms обходят его (form_ctx=None) —
  кандидат на изоляцию/удаление вместе с `frontend/actions/` и (опц.) `Services/sql/action_log`.
  Решение зависит от P2 (framework-forms) — зафиксировать явно, big-bang запрещён.

**Открытые вопросы для владельца перед P1.3:**
1. Нужен ли persistent журнал действий (`action_log`) как продуктовое требование?
2. ОК ли закрыть Q2-дыру (field-edit RBAC) точечно сейчас, до системного middleware?
