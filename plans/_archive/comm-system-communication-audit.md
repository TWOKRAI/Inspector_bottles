# Аудит механизмов коммуникации (comm-system) — 2026-06-03

> **Зачем.** Владелец: за время разработки агенты «накидали» разные системы общения. Цель comm-system — выявить **лучшие и нужные** механизмы, отбросить дубли, и при выгоде перенести длинные цепочки на единый механизм. Триггер — телеметрия: переносить ли её на RouterManager-хаб (идея владельца) вместо reuse `DataReceiverBridge` (план [`telemetry-delivery-simplification.md`](telemetry-delivery-simplification.md)).
>
> **Метод.** Read-only investigator (Opus) + codegraph/grep-числа + verified-probe из memory `project_telemetry_subscription_bug`. Связано с [`comm-system-target-architecture.md`](comm-system-target-architecture.md).

## Корневой вывод (HIGH confidence)

**Вопрос «перенести телеметрию на RouterManager-хаб» (вариант B) основан на ложной предпосылке: телеметрия УЖЕ ездит через хаб.** `state.changed` доставляется через `router_manager.register_message_handler("state.changed", proxy.on_state_changed)` (`frontend/process.py:91`; framework `process_module.py:271`). Серверная публикация (`ProcessMonitor → StateStore → DeltaDispatcher → router.send_async → queue_registry`) — тоже хаб (verified probe 2026-06-03).

**Разрыв доставки — НЕ в транспорте/хабе, а в ОДНОМ внутрипроцессном хопе GUI:** маршалинг из IO-потока в Qt main thread — `GuiStateProxy._dispatch_via_qt → QMetaObject.invokeMethod(_StateDeltaEmitter, "_on_state_deltas", QueuedConnection)` (`gui_state_proxy.py:106-133`), слот FIRED 0×. Рядом кадры через **тот же** `DataReceiverBridge._deliver = Signal(object)` + `emit()` (`bridge_impl.py:22,35,55`) пересекают тот же поток успешно. RouterManager обязан оставаться **Qt-free** (ADR) → он физически не может пересекать Qt-main-thread границу. Значит B либо ничего не меняет в баге, либо требует оживить **0-prod `RouterManager.request()`** (grep: только тесты + dev-gated `socket_bridge_adapter`) + закрыть блокер thread-guard — рост сложности на операции, которая не на причине.

## 1. Инвентаризация механизмов

| Механизм | Назначение | Живые потребители | Пересекает | Вердикт |
|---|---|---|---|---|
| **RouterManager + IMessageChannel** | IPC: send/receive/request/broadcast + middleware + реестр каналов | канон, прод-горячий | процесс | **канон** (IPC) |
| `RouterManager.request()` | sync req/reply по correlation_id | **0 prod** (только тесты) | процесс | канон-API, **спящий**; блокер thread-guard |
| **StateStore + DeltaDispatcher + StateProxy/GuiStateProxy** | реактивное состояние cross-process → телеметрия | прод-горячий (probe: publish 780×, dispatch 150×, on_state_changed 300×) | процесс + IO→Qt | **канон** (состояние) |
| **DataReceiverBridge + Qt-signals** | worker/IO → Qt main thread (кадры/команды/state) | прод (кадры `_deliver.emit` доказан) | поток IO→Qt | **канон** (последняя миля IO→Qt), Qt-завязан |
| `_StateDeltaEmitter` + `invokeMethod` | второй механизм IO→Qt только для state | **сломан** (FIRED 0×), дублирует bridge | поток | **дубль-убрать** |
| `_state_multiplexer` closure (`app.py:249-257`) | fan-out state в bindings+topology поверх single-slot | прод, костыль | — | **дубль-убрать** → multi-subscriber |
| **EventBus / QtEventBus** | типизированные in-proc события-факты | прод (`TopologyReplaced`…) | поток (Qt) | **канон** (события), НЕ дубль StateStore |
| **CommandManager + Dispatcher** | IPC-команды процессу/воркеру | прод-горячий (7+) | процесс | **канон** (команды) |
| `ActionBus` | GUI-команды/undo (patch) | **0 prod execute()** | — | **дубль-убрать из GUI** (класс — референс) |
| **CommandDispatcherOrchestrator** | GUI undo/redo (snapshot) | прод (Ctrl+Z) | — | **канон** (GUI-undo) |
| прямой `broadcast`/`queue_registry` | fan-out в обход хаба | прод, обход | процесс | **слить в хаб** |
| heartbeat (ProcessHeartbeat) | workers_status/effective_hz | прод | процесс | **нишевый-оставить** |
| Logger/Error/Stats (поверх CRM) | наблюдаемость | прод (Logger горячий; Stats к роутеру не подключён) | частично | **канон** (наблюдаемость) |

## 2. Карта дублей

- **D1 — IO→Qt доставка state:** `_StateDeltaEmitter+invokeMethod` ↔ `DataReceiverBridge._deliver`. Один сломан, второй доказан кадрами. **Центральный дубль запроса владельца.**
- **D2 — fan-out подписчиков state:** `_state_multiplexer` closure ↔ multi-subscriber listener.
- **D3 — undo:** `ActionBus` (мёртв) ↔ `CommandDispatcherOrchestrator` (жив).
- **D4 — broadcast команд:** прямой `queue_registry.broadcast` ↔ хаб `register_broadcast_route`.
- **D5 — ответ на request:** PM bespoke-reply `_handle_process_command` ↔ дженерик `reply_to_request` (comm-system §3.6).
- **D6 — SHM-fallback:** 2× `FrameShmMiddleware` (comm-system §9.2).

**НЕ дубли:** StateStore (что есть) vs EventBus (что произошло); RouterManager (адрес+транспорт) vs StateStore (реактивность) — ортогональны; CommandManager (IPC) vs CommandDispatcherOrchestrator (GUI-undo) — совпадает только слово.

## 3. Рекомендация по телеметрии: A vs B vs C

| Критерий | A (reuse DataReceiverBridge) | B (на RouterManager-хаб) | C (свой Signal на GuiStateProxy) |
|---|---|---|---|
| Механизмов в системе ПОСЛЕ | **−1** (удаляется emitter) | 0 или +1 (req/reply 0-prod оживлять) | +1 |
| Лечит реальный разрыв IO→Qt | **да** (путь кадров доказан) | **нет** (разрыв внутрипроцессный) | да |
| GuiStateProxy Qt-free (ADR) | **да** (sink — callback) | да | **нет** (нарушает ADR) |
| Объём/риск | малый, локальный, reversible | большой + блокер, **не на причине** | средний + нарушение ADR |

**Рекомендация: вариант A** (план `telemetry-delivery-simplification.md` верен). Единственный, кто **уменьшает число механизмов на один** (цель владельца «минус один, а не плюс») — устраняет дубль D1.

**Тонкость для владельца:** исходная идея «всё через RouterManager» для телеметрии УЖЕ выполнена на уровне транзита. `DataReceiverBridge` — не конкурирующий «ещё один механизм», а последняя миля IO→Qt внутри одного процесса (то, что хаб делать не должен, Qt-free). Reuse bridge не плодит механизм — убирает дубль. comm-system §7(а)/§9.10 это уже канонизировал.

**6 задач `telemetry-delivery-simplification.md` остаются валидны** (Task 1.1/1.2 = устранение D1+D2; 3.1/3.2 издатели метрик ортогональны выбору A/B). B не отменил бы ни одной, лишь добавил бы лишнюю (оживить request/reply).

## 4. Системный вывод для comm-system

**Каноны (оставить как единые, по сценариям):**
1. **RouterManager + IMessageChannel** — единый хаб IPC.
2. **StateStore** — реактивное состояние/телеметрия (транзит уже через хаб).
3. **DataReceiverBridge** — последняя миля IO→Qt (Qt-завязка изолирована).
4. **EventBus/QtEventBus** — in-proc события.
5. **CommandManager+Dispatcher** (IPC-команды) + **CommandDispatcherOrchestrator** (GUI-undo).
6. **Logger/Error/Stats** поверх CRM — наблюдаемость.

**На устранение/слияние (порядок — сначала чинящее телеметрию, не трогая hot-path):**
1. **D1** `_StateDeltaEmitter`+invokeMethod → bridge (telemetry Task 1.1) — первым.
2. **D2** `_state_multiplexer` → multi-subscriber (Task 1.2).
3. **D3** ActionBus из GUI → Orchestrator (comm-system P3).
4. **D4** прямой broadcast → хаб `register_broadcast_route` (P1).
5. **D5** PM bespoke-reply → `reply_to_request` (P2).
6. **D6** 2× FrameShmMiddleware → 1 (P2).

**Решённый спор:** «телеметрию на RouterManager-хаб» — отклонить как сформулировано (она уже на хабе). Единственная незакрытая часть — внутрипроцессный IO→Qt-хоп, который по дизайну принадлежит `DataReceiverBridge`, а не хабу.

## Достоверность
HIGH: прочитанный код (`gui_state_proxy.py`, `bridge_impl.py`, `process.py:91`) + grep-числа (`request()` = 0 prod) + verified-probe (memory `project_telemetry_subscription_bug`, сессия 2026-06-03). Прототип в этом анализе не запускался; «FIRED 0×» — из probe той же сессии, согласуется со статикой (invokeMethod по строковому имени слота — хрупкий, без compile-time проверки).
