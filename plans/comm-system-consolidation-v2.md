> ⚠️ **УСТАРЕЛО / SUPERSEDED (2026-06-02).** Это промежуточный analysis-grade черновик (собран вручную, пока фазы 3–4 не прошли).
> Актуальная **верифицированная** версия — [`plans/comm-system-target-architecture.md`](comm-system-target-architecture.md) (фаза 3 опровергла часть выводов ниже: RolesPanel «1 execute» → 0; «90% cross-machine» снято; Modbus INBOUND сломан; 5 фич ActionBus — `capability-to-build`, не absorbed). Этот файл оставлен только для истории; работать по target-architecture.

# Консолидация систем коммуникации — v2 (унификация вокруг RouterManager)

> **Источник:** мульти-агентный workflow `comm-arch-unification-v2` (2026-06-02).
> **Готовность:** фаза 1 (карты 15 подсистем) ✅ · фаза 2 (8 сквозных анализов) ✅ · фаза 3 (адверсариальная проверка claim'ов) ⏳ не завершена · фаза 4 (синтез) — этот документ собран вручную из результатов фаз 1–2.
> **Статус честности:** выводы — **analysis-grade**. Где агент привёл `file:line` — считать проверенным; пометки «дубль/мёртв» без `file:line` требуют code-verify (фаза 3) перед удалением.
> **Принципы владельца:** не переписывать, а **собрать в одну систему и довести до идеала**; ОДИН лучший на сценарий; «не используется ≠ не нужно»; функционал не теряется; проще отлаживать.
> **Прогон сохранён** (`plans/_wf_comm_arch_v2.js`, runId `wf_ea6b2725-41d`) — при сбросе лимита можно до-резюмить фазы 3–4 из кеша.

---

## 1. Вердикт по тезису владельца

**Тезис «RouterManager — единая универсальная точка коммуникации с подключаемыми каналами» — ВАЛИДЕН.**

RouterManager — единственная система, несущая то, что нельзя получить параллельными путями: **send/receive middleware-цепочку, централизованную статистику, request/reply и плагинный реестр каналов одного типа** (`IMessageChannel`) для Queue/Socket/Modbus. `register_channel` — тонкий, добавить redis/mcp-канал = реализовать контракт `IMessageChannel`, без правок ядра.

**Уточнение границ (важно для чистоты):** хаб = **слой маршрутизации + middleware + контракт канала**, а НЕ монолит-транспорт. Транспорт (очереди, SHM) живёт под хабом как каналы/транспортные стратегии. Хаб маршрутизирует по `type` + иерархическому адресу (`proc[.worker[. ...]]`, в перспективе `machine.proc.worker`).

Главный вывод честного аудита: **«трёх движков» нет.** Большинство «дублей» из прошлого черновика — это либо *слои одной башни над одним движком* (dispatch), либо *разные уровни ответственности* (IPC-команда vs GUI-undo). **Реальных дублей мало и они точечные** — это меняет план с «большого рефакторинга» на «обрамление + мелкие правки».

---

## 2. Канон по сценариям (один лучший на сценарий)

| Сценарий | Канонический механизм | Что absorb / примечание |
|---|---|---|
| Команда процессу/воркеру | `RouterManager.send(targets=[proc[.worker]], type=command)` | иерархическая адресация (ADR-COMM-004) |
| Синхронный запрос-ответ | `RouterManager.request()` + generic `reply_to_request()` | авто-reply по `request_id` в `receive()` — разблокирует надёжный subscribe |
| Кадр / data-поток | data-путь + `FrameShmMiddleware` (coords в msg, payload в SHM) | hot-path; **слить два FrameShmMiddleware в один** (generic — живой) |
| key→handler внутри процесса | `dispatch_module.Dispatcher` (один движок) | `CommandManager`, `message_dispatcher`, `channel_dispatcher` — его экземпляры через composition |
| Реактивное состояние / телеметрия | `state_store_module` (StateStore + StateProxy/GuiStateProxy) | `DeltaDispatcher` → канонический `_select_queue_type` вместо хардкода |
| Внутри-GUI событие | `domain EventBus` / `QtEventBus` | — |
| GUI-команда + undo/redo | `CommandDispatcherOrchestrator` (snapshot-based) | **вынести во framework** как generic capability; ActionBus не оживлять |
| Доставка worker→main thread (Qt) | `DataReceiverBridge` | убрать дубль-класс (shadowing), кандидат на carve-out |
| Внешний драйвер / сервис / контроллер | `IMessageChannel` в RouterManager (эталон — `ModbusChannel`) | redis/mcp/socket — по тому же контракту; SQL привести или задокументировать исключение |

---

## 3. Разбор «дубль или нет» (главная честная таблица)

| Подозрение | Вердикт | Суть |
|---|---|---|
| dispatch_module vs CommandManager vs message_dispatcher vs channel_dispatcher | **НЕ дубль (reuse)** | один класс `Dispatcher`, переиспользован тремя экземплярами через composition. Образцовый reuse. |
| `queue_type` vs `type` в конверте | **НЕ дубль** | `type` — семантика (9 `MessageType`); `queue_type` — транспортный хинт, **выводится** из `type` через `_select_queue_type`. Не хранить в продюсерах. |
| `request_id` vs `data.correlation_id` | **дубль имени** | свести к единому `request_id`; зеркало оставить только на переходный период PM-обёртки. |
| ActionBus vs CommandDispatcherOrchestrator | **РЕАЛЬНЫЙ дубль** | одна забота (GUI undo/redo) — два движка. Глобальный Ctrl+Z только на Orchestrator ([app.py:557](multiprocess_prototype/frontend/app.py#L557)); ActionBus в проде мёртв. Победитель — Orchestrator (snapshot+pure-apply даёт implicit rollback, надёжнее patch-based). |
| reply по `correlation_id`: generic `reply_to_request()` vs bespoke `_handle_process_command` | **узкий дубль** | generic-путь уже используется `process_lifecycle._make_command_handler` для всех команд CommandManager; bespoke ручной reply в PM — свести к generic. |
| FrameShmMiddleware: `router_module/middleware` vs `process_module/generic` | **дубль (~200 строк)** | слить в один; router-вариант не на hot-path. |
| FieldRouting / RouterSchemaAdapter | **НЕ дубль — две оси** | ось адресации (`process_targets`) живая (SSOT-декларация маршрута); ось kind — отдельные читатели той же декларации. ADR-COMM-004/001 фиксируют ортогональность address vs kind. |
| StateStore vs EventBus vs registers observers vs ObservableMixin | **разные уровни** | двухканон: StateStore = состояние, EventBus = in-proc события. Остальное — наблюдаемость/runtime-регистры, не конкуренты. |

---

## 4. Мелкие проблемы / быстрые победы (1–5 строк, чистят и упрощают отладку)

1. **`StateProxy.subscribe` сломан:** зовёт `_send_sync → router.send()`, а `send()` возвращает **статус отправки**, не ответ; callback регистрируется локально даже при провале сервера → ложный успех ([`state_proxy.py:243,287`](multiprocess_framework/modules/state_store_module/proxy/state_proxy.py#L243)). Чинит авто-reply по `request_id` (см. §5).
2. **`DeltaDispatcher` хардкодит `queue_type="system"`** ([`delta_dispatcher.py:115`](multiprocess_framework/modules/state_store_module/manager/delta_dispatcher.py#L115)) → заменить на `_select_queue_type()`.
3. **`RolesPanel` получает `bus=None`** (ActionBus не передан) → правки ролей молча теряются. Мелкий fix.
4. **Дубль-класс `DataReceiverBridge`** (shadowing) — удалить лишний.
5. **Мёртвый relay `PluginOrchestrator.register_changed`** (нет потребителя) — убрать.
6. **`state.changed` доставляется в `{gui}_system`, а GUI-воркер опрашивает `["data"]`** ([`process.py:131`](multiprocess_prototype/frontend/process.py#L131)) — закрыть разрыв приёма (горячий путь телеметрии).
7. **Vestigial `channel="data"/"system"` у продюсеров** — удалить у источника, а не стрипать post-hoc.

---

## 5. Унификации (минимальные, элегантные ходы)

- **Единый путь отправки:** свести `ProcessCommunication.send_to_process` / `RouterManager._deliver_by_targets` / `broadcast` к одному внутреннему `_dispatch(targets, msg)`; публичные API — фасады. Прикладной код **не** зовёт `queue_registry` напрямую. (Паритет: тот же `send_to_queue`.)
- **Дженерик request/reply:** авто-reply по `request_id` в `receive()`/`message_dispatcher` (если обработчик вернул значение). Затем перевести `StateProxy.subscribe` на `request()`.
- **GUI undo во framework:** вынести `CommandDispatcherOrchestrator` как generic snapshot-движок; ActionBus — пометить `@experimental` (capability), не удалять.
- **FrameShmMiddleware:** 2 → 1.
- **Конверт:** минимум = `type`, `sender`, `targets`, `data`, `request_id`; `queue_type` выводить; `channel` vestigial — убрать у продюсеров; `_address` — внутреннее.

---

## 6. Оставить как capability конструктора (не удалять)

- **dispatch стратегии PATTERN/FALLBACK/CHAIN + сценарии** — движок правильный, ценен для будущих pipeline/маршрутизаций; в проде живёт EXACT_MATCH, остальное — capability.
- **FieldRouting (ось адресации)** — SSOT-декларация маршрута в регистре; идея single-source-of-truth ценна.
- **ActionBus** — patch-движок как capability для будущих forms/system-settings (но Ctrl+Z-роль закрыта Orchestrator).
- **`system_events` канал** — ждёт первого потребителя.
- **SocketChannel / WorkerPoolDispatcher** — эталоны cross-process паттернов.

---

## 7. План этапами (инвариант приёмки: Pipeline камера→обработка→дисплей работает)

- **P0 — телеметрия (критично, последовательно, hot-path):** §4.1, §4.2, §4.6, §4.3. Файлы: `state_proxy.py`, `delta_dispatcher.py`, `frontend/process.py`, `roles_panel.py`.
- **P1 — единый путь + конверт (framework):** `_dispatch`, чистка vestigial `channel`, §4.7. Риск высокий (кадры) → полный регресс роутера.
- **P2 — дженерик request/reply + сервисы к правилам:** авто-reply, `StateProxy.subscribe` на `request()`; FrameShm 2→1; SQL — `IMessageChannel` или документированное исключение. Часть параллельно (worktree).
- **P3 — carve-out + капабилити:** Orchestrator → framework; пометки `@experimental`; унификация `request_id`/`correlation_id`; вынос suffix-парсинга каналов в утилиту.

---

## 8. Открытые вопросы владельцу

1. **SQL вне хаба** — приводить к `IMessageChannel` (единообразие) или оставить документированным исключением (прямой `execute_command` проще)?
2. **ActionBus** — держать как `@experimental` capability или удалить (роль undo закрыта Orchestrator)?
3. **Cross-machine адрес** — фиксируем `machine.proc.worker` как целевую схему сейчас или после стабилизации IPC?
4. **Carve-out GUI-bridge** — выносить Qt-bridge во framework (опц. frontend-слой) или оставить app-specific?

---

## 9. Что осталось не доделано (для до-резюма)

Фаза 3 (адверсариальная проверка по коду каждого «мёртв/дубль») и автоматический синтез с матрицей сохранности **не прогонялись** (остановлено по лимиту). До-резюмить:
`Workflow({scriptPath: "plans/_wf_comm_arch_v2.js", resumeFromRunId: "wf_ea6b2725-41d"})` — 15 карт + 8 анализов вернутся из кеша мгновенно, отработают только фазы 3–4.
