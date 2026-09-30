# actions_module — Архитектурные решения

## ACT-001: `set_pre_execute_hook` — минимальное расширение ActionBus для pre-execute блокировки

**Дата:** 2026-05-11
**Статус:** Принято
**PR:** PR2 auth-rbac (Group A)

### Контекст

Для блокировки мутаций до авторизации (PreAuthGuard) нужна точка перехвата
в ActionBus перед вызовом handler.apply(). Два варианта:
1. Один метод `set_pre_execute_hook(hook, on_blocked)` в ActionBus.
2. HandlerProxy-обёртки в bus_factory.

### Решение

Вариант 1 — один метод `set_pre_execute_hook`. Hook вызывается в `execute()`
перед `handler.apply()`. Если hook вернул False — apply не вызывается,
undo_stack не трогается, опционально вызывается on_blocked.

`undo()` и `redo()` хук НЕ проходят — откат уже совершённого действия не блокируется.

Один хук (last-write wins). Если уже установлен — заменяется.

### Альтернативы

- HandlerProxy: proxy обёртки дублируются для каждого handler-а, при добавлении
  нового handler блокировка теряется. Hook — единственная точка входа.
- Middleware-stack: избыточно для одного хука. Если в будущем понадобится
  цепочка — вводится middleware-stack в PR4.

### Последствия

- ActionBus остаётся простым и тестируемым.
- Приложение (prototype) регистрирует хук через bus_factory.
- Фреймворк не знает про конкретную auth-логику.

---

## ACT-002: `SnapshotHistory[T]` — generic snapshot-реализация-блок под контракт `UndoRedoController`

**Дата:** 2026-06-18
**Статус:** Принято
**Refs:** docs/audits/2026-06-18_command-undo-system.md, memory `feedback_framework_first`

### Контекст

Undo/redo — framework-концерн (нужен любому проекту). Контракт `UndoRedoController`
(`frontend_module/.../tab_layout_protocol.py`) уже допускает несколько реализаций. PATCH-движок
`ActionBus` жил во framework, а snapshot-логика была заперта в прототипе
(`adapters/dispatch/history.py::ProjectHistory`, привязан к `Project`). Конструктор должен
владеть ОБЕИМИ реализациями (правило framework-first): patch — для простых/сложных проектов,
snapshot — для проектов с чистым immutable-агрегатом.

### Решение

Вынести generic-ядро snapshot-стека во framework как `SnapshotHistory[T]` (+ `SnapshotEntry`)
в `actions_module` — рядом с patch-движком `ActionBus`. Стек параметризуется типом агрегата T
(immutable), Qt-free, без app-импортов. Прототип становится тонким потребителем:
`ProjectHistory(SnapshotHistory[Project])` переопределяет только `entries()` (проекция в
доменный `HistoryEntry`). Семантика 1:1 с прежним `ProjectHistory` (coalescing, max_history,
идентичность снимков) — подтверждено characterization-тестами.

`SnapshotHistory` — это блок ХРАНЕНИЯ (record/take_undo/take_redo/navig), а не контроллер:
контроллер (orchestrator) строится поверх и реализует `UndoRedoController`.

### Альтернативы

- Оставить snapshot-логику в прототипе — нарушает framework-first: конструктор без snapshot-блока.
- Вынести весь `CommandDispatcherOrchestrator` — отвергнуто: он привязан к домену
  (`Project.apply`, 15-арочный match-case) — это домен, а не generic-движок.

### Последствия

- Framework владеет двумя реализациями undo за одним контрактом (patch + snapshot).
- Прототип-сторона тоньше; 0 обратных импортов (generic над T).
- Следующий проект получает snapshot-undo переиспользованием `SnapshotHistory[ЕгоАгрегат]`.

---

## ACT-003: выбор вида UI как часть записи `SnapshotHistory` (непрозрачный memo)

**Дата:** 2026-09-30
**Статус:** Принято
**Refs:** plans/undo-restores-selection.md (Task 1.1), ACT-002

### Контекст

Отмена/повтор во вкладке pipeline возвращали данные (Project), но не выбор узлов: после `undo`
выбор оставался таким, каким его успел изменить пользователь, а reload сцены сохранял только
уцелевших из текущего выбора (G.6.3). Выбор — не часть Project и не должен попадать в домен.

### Решение

`record()` принимает `memo_before` / `memo_after` — непрозрачные для истории объекты
(по умолчанию `None`); запись хранит их рядом со снимками. `take_undo_with_memo()` возвращает
`(before, memo_before)`, `take_redo_with_memo()` — `(after, memo_after)`; `take_undo()` /
`take_redo()` остаются тонкими обёртками, отдающими только снимок.

- **Coalescing:** как и для снимков — `memo_before` берётся у самой первой записи серии
  ДОСЛОВНО (даже если он `None`), `memo_after` — у последней. Серия откатывается одним шагом
  к виду до первой правки.
- **Память:** memo живут только внутри записей; обрезка по `max_history` и `clear()` их
  отпускают, отдельных ссылок история не держит.
- **Интерпретацию memo делает потребитель.** История не читает memo и не зависит от Qt;
  прототип кладёт туда `PipelineSelectionMemo` (см. `CommandDispatcherOrchestrator`
  `view_state` / `add_view_restore_listener`).

### Альтернативы

- Хранить выбор в `Project` — отвергнуто: вид UI смешался бы с доменом и сериализацией.
- Отдельный стек выбора рядом с историей — отвергнуто: рассинхронизируется при coalescing,
  обрезке и `clear()`, тогда как запись уже владеет своим временем жизни.

### Последствия

- Вызовы без memo ведут себя как раньше (`None`).
- Запись «выбор до» первой правки серии координируется тем же правилом coalescing, что и снимок.
