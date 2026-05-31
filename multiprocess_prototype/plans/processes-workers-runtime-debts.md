# План: закрыть два долга ветки `feat/processes-workers-runtime`

> Slug: `processes-workers-runtime-debts` · Ветка: `feat/processes-workers-runtime`
> Продолжение [`processes-workers-runtime.md`](processes-workers-runtime.md) и
> [`pipeline-node-process-worker.md`](../frontend/widgets/tabs/pipeline/plans/pipeline-node-process-worker.md).

## Статус

| Фаза | Состояние |
|------|-----------|
| **Фаза 1 — live-телеметрия (StateStore)** | ✅ DONE — 788 тестов зелёные, ruff чист, headless-integration доказал U1-путь |
| **Фаза 2 — runtime по `assigned_worker` (вариант A)** | ⏳ PENDING — детальное ТЗ готово (Task 2.1–2.6) |
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

### Детальное ТЗ Фазы 2

> Порядок выполнения и зависимости: **2.1 → 2.2 → 2.3 → 2.4 → 2.5 → 2.6**. Задачи
> 2.1–2.4 — единый связный рефакторинг `_init_data_pipeline`; 2.5 встраивается в
> группировку 2.2/2.4; 2.6 — финальный тестовый прогон и обновление документации.
> Все задачи на ветке `feat/processes-workers-runtime`, `Refs: plans/processes-workers-runtime-debts.md`.

**Vertical slice:** Task 2.1 — обязательный tracer bullet. После него рантайм
**читает** `assigned_worker` из контекста плагина (новый публичный accessor) и
**логирует** план группировки — это уже наблюдаемый E2E-эффект (в логах процесса
видно «plugin X → worker Y») при нулевом изменении исполнения. Дальнейшие задачи
углубляют срез (группировка → handoff → lifecycle → edge cases).

#### Task 2.1 — Публичный доступ к `assigned_worker` плагина (tracer bullet)

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Дать рантайму надёжный публичный способ узнать назначенный воркер плагина (вложенный/плоский путь) и логировать вычисленный план назначений без изменения исполнения.
**Context:** Сейчас `assigned_worker` доступен только через приватный `orchestrator._contexts[i].config`, причём поле лежит вложенно (`ctx.config["config"]["assigned_worker"]`), а в части топологий — плоско. Прямой доступ к `_contexts` хрупок и нарушает инкапсуляцию. Нужен публичный accessor — фундамент для 2.2.
**Files:**
- `multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py` — добавить публичный API
- `multiprocess_framework/modules/process_module/generic/generic_process.py` — `_init_data_pipeline`: вычислить и залогировать план группировки (без смены исполнения)
- `multiprocess_framework/modules/process_module/tests/test_plugin_orchestrator.py` — тесты accessor
- `multiprocess_framework/modules/process_module/README.md` — упомянуть новый accessor (если есть раздел API оркестратора)

**Steps:**
1. В `PluginOrchestrator` добавить метод `assigned_worker_for(self, plugin: ProcessModulePlugin) -> str | None`:
   - найти индекс плагина в `self._plugins`, взять parallel-контекст `self._contexts[i]`;
   - извлечь значение робастно: сначала `ctx.config.get("config", {}).get("assigned_worker")`, при `None`/отсутствии — fallback `ctx.config.get("assigned_worker")`;
   - нормализовать: пустую строку / whitespace-only → `None` (трактуется как «дефолт»);
   - если плагин не найден в `self._plugins` → вернуть `None` (не бросать).
2. Добавить property `contexts(self) -> list[PluginContext]` (read-only возврат `self._contexts`) — публичная замена `_contexts` для тестов и будущих нужд. `_contexts` оставить как приватное хранилище.
3. В `GenericProcess._init_data_pipeline`, после разделения на source/processing, но ДО создания executors, вычислить словарь назначений `{plugin.name: orchestrator.assigned_worker_for(plugin) or DEFAULT}` и залогировать через `self._log_info` одной строкой (формат: `assigned_worker plan: {dict}`). DEFAULT для processing = `"pipeline_executor"`, для source = `f"source_producer_{name}"`. Исполнение НЕ менять — executors по-прежнему создаются как сейчас.
4. Тесты: `assigned_worker_for` возвращает значение из вложенного `config`; из плоского fallback; `None` при пустой строке; `None` для неизвестного плагина; `contexts` property отдаёт список параллельный `plugins`.

**Acceptance criteria:**
- [ ] `orchestrator.assigned_worker_for(plugin)` возвращает корректное значение для вложенного и плоского путей, `None` для пустого/whitespace и неизвестного плагина
- [ ] `orchestrator.contexts` доступен публично, длина == len(`orchestrator.plugins`)
- [ ] В логе процесса при старте видна строка `assigned_worker plan: {...}` (наблюдаемый эффект tracer bullet)
- [ ] Исполнение pipeline идентично прежнему (нулевой регресс): один `pipeline_executor`, source-producers как раньше
- [ ] `python scripts/run_framework_tests.py` зелёный; `make check` чист

**Out of scope:** группировка/handoff/lifecycle (2.2–2.4); смена реального количества executors; чтение поля из domain-модели (рантайм работает только с PluginContext).
**Edge cases:** плагин с пустой строкой `assigned_worker`; топология без секции `config` у плагина (плоский dict); список `_contexts` короче `_plugins` при частичном фейле configure (использовать поиск по объекту плагина, не индекс из `plugins`).
**Dependencies:** —
**Module contract:** public-api-change (новый публичный метод + property у `PluginOrchestrator`)

#### Task 2.2 — Группировка плагинов по `assigned_worker`

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Разложить processing- и source-плагины на упорядоченные группы по `assigned_worker` с сохранением исходного порядка цепочки, не меняя пока создание воркеров.
**Context:** Вариант A: воркер = параллельная ветвь с последовательной под-цепочкой из 1+ плагинов. Группировка — чистая функция над списком плагинов и их назначениями; вынесение в отдельную тестируемую единицу упрощает покрытие и снижает риск регресса в `_init_data_pipeline`.
**Files:**
- `multiprocess_framework/modules/process_module/generic/pipeline_grouping.py` — создать (чистая функция группировки)
- `multiprocess_framework/modules/process_module/generic/generic_process.py` — вызвать группировку, на её основе пока логировать структуру (исполнение менять в 2.3/2.4)
- `multiprocess_framework/modules/process_module/tests/test_pipeline_grouping.py` — создать (unit-тесты группировки)

**Steps:**
1. Создать модуль `pipeline_grouping.py` с функцией `group_processing_plugins(plugins, resolve_worker, default="pipeline_executor") -> list[PluginGroup]`, где `resolve_worker: Callable[[plugin], str | None]` (передаётся `orchestrator.assigned_worker_for`), а `PluginGroup` — небольшой dataclass `{worker_name: str, plugins: list, order_index: int}`.
2. Алгоритм (вариант A, смежные сегменты): идти по `plugins` в исходном порядке; начинать новую группу при смене эффективного `worker_name` (resolve→default) относительно предыдущего плагина. Соседние плагины с одинаковым назначением — в одну группу. `order_index` — позиция группы в цепочке (0 = первая). Это сохраняет последовательную семантику цепочки и даёт сегменты для handoff в 2.3.
3. Документировать выбор «смежные сегменты»: два неподряд идущих плагина с одинаковым `assigned_worker`, разделённые плагином другого воркера, образуют ДВЕ группы (порядок цепочки приоритетнее «слияния по имени»). Зафиксировать это решение комментарием/докстрингом и тестом.
4. Для source-плагинов добавить функцию `group_source_plugins(plugins, resolve_worker) -> list[PluginGroup]`, где default = `f"source_producer_{plugin.name}"`; источники не образуют последовательную цепочку — каждый источник = своя группа (один плагин), но `worker_name` берётся из `assigned_worker`, если задан.
5. В `_init_data_pipeline` вызвать обе функции, залогировать получившуюся структуру групп (расширив лог из 2.1). Реальное создание executors пока не трогать.
6. Тесты `test_pipeline_grouping.py`: пустой `assigned_worker` у всех → одна группа `pipeline_executor` (критичный кейс нулевого регресса); два плагина в один воркер → одна группа; чередование A-B-A → три группы; смешанные пустые/заданные; source-плагины с/без `assigned_worker`.

**Acceptance criteria:**
- [ ] `group_processing_plugins` при всех пустых назначениях возвращает ровно одну группу `pipeline_executor` со всеми плагинами в исходном порядке
- [ ] Чередование A-B-A даёт три группы (смежные сегменты), порядок `order_index` соответствует цепочке
- [ ] `group_source_plugins` назначает каждому источнику его `assigned_worker` либо `source_producer_<name>`
- [ ] Внутри группы порядок плагинов идентичен исходному списку `orchestrator.plugins`
- [ ] `python scripts/run_framework_tests.py` зелёный; `make check` чист

**Out of scope:** создание/пересоздание воркеров (2.4); межгрупповой handoff (2.3); edge cases несуществующий/protected (2.5) — здесь группировка лишь вычисляется.
**Edge cases:** один плагин; ноль processing-плагинов (вернуть пустой список групп); все плагины в один явный воркер; идентичные имена воркеров у несмежных групп.
**Dependencies:** 2.1
**Module contract:** new-lite (новый single-file публичный модуль `pipeline_grouping.py`)

#### Task 2.3 — Межгрупповой handoff данных через in-process очереди

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Связать соседние группы processing-плагинов in-process очередями: каждая группа читает из своей входной `queue.Queue`, не-последняя группа кладёт результат в очередь следующей, последняя группа отправляет по IPC `chain_targets`.
**Context:** Сейчас один `PipelineExecutor` читает из `chain_queue` и всегда шлёт по IPC. Для варианта A цепочка делится на смежные сегменты: DataReceiver → группа 1 → (in-process) → группа 2 → … → последняя группа → IPC. Одна группа = текущее поведение (вход `chain_queue`, выход IPC) — критичный нулевой регресс.
**Files:**
- `multiprocess_framework/modules/process_module/generic/pipeline_executor.py` — поддержать выход в in-process очередь вместо/помимо IPC
- `multiprocess_framework/modules/process_module/generic/generic_process.py` — связать очереди групп
- `multiprocess_framework/modules/process_module/tests/test_pipeline_executor.py` — тесты handoff и обратной совместимости

**Steps:**
1. Расширить `PipelineExecutor.__init__` опциональным `output_queue: queue.Queue | None = None`. Семантика: если `output_queue` задана — `_send_results` кладёт прошедшие цепочку items в неё (`output_queue.put(items, ...)`) и НЕ шлёт по IPC; если `None` — текущее поведение (IPC через `chain_targets`/per-item `target`). Сохранить SHM-write и circuit-breaker логику в обоих ветках.
2. Аккуратно решить вопрос с SHM на промежуточных звеньях: между in-process группами frame НЕ выгружать в SHM (item остаётся с `frame` в памяти процесса). SHM `strip_and_write` применять только в финальной (IPC) ветке. Зафиксировать это в докстринге и тесте (in-process item сохраняет `frame`).
3. В `_init_data_pipeline`: для N групп создать N входных очередей; первой группе вход = `self._chain_queue` (от DataReceiver); каждой не-последней группе передать `output_queue = <вход следующей группы>`; последней группе `output_queue=None` (IPC). `chain_targets` передавать только последней группе.
4. Уважать backpressure: `output_queue` создавать с тем же `queue_size`; при `Full` — поведение как у текущей очереди (логировать/дропать согласно существующему паттерну DataReceiver; если паттерна нет — блокирующий put с таймаутом и trace-лог при переполнении).
5. Тесты: (а) один executor без `output_queue` шлёт по IPC как раньше (регресс-гард, переиспользовать существующие тесты); (б) executor с `output_queue` кладёт результат в очередь и НЕ вызывает `send_fn`; (в) цепочка из двух executors через общую очередь: item, положенный в `chain_queue` группы 1, доходит до IPC после группы 2; (г) промежуточный item сохраняет `frame` (SHM не сработал).

**Acceptance criteria:**
- [ ] `PipelineExecutor(output_queue=None)` шлёт по IPC идентично текущему (нулевой регресс, существующие тесты зелёные)
- [ ] `PipelineExecutor(output_queue=q)` кладёт items в `q` и НЕ вызывает `send_fn`
- [ ] Двухгрупповая цепочка: вход в `chain_queue` группы 1 → IPC-send после последней группы (end-to-end тест на ≥2 группах)
- [ ] Между in-process группами frame не выгружается в SHM (item с `frame` доходит до следующей группы)
- [ ] `python scripts/run_framework_tests.py` зелёный; `make check` чист

**Out of scope:** запуск воркеров под группы (2.4); решение «несуществующий/protected воркер» (2.5). Здесь только механика очередей и executor-выхода.
**Edge cases:** одна группа (output_queue=None); пустой результат цепочки (ничего не put); переполнение `output_queue`; группа с одним плагином.
**Dependencies:** 2.2
**Module contract:** public-api-change (новый параметр `output_queue` у `PipelineExecutor.__init__`)

#### Task 2.4 — Lifecycle воркеров групп (создать/пересоздать с PipelineExecutor)

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Для каждой группы поднять воркер с именем группы и `target=PipelineExecutor.run_loop`: если воркер уже есть (IdleWorker из WorkerSpec) и не protected — остановить и пересоздать; если воркера нет — создать.
**Context:** WorkerSpec-воркеры могут существовать к моменту `_init_data_pipeline` как IdleWorker (no-op), но в текущих prototype-топологиях секция `workers:` не используется — воркер группы на старте может ОТСУТСТВОВАТЬ (создаётся live из GUI позже). Поэтому lifecycle должен и создавать (если нет), и пересоздавать (если есть незащищённый IdleWorker).
**Files:**
- `multiprocess_framework/modules/process_module/generic/generic_process.py` — `_init_data_pipeline`: замена прямого `create_worker("pipeline_executor", ...)` на per-group lifecycle
- `multiprocess_framework/modules/process_module/tests/test_process_lifecycle.py` (или новый `test_data_pipeline_groups.py`) — тесты lifecycle с фейковым WorkerManager

**Steps:**
1. Выделить хелпер `_spawn_group_worker(self, group, input_queue, output_queue, shm_middleware, ...)`:
   - построить `PipelineExecutor` для `group.plugins` с `chain_targets` (только для финальной группы) и `output_queue`;
   - `target = lambda stop, pause: executor.run_loop(input_queue, stop, pause)`;
   - проверить `worker_manager.has_worker(group.worker_name)`:
     - если есть и `is_worker_protected(...)` → НЕ трогать, вызвать fallback из 2.5 (логика edge case);
     - если есть и НЕ protected → `remove_worker(group.worker_name)` затем `create_worker(..., auto_start=True)`;
     - если нет → `create_worker(..., auto_start=True)`;
   - логировать `group worker '{name}' started ({n} plugins)`.
2. `data_receiver` создаётся как сейчас (один на процесс) и кладёт items в `chain_queue` первой группы.
3. Source-группы: переиспользовать существующую логику SourceProducer, но имя воркера брать из `group.worker_name` (из 2.2). Если source-плагину назначен явный `assigned_worker`, воркер именуется им; lifecycle (создать/пересоздать) аналогичен processing-группам.
4. Гарантировать порядок: воркеры финальной группы можно стартовать первыми или последними — зафиксировать (рекомендуется создавать от последней группы к первой, чтобы потребитель очереди был готов раньше продюсера; либо обосновать иной порядок). Описать выбор в докстринге.
5. Тесты с фейковым `worker_manager` (записывает вызовы `has_worker/is_worker_protected/remove_worker/create_worker`): (а) одна группа, воркера нет → один `create_worker("pipeline_executor")`, регресс; (б) воркер группы существует, не protected → `remove_worker`+`create_worker`; (в) две группы → два `create_worker` с разными именами и связанными очередями.

**Acceptance criteria:**
- [ ] Одна группа без существующего воркера → ровно один `create_worker("pipeline_executor", auto_start=True)` (нулевой регресс)
- [ ] Существующий незащищённый воркер группы → `remove_worker` затем `create_worker` (пересоздание с PipelineExecutor.run_loop)
- [ ] Отсутствующий воркер группы → `create_worker` (а не падение)
- [ ] N групп → N воркеров с именами групп, очереди связаны согласно 2.3
- [ ] `python scripts/run_framework_tests.py` зелёный; `make check` чист

**Out of scope:** edge case protected/несуществующий-как-аномалия (2.5 содержит fallback-логику — здесь только вызов хука); GUI-smoke вживую; адресация до воркера (отдельный план).
**Edge cases:** воркер группы существует и protected (делегировать в 2.5 fallback); WorkerSpec IdleWorker без cycle-метрик; повторный вызов `_init_data_pipeline` (не должен дублировать воркеры — но это вне типового lifecycle, отметить TODO если требуется).
**Dependencies:** 2.2, 2.3
**Module contract:** impl-only (внутренняя логика `GenericProcess`, публичный API не меняется)

#### Task 2.5 — Edge cases: protected-воркер и устойчивость группировки

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Корректно обработать аномальные назначения: `assigned_worker` указывает на protected-воркер → fallback в дефолт + warning; имя совпадает с системным/занятым воркером — без падения.
**Context:** Пользователь в Pipeline может назначить плагин в защищённый воркер (`message_processor`) или иной системный. Рантайм не должен ломать lifeline процесса — такие назначения сводятся к дефолтной группе с предупреждением. Несуществующий воркер уже покрыт «создать» в 2.4; здесь — защита от опасных имён.
**Files:**
- `multiprocess_framework/modules/process_module/generic/pipeline_grouping.py` или `generic_process.py` — guard эффективного имени воркера
- соответствующий тест-файл (`test_pipeline_grouping.py` / `test_data_pipeline_groups.py`)

**Steps:**
1. При вычислении эффективного `worker_name` (в группировке или в `_spawn_group_worker`) проверить через `worker_manager.is_worker_protected(name)`: если назначенный воркер protected И это не штатный дефолт группы — заменить на дефолт (`"pipeline_executor"` для processing) и залогировать `WARNING: assigned_worker '{name}' is protected → fallback to default`.
2. Если `is_worker_protected` недоступен (нет worker_manager, например в unit-тестах группировки) — guard не падает (no-op, трактует как не-protected). Решить, где удобнее держать guard: чистая группировка не имеет доступа к worker_manager → guard логичнее в `_spawn_group_worker`/перед группировкой передать предикат `is_protected`. Рекомендуется: `group_processing_plugins` принимает опциональный `is_protected: Callable[[str], bool] | None`, и при protected-назначении использует default.
3. Уточнить кейс «несколько плагинов назначены в protected-воркер» — все они уходят в дефолтную группу (могут слиться с дефолтной по смежности или образовать сегмент дефолта согласно правилу смежных сегментов 2.2).
4. Тесты: (а) плагин назначен в `message_processor` → попадает в дефолтную группу, в логах warning; (б) предикат `is_protected=None` → группировка работает как без guard; (в) несколько protected-назначений подряд.

**Acceptance criteria:**
- [ ] Назначение в protected-воркер → плагин в дефолтной группе + WARNING в логе
- [ ] Группировка без предиката `is_protected` (unit-режим) не падает и игнорирует guard
- [ ] lifeline процесса (`message_processor`) никогда не пересоздаётся под PipelineExecutor
- [ ] `python scripts/run_framework_tests.py` зелёный; `make check` чист

**Out of scope:** несуществующий воркер как ошибка (он штатно создаётся в 2.4); валидация имён на стороне GUI/Pipeline-инспектора; адресация до воркера.
**Edge cases:** `assigned_worker == "message_processor"`; `assigned_worker` == имя системного heartbeat-воркера (WorkerType.SYSTEM); пустой worker_manager.
**Dependencies:** 2.2, 2.4
**Module contract:** impl-only

#### Task 2.6 — Интеграционный тест варианта A + документация

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** End-to-end доказать вариант A на реальных GenericProcess-компонентах (≥2 группы), зафиксировать нулевой регресс и обновить документацию модуля/ADR.
**Context:** Unit-тесты покрывают группировку/handoff/lifecycle по отдельности; нужен один интеграционный тест на собранном data pipeline (как `test_integration_u1_delivery.py` из Фазы 1) и фиксация решения «вариант A» в DECISIONS/README.
**Files:**
- `multiprocess_framework/modules/process_module/tests/test_data_pipeline_variant_a.py` — создать (интеграционный тест)
- `multiprocess_framework/modules/process_module/DECISIONS.md` — ADR-запись «runtime по assigned_worker, вариант A» (затем `python -m scripts.sync`)
- `multiprocess_framework/modules/process_module/README.md` — раздел про группы/assigned_worker
- `multiprocess_framework/MODULES_STATUS.md` — отметить изменение, если ведётся

**Steps:**
1. Собрать минимальный GenericProcess (или его data-pipeline часть) с фейковым/реальным WorkerManager и 3+ processing-плагинами с назначениями, дающими ≥2 группы; прогнать item от `chain_queue` через все группы до перехвата IPC-send последней группы. Проверить порядок применения плагинов и доставку.
2. Регресс-сценарий в том же файле: все плагины без `assigned_worker` → один воркер `pipeline_executor`, IPC как раньше.
3. Добавить ADR в `DECISIONS.md` (код модуля + дата + ссылка на план): зафиксировать вариант A, правило смежных сегментов, in-process handoff без SHM на промежуточных звеньях, fallback protected→default. Запустить `python -m scripts.sync` и проверить `python scripts/validate.py` (нет дрифта документации).
4. Обновить README модуля: коротко описать, как `assigned_worker` раскладывает цепочку по воркерам и что одна группа == прежнее поведение.

**Acceptance criteria:**
- [ ] Интеграционный тест на ≥2 группах зелёный (item проходит все группы → один IPC-send)
- [ ] Регресс-сценарий в том же файле зелёный (одна группа == текущее поведение)
- [ ] ADR добавлен, `python -m scripts.sync` выполнен, `python scripts/validate.py` без дрифта
- [ ] README модуля обновлён (раздел про assigned_worker/группы)
- [ ] `python scripts/run_framework_tests.py` / `make test` полностью зелёные; `make check` чист

**Out of scope:** GUI-smoke вживую (qt_snapshot) — отложено до возможности запуска; продюсеры `state.fps`/`latency_ms`/`system.health.*`; push-модель адресной книги.
**Edge cases:** интеграция при отсутствии SHM (memory_manager=None); один source + одна processing-группа.
**Dependencies:** 2.1–2.5
**Module contract:** n/a (тесты + документация; код не меняется)

---

### Связь с аудитом коммуникаций (`multiprocess_framework/docs/COMMUNICATION_MAP.md`, 2026-05-31)

Многоагентный аудит всей системы коммуникаций (23 подсистемы, 166 механизмов) показал: канонический
cross-process транспорт — **адресация по имени процесса** (`send_message(target)` / `targets` →
`_deliver_by_targets` → `queue_registry`), а channel-routing RouterManager (`FieldRouting.channel`,
`register_route`) для рантайма почти мёртв. Отсюда ограничения для задач 2.1–2.6:

1. **assigned_worker — control-plane по targets.** Адресация по имени процесса; доставка через
   `_deliver_by_targets`/`queue_registry` (узаконено как основной путь, не «временный fallback»).
   Новых Router-каналов / `register_route` / broadcast-маршрутов под assigned_worker **не вводить**.
2. **In-process handoff = паттерн `chain_queue`** (`queue.Queue` + LOOP-worker через WorkerManager),
   как `DataReceiver → chain_queue → PipelineExecutor`. **Запрещено** реанимировать
   `WorkerPoolDispatcher` / `chain_module` / `CrossProcessStep` — они мёртвы и противоречат «минимум
   звеньев» (это уже зафиксировано в Out of scope задач 2.3/2.4 — здесь усилено явным запретом).
3. **Подтверждение назначения — через StateStore (живой долг #1), не через `process.command.response`**
   (response теряется, MEDIUM-риск аудита). Процесс публикует `processes.X.workers.Y.*` → GUI читает
   через bindings.
4. **SHM/frame-транспорт не задевается** — assigned_worker это control-plane, не data-plane
   (ADR-COMM-003 по SHM ортогонален Фазе 2).

Корректировки **декларативные** (зафиксировать опору на targets-транспорт + `chain_queue`-паттерн +
запрет мёртвых движков), структуру задач 2.1–2.6 не меняют. Подробности и предлагаемые ADR-COMM-001/002 —
в `COMMUNICATION_MAP.md`.

### Реконсиляция с transport-router-hub P2 (2026-05-31, решение владельца: ГИБРИД)

План [`transport-router-hub`](../../plans/2026-05-31_transport-router-hub/plan.md) (P2) ввёл
иерархическую адресацию `proc.worker`. Чтобы **не было двух транспортов для воркера**, оси
разведены (решение владельца «кадры—трубы, команды—почта»):

- **Кадры между группами воркеров (data-plane)** → **М1 «трубы»**: статическая топология
  in-process `queue.Queue` — **ровно Фаза 2 вариант A этого плана, БЕЗ изменений**. Handoff
  кадров НЕ адресный (не через `proc.worker`); cross-process — по имени процесса. Формулировка
  «адресация до воркера — отдельный план» здесь относится к КОМАНДАМ, не к кадрам, и остаётся в силе.
- **Команды/конфиг воркеру (control-plane)** → **М2 «почта»**: transport-router-hub P2.2
  (`RouterManager.register_worker_handler` + роутинг по `_address`). Эта ось **ортогональна**
  Фазе 2 и ей не нужна — Фаза 2 строит только data-plane handoff.

**Вывод:** Фаза 2 (вариант A) реализуется как расписано (2.1–2.6), НЕ ждёт P2.2 и НЕ переписывается
под адресную доставку кадров. Worker-handler из P2.2 — для будущей фичи «команда плагину-в-воркере»,
не для исполнения pipeline.

## Верификация (общая)

- Тесты из корня: `python scripts/run_framework_tests.py` / `make test`.
- `make check` (ruff + pyright + bandit).
- Qt-smoke (после Фазы 2 / при возможности запуска): назначить плагин в воркер в Pipeline → во вкладке
  «Процессы» виден воркер с телеметрией (effective_hz>0), а не IdleWorker.

## Коммиты

- Фаза 1 — отдельный `feat`-коммит (Layer: mixed). Фаза 2 — следующий (Layer: framework). `Refs` на
  этот план. Push-модель адресной книги + адресация до воркера — отдельный `/plan`.
