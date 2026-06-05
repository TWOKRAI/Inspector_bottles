export const meta = {
  name: 'comm-arch-unification-v2',
  description: 'Честный аудит и унификация систем коммуникации фреймворка вокруг RouterManager-хаба',
  phases: [
    { title: 'Map', detail: '15 параллельных читателей: по одной comm-подсистеме, с доказательствами вызовов' },
    { title: 'Cross-concern', detail: '8 агентов: сравнение по сквозным заботам, выбор ОДНОГО лучшего' },
    { title: 'Verify', detail: 'Адверсариальная проверка каждого claim «мёртв/дубль/удалить» по коду' },
    { title: 'Synthesize', detail: 'Целевая архитектура + матрица сохранности функций + критика + финал' },
  ],
}

// ─────────────────────────────────────────────────────────────────────────
// SCHEMAS
// ─────────────────────────────────────────────────────────────────────────

const SYSTEM_MAP = {
  type: 'object',
  additionalProperties: false,
  required: ['system', 'layer', 'responsibility', 'public_api', 'patterns',
             'capabilities', 'usage', 'overlaps_with', 'strengths', 'weaknesses',
             'modernity', 'why_created', 'notes'],
  properties: {
    system: { type: 'string' },
    layer: { type: 'string' },
    responsibility: { type: 'string', description: 'Одна фраза: каноническая ответственность' },
    public_api: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['name', 'purpose'],
        properties: { name: { type: 'string' }, signature: { type: 'string' }, purpose: { type: 'string' } },
      },
    },
    patterns: { type: 'array', items: { type: 'string' }, description: 'Паттерны: pub/sub, facade, strategy, middleware, ...' },
    capabilities: {
      type: 'array',
      description: 'Что система УМЕЕТ — нужно для матрицы сохранности функций при слиянии',
      items: {
        type: 'object', additionalProperties: false,
        required: ['capability', 'description'],
        properties: { capability: { type: 'string' }, description: { type: 'string' }, evidence: { type: 'string' } },
      },
    },
    usage: {
      type: 'object', additionalProperties: false,
      required: ['status', 'consumer_count', 'consumers', 'evidence_method'],
      properties: {
        status: { type: 'string', enum: ['live', 'partial', 'dead', 'tests-only'] },
        consumer_count: { type: 'integer' },
        consumers: {
          type: 'array',
          items: {
            type: 'object', additionalProperties: false,
            required: ['file_line', 'what', 'kind'],
            properties: {
              file_line: { type: 'string' },
              what: { type: 'string' },
              kind: { type: 'string', enum: ['production', 'test', 'self', 'docs'] },
            },
          },
        },
        evidence_method: { type: 'string', description: 'grep / qex / codegraph — как проверено' },
      },
    },
    overlaps_with: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['system', 'what_overlaps'],
        properties: { system: { type: 'string' }, what_overlaps: { type: 'string' }, nature: { type: 'string' } },
      },
    },
    strengths: { type: 'array', items: { type: 'string' } },
    weaknesses: { type: 'array', items: { type: 'string' } },
    modernity: { type: 'string', description: 'Оценка паттерна vs современная практика' },
    why_created: { type: 'string', description: 'Из ADR/DECISIONS — исходный замысел' },
    notes: { type: 'string' },
  },
}

const CONCERN_ANALYSIS = {
  type: 'object',
  additionalProperties: false,
  required: ['concern', 'systems_involved', 'comparison', 'duplication_verdict',
             'recommended_winner', 'rationale', 'features_to_absorb',
             'functionality_loss_check', 'keep_as_capability', 'claims_to_verify'],
  properties: {
    concern: { type: 'string' },
    systems_involved: { type: 'array', items: { type: 'string' } },
    comparison: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['system', 'does_what', 'pros', 'cons'],
        properties: {
          system: { type: 'string' }, does_what: { type: 'string' },
          pros: { type: 'array', items: { type: 'string' } },
          cons: { type: 'array', items: { type: 'string' } },
          unique_features: { type: 'array', items: { type: 'string' } },
        },
      },
    },
    duplication_verdict: { type: 'string', description: 'Есть ли РЕАЛЬНОЕ дублирование? Где именно?' },
    recommended_winner: { type: 'string', description: 'ОДИН лучший подход для этой заботы' },
    rationale: { type: 'string' },
    features_to_absorb: {
      type: 'array', description: 'Лучшие функции из проигравших, которые надо влить в победителя',
      items: {
        type: 'object', additionalProperties: false,
        required: ['from_system', 'feature', 'why'],
        properties: { from_system: { type: 'string' }, feature: { type: 'string' }, why: { type: 'string' } },
      },
    },
    functionality_loss_check: {
      type: 'array', description: 'Каждая способность проигравших → где живёт после унификации',
      items: {
        type: 'object', additionalProperties: false,
        required: ['capability', 'preserved_where', 'status'],
        properties: {
          capability: { type: 'string' },
          preserved_where: { type: 'string' },
          status: { type: 'string', enum: ['preserved', 'at-risk', 'lost', 'intentionally-dropped'] },
        },
      },
    },
    keep_as_capability: {
      type: 'array', description: 'Что НЕ удалять — оставить как capability конструктора',
      items: {
        type: 'object', additionalProperties: false,
        required: ['system', 'why'],
        properties: { system: { type: 'string' }, why: { type: 'string' } },
      },
    },
    claims_to_verify: {
      type: 'array', description: 'Спорные утверждения для адверсариальной проверки по коду',
      items: {
        type: 'object', additionalProperties: false,
        required: ['claim', 'why_uncertain'],
        properties: { claim: { type: 'string' }, why_uncertain: { type: 'string' } },
      },
    },
  },
}

const VERDICT = {
  type: 'object',
  additionalProperties: false,
  required: ['claim', 'verdict', 'evidence', 'confidence', 'correction'],
  properties: {
    claim: { type: 'string' },
    verdict: { type: 'string', enum: ['confirmed', 'refuted', 'partial'] },
    evidence: { type: 'array', items: { type: 'string' }, description: 'file:line факты' },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    correction: { type: 'string', description: 'Если refuted/partial — как на самом деле' },
  },
}

const CRITIQUE = {
  type: 'object',
  additionalProperties: false,
  required: ['gaps', 'unverified_claims', 'lost_capabilities', 'overall_grade'],
  properties: {
    gaps: { type: 'array', items: { type: 'string' }, description: 'Что упущено в синтезе' },
    unverified_claims: { type: 'array', items: { type: 'string' } },
    lost_capabilities: { type: 'array', items: { type: 'string' }, description: 'Способности, которые потерялись без обоснования' },
    overall_grade: { type: 'string' },
  },
}

// ─────────────────────────────────────────────────────────────────────────
// ОБЩИЕ ОГРАНИЧЕНИЯ (для всех агентов с доступом к коду)
// ─────────────────────────────────────────────────────────────────────────

const QEX_GUARD = `КРИТИЧНО про qex: индекс qex СВЕЖИЙ. ЗАПРЕЩЕНО запускать переиндексацию — НЕ вызывай mcp__qex__index_codebase / clear_index / download_model и slash /qex-rebuild /qex-reindex. Используй ТОЛЬКО mcp__qex__search_code для ПОИСКА (read-only). Прошлый аудит сорвался из-за случайного full-reindex — не повтори.`

// ─────────────────────────────────────────────────────────────────────────
// PHASE A — work-list (15 подсистем коммуникации)
// ─────────────────────────────────────────────────────────────────────────

const WORKITEMS = [
  {
    key: 'router', title: 'RouterManager — IPC-хаб (ядро)',
    scope: 'multiprocess_framework/modules/router_module/ (README.md, DECISIONS.md, interfaces.py, core/router_manager.py, channels/, middleware/, AsyncSender/AsyncReceiver)',
    questions: 'Полный набор send/send_async/request/receive/broadcast; как работает message_dispatcher и channel_dispatcher; контракт IMessageChannel; как регистрируются каналы; _select_queue_type; _deliver_by_targets; адресация targets vs channel. Это ядро — особенно тщательно.',
  },
  {
    key: 'channel_routing', title: 'channel_routing_module — паттерн CRM (база менеджеров и роутера)',
    scope: 'multiprocess_framework/modules/channel_routing_module/ (README, DECISIONS, ChannelRoutingManager, ChannelRegistry, IChannel, буферы Direct/Batch/AsyncSender)',
    questions: 'Что даёт базовый CRM; кто наследует (RouterManager, Logger/Error/Stats); буферные стратегии; почему это база, а не дубль роутера.',
  },
  {
    key: 'dispatch', title: 'dispatch_module — диспетчеризация key→handler (4 стратегии + сценарии)',
    scope: 'multiprocess_framework/modules/dispatch_module/ (README, core/dispatcher.py, strategies/*, scenarios.py, scenario_builder.py, base_dispatcher.py)',
    questions: 'Какие стратегии (EXACT/PATTERN/FALLBACK/CHAIN) и сценарии реально используются в проде, а какие только в тестах? Кто потребитель Dispatcher (command_module? router? другие)? Владелец считает модуль полезным — найди где он РЕАЛЬНО ценен и где мёртв. Сравни с message_dispatcher роутера.',
  },
  {
    key: 'message', title: 'message_module — конверт IPC (Message/MessageAdapter/MessageType)',
    scope: 'multiprocess_framework/modules/message_module/ (README, Message, MessageAdapter, MessageType, поля конверта)',
    questions: 'Полный список полей конверта; дубли queue_type/type, request_id/correlation_id, channel; 9 типов MessageType — все ли живые; что в _address. Кто создаёт сообщения мимо MessageAdapter.',
  },
  {
    key: 'command', title: 'command_module — CommandManager (фасад над dispatch)',
    scope: 'multiprocess_framework/modules/command_module/ (README, CommandManager, BaseCommandManager)',
    questions: 'Чем отличается от Dispatcher; зачем фасад; где register_command вызывается в проде; связь с RouterManager.receive. Не дублирует ли dispatch_module/ActionBus.',
  },
  {
    key: 'actions', title: 'actions_module — ActionBus (command/undo движок)',
    scope: 'multiprocess_framework/modules/actions_module/ (README, DECISIONS, bus.py)',
    questions: 'Точное число PROD-потребителей (прошлый аудит: 0). Проверь по всему репо (grep+qex+codegraph). Что умеет (undo/redo/capability) чего нет у CommandManager и у CommandDispatcherOrchestrator прототипа. Замысел из ADR. RolesPanel bus=None — реальный баг?',
  },
  {
    key: 'state_store', title: 'state_store_module — реактивное дерево состояния + подписки',
    scope: 'multiprocess_framework/modules/state_store_module/ (README, DECISIONS, StateStoreManager, StateProxy, GuiStateProxy, DeltaDispatcher, SubscriptionManager, IRouter Protocol, middleware)',
    questions: 'Как доставляются дельты (state.changed) и через какой queue_type; почему DeltaDispatcher хардкодит queue_type="system"; механизм subscribe/request_id; почему не зависит от RouterManager (IRouter). Это «главный для состояния» — оцени как канон pub/sub.',
  },
  {
    key: 'shared_resources', title: 'shared_resources_module — транспорт (QueueRegistry, SHM, EventManager, ProcessHandle)',
    scope: 'multiprocess_framework/modules/shared_resources_module/ (README, queues/core/manager.py send_to_queue, MemoryManager/SHM, EventManager, ProcessStateRegistry, ProcessHandle chainable API)',
    questions: 'Реальный транспорт под хабом; send_to_queue; какие очереди (_data/_system/_local/system_events); ProcessHandle.for_process().queue().send() — дублирует ли путь роутера; MemoryManager/SHM как транспорт кадров; EventManager.',
  },
  {
    key: 'process_comm', title: 'process_module — ProcessCommunication + FrameShmMiddleware + heartbeat',
    scope: 'multiprocess_framework/modules/process_module/ (communication/process_communication.py, generic/frame_shm_middleware.py, heartbeat/process_heartbeat.py)',
    questions: 'Фасад процесса send_message/send/broadcast/receive; дубль FrameShmMiddleware (router_module/middleware vs process_module/generic) — какой живой; тройная дверь в queue_registry (send_to_process vs router._deliver_by_targets vs broadcast); system_events 0 подписчиков; heartbeat поля.',
  },
  {
    key: 'process_manager', title: 'process_manager_module — оркестратор: reply_to_request, broadcast, state-server хост',
    scope: 'multiprocess_framework/modules/process_manager_module/ (process/process_manager_process.py _handle_process_command + reply_to_request, ProcessMonitor heartbeat/state broadcast, built-in commands)',
    questions: 'Где формируется ответ инициатору (ручной _handle_process_command vs дженерик reply_to_request — есть ли 0 ссылок); как PM хостит StateStore-server; broadcast статуса; protected:true потеря при recipe-launch (рестарт gui).',
  },
  {
    key: 'data_schema_routing', title: 'data_schema_module — FieldRouting / RouterSchemaAdapter (schema-driven routing)',
    scope: 'multiprocess_framework/modules/data_schema_module/ (core/field_routing.py FieldRouting, RouterSchemaAdapter, SchemaBase channel+process_targets)',
    questions: 'FieldRouting/RouterSchemaAdapter — где используется в проде vs только тесты; замысел из ADR (регистры как единый источник истины routing); связь с registers_module.resolve_dispatch_targets; это capability конструктора или мёртвый legacy? Честно.',
  },
  {
    key: 'services_channels', title: 'Services + service_module — IMessageChannel (Modbus эталон, Socket, SQL вне хаба)',
    scope: 'multiprocess_framework/modules/service_module/, Services/modbus/channels/modbus_channel.py, multiprocess_framework/modules/router_module/channels/socket_channel.py, Services/sql/core/sql_manager.py',
    questions: 'Как сервис регистрирует IMessageChannel в RouterManager (эталон ModbusChannel); SocketChannel backend_ctl; почему SQL вызывается execute_command В ОБХОД хаба; что нужно чтобы добавить redis/mcp-backend-control как канал — достаточен ли контракт IMessageChannel для cross-machine/контроллеров.',
  },
  {
    key: 'gui_layer', title: 'GUI comm-слой: domain EventBus, QtEventBus, CommandDispatcherOrchestrator, bridges',
    scope: 'multiprocess_prototype/domain/event_bus.py, multiprocess_prototype/frontend/qt_event_bus.py, multiprocess_prototype/adapters/dispatch/command_dispatcher.py, multiprocess_prototype/frontend/bridge.py, GuiStateBindings, _StateDeltaEmitter, app.py wiring',
    questions: 'Все механизмы сигналов GUI: Qt signals, domain EventBus, QtEventBus, CommandDispatcher (undo/redo snapshot), DataReceiverBridge (worker→main thread). ВЫЯВИ ЛИШНИЕ/ПУТАЮЩИЕ абстракции. Что из этого universal (carve-out во framework), что app-specific. Дубль-класс DataReceiverBridge (shadowing)? Сравни с framework ActionBus.',
  },
  {
    key: 'registers', title: 'registers_module — runtime регистров (resolve_dispatch_targets, connection_map, send_register_message)',
    scope: 'multiprocess_framework/modules/registers_module/ (README, RegistersManager, resolve_dispatch_targets, build_routing_map, connection_map, send_register_message, observers pub/sub)',
    questions: 'Как регистры маршрутизируют изменения; resolve_dispatch_targets vs router.targets vs FieldRouting; observers pub/sub vs StateStore vs EventBus — дубль реактивности? send_register_message — отдельная дверь в хаб?',
  },
  {
    key: 'chain', title: 'chain_module — DAG/Chain + WorkerPoolDispatcher (cross-process worker dispatch)',
    scope: 'multiprocess_framework/modules/chain_module/ (README, ChainRunnable/DagRunnable, WorkerPoolDispatcher round-robin/backpressure, WorkerTaskRequest/Response IPC, IRemoteExecutable)',
    questions: 'Это data-flow исполнитель внутри процесса, но WorkerPoolDispatcher делает cross-process IPC — пересекается ли с RouterManager? WorkerTaskRequest/Response — отдельный IPC-протокол мимо хаба? Когда это оправдано (hot data-path) vs дубль транспорта.',
  },
]

// ─────────────────────────────────────────────────────────────────────────
// PHASE A — fan-out maps
// ─────────────────────────────────────────────────────────────────────────

phase('Map')
log(`Фаза 1: картирование ${WORKITEMS.length} подсистем коммуникации (с доказательствами вызовов)`)

const mapPrompt = (it) => `Ты картируешь ОДНУ подсистему коммуникации Python-фреймворка многопроцессных приложений (проект Inspector_bottles, рабочая директория d:\\PROJECT_INNOTECH\\Inspector_vision\\Inspector_bottles). Цель — честная, доказательная карта для унификации архитектуры вокруг хаба RouterManager.

ПОДСИСТЕМА: ${it.title}
ОСНОВНОЙ SCOPE (прочитай это): ${it.scope}
КЛЮЧЕВЫЕ ВОПРОСЫ: ${it.questions}

ОБЯЗАТЕЛЬНО:
- Прочитай README.md, DECISIONS.md (если есть), interfaces.py и core-исходники из scope.
- Определи РЕАЛЬНУЮ ответственность и полный публичный API.
- Перечисли ВСЕ capabilities (что умеет) — это нужно, чтобы доказать «функционал не теряется» при слиянии.
- Найди РЕАЛЬНЫХ prod-потребителей с доказательствами file:line. Используй Grep И mcp__qex__search_code И mcp__codegraph__callers. Ищи по ВСЕМУ репозиторию. ИСКЛЮЧИ multiprocess_prototype_backup/ (это снэпшот — игнорировать). Отделяй prod-вызовы от тестов (kind: production/test/self/docs).
- Прочитай релевантные ADR, чтобы зафиксировать ЗАМЫСЕЛ (why_created) — принцип владельца: «не используется ≠ не нужно».
- Отметь пересечения (overlaps) с соседними comm-системами.
- Оцени современность паттерна (хорош/устарел) vs актуальная практика для масштабируемых распределённых систем.
- БУДЬ ЧЕСТЕН: прошлый аудит содержал ЛОЖНОЕ утверждение («register_message_handlers не вызывается» — оказалось вызывается). Не доверяй прошлым выводам — проверяй по коду. Если consumer_count=0, докажи это, а не предположи.
- Цель владельца — НЕ переписать, а собрать существующие модули в одну систему и довести до идеала. Поэтому в notes отметь МЕЛКИЕ конкретные проблемы (баги, рассинхрон, мёртвый relay, путающая абстракция), которые мешают «лаконичности и лёгкой отладке».
${QEX_GUARD}

Верни ТОЛЬКО структурированный объект (SYSTEM_MAP).`

const mapResults = await parallel(
  WORKITEMS.map((it) => () =>
    agent(mapPrompt(it), { label: `map:${it.key}`, phase: 'Map', schema: SYSTEM_MAP, model: 'sonnet' })),
)

const mapsByKey = {}
WORKITEMS.forEach((it, i) => { if (mapResults[i]) mapsByKey[it.key] = mapResults[i] })
const liveMaps = Object.values(mapsByKey)
log(`Фаза 1 готова: ${liveMaps.length}/${WORKITEMS.length} карт собрано`)

// ─────────────────────────────────────────────────────────────────────────
// PHASE B — cross-concern unification (barrier: каждой заботе нужны несколько карт)
// ─────────────────────────────────────────────────────────────────────────

phase('Cross-concern')

const CONCERNS = [
  {
    key: 'transport', title: 'Транспортный слой и каналы RouterManager (queue/shm/modbus/socket/sql + future redis/mcp)',
    keys: ['router', 'channel_routing', 'shared_resources', 'process_comm', 'services_channels', 'message', 'chain'],
    focus: 'Тезис владельца: RouterManager — ЕДИНЫЙ универсальный хаб с подключаемыми каналами (queue/shm/modbus/socket/sql/redis/mcp), маршрутизация по типу сообщения + адресу. Валидируй или оспорь. Спроектируй контракт канала, достаточный для cross-machine/контроллеров (modbus/socket/redis/mcp-backend-control). Реши: SHM и WorkerPoolDispatcher — это каналы хаба или оправданный отдельный hot-path? SQL мимо хаба — привести или оставить исключением? Тройная дверь в queue_registry — свести к одному _dispatch.',
  },
  {
    key: 'dispatch', title: 'Диспетчеризация key→handler',
    keys: ['dispatch', 'command', 'router', 'registers'],
    focus: 'dispatch_module (4 стратегии+сценарии) vs CommandManager (фасад) vs router.message_dispatcher vs registers.resolve_dispatch_targets. Владелец считает dispatch_module полезным — найди где он реально ценен (PATTERN/FALLBACK/CHAIN/scenarios) и где мёртв. ОДИН лучший слой диспетчеризации, в который вливаются лучшие функции остальных. Не теряем ли сценарии/паттерны.',
  },
  {
    key: 'commands', title: 'Команды + undo/redo',
    keys: ['actions', 'command', 'gui_layer', 'dispatch'],
    focus: 'ActionBus (framework, undo/redo, прошлый аудит: 0 prod) vs CommandDispatcherOrchestrator (prototype GUI, живой, undo/redo snapshot) vs CommandManager (IPC-команды). Это РАЗНЫЕ слои (IPC-команда процессу vs GUI-мутация с undo)? Нужен ли ActionBus как framework-capability или его роль закрывает prototype-вариант, который надо вынести во framework? Докажи без потери undo/redo.',
  },
  {
    key: 'state_pubsub', title: 'Состояние / pub-sub / реактивность',
    keys: ['state_store', 'gui_layer', 'registers', 'channel_routing'],
    focus: 'Сколько механизмов pub/sub: StateStore (дельты+glob-подписки), domain EventBus (GUI), registers observers, ConfigManager.subscribe, ObservableMixin. Это РАЗНЫЕ уровни или дубль? ОДИН канон реактивного состояния (StateStore) + ОДИН канон in-proc событий (EventBus). Что absorb. Лишние/путающие абстракции.',
  },
  {
    key: 'envelope', title: 'Конверт сообщения / контракт',
    keys: ['message', 'router', 'state_store', 'process_manager', 'process_comm'],
    focus: 'Минимальный канонический конверт. Дубли queue_type/type, request_id/correlation_id, vestigial channel="data"/"system". queue_type выводить из type через _select_queue_type. _address для иерархической адресации process→worker→deeper. Что убрать без потери совместимости.',
  },
  {
    key: 'gui_signals', title: 'GUI signal-слой и лишние абстракции',
    keys: ['gui_layer', 'state_store', 'process_comm'],
    focus: 'Все механизмы сигналов GUI: Qt signals, domain EventBus, QtEventBus, CommandDispatcher, DataReceiverBridge (worker→main thread), GuiStateBindings, _StateDeltaEmitter. ВЫЯВИ ЛИШНИЕ/ПУТАЮЩИЕ абстракции и дубль-классы (shadowing). Что canonical для: (а) backend→GUI телеметрия, (б) внутри-GUI событие, (в) GUI-команда+undo, (г) доставка worker→main thread. Что carve-out во framework.',
  },
  {
    key: 'request_reply', title: 'request/reply + иерархическая адресация (cross-machine ready)',
    keys: ['router', 'process_manager', 'message', 'shared_resources'],
    focus: 'router.request() (correlation_id) vs ручной reply в _handle_process_command vs дженерик reply_to_request (0 ссылок?). Нужен авто-reply по request_id в receive()/message_dispatcher. Иерархический адрес process→worker→deeper (нижние уровни опц., порядок обязателен). Готовность к cross-machine адресации (machine.process.worker?). Разблокирует ли это надёжный StateProxy.subscribe.',
  },
  {
    key: 'schema_routing', title: 'Schema-driven routing (FieldRouting) — capability или legacy',
    keys: ['data_schema_routing', 'registers', 'channel_routing', 'router'],
    focus: 'FieldRouting/RouterSchemaAdapter (декларативный routing из SchemaBase) — мёртвый legacy или ценная capability конструктора? Замысел: «регистр декларирует поле один раз, включая маршрут». Сравни с императивным targets. Решение: оживить как декларативный слой над хабом / оставить @experimental / удалить. Без потери идеи single-source-of-truth.',
  },
]

const concernPrompt = (c) => {
  const relevantMaps = c.keys.map((k) => mapsByKey[k]).filter(Boolean)
  return `Ты делаешь сквозной унификационный анализ ОДНОЙ заботы (concern) систем коммуникации фреймворка. Цель — выбрать ОДИН лучший подход и доказать, что функционал не теряется.

ЗАБОТА: ${c.title}
ФОКУС: ${c.focus}

КАРТЫ ВОВЛЕЧЁННЫХ ПОДСИСТЕМ (результат фазы 1, доказательная база):
${JSON.stringify(relevantMaps, null, 1)}

ОБЯЗАТЕЛЬНО:
- Честное сравнение: pros/cons/уникальные функции каждой системы по этой заботе.
- Вердикт по дублированию: есть ли РЕАЛЬНЫЙ дубль (одна операция — разные двери) или это разные уровни ответственности.
- Выбери ОДИН лучший (recommended_winner) — эффективный, современный, удобный. Не «тот что используют», а лучший по существу.
- features_to_absorb: лучшие функции проигравших, которые надо влить в победителя (чтобы он стал ЛУЧШИМ).
- functionality_loss_check: КАЖДАЯ способность проигравших → где живёт после унификации (preserved/at-risk/lost/intentionally-dropped). Цель — НЕ потерять функционал.
- keep_as_capability: что НЕ удалять (capability конструктора), даже если сейчас не используется — но только если нет дубля.
- claims_to_verify: спорные утверждения (особенно «мёртв/0 потребителей/дубль»), которые требуют проверки по коду на фазе 3. Прошлый аудит ошибался — будь скептичен.
- Если карт мало или данные противоречивы — отметь это, не выдумывай.
- Держи в уме масштаб: фреймворк-конструктор для мощных распределённых систем (серверные, машинное зрение с НС, микро/макросервисы), будущая связь с машинами/контроллерами.

Верни ТОЛЬКО структурированный объект (CONCERN_ANALYSIS).`
}

const concerns = await parallel(
  CONCERNS.map((c) => () =>
    agent(concernPrompt(c), { label: `concern:${c.key}`, phase: 'Cross-concern', schema: CONCERN_ANALYSIS })),
)
const liveConcerns = concerns.filter(Boolean)
log(`Фаза 2 готова: ${liveConcerns.length}/${CONCERNS.length} сквозных анализов`)

// ─────────────────────────────────────────────────────────────────────────
// PHASE C — adversarial verification (barrier: собрать+дедуп claims из карт и забот)
// ─────────────────────────────────────────────────────────────────────────

phase('Verify')

// собрать claims: статусы dead/partial/tests-only из карт + claims_to_verify + duplication_verdicts
const claimSet = new Map()
const addClaim = (text) => {
  const t = (text || '').trim()
  if (t.length > 8 && !claimSet.has(t)) claimSet.set(t, true)
}
for (const k of Object.keys(mapsByKey)) {
  const m = mapsByKey[k]
  if (m.usage && (m.usage.status === 'dead' || m.usage.status === 'tests-only' || m.usage.status === 'partial')) {
    addClaim(`Подсистема «${m.system}» имеет статус ${m.usage.status} (заявлено prod-потребителей: ${m.usage.consumer_count}). Проверь по коду, что это действительно так.`)
  }
}
for (const c of liveConcerns) {
  for (const cv of (c.claims_to_verify || [])) addClaim(cv.claim)
  if (c.duplication_verdict && /дубл|duplicat|дверь|обход|обхо/i.test(c.duplication_verdict)) {
    addClaim(`[concern: ${c.concern}] Вердикт дублирования: ${c.duplication_verdict}`)
  }
}
const claims = Array.from(claimSet.keys())
log(`Фаза 3: адверсариальная проверка ${claims.length} утверждений по коду`)

const verifyPrompt = (claim) => `Ты — скептик-верификатор. Проверь утверждение об архитектуре коммуникаций по РЕАЛЬНОМУ коду (проект Inspector_bottles, d:\\PROJECT_INNOTECH\\Inspector_vision\\Inspector_bottles). По умолчанию НЕ доверяй — ищи опровержение.

УТВЕРЖДЕНИЕ: «${claim}»

ОБЯЗАТЕЛЬНО:
- Проверь по коду: Grep + mcp__qex__search_code + mcp__codegraph__callers. Ищи по всему репо. ИСКЛЮЧИ multiprocess_prototype_backup/.
- Для «мёртв / 0 потребителей»: найди ВСЕ ссылки; отдели prod от тестов; если есть хоть один prod-потребитель — refuted.
- Для «дубль»: открой обе стороны и сравни фактический код-путь.
- Дай evidence строго как file:line факты.
- Прошлый аудит ошибался (ложно заявил «register_message_handlers не вызывается»). Не повтори: проверяй вызовы реально.
- confidence high только если лично видел код-доказательства.
${QEX_GUARD}

Верни ТОЛЬКО структурированный объект (VERDICT).`

const verdicts = (await parallel(
  claims.map((cl) => () =>
    agent(verifyPrompt(cl), { label: `verify:${cl.slice(0, 40)}`, phase: 'Verify', schema: VERDICT, model: 'sonnet' })),
)).filter(Boolean)

const refuted = verdicts.filter((v) => v.verdict === 'refuted')
const partial = verdicts.filter((v) => v.verdict === 'partial')
log(`Фаза 3 готова: ${verdicts.length} вердиктов · опровергнуто ${refuted.length} · частично ${partial.length}`)

// ─────────────────────────────────────────────────────────────────────────
// PHASE D — synthesis → critique → final
// ─────────────────────────────────────────────────────────────────────────

phase('Synthesize')

const corpus = {
  maps: mapsByKey,
  concerns: liveConcerns,
  verdicts,
}

const synthPrompt = `Ты — главный архитектор. На основе доказательной базы (карты подсистем + сквозные анализы + проверенные вердикты) спроектируй ЕДИНУЮ целевую архитектуру коммуникаций фреймворка-конструктора многопроцессных приложений.

ТЕЗИС ВЛАДЕЛЬЦА (валидируй и разверни, либо аргументированно скорректируй):
RouterManager — ЕДИНАЯ универсальная точка коммуникации. У него каналы: очереди, SHM, modbus, socket, redis, sql, mcp-backend-control. Он по типу сообщения и иерархическому адресу (process→worker→глубже, в перспективе machine→process→worker) доставляет данные. Остальное — надстройки/GUI-слой/legacy. Цель: ЛУЧШАЯ архитектура-конструктор для мощных распределённых систем (серверные, машинное зрение с нейросетями, микро/макросервисы), масштабируемая, с возможностью общаться с другими машинами и контроллерами.

ПРИНЦИПЫ ВЛАДЕЛЬЦА (соблюдай строго):
- ЭТО НЕ ПЕРЕПИСЫВАНИЕ. Модули уже написаны владельцем. Задача — СОБРАТЬ их в ОДНУ систему, обрамить и довести до идеала, найдя мелкие проблемы. Предлагай минимальные, элегантные ходы (слить дубль, убрать мёртвый relay, вывести поле, единый _dispatch), а не большие новые подсистемы.
- РЕЗУЛЬТАТ ДОЛЖЕН БЫТЬ: просто, лаконично, красиво, гениально — и чтобы ЛЕГЧЕ ОТЛАЖИВАТЬ (меньше дверей, один путь, явные имена, предсказуемый поток). Простота и debuggability — критерий качества наравне с полнотой.
- «Не используется ≠ не нужно» — удалять только при ДОКАЗАННОМ дубле функционала; иначе оставить как capability.
- Сделать ОДИН ЛУЧШИЙ на каждый сценарий, влив в него лучшие функции остальных.
- Доказать, что функционал НЕ теряется (матрица сохранности).
- Честность: учитывай вердикты фазы 3 (если claim refuted — НЕ строй на нём вывод).
- Отдельным разделом собери «мелкие проблемы» (быстрые победы) — то, что чинится в 1-5 строк и сразу делает систему чище/отлаживаемее.

ДОКАЗАТЕЛЬНАЯ БАЗА (JSON):
${JSON.stringify(corpus, null, 1)}

НАПИШИ ДОКУМЕНТ НА РУССКОМ (это user-facing, строго по language policy проекта). Структура:
1. **Резюме и вердикт по тезису** — RouterManager-хаб: подтверждён/скорректирован, главное в 5-7 строк.
2. **Карта целевой архитектуры** — слои коммуникации, ОДИН канон на каждый сценарий (таблица: сценарий → канонический механизм → что absorb из проигравших). Покрой: команда процессу/воркеру, request/reply, кадры/data-поток, реактивное состояние/телеметрия, внутри-GUI событие, GUI-команда+undo, доставка worker→main thread, внешний драйвер/сервис/контроллер.
3. **RouterManager как универсальный хаб** — контракт IMessageChannel, дизайн подключаемых каналов (queue/shm/modbus/socket/redis/sql/mcp), маршрутизация по type+адрес, иерархическая адресация и cross-machine-готовность. Где SHM/WorkerPoolDispatcher — канал или оправданный hot-path.
4. **Унификация диспетчеризации** — судьба dispatch_module (стратегии/сценарии), CommandManager, message_dispatcher: один слой.
5. **Унификация команд/undo** — ActionBus vs CommandDispatcher vs CommandManager: вердикт без потери undo/redo.
6. **Унификация pub/sub и состояния** — StateStore + EventBus как два канона; устранение лишних/путающих абстракций (перечисли конкретно какие убрать/слить).
7. **GUI signal-слой** — канон для каждого направления, что carve-out во framework, какие абстракции лишние.
8. **Канонический конверт сообщения** — минимальный контракт, что убрать (дубли полей), миграция совместимости.
9. **Матрица сохранности функционала** — таблица: способность → откуда → где живёт после унификации → статус (preserved/absorbed/capability/intentionally-dropped). НИ ОДНА способность без явной судьбы.
10. **Что оставить как capability конструктора (не удалять)** — с обоснованием (FieldRouting, сценарии dispatch, system_events, и т.п.).
11. **Мелкие проблемы / быстрые победы** — баги и рассинхроны, которые чинятся в 1-5 строк и сразу делают систему чище и отлаживаемее (мёртвый relay, хардкод queue_type, ложный успех подписки, shadowing-классы, bus=None и т.п.) — с file:line.
12. **План этапами P0→P3** — приоритеты, риски, паритет (не ломать трафик кадров/телеметрии), что параллельно/последовательно, carve-out prototype→framework.
13. **Открытые вопросы владельцу** — развилки, где нужно его решение.

Пиши плотно, по делу, с file:line ссылками из доказательной базы где уместно. Это финальный план-документ. Верни ТОЛЬКО markdown документа (без обёрток).`

let doc = await agent(synthPrompt, { label: 'synthesize', phase: 'Synthesize' })

const critique = await agent(
  `Ты — completeness-критик. Проверь черновик целевой архитектуры на полноту и честность ОТНОСИТЕЛЬНО доказательной базы.

ЧЕРНОВИК:
${doc}

ДОКАЗАТЕЛЬНАЯ БАЗА (для сверки):
${JSON.stringify(corpus, null, 1)}

Найди: (1) gaps — упущенные подсистемы/сценарии/заботы; (2) unverified_claims — выводы, построенные на refuted/partial вердиктах или без доказательств; (3) lost_capabilities — способности из карт, которые исчезли из матрицы сохранности без явной судьбы; (4) overall_grade. Будь строг.`,
  { label: 'critique', phase: 'Synthesize', schema: CRITIQUE },
)

if (critique && ((critique.gaps || []).length || (critique.unverified_claims || []).length || (critique.lost_capabilities || []).length)) {
  log(`Критика: gaps ${(critique.gaps||[]).length} · unverified ${(critique.unverified_claims||[]).length} · lost ${(critique.lost_capabilities||[]).length} — ревизия`)
  doc = await agent(
    `Доработай документ целевой архитектуры по замечаниям критика. Сохрани всю структуру и факты, исправь пробелы, убери выводы на refuted-вердиктах, верни в матрицу сохранности потерянные способности с явной судьбой.

ЗАМЕЧАНИЯ КРИТИКА:
${JSON.stringify(critique, null, 1)}

ТЕКУЩИЙ ДОКУМЕНТ:
${doc}

Верни ТОЛЬКО исправленный markdown документа (на русском, без обёрток).`,
    { label: 'finalize', phase: 'Synthesize' },
  )
} else {
  log('Критика: существенных пробелов нет')
}

return {
  document: doc,
  stats: {
    maps: liveMaps.length,
    concerns: liveConcerns.length,
    verdicts: verdicts.length,
    refuted: refuted.length,
    partial: partial.length,
    critique: critique || null,
  },
}
