# План: закрыть два долга ветки `feat/processes-workers-runtime`

> Slug: `processes-workers-runtime-debts` · Ветка: `feat/processes-workers-runtime`
> Продолжение [`processes-workers-runtime.md`](processes-workers-runtime.md) и
> [`pipeline-node-process-worker.md`](../frontend/widgets/tabs/pipeline/plans/pipeline-node-process-worker.md).

## Статус

| Фаза | Состояние |
|------|-----------|
| **Фаза 1 — live-телеметрия (StateStore)** | ✅ DONE — 788 тестов зелёные, ruff чист, headless-integration доказал U1-путь |
| **Фаза 2 — runtime по `assigned_worker` (вариант A)** | ⏳ PENDING |
| **Push-модель адресной книги + адресация до воркера** | 📋 Отдельный `/plan` позже (решение владельца) |

## Контекст

Два долга предыдущей сессии:
- **#1 live-телеметрия GUI** — карточки/таблица воркеров показывали статичные «—»; весь контур
  backend→GUI был dormant.
- **#2 runtime по `assigned_worker`** — Pipeline персистит выбор воркера, но рантайм его игнорирует;
  назначенные воркеры стартуют как `IdleWorker` (no-op).

**Решения владельца (обсуждение 2026-05-31):**
- #1 → полный **StateStore-путь** (реактивное дерево), не лёгкий обход.
- #2 → **вариант A** (воркер = параллельная ветвь с последовательной под-цепочкой из 1+ плагинов;
  обобщает B). Соответствует модели владельца: воркеры в процессе работают параллельно, цепочки
  раскладываются по воркерам через граф Pipeline; обычный случай — один воркер / N плагинов.
- Порядок: сначала #1 (отдельный коммит), потом #2.
- **Унификация IPC (U1):** `RouterManager.send(Message(targets=[...]))` доставляет через общий
  `queue_registry` (адресная книга оркестратора) — реализует исходный замысел «всё через RouterManager».
  Push-модель (оркестратор рассылает книгу + адресация до воркера) — отдельный план.

---

## Фаза 1 — live-телеметрия через StateStore ✅

**Ключевая находка (ревью Opus + проверка кода):** cross-process подписка StateStore в проде **не
работала** — `DeltaDispatcher` слал `state.changed` через `router.send_async` с `targets`, но
`_resolve_channels` поле `targets` не читает и route для `state.changed` нет → сообщение терялось
(зелёными были только тесты через `InMemoryRouter`, минующий каналы).

**Реализовано:**
- **1.0a (framework, router_module):** `RouterManager._do_send` — fallback `_deliver_by_targets`:
  если `_resolve_channels()`=[] и есть `msg["targets"]` (без явного `channel`) — доставка через
  `queue_registry.send_to_queue(target, qtype, msg)`. `qtype = msg["queue_type"]` или `"system"` для
  command, иначе `"data"`. Безопасно: добавляет доставку только там, где был silent drop.
- **1.0b (framework, state_store_module):** `DeltaDispatcher._send_state_changed` ставит
  `queue_type="system"` → `state.changed` ложится в `{sub}_system`, опрашиваемую штатным
  message_processor подписчика; `message_dispatcher` синхронно диспатчит handler.
- **1.1 (framework, process_manager_module):** `ProcessMonitor._publish_state()` + публикация
  `processes.X.state.status` (смена статуса) и `processes.X.workers.Y.{status,effective_hz}`
  (из heartbeat `workers_status`) в локальный `StateStoreManager` (без IPC).
- **1.2 (prototype, frontend):** `GuiProcess` — `GuiStateProxy` + `_StateDeltaEmitter` (Qt main-thread)
  + ручная регистрация handler `state.changed` + подписка `processes.**`. Дельты → `bridge.dispatch
  ({data_type:"state_delta",...})` → существующие `GuiStateBindings` оживают.
- **1.3 (prototype, frontend):** `bridge.py`/`bridge_impl.py` `dispatch` — `state_delta` → `kind="state"`.

**Верификация:** 788 passed (21 новый: U1 integration ×3, router fallback ×7, delta queue_type ×3,
process_monitor publish ×5, bridge/emitter ×3). `ruff check` чист. Headless-integration
(`test_integration_u1_delivery.py`) на реальных RouterManager+StateStoreManager+DeltaDispatcher
доказал доставку `state.changed` в очередь подписчика. GUI-smoke отложен (запуск приложения).

**Вне scope #1 (новый долг):** продюсеры `processes.X.state.fps`/`latency_ms` и `system.health.*` —
карточные FPS/Latency и health-метки останутся «—» до отдельной задачи.

---

## Фаза 2 — исполнение по `assigned_worker` (вариант A) ⏳

Эпицентр: `multiprocess_framework/modules/process_module/generic/generic_process.py`
(`_init_data_pipeline`).

- **2.1 Доступ к assigned_worker:** через `orchestrator._contexts` →
  `ctx.config.get("config", {}).get("assigned_worker")` (или публичный accessor `plugin.assigned_worker`).
- **2.2 Группировка:** processing-плагины по `assigned_worker`; пустой → дефолт `"pipeline_executor"`.
  Каждая группа → свой `PipelineExecutor` в своём воркере (имя группы); порядок внутри сохранён.
  Sources аналогично (`assigned_worker` или `source_producer_<name>`).
- **2.3 Поток данных между группами:** цепочка делится на смежные сегменты; in-process `queue.Queue`
  handoff между группами; последняя группа → IPC `chain_targets`. Одна группа = текущее поведение
  (нулевой регресс).
- **2.4 Lifecycle IdleWorker:** WorkerSpec-воркеры стартуют как IdleWorker до `_init_data_pipeline`.
  Перед созданием executor под именем группы — остановить незащищённый IdleWorker и пересоздать с
  `target=PipelineExecutor.run_loop` (guard `is_worker_protected`).
- **2.5 Edge cases:** несуществующий воркер → создать + лог; protected → fallback в дефолт + warning.

---

## Верификация (общая)

- Тесты из корня: `python scripts/run_framework_tests.py` / `make test`.
- `make check` (ruff + pyright + bandit).
- Qt-smoke (после Фазы 2 / при возможности запуска): назначить плагин в воркер в Pipeline → во вкладке
  «Процессы» виден воркер с телеметрией (effective_hz>0), а не IdleWorker.

## Коммиты

- Фаза 1 — отдельный `feat`-коммит (Layer: mixed). Фаза 2 — следующий (Layer: framework). `Refs` на
  этот план. Push-модель адресной книги + адресация до воркера — отдельный `/plan`.
