# Карта проекта и карточки модулей (`ea65a3334`)

Всё ниже — вывод атласа **как есть**, руками не правилось. Дерево: `.claude/worktrees/mco-stand`, `--ref` по умолчанию
(`HEAD` = `ea65a3334`), `--main-ref` по умолчанию (`main`).

Каждая команда запускалась из корня дерева `mco-stand` с `PYTHONPATH=<корень дерева>`, `PYTHONUTF8=1`,
`PYTHONDONTWRITEBYTECODE=1` так:

```
bash D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/scripts/machine_gate.sh light inspector-bottles-48 \
  D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python.exe -m scripts.atlas <подкоманда>
```

Всего: `index` — 1, `card` — 90 из 90, `map` — 6. Отказов и пропусков гейтом (код 75) не было.

Как читать карточки (замечания, не часть вывода):

* строка «Назначение» берётся из докстринга и может отставать (у `services/code_reader` сказано «приём по TCP», а
  рецепт quad работает через SDK);
* «API (0)» у `services/camera_device` не значит, что публичных классов нет: они в
  `Services/camera_device/interface.py`, `session.py`, `plugin_base.py`;
* плагины камеры и считывателя лежат в `services/*`, а не в `plugins/*`;
* «Открытые задачи» собраны из планов этого дерева; планы волны 2 (ветка `plan/mco-wave2`) сюда не входят;
* «Кто использует модуль» — статика по импортам; реестры, `getattr`, имена классов в YAML не видны.

## Оглавление

1. Индекс проекта (`atlas index`)
2. Паспорта (`atlas map`)
3. Карточки (`atlas card`), в порядке индекса:

   - `actions_module`
   - `app_module`
   - `base_manager`
   - `chain_module`
   - `channel_routing_module`
   - `command_module`
   - `config_module`
   - `console_module`
   - `data_schema_module`
   - `dispatch_module`
   - `display_module`
   - `error_module`
   - `event_module`
   - `frontend_module`
   - `logger_module`
   - `message_module`
   - `process_manager_module`
   - `process_module`
   - `recipe`
   - `registers_module`
   - `router_module`
   - `service_module`
   - `shared_resources_module`
   - `state_store_module`
   - `statistics_module`
   - `telemetry_readmodel_module`
   - `worker_module`
   - `services/auth`
   - `services/camera_device`
   - `services/code_reader`
   - `services/control_panel`
   - `services/dataset_gen`
   - `services/device_hub`
   - `services/documents`
   - `services/frame_buffer`
   - `services/hikvision_camera`
   - `services/layer_render`
   - `services/line_sim`
   - `services/ml_inference`
   - `services/ml_train`
   - `services/modbus`
   - `services/otel_export`
   - `services/phone_gateway`
   - `services/robot_comm`
   - `services/sql`
   - `services/vfd_comm`
   - `plugins/calibration`
   - `plugins/control`
   - `plugins/filter`
   - `plugins/hub`
   - `plugins/io`
   - `plugins/processing`
   - `plugins/render`
   - `plugins/runtime`
   - `plugins/sim`
   - `plugins/sinks`
   - `plugins/sources`
   - `plugins/utility`
   - `framework_meta`
   - `services_shared`
   - `plugins_shared`
   - `prototype/adapters`
   - `prototype/backend`
   - `prototype/domain`
   - `prototype/frontend`
   - `prototype/recipes`
   - `prototype/registers`
   - `prototype_root`
   - `tools/backend_ctl`
   - `prototype/apps`
   - `tools/tools`
   - `scripts`
   - `scripts/atlas`
   - `tools/utils`
   - `prototype/robot`
   - `docs/examples`
   - `tools/backend_ctl/probes`
   - `frontend_module/components`
   - `frontend_module/components/_examples`
   - `frontend_module/components/base`
   - `frontend_module/core`
   - `frontend_module/widgets`
   - `frontend_module/widgets/chrome`
   - `frontend_module/widgets/tabs`
   - `process_module/generic`
   - `prototype/frontend/widgets`
   - `prototype/frontend/widgets/tabs`
   - `prototype/frontend/widgets/tabs/pipeline`
   - `prototype/frontend/widgets/tabs/services`
   - `prototype/frontend/widgets/tabs/settings`

## 1. Индекс проекта

Команда: `atlas index` (без `--write`).

````text
# Индекс проекта — собран командой `python -m scripts.atlas index --write`, руками не править
actions_module — Action-шина с undo/redo и объединением правок для GUI; сюда — менять откат и повтор действий
  IRegistersManagerGui (1), IActionLogRepository, IActionLogWriter
  классы: Action, ActionBuilder, ActionBus, ActionHandler, NodeMoveHandler, RegisterBindingLike, SnapshotEntry, SnapshotHistory, TopologyBridgeProtocol, TopologyHolderProtocol, TopologyMutationHandler
app_module — Шаблон приложения (composition root): общая сборка многопроцессного приложения; сюда — менять каркас запуска
  ManifestStoreProtocol (2), BlueprintLoader (0), LauncherFactory (0), ProcDictsBuilder (0), StateBootstrap (0), … ещё 1
  классы: ActivePipeline, AppManifest, AppSpec, BlueprintError, DiscoveryResult, DiscoverySpec, GenericProcessManagerApp, ManifestStore, ServiceManifest, SystemBuilder, ThrottleRules
base_manager — Базовый менеджер: жизненный цикл, адаптеры, наблюдаемость; сюда — менять фундамент всех менеджеров
  IObservableMixin (12), IScope (11), IBaseManager (10), CloseReport (3), IHandle (3), … ещё 5
  классы: BaseAdapter, BaseManager, BaseManagerConfig, Handle, IBaseAdapter, ManagerRegistry, ObservableMixin, ProcessStatus, ProxyCreator, Scope, ScopeClosedError, Stoppable
chain_module — Движок исполнения цепочек и DAG-pipeline, в т.ч. между процессами; сюда — менять порядок и шаги исполнения
  IChainLogger (3), IExecutionStep (2), IChainRunnable (1), IRemoteExecutable (1), INodeConnection (0), … ещё 2
  классы: ChainContext, ChainResult, ChainRunnable, ChainThreadPool, DagRunnable, IChainContext, IRunnableChain, IStepNode, IStepNodeWithWorker, LatencyTracker, ParallelChainRunnable, PendingTask, RunnableStep, WorkerPoolDispatcher, WorkerPoolExecutor, WorkerTaskRequest, WorkerTaskResponse
channel_routing_module — Базовая маршрутизация по каналам для роутера, логгера и ошибок; сюда — менять общую логику каналов
  IChannelRoutingManager (6), IBufferStrategy (5), IChannel (5), Outcome, channel_accepted, … ещё 1
  классы: AsyncSenderBuffer, BatchDrainWorker, BoundedChannel, ChannelRegistry, ChannelRoutingConfig, ChannelRoutingManager, ChannelRoutingManagerConfig, DirectBuffer, ErrorLike, LoggerLike, NumberRecord, ObservabilityDrainAdapter, ObservabilityHub, ObservabilitySearchError, ObservabilityStore, RecordForwardChannel, StatsLike, StoreTapChannel
command_module — Менеджер команд над dispatch_module: регистрация обработчиков по имени; сюда — менять приём команд
  ICommandManager (9)
  классы: BaseCommandManager, CommandAdapter, CommandManager, CommandManagerConfig
config_module — Управление конфигурациями в рантайме: схемы, контейнер, менеджер; сюда — менять загрузку и хранение конфигов
  IConfig (9), IConfigManager (7), IConfigObserver (0)
  классы: Config, ConfigFileWatcher, ConfigLoader, ConfigManager, ConfigManagerConfig, ConfigSchemaAdapter, ConfigSection, FeatureFlag, FlagState
console_module — Менеджер терминальных окон процесса: показ, перехват вывода, ввод; сюда — менять консоль процесса
  IConsoleManager (10), IPlatformConsole (8)
  классы: ConsoleAdapter, ConsoleConfig, ConsoleLogChannel, ConsoleManager, ConsoleRedirector, RegisterCommandHandler, SystemCommandHandler, UnixConsole, WindowsConsole
data_schema_module — Ядро описания структур данных на Pydantic: схемы, поля, маршрутизация; сюда — менять схемы и валидацию
  HasBuild, IAsyncRegisterStorage, IAsyncSchemaStorage, IDataConverter, IDataValidator, … ещё 12
  классы: AlgorithmRegisters, BaseComponentModel, BaseManagerModel, ComponentDNA, ComponentHierarchy, ComponentLocation, ComponentType, DNAFactory, DataConverter, DataManagerError, DataReference, DataSchemaError, DataValidator, DatabaseConfig, DatabaseVisualizationFormatter, DescriptorSchemaMeta, DrawRegisters, ExcelVisualizationFormatter, FieldMeta, FieldRouting, FileStorage, FormatType, HtmlDocumentationFormatter, HtmlVisualizationFormatter, IDocumentationFormatter, ISchema, ISchemaAdapter, ISchemaDocumentationGenerator, ISchemaManager, ISchemaRegistry, ISchemaStorage, ISchemaVisualizer, IStorageManager, IVersionManager, IVisualizationFormatter, InvalidParameterError, JsonVisualizationFormatter, LoggerConfig, ManagerDataAdapter, MarkdownDocumentationFormatter, MermaidVisualizationFormatter, MetricsCollector, ModelFactory, ProcessDataContainer, ProcessRegistersRegistry, ProcessingRegisters, RegisterDescriptor, RegisterDispatchMeta, RegistersContainer, RegistersMeta, RegistersScanner, ResourceReference, ResourceType, RstDocumentationFormatter, SchemaBase, SchemaDocumentationGenerator, SchemaMixin, SchemaNotFoundError, SchemaRegistrationError, SchemaRegistry, SchemaValidationError, SchemaVisualizer, ServerConfig, StorageManager, TextVisualizationFormatter, VersionInfo, VersionManager, VersionManagerError
dispatch_module — Диспетчеризация входящих сообщений к обработчикам внутри процесса; сюда — менять стратегии обработки
  IDispatcher (7), DispatchStrategy
  классы: BaseDispatcher, BaseStrategy, ChainMatchStrategy, Dispatcher, ExactMatchStrategy, FallbackMatchStrategy, HandlerInfo, PatternMatchStrategy, Scenario, ScenarioBuilder, ScenarioManager
display_module — Реестр именованных SHM-каналов для вывода кадров; сюда — менять каналы отображения кадров
  IDisplayRegistry (6), IDisplayChannel (4), DisplayEntry (0)
  классы: DisplayRegistry
error_module — Менеджер ошибок на базе логгера: каналы по уровням, traceback; сюда — менять обработку и запись ошибок
  IErrorManager (8), DeviceOpenFailed, FrameworkFailure, ObservabilityMisuse, ResourceUnavailable, … ещё 1
  классы: ErrorManager, ErrorManagerConfig, SubsystemStartFailed
event_module — Типизированная шина событий-фактов внутри процесса; сюда — менять подписки и публикацию событий
  EventBusProtocol (2), Subscription (1)
  классы: EventBus, Subscribers
frontend_module — UI-фреймворк: конструктор PySide6-приложений из виджетов и регистров; сюда — менять GUI-каркас
  IFrontendManager (6), IConfigurableWidget (4), IRegistersManager (3), IRegistersManagerGui (3), IWidgetRegistry (3), … ещё 20
  классы: AccessContext, AccessContextSource, ActionBuilderProtocol, CommandSender, CommandSenderTap, CommandValidator, ConfigSnapshotManager, FormContext, FramePump, FrontendLaunchHooks, FrontendManager, FrontendManagerConfig, ICommandCatalog, IProcess, IRequestingProcess, IRouterLike, ISignalProvider, IWidgetFactory, IWindowRegistry, LazyTab, LoadingWindow, ProcessDiff, QtEventBus, RecipeManagerProtocol, RegisterBinding, RegisterFieldMeta, RemoteCommandSender, RemoteFrameSource, RemoteFrameSourceError, RemoteStateProxy, ResolvedMeta, SettingsProfileManagerProtocol, ShmConfig, SupportsCommandMessage, TabRegistry, TabSpec, TelemetryHistorySource, TelemetryPoller, TelemetryViewModel, ThemeManager, ThemePresetsManager, ThreadEntry, ThreadManager, ThreadManagerConfig, TopologyDiff, UiEventTap, ValidationResult, WidgetDescriptor, WindowConfig, WindowManager, WindowManagerConfig, WireConfig, WireDiff, WireMetrics, WireStatus, WireStatusMonitor, YamlPersistenceStore
logger_module — Менеджер логирования: каналы записи, сбор логов процессов; сюда — менять вывод и хранение логов
  ILoggerManager (19), ILogChannel (2), LogLevel, LogScope, ScopeName
  классы: ConsoleChannel, ErrorFloor, FileChannel, FrameTraceChannel, HttpChannel, LogChannel, LogRecord, LoggerChannelSchema, LoggerCore, LoggerManager, LoggerManagerConfig, LoggerRuleSchema, LoggerScopeSchema, MemoryChannel, NameHierarchy, NullChannel, ProcessHooks, RateSampler, RouterPushChannel, SealFormatter, SecretRedactor, StdLoggerFacade, WindowedVoices
message_module — Транспортный протокол сообщений между менеджерами и процессами; сюда — менять формат сообщений
  IMessage (12)
  классы: AddressValidationError, CommandMessageSchema, ContractCheck, LogLevel, LogMessageSchema, Message, MessageAdapter, MessageContract, MessageContractRegistry, MessageType, MessageValidationError, Priority
process_manager_module — Оркестратор процессов: запуск системы, реестр, приоритеты, мониторинг; сюда — менять управление процессами
  ISystemLauncher (9), IProcessManagerProcess (7), IProcessRegistry (7)
  классы: AlertRule, AutostartLatch, ChildProcessStop, EvalInput, ObservabilitySubscriptionBroker, PreStopStep, ProcessConfig, ProcessManagerProcess, ProcessMonitor, ProcessPriority, ProcessRegistry, ProcessSchemaAdapter, ProcessSpawner, ProcessStatusMonitor, ProcessTreeGuard, RestartPolicy, RunConfig, RunFlag, RunState, SpawnBackend, StubPlatformAdapter, SystemBlueprint, SystemLauncher, TopologyManager, Wire
process_module — Базовый класс процесса: создание, инициализация, управление, мониторинг; сюда — менять жизнь процесса
  IProcessModule (14), IProcessCommunication (11), ISharedResources (5), ProcessStatsDict
  классы: BreakerState, BuiltinCommands, CircuitBreaker, CollectionExecutor, ConfigReloadParams, ConsoleProcessConfig, CpuClock, DiagThreadRaiseParams, DiagWarnParams, FlightRecorder, ForwarderWithCounters, GcCollectionOwner, GcDiscipline, GcOwnerStats, HealthField, HealthReportParams, HealthReporter, HealthSelfTestError, HealthState, HealthStatus, IActuationScheduler, IHealthReporter, IPluginCommandManager, IPluginMemoryManager, IPluginRouter, IPluginStatsManager, IPluginWorkerManager, IProcessServices, IoPeekPublisher, LastErrorKey, LogTailSubscribeParams, LogTailUnsubscribeParams, LoggerSinkParams, LoggerSinkTailParams, ManagerType, ManagersBundle, ManagersConfig, MetricRule, MockCommandManager, MockDocumentSink, MockProcessServices, MockStatsManager, MockWorkerManager, NoParams, NodeMemory, ObservabilityAudit, ObservabilityCommandsConfig, ObservabilityConfig, ObservabilityDocumentsConfig, ObservabilityErrorsConfig, ObservabilityEventsConfig, ObservabilityFlightConfig, ObservabilityHistoryConfig, ObservabilityIntrospectParams, ObservabilityLayers, ObservabilityPersistParams, ObservabilityStatsConfig, ObservabilityTailBrokerParams, ObservabilityTailSubscribeParams, ObservabilityTailUnsubscribeParams, ObservabilityVoicesConfig, ObservationPolicy, ObservationPolicyConfig, PluginCategory, PluginContext, PluginDiscoveryResult, PluginEntry, PluginLevels, PluginManager, PluginMetrics, PluginState, PluginTestBench, PolicyDecision, Port, PortValidationError, ProcessAdapter, ProcessCommunication, ProcessConfigDict, ProcessConfigHandler, ProcessHeartbeat, ProcessIO, ProcessLaunchConfig, ProcessLifecycle, ProcessManagers, ProcessMetadataDict, ProcessModule, ProcessModulePlugin, ProcessPriorityLevel, ProcessState, ProgressTracker, QueueType, ReadinessField, ReadinessPolicy, ReadinessReasonKey, RouterRelayParams, RoutingProbeParams, RoutingRefreshParams, SchemaAdapter, SubPluginContext, SystemThreads, TelemetryGate, TelemetryPublishConfig, TelemetryReconfigureParams, WideEventSelector, WireConfigureParams, WireDeconfigureParams, WorkerCreateParams, WorkerNameParams
recipe — Управление рецептами: снимки конфигурации, определение формата, миграции, CRUD; сюда — менять рецепты
  RecipeManagerProtocol (15), RecipeEngineProtocol (10), StoreProtocol (3)
  классы: RecipeConflict, RecipeEngine, RecipeFormatError, RecipeFormatHook, RecipeLockTimeout, RecipeManager, RecipeService, YamlPatchConflict, YamlWriteRefused
registers_module — Рантайм именованных регистров: подписки на поля, карта маршрутов, отправка; сюда — менять регистры
  IRegistersManager (15)
  классы: FieldInfo, RegistersManager
router_module — Маршрутизация сообщений между процессами через RouterManager; сюда — менять каналы и правила доставки
  IRouterManager (21), IMessageChannel (9)
  классы: AsyncReceiver, AsyncSender, FrameShmMiddleware, MessageChannel, MiddlewarePipeline, QueueChannel, RouteDecision, RouterAdapter, RouterManager, RouterManagerConfig, RouterReentrantRequestError, RouterSchemaAdapter, RouterSendError, SocketAuthError, SocketBridgeAdapter, SocketChannel, SocketClient, SocketConnectionLost, UnknownMessageTypeError
service_module — Реестр и жизненный цикл долгоживущих сервисов (камеры, БД, auth); сюда — менять учёт сервисов
  IService (3), ServiceLifecycle (0)
  классы: DiscoveryResult, ServiceEntry, ServiceHost, ServiceRegistry
shared_resources_module — Pickle-safe реестр общих ресурсов для межпроцессного обмена; сюда — менять передачу ресурсов процессам
  IConfigStore, IEventManager, IMemoryManager, IProcessStateRegistry, IQueueRegistry, … ещё 1
  классы: ConfigStore, DataSchemaAdapter, EventHandle, EventManager, EventType, EventsProxy, FramePool, FrameReader, ISharedResourcesManager, LoanLedger, LoanTicket, ManagerStatsMixin, MemoryAccessStatus, MemoryConfigDict, MemoryHandle, MemoryManager, PoolStats, ProcessData, ProcessDataDict, ProcessDataKeys, ProcessHandle, ProcessStateRegistry, QoSProfile, QueueConfigDict, QueueHandle, QueueRegistry, QueuesProxy, ReaderGoneQueue, ResourceType, RingBufferReader, RingBufferWriter, SharedResourcesManager, SharedResourcesManagerConfig, ShmFrameReader, ShmRegistry
state_store_module — Реактивное иерархическое дерево состояния: сервер и клиентский кэш с подписками; сюда — менять общее состояние
  IStateProxy (7), IStateStore (6), IStateStoreManager (5), IRouter (3)
  классы: Delta, DeltaDispatcher, GuiStateProxy, HealthMonitor, IStateAdapter, InMemoryRouter, LeafCopy, LoggingMiddleware, MetricsMiddleware, MiddlewarePipeline, PersistenceManager, PersistenceMiddleware, Selector, SelectorRegistry, StateAdapterBase, StateInspector, StateMiddleware, StateProxy, StateStoreManager, StateWriter, Subscription, SubscriptionManager, ThrottleMiddleware, TopologyGateMiddleware, Transaction, TreeStore, ValidationMiddleware, WatchedProcess
statistics_module — Менеджер статистики и метрик, третья плоскость наблюдаемости; сюда — менять сбор и вывод метрик
  IStatsManager (9)
  классы: AggregationWindow, CardinalityGuard, FileStatsChannel, HubStatsChannel, LogStatsChannel, MetricRecord, MetricType, NumbersGate, ObservationManager, ObservationPort, ObservationRecord, PathSchedule, PluginObservationHandle, StatsAdapter, StatsManager, StatsManagerConfig
telemetry_readmodel_module — Qt-free ядро read-model телеметрии: проекция значений и кольцевая история; сюда — менять чтение телеметрии
  ITelemetryReadModel (11)
  классы: TelemetryReadModel
worker_module — Менеджер потоков-воркеров внутри процесса: старт, стоп, пауза, перезапуск; сюда — менять управление потоками
  IWorkerManager (22), IWorkerRegistry (8), IExecutorManager (6), IWorkerLifecycle (4), OrderedExecutor (4), … ещё 3
  классы: ExecutionMode, ExecutorManager, ExecutorSpec, IExecutorRegistry, KeyedExecutor, ThreadConfig, ThreadPriority, ThreadWorkerConfig, WorkerAdapter, WorkerInfo, WorkerLifecycle, WorkerManager, WorkerManagerConfig, WorkerRegistry, WorkerSchemaAdapter, WorkerStatus, WorkerType
services/auth — Аутентификация и RBAC: хеши паролей, пользователи, роли; сюда — менять вход и права доступа
  IAuthManager (12), IUserStorage (5), IPasswordHasher (2), ISessionTracker (2), IAuditWriter (1)
  классы: AccountLocked, AuditEntry, AuditImmutableError, AuditWriter, AuthConfig, AuthError, AuthManager, AuthService, BcryptHasher, DevPasswordRequired, InvalidCredentials, LastAdminError, LockoutPolicy, LockoutTracker, PasswordPolicy, PermissionDenied, PermissionDescriptor, PermissionsRegistry, Role, RoleNotFound, SessionEntry, SessionExpired, SessionTracker, SqliteAuditStorage, StorageCorrupted, User, UserAlreadyExists, UserNotFound, WeakPassword, YamlUserStorage
services/camera_device — Общее ядро камер: контракт порта прибора и его фейк; сюда — менять порт, границу SDK и эмуляцию
  классы: AmbiguousDeviceError, ApplyParamsArgs, Binding, CameraDeviceError, CameraDevicePlugin, CameraDeviceRegisters, DeviceIdentity, DeviceInfo, DevicePort, DeviceSdk, DeviceSession, FakePort, ParamInfo, PortError, ProfileRunner, ProfileState, RawFrame, ReleaseDeviceArgs, Step, TakeDeviceArgs
services/code_reader — Сервис считывателя кодов Hikrobot ID3000: приём результатов по TCP, разбор; сюда — менять чтение кодов
  CodeReaderSinkProtocol (6), CodeQuality, CodeRead, ReadResult, ReadStatus, … ещё 5
  классы: BCR_INFO_EX2, CODE_INFO, CodeReaderPlugin, CodeReaderPluginConfig, CodeReaderRegisters, CodeReaderSdkPlugin, CodeReaderSdkPluginConfig, CodeReaderSdkRegisters, DEVICE_INFO, DEVICE_INFO_LIST, DeviceEntry, ENUMVALUE, FLOATVALUE, GIGE_DEVICE_INFO, Handler, IMAGE_OUT_INFO_EX2, INTVALUE_EX, MvCodeReaderApi, POINT_I, Probe, RESULT_BCR_EX2, RawFrame, ResultSink, SPECIAL_INFO, SdkCodeReader, SdkError, SdkFrame, SdkNotFoundError, Server, USB3_DEVICE_INFO
services/control_panel — Сервис Пульт: GUI-контролы выдают значения на порты pipeline; сюда — менять контролы и их сигналы
  ControlSpec, ControlType
  классы: ControlPanelConfig, ControlPanelPlugin, ControlPanelRegisters
services/dataset_gen — Генератор синтетического датасета методом cut-and-paste; сюда — менять создание обучающих данных
  SampleGenerator (4)
  классы: AugmentConfig, BrightnessContrastAug, ChannelShiftAug, ColorTemperatureAug, ContactShadowAug, DatasetEngine, DatasetGenService, GammaAug, GaussianBlurAug, GeneratorConfig, GlareAug, JpegAug, LayerSceneGenerator, MotionBlurAug, NoiseAug, OcclusionAug, OutputConfig, PlacementConfig, RotationAug, SampleLabel, ScaleAug, ShadowAug, ShiftAug, SymmetryConfig, SyntheticDataset, TrainCrop, TrainLabel, TrainSection, VignetteAug
services/device_hub — Центральный реестр устройств и менеджер соединений; сюда — менять учёт и подключение устройств
  классы: BadArgs, BaseDeviceDriver, DeviceBusyError, DeviceDriver, DeviceEntry, DeviceHubError, DeviceKind, DeviceManager, DeviceNotFoundError, DriverContext, ExchangeLog, ExchangeLogTransport, GenericModbusDriver, HikvisionDriver, JobMixin, JogMixin, JogView, OpSource, OpSpec, OpsMixin, ParamMixin, ParkBegin, ParkMachine, ParkView, ProgramMixin, RegisterTransportUnavailable, RegistryIntegrityError, RegistryStore, RobotDriver, RobotDriverV2, RobotOpError, RobotState, RobotStateView, StopAwareDriver, StopMixin, TransportBuildError, VfdDriver, WarnLog
services/documents — Хранилище документов: аудит смен наблюдаемости и вердикты по детали; сюда — менять аудит и вердикты
  IDocumentStore (3), IDocumentSink (1), KIND_AUDIT, KIND_VERDICT
  классы: DocumentRow, DocumentStore
services/frame_buffer — Кольцо кадров по времени и формат сегмента; сюда — менять вытеснение, закрепление, формат записи
  классы: TimeRing
services/hikvision_camera — Сервис промышленной камеры Hikvision: SDK, логика, плагин; сюда — менять работу с камерой
  HikvisionCameraProtocol (6)
  классы: CameraParameters, CameraState, DeviceEntry, DeviceInfo, FakeBackend, FakeMvCamera, FrameConverter, HikvisionCamera, HikvisionCameraConfig, HikvisionCameraPlugin, HikvisionCameraRegisters, HikvisionCameraService, HikvisionCameraWindow, MVCC_ENUMENTRY, MVCC_ENUMVALUE, MVCC_FLOATVALUE, MVCC_INTVALUE, MVCC_INTVALUE_EX, MVCC_STRINGVALUE, MV_CC_DEVICE_INFO, MV_CC_DEVICE_INFO_LIST, MV_FRAME_OUT, MV_FRAME_OUT_INFO, MV_GIGE_DEVICE_INFO, MV_USB3_DEVICE_INFO, MvCamera, MvsBackend, MvsPort, MvsSdk, PixelType, ProbeError, SdkError, Session
services/layer_render — Слои сцены: фон, объект, пресет, каталог классов; сюда — менять сборку кадра из слоёв
  ScrollingTile (0), SolidFill (0)
  классы: CatalogConfig, ClassEntry, ClassMeta, ComposedLayers, EffectSpec, LayerAugment, LayerSpec, ObjectFactory, PlacedObject, PreviewLimitError, RenderedObject, SceneBackground, ScenePreset, SpriteCatalog
services/line_sim — Объект-агностичный движок сцены лента с объектами; сюда — менять симуляцию ленты
  SceneCompositorProtocol (3), ObjectPassport (2), AUGMENT_FIELDS, LayerAugment, LayerMode, … ещё 3
  классы: BeltGeometry, DiscSequence, JobDone, LayeredObject, MatchResult, ObjectFactory, ObjectSpawner, SceneCompositor, SeamlessResult, SequenceBusy, SequenceHead, TruthLedger
services/ml_inference — Инференс нейросетей для pipeline: кадр на входе, классы и confidence на выходе; сюда — менять инференс
  InferenceBackend (5), ModelCatalog (3)
  классы: BaseInferenceBackend, InferenceEngine, MLInferenceConfig, MLInferencePlugin, MLInferenceRegisters, MLInferenceService, ModelAssetError, ModelDiagnosis, ModelRegistry, ModelSpec, Normalize, ONNXRuntimeBackend, TorchBackend
services/ml_train — Обучение классификаторов и выбор лучшей модели по метрикам; сюда — менять обучение и сравнение прогонов
  RunSource (2), ModelExporter (0), TrainSample (0)
  классы: AugmentConfig, DataBundle, DataConfig, ExportConfig, ExportedDataset, FolderDataset, MLTrainService, ModelConfig, MultiHeadModel, NormalizeConfig, OptimConfig, RunInfo, RunRegistry, TrainConfig, TrainResult, TrainSection, Trainer
services/modbus — Драйвер Modbus-TCP и RS485 для связи с PLC; сюда — менять обмен по Modbus
  ModbusClientProtocol (9), RegisterTransport (3)
  классы: ConnectionState, DeviceProtocol, Field, ModbusChannel, ModbusConfig, ModbusConnectionError, ModbusDevice, ModbusDriverError, ModbusIOError, ModbusNotAvailableError, ModbusPlugin, ModbusPluginConfig, ModbusPoller, ModbusRegisters, ModbusSdkClient, ModbusService, ModbusStatus, ProtocolFileError, Reg, RegBlock, RegDW, RegisterBlock, RegisterKind, RegisterMap, RegisterMeta, TransportType
services/otel_export — Экспорт записей наблюдаемости наружу по OTLP; сюда — менять маппинг и отправку данных наблюдаемости
  ObservabilityPort (5), LogExporter (2), RecordMapper (1), ResourceResolver (1), ExportOutcome (0), … ещё 3
  классы: DisplayRecordMapper, FlushOutcome, MappedRecord, OtelExportConfig, OtlpHttpExporter, PooledResourceResolver, Resource
services/phone_gateway — Приём фото и слов с телефона по WiFi через браузер; сюда — менять приём данных с телефона
  FrameSource (2)
  классы: PhoneCameraConfig, PhoneCameraPlugin, PhoneCameraRegisters, PhoneGateway
services/robot_comm — Сервис робота Delta поверх Modbus: карта регистров, доменные методы; сюда — менять управление роботом
  RobotClientProtocol (18), DeviceTransport (6)
  классы: Action, BeltDrive, BeltResult, BuildError, CalibrationError, ClientV2Config, CmdResult, CompileError, DemoDriver, DrawPoint, ErrorEvent, FakeRobotTransport, Frame, FrameDef, FrameFit, GeneratedProgram, GeneratorError, InvalidStoreKey, JobEcho, JobRecord, JournalEntry, LineLink, LineRobotState, Move, ParamsDoc, Point, Program, Record, RevisionConflict, RobotAborted, RobotClient, RobotClientV2, RobotCommError, RobotCommService, RobotCommandError, RobotConfig, RobotDataInvalid, RobotDataStore, RobotJobError, RobotModel, RobotNak, RobotNotConnectedError, RobotParamsV2, RobotPosition, RobotSimCore, RobotSimCoreV2, RobotStoreError, RobotSyncError, RobotTimeout, RobotWatchdogDisabled, RunReport, ScaraModel, Scenario, SimJournal, SimMonitorWindow, SimRobotServer, SimView, StopResult, StoreDocumentInvalid, StoredDoc, SyncCancelled, SyncReport, Telemetry, TimeTape, ToolCheck, Workspace, WrongFirmware, ZScale
services/sql — Универсальный SQL-менеджер на SQLAlchemy: PostgreSQL, MySQL, SQLite; сюда — менять доступ к БД
  ISQLManager (8), IRepository (7), IAsyncEngineAdapter (3), IEngineAdapter (3), ISchemaMapper (3), … ещё 3
  классы: ActionLogRecovery, ActionLogRepository, ActionLogRotation, ActionLogRow, ActionLogWriter, AsyncQuerySet, AsyncSQLAlchemyUnitOfWork, BaseAsyncAdapter, BaseSyncAdapter, DBExecuteCommand, DBInsertCommand, DBQueryCommand, DDLBuilder, ExportFormat, GenericRepository, IAsyncUnitOfWork, ISyncEngineAdapter, IUnitOfWork, MySQLAsyncAdapter, MySQLSyncAdapter, PostgreSQLAsyncAdapter, PostgreSQLSyncAdapter, QuerySet, SQLAlchemyUnitOfWork, SQLManager, SQLManagerConfig, SQLMeta, SQLiteAsyncAdapter, SQLiteSyncAdapter, SchemaBaseMapper, SqlService, TableExporter
services/vfd_comm — Сервис частотного преобразователя INVT GD20, не зависит от транспорта; сюда — менять управление ПЧ
  VfdClientProtocol (7)
  классы: VFDStatus, VfdBridgeStaleError, VfdClient, VfdCommError, VfdCommService, VfdConfig, VfdFrequencyError
plugins/calibration — Плагины калибровки (камера и робот и др.); сюда — менять калибровочные плагины
  классы: CalibrationError, CameraRobotCalibrationConfig, CameraRobotCalibrationPlugin, CameraRobotCalibrationRegisters
plugins/control — Плагины управления внешними устройствами: роботы, IO, реле; сюда — менять управляющие плагины
  классы: RobotControlConfig, RobotControlPlugin, RobotControlRegisters
plugins/filter — Плагины фильтрации и анализа координат (виртуальная линия и др.); сюда — менять фильтры координат
  классы: CentroidTracker, LineFilterConfig, LineFilterPlugin, LineFilterRegisters, Track
plugins/hub — Плагины-хабы (always-on сервисы устройств, device_hub); сюда — менять хаб устройств и его IPC-клиент
  классы: DeviceHubClient, DeviceHubPlugin, DeviceHubPluginConfig, DeviceHubRegisters, ScopeThreadSurvived
plugins/io — Плагины ввода-вывода: запись в БД, выгрузка кадров, экспорт; сюда — менять ввод-вывод
  классы: DatabasePlugin, DatabasePluginConfig, DatabaseRegisters, DetectionSchema, DrawingIoPlugin, DrawingIoPluginConfig, DrawingIoRegisters, FrameBufferPlugin, FrameBufferPluginConfig, FrameBufferRegisters, FrameSaverPlugin, FrameSaverPluginConfig, FrameSaverRegisters, OtelExportPlugin, OtelExportPluginConfig, OtelExportRegisters, OtelExportSubscribeError, RobotDrawPlugin, RobotDrawPluginConfig, RobotDrawRegisters, RobotIoPlugin, RobotIoPluginConfig, RobotIoRegisters, TelemetrySinkPlugin, TelemetrySinkPluginConfig, TelemetrySinkRegisters, TelemetrySnapshot
plugins/processing — Плагины обработки кадров: фильтры, детекторы, преобразования; сюда — менять обработку кадров
  классы: BlobDetectorConfig, BlobDetectorPlugin, BlobDetectorRegisters, BlobFilterPlugin, BlobFilterPluginConfig, BlobFilterRegisters, BlurPlugin, BlurPluginConfig, CenterCropConfig, CenterCropPlugin, CenterCropRegisters, CircleDetectorConfig, CircleDetectorPlugin, CircleDetectorRegisters, CoFusion, ColorConvertConfig, ColorConvertPlugin, ColorConvertRegisters, ColorMaskPlugin, ColorMaskPluginConfig, ColorMaskRegisters, ContourDrawPlugin, ContourDrawPluginConfig, ContourDrawRegisters, ContourFinderPlugin, ContourFinderPluginConfig, ContourFinderRegisters, CropPlugin, CropPluginConfig, CropRegisters, DoubleConvBlock, DoubleFusion, EdgeDetectionPlugin, EdgeDetectionPluginConfig, EdgeDetectionRegisters, FlipPlugin, FlipPluginConfig, GrayscalePlugin, GrayscalePluginConfig, HsvMaskPlugin, HsvMaskPluginConfig, HsvMaskRegisters, ImageAdjustPlugin, ImageAdjustPluginConfig, ImageAdjustRegisters, MaskToFrameConfig, MaskToFramePlugin, MaskToFrameRegisters, MorphologyPlugin, MorphologyPluginConfig, MorphologyRegisters, NegativePlugin, NegativePluginConfig, PixelToRobotPlugin, PixelToRobotPluginConfig, PixelToRobotRegisters, PointsRenderPlugin, PointsRenderPluginConfig, PointsRenderRegisters, RegionSplitPlugin, RegionSplitPluginConfig, ResizePlugin, ResizePluginConfig, ResizeRegisters, RobotScalePlugin, RobotScalePluginConfig, RobotScaleRegisters, RoiCropConfig, RoiCropPlugin, RoiCropRegisters, SegmentationPlugin, SegmentationPluginConfig, SegmentationRegisters, SingleConvBlock, Slot, Smish, StitcherPlugin, StitcherPluginConfig, StrokesToPointsPlugin, StrokesToPointsPluginConfig, StrokesToPointsRegisters, TED, TextVectorPlugin, TextVectorPluginConfig, TextVectorRegisters, U2NetPortraitDetector, UpConvBlock, WordAssembler, WordLayoutPlugin, WordLayoutPluginConfig, WordLayoutRegisters
plugins/render — Плагины отрисовки overlay и композитинга кадров для GUI; сюда — менять отрисовку
  классы: CircleDrawConfig, CircleDrawPlugin, CircleDrawRegisters, OverlayDrawConfig, OverlayDrawPlugin, OverlayDrawRegisters, RenderOverlayConfig, RenderOverlayPlugin, RenderOverlayRegisters, RendererCompositorConfig, RendererCompositorPlugin, RendererCompositorRegisters
plugins/runtime — Плагины-исполнители pipeline: chain executor, пулы воркеров; сюда — менять исполнение pipeline
  классы: ChainExecutorConfig, ChainExecutorPlugin, ChainExecutorRegisters, WorkerPoolConfig, WorkerPoolPlugin, WorkerPoolRegisters
plugins/sim — Плагины-хосты симулятора линии; сервис держит логику, плагин жизненный цикл; сюда — менять хост симуляции
  классы: LayerPreviewPlugin, MjpegSinkConfig, MjpegSinkPlugin, PultWebPlugin, SceneSourcePlugin, SimRobotHostPlugin
plugins/sinks — Плагины-приёмники: вывод и экспорт данных из конца цепочки; сюда — менять приёмники данных
  классы: ModbusSinkPlugin, ModbusSinkPluginConfig, ModbusSinkRegisters
plugins/sources — Плагины источников данных: камеры, файлы, генераторы; сюда — менять источники
  классы: CameraBackend, CameraServiceConfig, CameraServicePlugin, CameraServiceRegisters, CapturePlugin, CapturePluginConfig, FileSourceBackend, FrameCounterPlugin, FrameCounterPluginConfig, FrameGenerator, HeartbeatPlugin, HeartbeatPluginConfig, HikvisionBackend, ParamSpec, SimulatorBackend, StreamSourceBackend, SyntheticFrameSourcePlugin, WebcamBackend
plugins/utility — Служебные и тестовые плагины (heartbeat, pilot_widgets и др.); сюда — менять служебные плагины
  классы: PilotWidgetsPlugin, PilotWidgetsRegisters
framework_meta — Корневые файлы пакета фреймворка и его документация; сюда — менять версию, общие импорты, доки фреймворка
  классы: FallbackLogger, RegistrySnapshot
services_shared — Корневой пакет Services и его STATUS; общий уровень сервисов
plugins_shared — Общие доменные утилиты нескольких плагинов, сами не плагины; сюда — менять общий код плагинов
  классы: InspectorManager, JoinInspectorManager
prototype/adapters — Adapter-слой между domain Protocols и реестрами фреймворка; сюда — менять привязку domain к реестрам
prototype/backend — Backend прототипа: конфигурация системы и топология процессов и плагинов; сюда — менять wiring системы
prototype/domain — Изолированный типизированный domain-слой: frozen-сущности и исключения; сюда — менять доменные сущности
prototype/frontend — GUI-пакет прототипа: Qt-презентация PySide6 поверх бэкенда; сюда — менять экраны и GUI прототипа
prototype/recipes — Управление рецептами прототипа: RecipeManager и миграции форматов; сюда — менять рецепты прототипа
prototype/registers — Общие регистры прототипа между плагинами и RegistersManager; сюда — менять shared-регистры
prototype_root — Корень прототипа инспекции дефектов: запуск, оркестратор, app.yaml, документы; сюда — менять запуск прототипа
tools/backend_ctl — Headless-драйвер бэкенда по TCP, GUI по сокету, dev-инструмент; сюда — менять управление бэкендом
  IBackendClient (7), ISubscriptionRegistry (5), IEventSource (3)
  классы: AuditLog, BackendDriver, BackendHarness, BackendUnavailable, Capabilities, DeliveryWindow, DriverSession, EventHub, MCPNotInstalled, MemoryStats, ObservabilityCounters, ProcessCapabilities, QueueDepths, RecordWriter, Recorder, Recording, RecordingError, RegisterOps, ReplayPlayer, RouterStats, SDKToolServer, TokenFileMissing, TokenRejected, ToolSpec, WatchController, WorkerStatus
prototype/apps — Готовые приложения на фреймворке (line_sim: симулятор линии); сюда — менять запуск и конфиги приложений
tools/tools — Внешние стенды и вспомогательные инструменты (otel_stand: арбитр OTLP); сюда — менять стенды проверки
scripts — Каталог утилит проекта; сюда — менять служебные скрипты репозитория
scripts/atlas — Атлас: реестр доказанности и знаний из git, планов и modules.yaml; сюда — менять сборку карточек и страниц
tools/utils — Мелкие общие утилиты: таймер, профилирование, fps_module, file_comments; сюда — менять отладочные помощники
  классы: AverageFPS, Config, ConfigLoader, DebugLogger, FPSProvider, FileProcessorFacade, FileStats, FileStatsCounter, FrameFPS, OSType, PathCommenter, RingBufferFPS, SimpleDebugLogger, Timer
prototype/robot — Lua-программы и ПК-скрипты робота Delta SCARA (DRAStudio, Modbus); сюда — менять прошивку и пробы робота
docs/examples — Пример приложения minimal_app, рыба-шаблон; сюда — смотреть образец использования фреймворка
tools/backend_ctl/probes — Ручные live-пробники backend_ctl, не входят в обычный прогон тестов; сюда — менять пробники
  классы: AppProfile, Arrivals, Collector, LogStormPlugin
frontend_module/components — Примитивы контролов: Traits, Presenter, View, Facade; сюда — менять базовые контролы GUI
  классы: CardAction, CheckboxControl, CheckboxControlResult, CheckboxPresenter, CheckboxRegister, CheckboxView, CheckboxViewConfig, ComboControl, ComboControlResult, ComboPresenter, ComboRegister, ComboView, ComboViewConfig, CompoundControl, CompoundControlConfig, CompoundControlResult, CompoundNumericConfig, CompoundNumericControl, CompoundNumericControlResult, ControlFactory, CrudTable, EntityCard, GroupConfig, LabelConfig, LabelView, LabeledNumericGroupConfig, LabeledNumericGroupView, MasterDetailLayout, NumericControl, NumericControlResult, NumericPresenter, NumericViewConfig, SliderConfig, SliderControl, SliderControlResult, SliderPresenter, SliderRegister, SliderValueView, SpinBoxConfig, SpinBoxControl, SpinBoxControlResult, SpinBoxPresenter, SpinBoxValueView, StatusIndicator
frontend_module/components/_examples — Учебные схемы и адаптеры к контролам; сюда — смотреть пример адаптера, не боевой код
  классы: ExampleBgrTripletRegister, ExampleCheckboxUiConfig, ExampleCheckboxValueRegister, ExampleComboUiConfig, ExampleComboValueRegister, ExampleCompoundMixedUiConfig, ExampleCompoundNumericUiConfig, ExampleGroupRowUiConfig, ExampleLabelUiConfig, ExampleMixedBoolRegister, ExampleMixedFloatRegister, ExampleNumericUiConfig, ExampleNumericValueRegister, ExampleSliderUiConfig, ExampleSliderValueRegister, ExampleSpinboxUiConfig, ExampleSpinboxValueRegister, GroupRowExampleResult, LabelExampleResult
frontend_module/components/base — Базовый слой контролов: контракты, конфиг, мост к регистрам, traits; сюда — менять основу контролов
  IControlView (8), INumericView (4), IRegisterPort (4), IFieldBinding (0), IRegistersManagerGui, … ещё 1
  классы: AccessTrait, BaseControlConfig, BindingConfig, ControlAccessDeniedEvent, ControlHooks, ControlWriteCommittedEvent, ControlWriteRejectedEvent, DebounceTrait, LegacySyncContext, LegacySyncTrait, RegisterAdapter, SchemaTrait, SyncTrait, TouchKeyboardConfig, ValueTransformer
frontend_module/core — Базовые классы frontend_module без Qt: маршрутизация команд, мост регистров; сюда — менять ядро GUI-фреймворка
  классы: AppIdentity, BaseConfigurableWidget, FrontendAppContext, FrontendRegistersBridge, GuiMemoryPolicy, QThreadHandle, QtTreeMismatch, RoutedCommandSender, UiDiagnosticsSession, WidgetRegistry, WindowEntry, WindowRegistry
frontend_module/widgets — Составные UI-компоненты: вкладки, таблицы, шапка, клавиатура; сюда — менять составные виджеты
  классы: AdminButtonConfig, AdminButtonWidget, BaseEditorModel, BaseEditorToolbar, BaseEditorTreeView, BaseWidget, ButtonHeader, EntityLevel, EntityTreeConfig, EntityTreeWidget, HeaderButtonItem, HeaderButtonsConfig, HeaderButtonsWidget, HeaderConfig, HeaderWidget, ImagePanelWidget, LineEditTouchKeyboardFilter, LogoConfig, LogoWidget, ParamDef, ParamsForm, PerformanceMonitor, SchemaInspectorPanel, SeriesSpec, StructuredTableWidget, StructuredTwoLevelTreeWidget, TableWithToolbar, TelemetryChart, TemplateModel, TemplatePanelWidget, TemplatePresenter, TemplateUiConfig, TouchLineEditItemDelegate, TwoLevelTreeWithToolbar, VirtualKeyboard, VirtualKeyboardMini, WidgetSignalBus
frontend_module/widgets/chrome — Заголовок приложения, боковые панели и оверлеи; сюда — менять обрамление окна
  классы: AppHeaderWidget, BrandLabel, CollapsibleSidePanel, HeaderModeToggle, InfoTickerWidget, RecordingIndicator, RecordingIndicatorConfig, SearchFilterBar, StatusStripWidget, ViewModeToggle, WatchdogOverlay
frontend_module/widgets/tabs — Вкладки: TabWidget, BaseTab, MVP-база, привязка к регистрам; сюда — менять каркас вкладок
  классы: BaseColumnarTab, BaseListNavTab, BaseTab, BaseTreeNavTab, CurrentPageStack, DiffScrollTabLayout, MvpTabBase, PanelTabBase, RegisterBindingContext, RegisterSpinboxRowSpec, SectionProtocol, SectionSpec, SectionWithEvents, StandardTabLayout, TabLayoutProtocol, TabPresenterBase, TabViewProtocol, TabWidget, TreeNavTabPresenter, UndoRedoController
process_module/generic — GenericProcess: конфиг-драйвен процесс с загрузкой плагинов из конфига; сюда — менять универсальный процесс
  классы: ActuationScheduler, AllocProfiler, CycleMetricsRecorder, DataReceiver, FramePacer, GenericProcess, GenericProcessConfig, IdleWorker, ItemCollector, LatencyProbes, LatestMailbox, PassThroughCollector, PipelineExecutor, PipelineStepNode, PluginConfig, PluginOperationStep, PluginOrchestrator, PluginRunner, SourceProducer, SuspectTagStep
prototype/frontend/widgets — Виджеты GUI прототипа по доменам: вкладки, дисплеи, диалоги, камера; сюда — менять экраны и компоненты UI
prototype/frontend/widgets/tabs — Вкладки приложения: реестр фабрик вкладок из единого списка TABS; сюда — менять состав вкладок
prototype/frontend/widgets/tabs/pipeline — Вкладка визуального конструктора pipeline: граф, палитра плагинов, инспектор; сюда — менять редактор pipeline
prototype/frontend/widgets/tabs/services — Вкладка управления сервисами: секции из реестра, запуск/остановка, пути; сюда — менять экран сервисов
prototype/frontend/widgets/tabs/settings — Пилотная вкладка Settings, сквозной пример таба; сюда — менять вкладку настроек
````

## 2. Паспорта (`atlas map`)

### map services/camera_device

Команда: `atlas map services/camera_device`

````text
== unit services/camera_device ==
Services/camera_device/; sha ea65a3334252c823ac2e8772df9dd703920a5f66; scanner 1-d8b9d44d5b0d
purpose: Общее ядро камер: контракт порта прибора и его фейк; сюда — менять порт, границу SDK и эмуляцию
interface: layer services/camera_device
  all: AmbiguousDeviceError, Binding, DeviceIdentity, DeviceInfo, DevicePort, DeviceSdk, ParamInfo, PortError, RawFrame, entry_text, in_camera_subnet, select_device
  members:
    Services/camera_device/interface.py — Контракт порта камеры: типы, ошибка, `DeviceSdk` и `DevicePort` (Task 1.5).  (DeviceIdentity, DeviceInfo, Binding, ParamInfo, RawFrame, PortError, +6)
    Services/camera_device/plugin_base.py — CameraDevicePlugin — источник кадров ядра камеры: сеанс `DeviceSession` -> очередь кадров -> item -> дерево.  (CameraDeviceError, create_port, CameraDevicePlugin)
    Services/camera_device/registers_base.py — Register ядра камеры (Task 2.3a): общий для базового плагина с `driver: fake` и вендорских плагинов.  (CameraDeviceRegisters)
    Services/camera_device/__init__.py — Общее ядро камер: контракт порта прибора и его фейк; сюда — менять порт, границу SDK и эмуляцию
    Services/camera_device/commands.py — Модели аргументов команд плагина камеры (Task 2.3c, module contract lite).  (TakeDeviceArgs, ReleaseDeviceArgs, ApplyParamsArgs)
    Services/camera_device/params.py — План записи профиля камеры из register'а и таблицы привязки (Task 1.6).  (Step, build_plan, check_bindings)
    Services/camera_device/plugin.py — Точка обнаружения плагина `camera_device`: `discover()` ищет файлы `plugin.py`, сам класс — в `plugin_base.py`.
    Services/camera_device/profiles.py — Профили run/rest и проверка записи чтением (Task 2.2, Р6).  (ProfileState, within_tolerance, ProfileRunner)
    Services/camera_device/session.py — Сеанс прибора `DeviceSession` (Task 2.1): поток-владелец, жизненный цикл, ошибки кадра, сторож.  (describe_error, DeviceSession)
    Services/camera_device/testing/__init__.py — Тестовые средства ядра камер: честный фейк порта и записи узлов приборов.
    Services/camera_device/testing/fake_port.py — Честный фейк порта камеры (Task 1.5): ведёт себя как прибор, а не как заглушка.  (FakePort, make_port, from_recording)
links: найдено 4 (формы: import); не видно: динамика, аннотации, упоминания
  used_by: 1
    services/hikvision_camera — Services/hikvision_camera/driver.py:24 (import) ×4
runtime:
  threads: —
  commands: —
  io: —
checks:
  tests: 29
    Services/camera_device/tests/test_plugin_commands.py — Services/camera_device/tests/test_plugin_commands.py:1 ×33
    Services/camera_device/tests/test_plugin_device_commands.py — Services/camera_device/tests/test_plugin_device_commands.py:1 ×30
    Services/camera_device/tests/test_live_apply_hazards.py — Services/camera_device/tests/test_live_apply_hazards.py:1 ×28
    Services/camera_device/tests/test_plugin_base_hazards.py — Services/camera_device/tests/test_plugin_base_hazards.py:1 ×27
    Services/camera_device/tests/test_readiness.py — Services/camera_device/tests/test_readiness.py:1 ×26
    Services/camera_device/tests/test_session_lifecycle_hazards.py — Services/camera_device/tests/test_session_lifecycle_hazards.py:1 ×22
    Services/camera_device/tests/test_fake_port_options.py — Services/camera_device/tests/test_fake_port_options.py:1 ×20
    Services/camera_device/tests/test_plugin_observability.py — Services/camera_device/tests/test_plugin_observability.py:1 ×18
    Services/camera_device/tests/test_fake_port_hazards.py — Services/camera_device/tests/test_fake_port_hazards.py:1 ×17
    Services/camera_device/tests/test_plugin_commands_hazards.py — Services/camera_device/tests/test_plugin_commands_hazards.py:1 ×17
    Services/camera_device/tests/test_live_apply_wiring.py — Services/camera_device/tests/test_live_apply_wiring.py:1 ×15
    Services/camera_device/tests/test_session_profiles_hazards.py — Services/camera_device/tests/test_session_profiles_hazards.py:1 ×15
    Services/camera_device/tests/test_plugin_base.py — Services/camera_device/tests/test_plugin_base.py:1 ×14
    Services/camera_device/tests/test_plugin_device_commands_hazards.py — Services/camera_device/tests/test_plugin_device_commands_hazards.py:1 ×14
    Services/camera_device/tests/test_stream_health_hazards.py — Services/camera_device/tests/test_stream_health_hazards.py:1 ×11
    Services/camera_device/tests/test_fake_port_modes.py — Services/camera_device/tests/test_fake_port_modes.py:1 ×10
    Services/camera_device/tests/test_identity_stream_contract.py — Services/camera_device/tests/test_identity_stream_contract.py:1 ×10
    Services/camera_device/tests/test_session_lifecycle.py — Services/camera_device/tests/test_session_lifecycle.py:1 ×10
    Services/camera_device/tests/test_session_profiles.py — Services/camera_device/tests/test_session_profiles.py:1 ×10
    Services/camera_device/tests/test_params.py — Services/camera_device/tests/test_params.py:1 ×9
    Services/camera_device/tests/test_run_locked_commands_camera.py — Services/camera_device/tests/test_run_locked_commands_camera.py:1 ×9
    Services/camera_device/tests/test_source_queue_frames.py — Services/camera_device/tests/test_source_queue_frames.py:1 ×9
    Services/camera_device/tests/test_live_apply_session.py — Services/camera_device/tests/test_live_apply_session.py:1 ×8
    Services/camera_device/tests/test_params_hazards.py — Services/camera_device/tests/test_params_hazards.py:1 ×8
    Services/camera_device/tests/test_live_apply_plugin.py — Services/camera_device/tests/test_live_apply_plugin.py:1 ×6
    Services/camera_device/tests/test_slice_plugin.py — Services/camera_device/tests/test_slice_plugin.py:1 ×6
    Services/camera_device/tests/test_apply_params_bindings_refused.py — Services/camera_device/tests/test_apply_params_bindings_refused.py:1 ×4
    Services/camera_device/tests/test_port_contract.py — Services/camera_device/tests/test_port_contract.py:1 ×2
    Services/camera_device/tests/test_run_locked_commands_camera_hazards.py — Services/camera_device/tests/test_run_locked_commands_camera_hazards.py:1 ×2
status: tier —; doc_missing нет; dynamic —
  stale: —
  frozen: —
````

### map services/code_reader

Команда: `atlas map services/code_reader`

````text
== unit services/code_reader ==
Services/code_reader/; sha ea65a3334252c823ac2e8772df9dd703920a5f66; scanner 1-d8b9d44d5b0d
purpose: Сервис считывателя кодов Hikrobot ID3000: приём результатов по TCP, разбор; сюда — менять чтение кодов
interface: layer services/code_reader
  all: ReadResult, ReadStatus, ResultSink, parse_packet, split_stream
  members:
    Services/code_reader/__init__.py — Сервис считывателя кодов Hikrobot ID3000: приём результатов по TCP, разбор; сюда — менять чтение кодов
    Services/code_reader/core/__init__.py — Ядро сервиса code_reader: разбор результата и приём по TCP.
    Services/code_reader/core/result.py — Разбор результата чтения, приходящего от считывателя ID3000.  (ReadStatus, ReadResult, parse_packet, split_stream)
    Services/code_reader/core/sdk_frame.py — Модель кадра прибора, полученного через MvCodeReader SDK.  (CodeQuality, CodeRead, SdkFrame, frame_from_raw, decode_image)
    Services/code_reader/core/sdk_reader.py — Сессия прибора через MvCodeReader SDK: открыть, крутить захват в потоке, отдать кадр.  (SdkCodeReader)
    Services/code_reader/core/sink.py — Приём результатов чтения по TCP.  (ResultSink)
    Services/code_reader/interfaces.py — Публичные контракты code_reader.  (CodeReaderSinkProtocol)
    Services/code_reader/plugin/__init__.py — Плагины считывателя кодов ID3000 для multiprocess_prototype (TCP и SDK).
    Services/code_reader/plugin/config.py — Конфиг CodeReaderPlugin — identity + register_bindings.  (CodeReaderPluginConfig)
    Services/code_reader/plugin/plugin.py — CodeReaderPlugin — source-плагин «код с промышленного считывателя ID3000».  (CodeReaderPlugin)
    Services/code_reader/plugin/registers.py — CodeReaderRegisters — параметры приёма и телеметрия считывателя.  (CodeReaderRegisters)
    Services/code_reader/plugin/sdk_config.py — Конфиг CodeReaderSdkPlugin — identity + register_bindings.  (CodeReaderSdkPluginConfig)
    Services/code_reader/plugin/sdk_plugin.py — CodeReaderSdkPlugin — source-плагин «кадр и коды с прибора через MvCodeReader SDK».  (CodeReaderSdkPlugin)
    Services/code_reader/plugin/sdk_registers.py — CodeReaderSdkRegisters — параметры SDK-канала и телеметрия считывателя.  (CodeReaderSdkRegisters)
    Services/code_reader/sdk/__init__.py — Слой MvCodeReader SDK (``MvCodeReaderCtrl.dll``): загрузка, структуры, тонкая обёртка.
    Services/code_reader/sdk/api.py — Тонкая обёртка над ``MvCodeReaderCtrl.dll``: перечисление, открытие, захват кадра.  (DeviceEntry, RawFrame, MvCodeReaderApi)
    Services/code_reader/sdk/errors.py — Коды возврата MvCodeReader SDK и исключения слоя ``sdk/``.  (unsigned, SdkError, SdkNotFoundError)
    Services/code_reader/sdk/loader.py — Поиск и ленивая загрузка ``MvCodeReaderCtrl.dll``.  (find_sdk_dir, load_library)
    показано 18 из 27; все: --all members
links: найдено 0; не видно: динамика, аннотации, упоминания
  used_by: —
runtime:
  threads: 5
    Thread (daemon: True) — Services/code_reader/core/sdk_reader.py:254
    Thread (daemon: True) — Services/code_reader/core/sink.py:203
    Thread (daemon: True) — Services/code_reader/core/sink.py:273
    Thread (daemon: True) — Services/code_reader/tools/id3000_tcp_sink.py:102
    Thread (daemon: True) — Services/code_reader/tools/reader_sim.py:107
  commands: —
  io: 1
    replaces path — Services/code_reader/tools/cam_cfg.py:58
checks:
  tests: 21
    Services/code_reader/tests/test_sdk_reader.py — Services/code_reader/tests/test_sdk_reader.py:1 ×55
    Services/code_reader/tests/test_sdk_params.py — Services/code_reader/tests/test_sdk_params.py:1 ×53
    Services/code_reader/tests/test_sdk_layer.py — Services/code_reader/tests/test_sdk_layer.py:1 ×51
    Services/code_reader/tests/test_cam_cfg.py — Services/code_reader/tests/test_cam_cfg.py:1 ×44
    Services/code_reader/tests/test_plugin.py — Services/code_reader/tests/test_plugin.py:1 ×41
    Services/code_reader/tests/test_sdk_trigger.py — Services/code_reader/tests/test_sdk_trigger.py:1 ×25
    Services/code_reader/tests/test_mvcr_probe_hazards.py — Services/code_reader/tests/test_mvcr_probe_hazards.py:1 ×21
    Services/code_reader/tests/test_sdk_trigger_live_hazards.py — Services/code_reader/tests/test_sdk_trigger_live_hazards.py:1 ×21
    Services/code_reader/tests/test_cam_cfg_hazards.py — Services/code_reader/tests/test_cam_cfg_hazards.py:1 ×20
    Services/code_reader/tests/test_sdk_trigger_hazards.py — Services/code_reader/tests/test_sdk_trigger_hazards.py:1 ×18
    Services/code_reader/tests/test_result.py — Services/code_reader/tests/test_result.py:1 ×16
    Services/code_reader/tests/test_sdk_labels_check.py — Services/code_reader/tests/test_sdk_labels_check.py:1 ×11
    Services/code_reader/tests/test_sdk_overlay.py — Services/code_reader/tests/test_sdk_overlay.py:1 ×11
    Services/code_reader/tests/test_sdk_labels_robust.py — Services/code_reader/tests/test_sdk_labels_robust.py:1 ×10
    Services/code_reader/tests/test_sdk_overlay_labels.py — Services/code_reader/tests/test_sdk_overlay_labels.py:1 ×10
    Services/code_reader/tests/test_sdk_plugin.py — Services/code_reader/tests/test_sdk_plugin.py:1 ×10
    Services/code_reader/tests/test_sdk_trigger_live_contract.py — Services/code_reader/tests/test_sdk_trigger_live_contract.py:1 ×9
    показано 17 из 21; все: --all tests
status: tier —; doc_missing нет; dynamic —
  stale: —
  frozen: —
````

### map services/hikvision_camera

Команда: `atlas map services/hikvision_camera`

````text
== unit services/hikvision_camera ==
Services/hikvision_camera/; sha ea65a3334252c823ac2e8772df9dd703920a5f66; scanner 1-d8b9d44d5b0d
purpose: Сервис промышленной камеры Hikvision: SDK, логика, плагин; сюда — менять работу с камерой
interface: layer services/hikvision_camera
  all: HikvisionCamera, CameraState, enum_devices, DeviceInfo, CameraParameters, FrameConverter
  members:
    Services/hikvision_camera/__init__.py — Сервис промышленной камеры Hikvision: SDK, логика, плагин; сюда — менять работу с камерой
    Services/hikvision_camera/core/discovery.py — Обнаружение камер Hikvision (GigE / USB).  (DeviceInfo, enum_devices)
    Services/hikvision_camera/core/camera.py — HikvisionCamera — state machine камеры с валидацией переходов.  (CameraState, HikvisionCamera)
    Services/hikvision_camera/core/converter.py — Конвертер сырых кадров Hikvision в BGR.  (FrameConverter)
    Services/hikvision_camera/core/parameters.py — Чтение и запись параметров камеры: frame_rate, exposure_time, gain.  (CameraParameters, get_parameters, set_parameters)
    Services/hikvision_camera/sdk/bindings.py — Минимальный ctypes-wrapper для Hikvision MvCameraControl.dll.  (MvCamera)
    Services/hikvision_camera/sdk/constants.py — Константы Hikvision SDK -- только реально используемые значения.  (PixelType)
    Services/hikvision_camera/sdk/structures.py — ctypes-структуры Hikvision SDK -- только необходимые для работы.  (MV_GIGE_DEVICE_INFO, MV_USB3_DEVICE_INFO, MV_CC_DEVICE_INFO, MV_CC_DEVICE_INFO_LIST, MV_FRAME_OUT_INFO, MV_FRAME_OUT, +6)
    Services/hikvision_camera/__main__.py — Точка входа: python -m Services.hikvision_camera  (main)
    Services/hikvision_camera/core/__init__.py — Core layer — камера, обнаружение устройств, параметры, конвертер.
    Services/hikvision_camera/driver.py — Драйвер `mvs` (Task 4.1): порт ядра камеры `camera_device` — тонкий адаптер над `MvCamera`.  (MvsSdk, MvsPort, make_port)
    Services/hikvision_camera/interfaces.py — Публичные контракты hikvision_camera.  (HikvisionCameraProtocol)
    Services/hikvision_camera/plugin/__init__.py — Плагин Hikvision камеры для multiprocess_prototype.
    Services/hikvision_camera/plugin/config.py — Конфиг HikvisionCameraPlugin -- параметры Hikvision source-плагина.  (HikvisionCameraConfig)
    Services/hikvision_camera/plugin/plugin.py — HikvisionCameraPlugin -- source-плагин камеры Hikvision на ядре `camera_device`.  (HikvisionCameraPlugin)
    Services/hikvision_camera/plugin/registers.py — Register камеры Hikvision: поля ядра `camera_device` плюс вендорские параметры MVS.  (HikvisionCameraRegisters)
    Services/hikvision_camera/sdk/__init__.py — Hikvision SDK -- минимальный публичный API.
    Services/hikvision_camera/sdk/errors.py — Коды ошибок Hikvision SDK и утилиты обработки ошибок.  (SdkError, error_description, check_sdk_error)
    показано 18 из 23; все: --all members
links: найдено 14 (формы: import); не видно: динамика, аннотации, упоминания
  used_by: 4
    services/device_hub — Services/device_hub/drivers/hikvision_driver.py:40 (import) ×6
    plugins/sources — Plugins/sources/camera_service/backends/hikvision.py:17 (import) ×4
    services/code_reader — Services/code_reader/tools/id3000_discover.py:45 (import) ×3
    plugins/hub — Plugins/hub/device_hub/plugin.py:1260 (import) ×1
runtime:
  threads: 1
    Thread (daemon: True) — Services/hikvision_camera/tools/mvs_probe.py:673
  commands: —
  io: —
checks:
  tests: 19
    Services/hikvision_camera/tests/test_mvs_probe.py — Services/hikvision_camera/tests/test_mvs_probe.py:1 ×36
    Services/hikvision_camera/tests/test_driver_mvs.py — Services/hikvision_camera/tests/test_driver_mvs.py:1 ×30
    Services/hikvision_camera/tests/test_bindings_getters.py — Services/hikvision_camera/tests/test_bindings_getters.py:1 ×26
    Services/hikvision_camera/tests/test_converter.py — Services/hikvision_camera/tests/test_converter.py:1 ×20
    Services/hikvision_camera/tests/test_camera.py — Services/hikvision_camera/tests/test_camera.py:1 ×17
    Services/hikvision_camera/tests/test_4_2d_acceptance.py — Services/hikvision_camera/tests/test_4_2d_acceptance.py:1 ×15
    Services/hikvision_camera/tests/test_plugin_on_core_contract.py — Services/hikvision_camera/tests/test_plugin_on_core_contract.py:1 ×15
    Services/hikvision_camera/tests/test_plugin.py — Services/hikvision_camera/tests/test_plugin.py:1 ×13
    Services/hikvision_camera/tests/test_driver_identity_stream.py — Services/hikvision_camera/tests/test_driver_identity_stream.py:1 ×12
    Services/hikvision_camera/tests/test_plugin_on_core.py — Services/hikvision_camera/tests/test_plugin_on_core.py:1 ×12
    Services/hikvision_camera/tests/test_constants.py — Services/hikvision_camera/tests/test_constants.py:1 ×10
    Services/hikvision_camera/tests/test_parameters.py — Services/hikvision_camera/tests/test_parameters.py:1 ×10
    Services/hikvision_camera/tests/test_plugin_on_core_session.py — Services/hikvision_camera/tests/test_plugin_on_core_session.py:1 ×9
    Services/hikvision_camera/tests/test_errors.py — Services/hikvision_camera/tests/test_errors.py:1 ×8
    Services/hikvision_camera/tests/test_live_path_fixes.py — Services/hikvision_camera/tests/test_live_path_fixes.py:1 ×7
    Services/hikvision_camera/tests/test_discovery.py — Services/hikvision_camera/tests/test_discovery.py:1 ×4
    Services/hikvision_camera/tests/test_capture_stamps.py — Services/hikvision_camera/tests/test_capture_stamps.py:1 ×3
    Services/hikvision_camera/tests/test_gain_range.py — Services/hikvision_camera/tests/test_gain_range.py:1 ×2
    Services/hikvision_camera/tests/test_plugin_on_core_hazards.py — Services/hikvision_camera/tests/test_plugin_on_core_hazards.py:1 ×2
status: tier —; doc_missing нет; dynamic —
  stale: —
  frozen: —
````

### map plugins/sources

Команда: `atlas map plugins/sources`

````text
== unit plugins/sources ==
Plugins/sources/; sha ea65a3334252c823ac2e8772df9dd703920a5f66; scanner 1-d8b9d44d5b0d
purpose: Плагины источников данных: камеры, файлы, генераторы; сюда — менять источники
interface: layer plugins/sources
  all: —
  members:
    Plugins/sources/camera_service/backends/webcam_controls.py — Универсальный control-core веб-камеры (OpenCV CAP_PROP).  (ParamSpec, decode_fourcc, apply_param, set_mjpg, apply_open_sequence, read_actual, +1)
    Plugins/sources/__init__.py — Плагины источников данных: камеры, файлы, генераторы; сюда — менять источники
    Plugins/sources/camera_service/__init__.py — CameraServicePlugin — multi-backend камера (simulator/webcam/hikvision/file).
    Plugins/sources/camera_service/backends/__init__.py — Backends для CameraServicePlugin — factory, константы, re-exports.  (create_backend, hw_release_delay)
    Plugins/sources/camera_service/backends/base.py — CameraBackend Protocol — интерфейс для всех backend'ов камеры.  (CameraBackend)
    Plugins/sources/camera_service/backends/file_source.py — FileSourceBackend — захват кадров из видеофайла.  (FileSourceBackend)
    Plugins/sources/camera_service/backends/hikvision.py — HikvisionBackend — захват с промышленных камер Hikvision (MVS SDK).  (HikvisionBackend)
    Plugins/sources/camera_service/backends/simulator.py — SimulatorBackend — генерация тестовых кадров.  (FrameGenerator, SimulatorBackend)
    Plugins/sources/camera_service/backends/stream_source.py — StreamSourceBackend — захват кадров из сетевого видеопотока (MJPEG/RTSP/...).  (StreamSourceBackend)
    Plugins/sources/camera_service/backends/webcam.py — WebcamBackend — захват с веб-камеры через OpenCV.  (WebcamBackend)
    Plugins/sources/camera_service/config.py — Конфиг CameraServicePlugin — параметры multi-backend камеры.  (CameraServiceConfig)
    Plugins/sources/camera_service/plugin.py — CameraServicePlugin -- multi-backend камера.  (CameraServicePlugin)
    Plugins/sources/camera_service/registers.py — CameraServiceRegisters — runtime-tunable параметры камеры (inspector subset).  (CameraServiceRegisters)
    Plugins/sources/capture/__init__.py — CapturePlugin — захват кадров с вебкамеры через cv2.VideoCapture → SHM ring-buffer.
    Plugins/sources/capture/config.py — Конфиг CapturePlugin — параметры захвата с вебкамеры.  (CapturePluginConfig)
    Plugins/sources/capture/plugin.py — CapturePlugin -- захват кадров с вебкамеры.  (CapturePlugin)
    Plugins/sources/frame_counter/__init__.py — FrameCounterPlugin — простой приёмник кадров для проверки IPC frame flow.
    Plugins/sources/frame_counter/config.py — Конфиг FrameCounterPlugin.  (FrameCounterPluginConfig)
    Plugins/sources/frame_counter/plugin.py — FrameCounterPlugin -- счётчик кадров + FPS лог.  (FrameCounterPlugin)
    Plugins/sources/heartbeat/__init__.py — Heartbeat plugin — периодический лог для проверки работоспособности системы.
    Plugins/sources/heartbeat/config.py — Конфигурация HeartbeatPlugin.  (HeartbeatPluginConfig)
    Plugins/sources/heartbeat/plugin.py — HeartbeatPlugin — периодический лог для проверки работоспособности системы.  (HeartbeatPlugin)
    Plugins/sources/synthetic_frame_source/__init__.py — SyntheticFrameSourcePlugin — генератор кадров без реального железа (Ф7 G.1 baseline).
    Plugins/sources/synthetic_frame_source/plugin.py — SyntheticFrameSourcePlugin -- генератор синтетических кадров БЕЗ реального железа.  (SyntheticFrameSourcePlugin)
links: найдено 2 (формы: import); не видно: динамика, аннотации, упоминания
  used_by: 2
    prototype/frontend/widgets/tabs — multiprocess_prototype/frontend/widgets/tabs/plugins/sandbox.py:524 (import) ×1
    prototype/frontend/widgets/tabs/services — multiprocess_prototype/frontend/widgets/tabs/services/camera/widget.py:27 (import) ×1
runtime:
  threads: —
  commands: —
  io: —
checks:
  tests: 13
    Plugins/sources/capture/tests/test_plugin.py — Plugins/sources/capture/tests/test_plugin.py:1 ×21
    Plugins/sources/camera_service/tests/test_webcam_controls.py — Plugins/sources/camera_service/tests/test_webcam_controls.py:1 ×16
    Plugins/sources/camera_service/tests/test_plugin.py — Plugins/sources/camera_service/tests/test_plugin.py:1 ×14
    Plugins/sources/camera_service/tests/test_commands.py — Plugins/sources/camera_service/tests/test_commands.py:1 ×12
    Plugins/sources/camera_service/tests/test_backends.py — Plugins/sources/camera_service/tests/test_backends.py:1 ×9
    Plugins/sources/camera_service/tests/test_stream_hazards.py — Plugins/sources/camera_service/tests/test_stream_hazards.py:1 ×8
    Plugins/sources/camera_service/tests/test_health_fault.py — Plugins/sources/camera_service/tests/test_health_fault.py:1 ×7
    Plugins/sources/camera_service/tests/test_stream_source_acceptance.py — Plugins/sources/camera_service/tests/test_stream_source_acceptance.py:1 ×7
    Plugins/sources/synthetic_frame_source/tests/test_capture_stamps.py — Plugins/sources/synthetic_frame_source/tests/test_capture_stamps.py:1 ×7
    Plugins/sources/capture/tests/test_health_fault.py — Plugins/sources/capture/tests/test_health_fault.py:1 ×5
    Plugins/sources/camera_service/tests/test_hik_release_regression.py — Plugins/sources/camera_service/tests/test_hik_release_regression.py:1 ×4
    Plugins/sources/camera_service/tests/test_hik_open_retry.py — Plugins/sources/camera_service/tests/test_hik_open_retry.py:1 ×3
    Plugins/sources/capture/tests/test_failure_classes_capture_acceptance.py — Plugins/sources/capture/tests/test_failure_classes_capture_acceptance.py:1 ×1
status: tier —; doc_missing да; dynamic —
  stale: —
  frozen: —
````

### map process_module

Команда: `atlas map process_module`

````text
== unit process_module ==
multiprocess_framework/modules/process_module/; sha ea65a3334252c823ac2e8772df9dd703920a5f66; scanner 1-d8b9d44d5b0d
purpose: Базовый класс процесса: создание, инициализация, управление, мониторинг; сюда — менять жизнь процесса
interface: layer process_module
  all: ProcessModule, ManagersConfig, managers_from_log_dir, managers_payload_for_proc, IProcessModule, ISharedResources, IProcessCommunication, ProcessPriorityLevel, ProcessStatus, ManagerType, QueueType, ProcessConfigDict, ProcessStatsDict, ProcessMetadataDict, ProcessAdapter, SchemaAdapter, ProcessIO, ProcessLaunchConfig, class_path_from_type, DEFAULT_QUEUES, merge_managers, ConsoleProcessConfig, TelemetryPublishConfig, MetricRule, GenericProcess, GenericProcessConfig, PluginConfig, ProcessModulePlugin, PluginContext, SystemBlueprint, ProcessConfig, Wire, Port, PluginRegistry, register_plugin
  members:
    multiprocess_framework/modules/process_module/plugins/__init__.py — Plugin system для GenericProcess — единый фасад для плагинов.
    multiprocess_framework/modules/process_module/configs/observability_layers.py — Слоистое владение конфигом наблюдаемости (Task 5.12).  (recipe_defaults_apply_to, resolve_recipe_section, orchestrator_observability_config, ObservabilityLayers, read_process_config, layers_are_silent, +9)
    multiprocess_framework/modules/process_module/plugins/base.py — ProcessModulePlugin + PluginContext — ядро plugin-системы.  (for_each, PluginState, PluginContext, SubPluginContext, ProcessModulePlugin)
    multiprocess_framework/modules/process_module/plugins/registry.py — PluginRegistry — глобальный каталог плагинов.  (PluginEntry, register_plugin)
    multiprocess_framework/modules/process_module/health/schema.py — Контракт health-подсистемы: пути state-дерева и словарь значений.  (HealthStatus, HealthField, LastErrorKey, ReadinessField, ReadinessReasonKey, readiness_reason_is_valid, +5)
    multiprocess_framework/modules/process_module/configs/observability_companion.py — Спутник рецепта — machine-owned файл слоя L2 (Task 5.12, шаг 7).  (companion_path, load_companion, build_companion_section, write_companion, compose_over_base, compose_recipe_layer, +1)
    multiprocess_framework/modules/process_module/core/process_module.py — Базовый класс для всех процессов системы (Refactored).  (ProcessModule)
    multiprocess_framework/modules/process_module/managers/observability_reload.py — Observability hot-reload: ConfigFileWatcher → reconfigure(Logger/Error/Stats).  (resolve_base_log_dir, base_managers_payload, compose_managers_payload, observability_effective, observability_verified, observability_provenance, +11)
    multiprocess_framework/modules/process_module/plugins/port.py — Port — типизированный вход/выход плагина.  (Port, are_ports_compatible, PortValidationError, validate_items_against_ports, available_keys, validate_chain_detailed, +1)
    multiprocess_framework/modules/process_module/__init__.py — Базовый класс процесса: создание, инициализация, управление, мониторинг; сюда — менять жизнь процесса
    multiprocess_framework/modules/process_module/commands/builtin_commands.py — BuiltinCommands — встроенные команды ProcessModule через IProcessServices.  (BuiltinCommands)
    multiprocess_framework/modules/process_module/configs/managers_config.py — ManagersConfig — корневая SchemaBase-сборка секций proc_dict['managers'].  (root_level_rule, ManagersConfig, managers_payload_for_proc, managers_from_log_dir, merge_managers)
    multiprocess_framework/modules/process_module/configs/observability_refs.py — Ссылки секции наблюдаемости, за которыми нет приёмника (Task 5.5).  (known_refs_from_managers, unknown_observability_refs, unknown_recipe_processes, format_unknown_refs, unknown_refs_for, report_unknown_refs, +1)
    показано 13 из 66; все: --all members
links: найдено 409 (формы: import); не видно: динамика, аннотации, упоминания
  used_by: 38
    plugins/processing — Plugins/processing/blob_detector/config.py:11 (import) ×127
    plugins/io — Plugins/io/database/config.py:11 (import) ×41
    plugins/render — Plugins/render/circle_draw/config.py:7 (import) ×28
    plugins/sources — Plugins/sources/camera_service/config.py:7 (import) ×27
    process_manager_module — multiprocess_framework/modules/process_manager_module/launcher/spawner.py:15 (import) ×24
    process_module/generic — multiprocess_framework/modules/process_module/generic/frame_trace.py:404 (import) ×20
    plugins/runtime — Plugins/runtime/chain_executor/config.py:11 (import) ×18
    app_module — multiprocess_framework/modules/app_module/builder.py:235 (import) ×11
    services/control_panel — Services/control_panel/plugin/config.py:7 (import) ×11
    services/phone_gateway — Services/phone_gateway/plugin/config.py:7 (import) ×11
    other — docs/reports/2026-10-28_lifecycle-stop-ownership_C-60-stand/stand_c60_child.py:24 (import) ×9
    plugins/control — Plugins/control/robot_control/config.py:11 (import) ×9
    plugins/sim — Plugins/sim/layer_preview/plugin.py:65 (import) ×8
    показано 13 из 38; все: --all used_by
runtime:
  threads: 1
    Thread (daemon: True) — multiprocess_framework/modules/process_module/commands/builtin_commands.py:3650
  commands: —
  io: 1
    replaces path — multiprocess_framework/modules/process_module/configs/observability_companion.py:139
checks:
  tests: 292
    multiprocess_framework/modules/process_module/tests/test_wide_event_hazards.py — multiprocess_framework/modules/process_module/tests/test_wide_event_hazards.py:1 ×44
    multiprocess_framework/modules/process_module/tests/test_introspect_commands.py — multiprocess_framework/modules/process_module/tests/test_introspect_commands.py:1 ×43
    multiprocess_framework/modules/process_module/tests/test_observability_audit.py — multiprocess_framework/modules/process_module/tests/test_observability_audit.py:1 ×42
    multiprocess_framework/modules/process_module/tests/test_plugin_levels_hazards.py — multiprocess_framework/modules/process_module/tests/test_plugin_levels_hazards.py:1 ×42
    multiprocess_framework/modules/process_module/tests/test_telemetry_reload.py — multiprocess_framework/modules/process_module/tests/test_telemetry_reload.py:1 ×41
    multiprocess_framework/modules/process_module/tests/test_observability_companion.py — multiprocess_framework/modules/process_module/tests/test_observability_companion.py:1 ×37
    multiprocess_framework/modules/process_module/tests/test_observability_ttl.py — multiprocess_framework/modules/process_module/tests/test_observability_ttl.py:1 ×36
    multiprocess_framework/modules/process_module/tests/test_plugin_runner.py — multiprocess_framework/modules/process_module/tests/test_plugin_runner.py:1 ×35
    multiprocess_framework/modules/process_module/tests/test_frame_trace_fanin.py — multiprocess_framework/modules/process_module/tests/test_frame_trace_fanin.py:1 ×34
    multiprocess_framework/modules/process_module/plugins/tests/test_plugin_manifest.py — multiprocess_framework/modules/process_module/plugins/tests/test_plugin_manifest.py:1 ×32
    multiprocess_framework/modules/process_module/tests/test_observability_refs.py — multiprocess_framework/modules/process_module/tests/test_observability_refs.py:1 ×32
    multiprocess_framework/modules/process_module/tests/test_flight_recorder_hazards.py — multiprocess_framework/modules/process_module/tests/test_flight_recorder_hazards.py:1 ×30
    показано 12 из 292; все: --all tests
status: tier core; doc_missing нет; dynamic —
  stale: —
  frozen: —
````

### map process_manager_module

Команда: `atlas map process_manager_module`

````text
== unit process_manager_module ==
multiprocess_framework/modules/process_manager_module/; sha ea65a3334252c823ac2e8772df9dd703920a5f66; scanner 1-d8b9d44d5b0d
purpose: Оркестратор процессов: запуск системы, реестр, приоритеты, мониторинг; сюда — менять управление процессами
interface: layer process_manager_module
  all: ISystemLauncher, IProcessManagerProcess, IProcessRegistry, SystemLauncher, ProcessSpawner, ProcessManagerProcess, ProcessRegistry, ProcessPriority, ProcessStatusMonitor, ProcessMonitor, ProcessSchemaAdapter
  members:
    multiprocess_framework/modules/process_manager_module/topology/blueprint.py — SystemBlueprint — SchemaBase-чертёж системы.  (Wire, ProcessConfig, SystemBlueprint)
    multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py — SystemLauncher — фасад запуска системы (Refactored).  (SystemLauncher)
    multiprocess_framework/modules/process_manager_module/core/process_registry.py — ProcessRegistry — реестр процессов ОС + lifecycle + создание.  (ProcessRegistry)
    multiprocess_framework/modules/process_manager_module/launcher/__init__.py — Launcher для запуска системы.
    multiprocess_framework/modules/process_manager_module/process/run_config.py — Ключи работы системы в конфиге PM одной моделью (Task 2.7 S3b1, ADR-PMM-049).  (RunConfig, run_config_value)
    multiprocess_framework/modules/process_manager_module/launcher/schema.py — Схема proc_dict для process_manager_module.
    multiprocess_framework/modules/process_manager_module/__init__.py — Оркестратор процессов: запуск системы, реестр, приоритеты, мониторинг; сюда — менять управление процессами
    multiprocess_framework/modules/process_manager_module/process/backend_ctl_endpoint.py — backend_ctl_endpoint — поднятие SocketChannel в ProcessManager (dev-гейт).  (is_enabled, setup_backend_ctl_channel, teardown_backend_ctl_channel)
    multiprocess_framework/modules/process_manager_module/process/process_manager_process.py — ProcessManagerProcess — процесс-оркестратор (Refactored).  (ProcessManagerProcess)
    multiprocess_framework/modules/process_manager_module/adapters/__init__.py — Адаптеры для ProcessManagerModule.
    multiprocess_framework/modules/process_manager_module/adapters/schema_adapter.py — ProcessSchemaAdapter — преобразование SchemaBase в конфиг для запуска процесса.  (ProcessSchemaAdapter)
    multiprocess_framework/modules/process_manager_module/core/__init__.py — Core компоненты Process Manager Module.
    multiprocess_framework/modules/process_manager_module/core/alert_rules.py — alert_rules — декларативные правила алертинга поверх supervisor-событий (NEW-7).  (AlertRule, rules_for_event, counter_rules, should_fire, counter_growth)
    multiprocess_framework/modules/process_manager_module/core/bundle_contract.py — Bundle Contract — pickle-safe dict, передаваемый в дочерний процесс через Process(args=...).  (validate_bundle, build_bundle)
    показано 14 из 41; все: --all members
links: найдено 36 (формы: import); не видно: динамика, аннотации, упоминания
  used_by: 10
    other — docs/reports/2026-10-26_lifecycle-stop-ownership_1.9b-stand/stand_backend.py:30 (import) ×13
    app_module — multiprocess_framework/modules/app_module/builder.py:38 (import) ×7
    prototype/backend — multiprocess_prototype/backend/assembly/assembler.py:25 (import) ×6
    process_module — multiprocess_framework/modules/process_module/__init__.py:120 (import) ×3
    tools/backend_ctl — backend_ctl/endpoint_config.py:24 (import) ×2
    framework_meta — multiprocess_framework/__init__.py:93 (import) ×1
    prototype/frontend/widgets — multiprocess_prototype/frontend/widgets/topology/presenter.py:12 (import) ×1
    prototype/frontend/widgets/tabs/settings — multiprocess_prototype/frontend/widgets/tabs/settings/yaml_io.py:14 (import) ×1
    prototype/recipes — multiprocess_prototype/recipes/save.py:173 (import) ×1
    prototype_root — multiprocess_prototype/main.py:21 (import) ×1
runtime:
  threads: 3
    Thread (daemon: True) — multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:2060
    Thread (daemon: True) — multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:3449
    Thread (daemon: True) — multiprocess_framework/modules/process_manager_module/runner/process_runner.py:167
  commands: —
  io: —
checks:
  tests: 152
    multiprocess_framework/modules/process_manager_module/tests/test_process_monitor.py — multiprocess_framework/modules/process_manager_module/tests/test_process_monitor.py:1 ×76
    multiprocess_framework/modules/process_manager_module/tests/test_observability_broker.py — multiprocess_framework/modules/process_manager_module/tests/test_observability_broker.py:1 ×63
    multiprocess_framework/modules/process_manager_module/tests/test_apply_topology.py — multiprocess_framework/modules/process_manager_module/tests/test_apply_topology.py:1 ×47
    multiprocess_framework/modules/process_manager_module/tests/test_telemetry_broadcast.py — multiprocess_framework/modules/process_manager_module/tests/test_telemetry_broadcast.py:1 ×47
    multiprocess_framework/modules/process_manager_module/tests/test_supervision_strategies.py — multiprocess_framework/modules/process_manager_module/tests/test_supervision_strategies.py:1 ×41
    multiprocess_framework/modules/process_manager_module/tests/test_alerting.py — multiprocess_framework/modules/process_manager_module/tests/test_alerting.py:1 ×38
    multiprocess_framework/modules/process_manager_module/tests/test_topology_manager.py — multiprocess_framework/modules/process_manager_module/tests/test_topology_manager.py:1 ×37
    multiprocess_framework/modules/process_manager_module/tests/test_process_manager_process.py — multiprocess_framework/modules/process_manager_module/tests/test_process_manager_process.py:1 ×36
    multiprocess_framework/modules/process_manager_module/tests/test_ready_gate_redelivery.py — multiprocess_framework/modules/process_manager_module/tests/test_ready_gate_redelivery.py:1 ×31
    multiprocess_framework/modules/process_manager_module/tests/test_stop_budget_child_stop_acceptance.py — multiprocess_framework/modules/process_manager_module/tests/test_stop_budget_child_stop_acceptance.py:1 ×29
    multiprocess_framework/modules/process_manager_module/tests/test_topology_seeds.py — multiprocess_framework/modules/process_manager_module/tests/test_topology_seeds.py:1 ×28
    multiprocess_framework/modules/process_manager_module/tests/test_process_runner.py — multiprocess_framework/modules/process_manager_module/tests/test_process_runner.py:1 ×27
    multiprocess_framework/modules/process_manager_module/tests/test_telemetry_addressed_delta_hazards.py — multiprocess_framework/modules/process_manager_module/tests/test_telemetry_addressed_delta_hazards.py:1 ×27
    multiprocess_framework/modules/process_manager_module/tests/test_interfaces.py — multiprocess_framework/modules/process_manager_module/tests/test_interfaces.py:1 ×26
    показано 14 из 152; все: --all tests
status: tier core; doc_missing нет; dynamic —
  stale: —
  frozen: —
````

## 3. Карточки (`atlas card`)

### card actions_module

Команда: `atlas card actions_module`

````text
Модуль actions_module — framework, ярус optional
Назначение: Action-шина с undo/redo и объединением правок для GUI; сюда — менять откат и повтор действий
API (3): IActionLogRepository, IActionLogWriter, IRegistersManagerGui
Открытые задачи: нет
Коммиты (12 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  09ea9a1 2026-09-30 feat(pipeline): undo/redo возвращают выбор операции — memo в SnapshotHistory
  fde79ab 2026-09-30 test(pipeline): undo-restores-selection — слепые приёмочные A1–A9 (RED)
  23184cc 2026-08-09 feat(observability): merge — влить observability-unified-routing — Ф0–Ф8 наблюдаемости
  bf484bc 2026-07-19 refactor(framework): создать actions_module/interfaces.py — канонический контракт (Фаза 2)
Находки (6):
  warning P2_DOCSTRING module:actions_module SnapshotHistory.can_redo
  warning P2_DOCSTRING module:actions_module SnapshotHistory.can_undo
  warning P3_NO_ALL module:actions_module multiprocess_framework/modules/actions_module/persistence/interfaces.py
  info INTERFACE_WITHOUT_TEST interface:actions_module:IActionLogRepository -
  info INTERFACE_WITHOUT_TEST interface:actions_module:IActionLogWriter -
  info INTERFACE_WITHOUT_TEST interface:actions_module:IRegistersManagerGui -
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 35, из них тестов 18
  Services/sql/action_log/log_writer.py:22
  Services/sql/action_log/recovery.py:17
  Services/sql/action_log/repository.py:16
  Services/sql/action_log/schema_ext.py:18
  multiprocess_framework/__init__.py:138
  multiprocess_framework/modules/frontend_module/forms/form_context.py:17
  multiprocess_prototype/adapters/dispatch/history.py:21
  multiprocess_prototype/frontend/actions/__init__.py:7
  multiprocess_prototype/frontend/actions/builder.py:8
  multiprocess_prototype/frontend/actions/bus_factory.py:10
  … ещё 7
  тесты: 18 файлов, первые 3: Services/auth/tests/test_role_update_handler.py, multiprocess_framework/modules/frontend_module/tests/integration/test_form_context_integration.py, multiprocess_framework/modules/frontend_module/tests/test_combo_form_ctx.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 39 из 41
  П3 __all__ у interfaces.py и __init__.py: 4 из 5
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card app_module

Команда: `atlas card app_module`

````text
Модуль app_module — framework, ярус optional
Назначение: Шаблон приложения (composition root): общая сборка многопроцессного приложения; сюда — менять каркас запуска
API (6): BlueprintLoader, LauncherFactory, ManifestStoreProtocol, ProcDictsBuilder, StateBootstrap, ThrottleRules
Открытые задачи (5 планов, 52 задач):
  line-sim — 4: 4.1, 4.2, 4.3, 6.4
  observation-port — 2: 0.2, 2.4
  telemetry-stage6 — 2: 1.2, 3.5
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
Коммиты (27 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  0f1883a 2026-11-07 feat(process): слияние gui-close-1.1a — PM отвечает на команды всё окно остановки детей
  4f56e96 2026-10-25 merge: C-21(б) — последний активный рецепт в <stem>.state.yaml вне git, app.yaml — умолча…
  5ae0b39 2026-10-12 merge: lifecycle-owner-scope 1.2a — корень процесса с барьерами, stop() = cancel(), один …
  08b2251 2026-09-30 test: снять недействующие pytest.mark.timeout по репо (R-6)
Находки (7):
  warning P1_IMPL_NOT_INHERITING module:app_module ManifestStore>ManifestStoreProtocol
  warning P2_DOCSTRING module:app_module DiscoveryResult.service_names
  warning P2_DOCSTRING module:app_module ManifestStore.path
  warning P2_DOCSTRING module:app_module ManifestStoreProtocol.read_raw
  warning P2_DOCSTRING module:app_module ManifestStoreProtocol.update
  info INTERFACE_WITHOUT_TEST interface:app_module:LauncherFactory -
  info INTERFACE_WITHOUT_TEST interface:app_module:ThrottleRules -
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 43, из них тестов 34
  apps/line_sim/run.py:20
  backend_ctl/probes/probe_observability_consumer_acceptance.py:114
  examples/minimal_app/run.py:19
  multiprocess_prototype/backend/config/manifest.py:132
  multiprocess_prototype/backend/launch.py:476
  multiprocess_prototype/backend/orchestrator_hooks.py:24
  multiprocess_prototype/frontend/app.py:968
  multiprocess_prototype/main.py:123
  multiprocess_prototype/orchestrator.py:26
  тесты: 34 файлов, первые 3: Plugins/sim/robot_host/tests/test_v2_one_app_smoke.py, Plugins/sim/scene_source/tests/test_acceptance_c87_live_step.py, apps/line_sim/tests/test_f1_task11_acceptance.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 1
  П2 docstring Google у публичного API: 31 из 35
  П3 __all__ у interfaces.py и __init__.py: 2 из 2
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 2 из 2
````

### card base_manager

Команда: `atlas card base_manager`

````text
Модуль base_manager — framework, ярус core
Назначение: Базовый менеджер: жизненный цикл, адаптеры, наблюдаемость; сюда — менять фундамент всех менеджеров
API (10): CloseReport, IBaseAdapter, IBaseManager, IHandle, IObservableMixin, IScope, Reporter, Resource, ScopeClosedError, Stoppable
Открытые задачи (3 планов, 46 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  observation-port — 2: 0.2, 2.4
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
Коммиты (53 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  751ba0d 2026-10-21 merge: feat/lifecycle-executor-manager в main — Task 1.9m, ExecutorManager
  f2268be 2026-10-13 merge: lifecycle-owner-scope — хвосты 1.2b в документах и закрытие плана на достигнутом
  4bd81f4 2026-10-13 merge: lifecycle-owner-scope 1.2b-3 — Services и прототип на _on_shutdown, принуждение Р1…
  427c3cb 2026-10-13 merge: lifecycle-owner-scope 1.2b-ki — BaseException в scope.close() не отменяет _on_shut…
Находки (8):
  warning P1_IMPL_NOT_INHERITING module:base_manager BaseAdapter>IBaseAdapter
  warning P1_IMPL_NOT_INHERITING module:base_manager Handle>IHandle
  warning P1_IMPL_NOT_INHERITING module:base_manager Scope>IScope
  warning P2_DOCSTRING module:base_manager ObservableMixin.log_critical
  warning P2_DOCSTRING module:base_manager ObservableMixin.log_debug
  warning P2_DOCSTRING module:base_manager ObservableMixin.log_error
  warning P2_DOCSTRING module:base_manager ObservableMixin.log_info
  warning P2_DOCSTRING module:base_manager ObservableMixin.log_warning
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 117, из них тестов 63
  Plugins/hub/device_hub/plugin.py:28
  Services/auth/audit_writer.py:35
  Services/auth/manager.py:33
  Services/code_reader/tools/thread_split_probe.py:37
  Services/device_hub/drivers/base.py:21
  Services/device_hub/drivers/robot_driver_v2/driver.py:72
  Services/device_hub/drivers/robot_driver_v2/state.py:19
  Services/device_hub/manager.py:21
  Services/sql/core/sql_manager.py:15
  backend_ctl/probes/probe_c2_error_route.py:72
  … ещё 44
  тесты: 63 файлов, первые 3: Plugins/calibration/camera_robot/tests/test_v2_driver_contract.py, Plugins/hub/device_hub/tests/test_c60b_hook_acceptance.py, Plugins/hub/device_hub/tests/test_hub_request_stop_hook.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 60 из 63
  П2 docstring Google у публичного API: 95 из 100
  П3 __all__ у interfaces.py и __init__.py: 11 из 11
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card chain_module

Команда: `atlas card chain_module`

````text
Модуль chain_module — framework, ярус core
Назначение: Движок исполнения цепочек и DAG-pipeline, в т.ч. между процессами; сюда — менять порядок и шаги исполнения
API (7): IChainLogger, IChainRunnable, IExecutionStep, INodeConnection, IRemoteExecutable, IStepNode, IStepNodeWithWorker
Открытые задачи (2 планов, 33 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  telemetry-stage6 — 2: 1.2, 3.5
Коммиты (18 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  4bd81f4 2026-10-13 merge: lifecycle-owner-scope 1.2b-3 — Services и прототип на _on_shutdown, принуждение Р1…
  005df13 2026-10-13 merge: lifecycle-owner-scope 1.2b-2 — кодмод 23 классов в _on_shutdown, срок второго вызо…
  cda5e12 2026-08-13 feat(framework): 2.2 — пределы у плоскости stats до доставки
  e83b0bf 2026-07-25 feat(framework): ярусная карта модулей + публичный API-контракт (Ф8 H.1, NEW-10)
Находки (21):
  warning P1_IMPL_NOT_INHERITING module:chain_module ChainThreadPool>IChainLogger
  warning P1_IMPL_NOT_INHERITING module:chain_module LatencyTracker>IChainLogger
  warning P1_IMPL_NOT_INHERITING module:chain_module WorkerPoolDispatcher>IChainLogger
  warning P1_IMPL_NOT_INHERITING module:chain_module WorkerPoolExecutor>IChainLogger
  warning P2_DOCSTRING module:chain_module ChainRunnable.steps
  warning P2_DOCSTRING module:chain_module DagRunnable.steps
  warning P2_DOCSTRING module:chain_module IChainLogger.log_error
  warning P2_DOCSTRING module:chain_module IChainLogger.log_info
  warning P2_DOCSTRING module:chain_module IChainLogger.log_warning
  warning P2_DOCSTRING module:chain_module IRunnableChain.execute
  … ещё 11
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 5, из них тестов 3
  multiprocess_framework/__init__.py:129
  multiprocess_framework/modules/process_module/generic/pipeline_executor.py:22
  тесты: 3 файлов, первые 3: multiprocess_framework/modules/process_module/tests/test_pipeline_chain_engine.py, multiprocess_framework/modules/tests/test_manager_shutdown_1_2b_2_acceptance.py, multiprocess_framework/modules/tests/test_manager_shutdown_1_2b_2_hazards.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 4
  П2 docstring Google у публичного API: 48 из 60
  П3 __all__ у interfaces.py и __init__.py: 7 из 7
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card channel_routing_module

Команда: `atlas card channel_routing_module`

````text
Модуль channel_routing_module — framework, ярус core
Назначение: Базовая маршрутизация по каналам для роутера, логгера и ошибок; сюда — менять общую логику каналов
API (6): IBufferStrategy, IChannel, IChannelRoutingManager, Outcome, channel_accepted, outcome_of
Открытые задачи (4 планов, 48 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  observation-port — 2: 0.2, 2.4
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
  telemetry-stage6 — 2: 1.2, 3.5
Коммиты (53 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  4bd81f4 2026-10-13 merge: lifecycle-owner-scope 1.2b-3 — Services и прототип на _on_shutdown, принуждение Р1…
  005df13 2026-10-13 merge: lifecycle-owner-scope 1.2b-2 — кодмод 23 классов в _on_shutdown, срок второго вызо…
  b7babad 2026-09-08 merge: observability-closure (fcfbbdf7) в main — Ф0-Ф3 и две задачи Ф4 доставлены полосам
  9245c73 2026-09-07 fix(framework): голос о смене смысла stats.enabled переехал с разбора на действие
Находки (34):
  warning P2_DOCSTRING module:channel_routing_module AsyncSenderBuffer.stats
  warning P2_DOCSTRING module:channel_routing_module BoundedChannel.capacity
  warning P2_DOCSTRING module:channel_routing_module BoundedChannel.channel_type
  warning P2_DOCSTRING module:channel_routing_module BoundedChannel.name
  warning P2_DOCSTRING module:channel_routing_module DirectBuffer.stats
  warning P2_DOCSTRING module:channel_routing_module ErrorLike.record_error
  warning P2_DOCSTRING module:channel_routing_module ErrorLike.track_error
  warning P2_DOCSTRING module:channel_routing_module LoggerLike.critical
  warning P2_DOCSTRING module:channel_routing_module LoggerLike.debug
  warning P2_DOCSTRING module:channel_routing_module LoggerLike.error
  … ещё 24
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 84, из них тестов 52
  Plugins/io/otel_export/plugin.py:87
  Services/otel_export/config.py:24
  Services/otel_export/mapping.py:53
  backend_ctl/driver.py:53
  backend_ctl/protocol.py:29
  multiprocess_framework/__init__.py:47
  multiprocess_framework/modules/base_manager/mixins/observable_mixin.py:468
  multiprocess_framework/modules/error_module/core/error_manager.py:30
  multiprocess_framework/modules/logger_module/__init__.py:39
  multiprocess_framework/modules/logger_module/channels/router_push_channel.py:27
  … ещё 22
  тесты: 52 файлов, первые 3: backend_ctl/tests/test_driver.py, backend_ctl/tests/test_stop_summary_live.py, backend_ctl/tests/test_task_3_5_hazards.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 16 из 16
  П2 docstring Google у публичного API: 81 из 113
  П3 __all__ у interfaces.py и __init__.py: 5 из 6
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card command_module

Команда: `atlas card command_module`

````text
Модуль command_module — framework, ярус core
Назначение: Менеджер команд над dispatch_module: регистрация обработчиков по имени; сюда — менять приём команд
API (1): ICommandManager
Открытые задачи (3 планов, 41 задач):
  backend-ctl-proof-discipline — 8: 0.1, 0.2, 1.1, 1.2, 1.3, 1.4, … ещё 2
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  telemetry-stage6 — 2: 1.2, 3.5
Коммиты (17 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  751ba0d 2026-10-21 merge: feat/lifecycle-executor-manager в main — Task 1.9m, ExecutorManager
  6c4fc76 2026-10-21 merge: feat/lifecycle-keyed-executor в main — Task 1.9a, KeyedExecutor и развилка «на мес…
  005df13 2026-10-13 merge: lifecycle-owner-scope 1.2b-2 — кодмод 23 классов в _on_shutdown, срок второго вызо…
  97564e4 2026-09-05 docs(plans): Task 3.2 ПРИНЯТА 8.5/10 — пять условий ревью закрыты
Находки (5):
  warning P2_DOCSTRING module:command_module BaseCommandManager.get_command_info
  warning P2_DOCSTRING module:command_module BaseCommandManager.get_commands
  warning P2_DOCSTRING module:command_module BaseCommandManager.handle_command
  warning P2_DOCSTRING module:command_module BaseCommandManager.overwrite_command
  warning P2_DOCSTRING module:command_module BaseCommandManager.register_command
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 22, из них тестов 17
  multiprocess_framework/__init__.py:80
  multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:22
  multiprocess_framework/modules/process_module/configs/managers_config.py:18
  multiprocess_framework/modules/process_module/managers/process_managers.py:213
  multiprocess_framework/modules/router_module/core/router_manager.py:1377
  тесты: 17 файлов, первые 3: Plugins/hub/device_hub/tests/test_robot_v2_commands_acceptance.py, Plugins/hub/device_hub/tests/test_spi_commands_acceptance.py, Plugins/hub/device_hub/tests/test_t54_calib_commands_acceptance.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 1 из 1
  П2 docstring Google у публичного API: 29 из 34
  П3 __all__ у interfaces.py и __init__.py: 5 из 5
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card config_module

Команда: `atlas card config_module`

````text
Модуль config_module — framework, ярус core
Назначение: Управление конфигурациями в рантайме: схемы, контейнер, менеджер; сюда — менять загрузку и хранение конфигов
API (3): IConfig, IConfigManager, IConfigObserver
Открытые задачи (2 планов, 32 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  truth-holes-closure — 1: 1.3
Коммиты (27 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  005df13 2026-10-13 merge: lifecycle-owner-scope 1.2b-2 — кодмод 23 классов в _on_shutdown, срок второго вызо…
  b0b6a2a 2026-10-12 merge: lifecycle-owner-scope 1.2b-1 — шаблонный shutdown() и scope в BaseManager
  3af1d51 2026-10-08 Merge pull request #27 from TWOKRAI/claude/upbeat-rubin-h6gl6i
  541002d 2026-10-08 fix(framework): k0 1.2 — watcher применяет итоговую запись после отброшенного события
Находки (2):
  warning P1_IMPL_NOT_INHERITING module:config_module Config>IConfig
  warning P2_DOCSTRING module:config_module ConfigManager.initialize
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 31, из них тестов 12
  multiprocess_framework/__init__.py:69
  multiprocess_framework/modules/app_module/orchestrator.py:433
  multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:454
  multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:18
  multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:23
  multiprocess_framework/modules/process_module/commands/builtin_commands.py:4178
  multiprocess_framework/modules/process_module/configs/process_config_handler.py:13
  multiprocess_framework/modules/process_module/generic/data_receiver.py:82
  multiprocess_framework/modules/process_module/generic/perf_probes.py:25
  multiprocess_framework/modules/process_module/generic/plugin_runner.py:42
  … ещё 9
  тесты: 12 файлов, первые 3: multiprocess_framework/modules/app_module/tests/test_observability_watcher_events.py, multiprocess_framework/modules/app_module/tests/test_observability_watcher_flight.py, multiprocess_framework/modules/process_manager_module/tests/test_process_manager_process.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 1 из 2
  П2 docstring Google у публичного API: 46 из 47
  П3 __all__ у interfaces.py и __init__.py: 7 из 7
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card console_module

Команда: `atlas card console_module`

````text
Модуль console_module — framework, ярус core
Назначение: Менеджер терминальных окон процесса: показ, перехват вывода, ввод; сюда — менять консоль процесса
API (2): IConsoleManager, IPlatformConsole
Открытые задачи (1 планов, 31 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
Коммиты (10 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  5df91c4 2026-11-01 merge: console-detach — WindowsConsole не отсоединяет процесс от чужой консоли, тесты бол…
  005df13 2026-10-13 merge: lifecycle-owner-scope 1.2b-2 — кодмод 23 классов в _on_shutdown, срок второго вызо…
  e83b0bf 2026-07-25 feat(framework): ярусная карта модулей + публичный API-контракт (Ф8 H.1, NEW-10)
  d9dddf4 2026-07-19 refactor(framework): переместить ConsoleProcessConfig console_module → process_module (Фа…
Находки (22):
  warning P2_DOCSTRING module:console_module ConsoleAdapter.is_initialized
  warning P2_DOCSTRING module:console_module ConsoleLogChannel.channel_type
  warning P2_DOCSTRING module:console_module ConsoleLogChannel.close
  warning P2_DOCSTRING module:console_module ConsoleLogChannel.get_info
  warning P2_DOCSTRING module:console_module ConsoleLogChannel.name
  warning P2_DOCSTRING module:console_module ConsoleLogChannel.write
  warning P2_DOCSTRING module:console_module ConsoleManager.close_console
  warning P2_DOCSTRING module:console_module ConsoleManager.create_console
  warning P2_DOCSTRING module:console_module ConsoleManager.get_debug_info
  warning P2_DOCSTRING module:console_module ConsoleManager.get_stats
  … ещё 12
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 6, из них тестов 1
  multiprocess_framework/__init__.py:89
  multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:24
  multiprocess_framework/modules/process_module/configs/console_process_config.py:12
  multiprocess_framework/modules/process_module/configs/managers_config.py:19
  multiprocess_framework/modules/process_module/managers/process_managers.py:214
  тесты: 1 файлов, первые 3: multiprocess_framework/modules/statistics_module/tests/test_limits_acceptance.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 3 из 3
  П2 docstring Google у публичного API: 39 из 60
  П3 __all__ у interfaces.py и __init__.py: 8 из 8
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card data_schema_module

Команда: `atlas card data_schema_module`

````text
Модуль data_schema_module — framework, ярус core
Назначение: Ядро описания структур данных на Pydantic: схемы, поля, маршрутизация; сюда — менять схемы и валидацию
API (17): HasBuild, IAsyncRegisterStorage, IAsyncSchemaStorage, IDataConverter, IDataValidator, IDocumentationFormatter, IRegisterStorage, ISchema, ISchemaAdapter, ISchemaDocumentationGenerator, ISchemaManager, ISchemaRegistry, ISchemaStorage, ISchemaVisualizer, IStorageManager, IVersionManager, IVisualizationFormatter
Открытые задачи (5 планов, 64 задач):
  observation-port — 2: 0.2, 2.4
  gui-service — 11: 1.4, 1b.2b, 1b.2c, 1b.3, 1b.4, 2.1, … ещё 5
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  frontend-constructor — 18: T2.0, T3.0, T3.1, T3.2, T3.3, T3.4, … ещё 12
  telemetry-stage6 — 2: 1.2, 3.5
Коммиты (36 всего, последние 5):
  f2304d4 2026-11-24 merge: fix/lane-t-win-baseline — красные Windows/Python 3.12 исправлены по причине, отчёт…
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  c5f5446 2026-11-01 merge: W1b — ядро camera_device, FieldMeta.apply/enabled_if, ADR-CAM
  68fb2e6 2026-10-02 chore(merge): Task 5.5 — зелёный набор фреймворка и гейт /dev:ship в main
  a6984d4 2026-10-02 refactor(data_schema): refusal_text — публичный вход модуля, без приватного импорта
Находки (44):
  warning P2_DOCSTRING module:data_schema_module HasBuild.build
  warning P2_DOCSTRING module:data_schema_module IAsyncSchemaStorage.delete
  warning P2_DOCSTRING module:data_schema_module IAsyncSchemaStorage.exists
  warning P2_DOCSTRING module:data_schema_module IAsyncSchemaStorage.load
  warning P2_DOCSTRING module:data_schema_module IAsyncSchemaStorage.save
  warning P2_DOCSTRING module:data_schema_module ISchema.get_all_fields_meta
  warning P2_DOCSTRING module:data_schema_module ISchema.get_field_meta
  warning P2_DOCSTRING module:data_schema_module ISchema.model_dump
  warning P2_DOCSTRING module:data_schema_module ISchema.update_field
  warning P2_DOCSTRING module:data_schema_module ISchema.validate_field
  … ещё 34
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 134, из них тестов 42
  Plugins/io/database/schemas.py:24
  Plugins/io/telemetry_sink/schemas.py:15
  Plugins/utility/pilot_widgets/registers.py:17
  Services/auth/crypto/policies.py:16
  Services/auth/models.py:25
  Services/camera_device/params.py:23
  Services/documents/schema.py:18
  Services/hikvision_camera/plugin/config.py:7
  Services/hikvision_camera/plugin/registers.py:12
  Services/robot_comm/core/params_v2.py:12
  … ещё 82
  тесты: 42 файлов, первые 3: Services/camera_device/tests/test_params.py, Services/camera_device/tests/test_params_hazards.py, Services/camera_device/tests/test_plugin_base_hazards.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 200 из 225
  П3 __all__ у interfaces.py и __init__.py: 21 из 21
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 5
````

### card dispatch_module

Команда: `atlas card dispatch_module`

````text
Модуль dispatch_module — framework, ярус core
Назначение: Диспетчеризация входящих сообщений к обработчикам внутри процесса; сюда — менять стратегии обработки
API (2): DispatchStrategy, IDispatcher
Открытые задачи (2 планов, 33 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  telemetry-stage6 — 2: 1.2, 3.5
Коммиты (19 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  005df13 2026-10-13 merge: lifecycle-owner-scope 1.2b-2 — кодмод 23 классов в _on_shutdown, срок второго вызо…
  97564e4 2026-09-05 docs(plans): Task 3.2 ПРИНЯТА 8.5/10 — пять условий ревью закрыты
  757a2d4 2026-09-05 feat(observability): Task 3.2 К2 — сводка регистрации одной INFO-строкой (вердикт CTO)
  1320868 2026-09-05 feat(observability): Task 3.2 — болтовня регистрации на DEBUG, BUSINESS уходит из system.…
Находки (13):
  warning P1_IMPL_NOT_INHERITING module:dispatch_module Dispatcher>IDispatcher
  warning P2_DOCSTRING module:dispatch_module BaseDispatcher.dispatch
  warning P2_DOCSTRING module:dispatch_module BaseDispatcher.get_all_handlers
  warning P2_DOCSTRING module:dispatch_module BaseDispatcher.get_handler_info
  warning P2_DOCSTRING module:dispatch_module BaseDispatcher.get_handlers_by_tag
  warning P2_DOCSTRING module:dispatch_module BaseDispatcher.overwrite_handler
  warning P2_DOCSTRING module:dispatch_module BaseDispatcher.register_handler
  warning P2_DOCSTRING module:dispatch_module BaseDispatcher.update_expects_full_message
  warning P2_DOCSTRING module:dispatch_module BaseDispatcher.update_handler_efficiency
  warning P2_DOCSTRING module:dispatch_module BaseDispatcher.update_handler_function
  … ещё 3
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 8, из них тестов 5
  multiprocess_framework/__init__.py:49
  multiprocess_framework/modules/command_module/core/command_manager.py:16
  multiprocess_framework/modules/router_module/core/router_manager.py:18
  тесты: 5 файлов, первые 3: multiprocess_framework/modules/channel_routing_module/tests/test_task_3_2_boot_chatter_store.py, multiprocess_framework/modules/command_module/tests/test_command_manager.py, multiprocess_framework/modules/logger_module/tests/test_declared_source_names.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 1
  П2 docstring Google у публичного API: 53 из 64
  П3 __all__ у interfaces.py и __init__.py: 6 из 6
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card display_module

Команда: `atlas card display_module`

````text
Модуль display_module — framework, ярус optional
Назначение: Реестр именованных SHM-каналов для вывода кадров; сюда — менять каналы отображения кадров
API (3): DisplayEntry, IDisplayChannel, IDisplayRegistry
Открытые задачи (1 планов, 31 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
Коммиты (5 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  e83b0bf 2026-07-25 feat(framework): ярусная карта модулей + публичный API-контракт (Ф8 H.1, NEW-10)
  9d459fe 2026-06-07 Merge feat/displays-in-recipe: дисплеи как часть рецепта
  b7fa95d 2026-05-25 Merge branch 'feat/displays-tab' into main
  cce2ade 2026-05-25 Merge chore/devseed-update-2026-05 into main
Находки (4):
  warning P1_IMPL_NOT_INHERITING module:display_module DisplayRegistry>IDisplayRegistry
  warning P4_DIRECT_WRITE module:display_module multiprocess_framework/modules/display_module/registry.py::DisplayRegistry.persist
  info INTERFACE_WITHOUT_TEST interface:display_module:IDisplayChannel -
  info INTERFACE_WITHOUT_TEST interface:display_module:IDisplayRegistry -
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 15, из них тестов 6
  multiprocess_prototype/adapters/catalogs/display_catalog.py:25
  multiprocess_prototype/backend/config/displays_loader.py:21
  multiprocess_prototype/backend/displays/blueprint_binding.py:27
  multiprocess_prototype/backend/orchestrator_hooks.py:243
  multiprocess_prototype/backend/state/adapters/display_state_adapter.py:22
  multiprocess_prototype/frontend/app.py:359
  multiprocess_prototype/frontend/app_services_factory.py:53
  multiprocess_prototype/frontend/widgets/displays/preview_window.py:36
  multiprocess_prototype/frontend/widgets/tabs/displays/tab.py:745
  тесты: 6 файлов, первые 3: multiprocess_prototype/adapters/tests/conftest.py, multiprocess_prototype/adapters/tests/test_recipe_canonical.py, multiprocess_prototype/backend/displays/tests/test_blueprint_binding.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 1
  П2 docstring Google у публичного API: 22 из 22
  П3 __all__ у interfaces.py и __init__.py: 2 из 2
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 1
````

### card error_module

Команда: `atlas card error_module`

````text
Модуль error_module — framework, ярус core
Назначение: Менеджер ошибок на базе логгера: каналы по уровням, traceback; сюда — менять обработку и запись ошибок
API (6): DeviceOpenFailed, FrameworkFailure, IErrorManager, ObservabilityMisuse, ResourceUnavailable, SubsystemStartFailed
Открытые задачи (3 планов, 45 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
  ULTRACODE_BACKLOG — 1: T1
Коммиты (20 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  2172288 2026-09-01 fix(observability): находки ревью Task 1.3b — 2 major, 3 minor закрыты
  1619de7 2026-09-01 feat(observability): Task 1.3b — 46 адресов на один разъём; классы отказа; разводка имён …
  1e3c60c 2026-08-31 feat(observability): Task 1.3b — одна дверь «факт + голос»; типы отказов; тотальный _trac…
  b1179d5 2026-08-31 feat(observability): Task 1.3a — факт всегда, голос по окну; HealthState стал видом
Находки (1):
  warning P2_DOCSTRING module:error_module ErrorManager.initialize
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 50, из них тестов 37
  Plugins/hub/device_hub/plugin.py:30
  Plugins/io/robot_draw/plugin.py:22
  Plugins/io/robot_io/plugin.py:21
  Plugins/sources/capture/plugin.py:14
  backend_ctl/probes/probe_c2_error_route.py:43
  multiprocess_framework/__init__.py:60
  multiprocess_framework/modules/base_manager/mixins/observable_mixin.py:650
  multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:213
  multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:25
  multiprocess_framework/modules/process_manager_module/process/topology_manager.py:36
  … ещё 3
  тесты: 37 файлов, первые 3: Plugins/hub/device_hub/tests/test_failure_classes_device_hub_acceptance.py, Plugins/io/robot_io/tests/test_c104_dropped_job_visible_acceptance.py, backend_ctl/tests/test_overview.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 1 из 1
  П2 docstring Google у публичного API: 16 из 17
  П3 __all__ у interfaces.py и __init__.py: 4 из 4
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card event_module

Команда: `atlas card event_module`

````text
Модуль event_module — framework, ярус optional
Назначение: Типизированная шина событий-фактов внутри процесса; сюда — менять подписки и публикацию событий
API (2): EventBusProtocol, Subscription
Открытые задачи: нет
Коммиты (11 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  1392d49 2026-10-06 fix: T1 гейт — логгер через get_std_logger в lifetime/subscribers/qt_lifetime
  4081dfe 2026-10-06 test: T1 C1 — тесты возвращают состояние gc через paused_gc(), не gc.enable()
  a2d027d 2026-10-05 fix(base_manager): ревью 0.3 р1 — третий вид после _done.set(), проверка владельца в add
  693a568 2026-10-05 test(event_module): ревью 0.3 р1 — красные на п.3 и п.5
Находки (5):
  warning P1_IMPL_NOT_INHERITING module:event_module EventBus>EventBusProtocol
  warning P1_IMPL_NOT_INHERITING module:event_module _Subscription>Subscription
  warning P2_DOCSTRING module:event_module Subscribers.emits_after_close
  warning P2_DOCSTRING module:event_module Subscribers.error_count
  warning P2_DOCSTRING module:event_module Subscribers.errors
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 4, из них тестов 1
  multiprocess_framework/modules/frontend_module/qt_event_bridge.py:53
  multiprocess_prototype/domain/event_bus.py:16
  multiprocess_prototype/domain/protocols/event_bus.py:14
  тесты: 1 файлов, первые 3: multiprocess_framework/modules/frontend_module/tests/test_qt_event_bridge.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 2
  П2 docstring Google у публичного API: 11 из 14
  П3 __all__ у interfaces.py и __init__.py: 2 из 2
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card frontend_module

Команда: `atlas card frontend_module`

````text
Модуль frontend_module — framework, ярус optional
Назначение: UI-фреймворк: конструктор PySide6-приложений из виджетов и регистров; сюда — менять GUI-каркас
API (25): AccessContextSource, AppIdentity, DEFAULT_TRACKED_SUFFIXES, IConfigurableWidget, IFrontendManager, IRegistersManager, IRegistersManagerGui, IRouterLike, ISignalProvider, IWidgetFactory, IWidgetRegistry, IWindowRegistry, LazyTab, PlaceholderFactory, QThreadHandle, QtTreeMismatch, SupportsCommandMessage, TabRegistry, TabSpec, TelemetryHistorySource, … ещё 5
Открытые задачи (9 планов, 94 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  frontend-constructor — 18: T2.0, T3.0, T3.1, T3.2, T3.3, T3.4, … ещё 12
  observation-port — 2: 0.2, 2.4
  telemetry-stage6 — 2: 1.2, 3.5
  backend-ctl-framework-module — 10: 1.1, 1.2, 2.1, 2.2, 2.3, 2.4, … ещё 4
  … ещё 4 планов
Коммиты (87 всего, последние 5):
  47e9778 2026-11-24 merge: тракт кадров gui — ящик, насос, метрики, дешёвый кадр, отложенная копия T5, штампы…
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  005df13 2026-10-13 merge: lifecycle-owner-scope 1.2b-2 — кодмод 23 классов в _on_shutdown, срок второго вызо…
  c2afd1f 2026-10-06 fix(process): T1 ревью р2 — install внутри suspend не теряет политику, откат gen2 как в C…
  e913c68 2026-10-06 test(frontend): T1 р2 — приложение в тесте отказа attach живёт и умирает на своём потоке
Находки (18):
  warning P1_IMPL_NOT_INHERITING module:frontend_module FrontendManager>IFrontendManager
  warning P2_DOCSTRING module:frontend_module TelemetryHistorySource.allowed_metrics
  warning P2_DOCSTRING module:frontend_module TelemetryHistorySource.db_path
  warning P4_DIRECT_WRITE module:frontend_module multiprocess_framework/modules/frontend_module/managers/config_snapshot_manager.py::ConfigSnapshotManager._write_yaml
  warning P4_DIRECT_WRITE module:frontend_module multiprocess_framework/modules/frontend_module/managers/theme_presets_manager.py::ThemePresetsManager._save
  warning P4_DIRECT_WRITE module:frontend_module multiprocess_framework/modules/frontend_module/managers/yaml_persistence_store.py::YamlPersistenceStore._write_raw
  info INTERFACE_WITHOUT_TEST interface:frontend_module:AccessContextSource -
  info INTERFACE_WITHOUT_TEST interface:frontend_module:IConfigurableWidget -
  info INTERFACE_WITHOUT_TEST interface:frontend_module:IFrontendManager -
  info INTERFACE_WITHOUT_TEST interface:frontend_module:IRegistersManager -
  … ещё 8
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 99, из них тестов 28
  Services/robot_comm/gui/line_source.py:35
  multiprocess_framework/modules/frontend_module/components/_examples/checkbox/schemas.py:13
  multiprocess_framework/modules/frontend_module/components/_examples/combo/schemas.py:13
  multiprocess_framework/modules/frontend_module/components/_examples/compound_mixed/schemas.py:11
  multiprocess_framework/modules/frontend_module/components/_examples/compound_numeric/schemas.py:11
  multiprocess_framework/modules/frontend_module/components/_examples/group/schemas.py:11
  multiprocess_framework/modules/frontend_module/components/_examples/label/schemas.py:9
  multiprocess_framework/modules/frontend_module/components/_examples/numeric/schemas.py:13
  multiprocess_framework/modules/frontend_module/components/_examples/slider/schemas.py:13
  multiprocess_framework/modules/frontend_module/components/_examples/spinbox/schemas.py:11
  … ещё 61
  тесты: 28 файлов, первые 3: Services/robot_comm/tests/test_t38_line_view_acceptance.py, multiprocess_framework/modules/router_module/tests/test_t47c_ring_default.py, multiprocess_prototype/frontend/actions/middleware/tests/test_pre_auth_guard.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 1 из 2
  П2 docstring Google у публичного API: 57 из 59
  П3 __all__ у interfaces.py и __init__.py: 13 из 13
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 3
````

### card logger_module

Команда: `atlas card logger_module`

````text
Модуль logger_module — framework, ярус core
Назначение: Менеджер логирования: каналы записи, сбор логов процессов; сюда — менять вывод и хранение логов
API (5): ILogChannel, ILoggerManager, LogLevel, LogScope, ScopeName
Открытые задачи (7 планов, 68 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
  telemetry-stage6 — 2: 1.2, 3.5
  ULTRACODE_BACKLOG — 1: T1
  backend-ctl-proof-discipline — 8: 0.1, 0.2, 1.1, 1.2, 1.3, 1.4, … ещё 2
  … ещё 2 планов
Коммиты (61 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  4bd81f4 2026-10-13 merge: lifecycle-owner-scope 1.2b-3 — Services и прототип на _on_shutdown, принуждение Р1…
  005df13 2026-10-13 merge: lifecycle-owner-scope 1.2b-2 — кодмод 23 классов в _on_shutdown, срок второго вызо…
  1392d49 2026-10-06 fix: T1 гейт — логгер через get_std_logger в lifetime/subscribers/qt_lifetime
  9d8e5df 2026-10-05 merge: main в feat/lifecycle-owner-scope перед ревью Task 0.2 и стартом 0.3/0.4
Находки (24):
  warning P1_IMPL_NOT_INHERITING module:logger_module RouterPushChannel>ILogChannel
  warning P2_DOCSTRING module:logger_module ConsoleChannel.write
  warning P2_DOCSTRING module:logger_module ErrorFloor.close
  warning P2_DOCSTRING module:logger_module ErrorFloor.path
  warning P2_DOCSTRING module:logger_module HttpChannel.write
  warning P2_DOCSTRING module:logger_module LogChannel.channel_type
  warning P2_DOCSTRING module:logger_module LogChannel.close
  warning P2_DOCSTRING module:logger_module LogChannel.name
  warning P2_DOCSTRING module:logger_module LogChannel.write
  warning P2_DOCSTRING module:logger_module RouterPushChannel.channel_type
  … ещё 14
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 287, из них тестов 110
  Plugins/io/otel_export/plugin.py:92
  Plugins/runtime/chain_executor/plugin.py:20
  Plugins/runtime/worker_pool/plugin.py:16
  Services/code_reader/core/sdk_reader.py:28
  Services/dataset_gen/core/realcut.py:21
  Services/device_hub/drivers/base.py:22
  Services/device_hub/drivers/exchange_log.py:44
  Services/device_hub/manager.py:23
  Services/hikvision_camera/sdk/bindings.py:12
  Services/ml_inference/backends/base.py:11
  … ещё 167
  тесты: 110 файлов, первые 3: Plugins/control/robot_control/tests/test_flight_dump_emitter.py, Plugins/control/robot_control/tests/test_trace_id_guard_usage.py, Plugins/control/robot_control/tests/test_trace_id_outside_message_text_acceptance.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 11 из 12
  П2 docstring Google у публичного API: 60 из 79
  П3 __all__ у interfaces.py и __init__.py: 6 из 6
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 2
````

### card message_module

Команда: `atlas card message_module`

````text
Модуль message_module — framework, ярус core
Назначение: Транспортный протокол сообщений между менеджерами и процессами; сюда — менять формат сообщений
API (1): IMessage
Открытые задачи (2 планов, 40 задач):
  transport-router-hub — 9: P0.1, P0.2, P0.3, P1.1, P1.2, P1.3, … ещё 3
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
Коммиты (17 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  6b47bd0 2026-10-08 Merge pull request #25 from TWOKRAI/claude/kind-bohr-8tf51g
  e83b0bf 2026-07-25 feat(framework): ярусная карта модулей + публичный API-контракт (Ф8 H.1, NEW-10)
  8cce529 2026-07-13 Merge branch 'feat/constructor-f7': G.2 — kind-каналы за флагом, единый конверт команд, м…
  7a58c0a 2026-07-11 Merge branch 'docs/plans-single-queue': единая очередь задач — QUEUE.md строгая последова…
Находки (3):
  warning P1_IMPL_NOT_INHERITING module:message_module Message>IMessage
  warning P2_DOCSTRING module:message_module CommandMessageSchema.get_schema_info
  warning P2_DOCSTRING module:message_module LogMessageSchema.get_schema_info
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 24, из них тестов 7
  Plugins/hub/device_hub/client.py:115
  Plugins/io/otel_export/plugin.py:94
  backend_ctl/driver.py:42
  multiprocess_framework/__init__.py:41
  multiprocess_framework/modules/frontend_module/bridge/command_sender.py:15
  multiprocess_framework/modules/frontend_module/bridge/remote_command_sender.py:53
  multiprocess_framework/modules/process_manager_module/process/pre_stop.py:31
  multiprocess_framework/modules/process_manager_module/topology/blueprint.py:682
  multiprocess_framework/modules/process_module/commands/builtin_commands.py:4155
  multiprocess_framework/modules/process_module/communication/process_communication.py:17
  … ещё 7
  тесты: 7 файлов, первые 3: backend_ctl/tests/test_system_shutdown_driver_envelope.py, multiprocess_framework/modules/frontend_module/tests/test_remote_command_sender.py, multiprocess_framework/modules/process_manager_module/tests/test_supervision_status_system_stop.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 1
  П2 docstring Google у публичного API: 82 из 84
  П3 __all__ у interfaces.py и __init__.py: 12 из 12
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card process_manager_module

Команда: `atlas card process_manager_module`

````text
Модуль process_manager_module — framework, ярус core
Назначение: Оркестратор процессов: запуск системы, реестр, приоритеты, мониторинг; сюда — менять управление процессами
API (3): IProcessManagerProcess, IProcessRegistry, ISystemLauncher
Открытые задачи (10 планов, 70 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  recipe-orchestrator-unify — 4: 1.2, 2.0, 2.1, 2.3
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
  observation-port — 2: 0.2, 2.4
  telemetry-stage6 — 2: 1.2, 3.5
  … ещё 5 планов
Коммиты (174 всего, последние 5):
  47e9778 2026-11-24 merge: тракт кадров gui — ящик, насос, метрики, дешёвый кадр, отложенная копия T5, штампы…
  c27a8e2 2026-11-24 merge: docs/camera-4.2d-4.2e-status — рецепт hikvision_id3013_quad (4.2i): две камеры MVS…
  e1e4288 2026-11-24 merge: docs/camera-4.2d-4.2e-status — рецепт hikvision_id3013_view (4.2g): камера MVS + д…
  5680c9c 2026-11-24 merge: docs/camera-4.2d-4.2e-status — тестовый рецепт hikvision_id3013_test (4.2f), оценк…
  f2304d4 2026-11-24 merge: fix/lane-t-win-baseline — красные Windows/Python 3.12 исправлены по причине, отчёт…
Находки (17):
  warning P1_IMPL_NOT_INHERITING module:process_manager_module ProcessManagerProcess>IProcessManagerProcess
  warning P1_IMPL_NOT_INHERITING module:process_manager_module ProcessRegistry>IProcessRegistry
  warning P1_IMPL_NOT_INHERITING module:process_manager_module SystemLauncher>ISystemLauncher
  warning P2_DOCSTRING module:process_manager_module ProcessMonitor.get_stats
  warning P2_DOCSTRING module:process_manager_module ProcessMonitor.start
  warning P2_DOCSTRING module:process_manager_module ProcessRegistry.add_process
  warning P2_DOCSTRING module:process_manager_module ProcessRegistry.create_and_register
  warning P2_DOCSTRING module:process_manager_module ProcessRegistry.get_process_by_name
  warning P2_DOCSTRING module:process_manager_module ProcessRegistry.remove_process
  warning P2_DOCSTRING module:process_manager_module ProcessRegistry.start_all
  … ещё 7
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 68, из них тестов 52
  backend_ctl/endpoint_config.py:25
  backend_ctl/harness.py:51
  multiprocess_framework/__init__.py:94
  multiprocess_framework/modules/app_module/builder.py:39
  multiprocess_framework/modules/app_module/entry.py:21
  multiprocess_framework/modules/app_module/interfaces.py:27
  multiprocess_framework/modules/app_module/orchestrator.py:34
  multiprocess_framework/modules/conftest.py:23
  multiprocess_framework/modules/process_module/__init__.py:120
  multiprocess_prototype/backend/assembly/assembler.py:26
  … ещё 6
  тесты: 52 файлов, первые 3: Services/camera_device/tests/test_run_locked_commands_camera.py, Services/robot_comm/tests/_t38_line_host.py, backend_ctl/tests/test_c88_shutdown_outcomes_acceptance.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 3
  П2 docstring Google у публичного API: 94 из 106
  П3 __all__ у interfaces.py и __init__.py: 10 из 10
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 2
````

### card process_module

Команда: `atlas card process_module`

````text
Модуль process_module — framework, ярус core
Назначение: Базовый класс процесса: создание, инициализация, управление, мониторинг; сюда — менять жизнь процесса
API (4): IProcessCommunication, IProcessModule, ISharedResources, ProcessStatsDict
Открытые задачи (16 планов, 123 задач):
  observation-port — 2: 0.2, 2.4
  telemetry-stage6 — 2: 1.2, 3.5
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
  backend-ctl-proof-discipline — 8: 0.1, 0.2, 1.1, 1.2, 1.3, 1.4, … ещё 2
  … ещё 11 планов
Коммиты (332 всего, последние 5):
  f82e3a1 2026-11-25 merge: W1-c — имя процесса в логе плагина с загрузки в integ/multicam-obs
  06a74ec 2026-11-25 fix(framework): W1-c — сбой контекста логгера не роняет initialize()
  06e0a93 2026-11-25 fix(framework): W1-c — база контекста логгера до загрузки плагинов
  ff2e7e2 2026-11-25 test(multicam-obs): слепые тесты волны 1 — личность камеры, триггер считывателя, имя проц…
  47e9778 2026-11-24 merge: тракт кадров gui — ящик, насос, метрики, дешёвый кадр, отложенная копия T5, штампы…
Находки (16):
  warning P2_DOCSTRING module:process_module IProcessModule.broadcast_message
  warning P2_DOCSTRING module:process_module IProcessModule.get_config
  warning P2_DOCSTRING module:process_module IProcessModule.get_stats
  warning P2_DOCSTRING module:process_module IProcessModule.initialize
  warning P2_DOCSTRING module:process_module IProcessModule.receive_message
  warning P2_DOCSTRING module:process_module IProcessModule.run
  warning P2_DOCSTRING module:process_module IProcessModule.send_message
  warning P2_DOCSTRING module:process_module IProcessModule.should_stop
  warning P2_DOCSTRING module:process_module IProcessModule.shutdown
  warning P2_DOCSTRING module:process_module IProcessModule.stop
  … ещё 6
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 475, из них тестов 258
  Plugins/calibration/camera_robot/config.py:8
  Plugins/calibration/camera_robot/plugin.py:31
  Plugins/calibration/camera_robot/registers.py:8
  Plugins/control/robot_control/config.py:11
  Plugins/control/robot_control/plugin.py:47
  Plugins/control/robot_control/registers.py:11
  Plugins/filter/line_filter/config.py:11
  Plugins/filter/line_filter/plugin.py:19
  Plugins/filter/line_filter/registers.py:12
  Plugins/hub/device_hub/config.py:8
  … ещё 207
  тесты: 258 файлов, первые 3: Plugins/control/robot_control/tests/test_flight_dump_emitter.py, Plugins/control/robot_control/tests/test_t52_actuation_contract.py, Plugins/control/robot_control/tests/test_t52_author.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 5 из 5
  П2 docstring Google у публичного API: 127 из 141
  П3 __all__ у interfaces.py и __init__.py: 16 из 17
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 1 из 2
````

### card recipe

Команда: `atlas card recipe`

````text
Модуль recipe — framework, ярус optional
Назначение: Управление рецептами: снимки конфигурации, определение формата, миграции, CRUD; сюда — менять рецепты
API (3): RecipeEngineProtocol, RecipeManagerProtocol, StoreProtocol
Открытые задачи (2 планов, 33 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  observation-port — 2: 0.2, 2.4
Коммиты (21 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  287cb8d 2026-11-06 docs(recipe): C-30 1.3 — ADR-RCP-009/010, README/STATUS, OPEN_QUESTIONS, sync
  610cc89 2026-11-06 feat(recipe): C-30 1.5 — страж одного писателя R1–R4, миграция canonicalize_gui_positions…
  b807e6a 2026-11-06 fix(recipe): C-30 1.4 — recipe.save и RecipeEngine.save/load пишут дельту через движок
  b2e1298 2026-10-27 merge: C-30 промежуточно 11/17 — дельта-движок рецепта, канон, ревизия, Save одной записью
Находки (4):
  warning P1_IMPL_NOT_INHERITING module:recipe RecipeEngine>RecipeEngineProtocol
  warning P1_IMPL_NOT_INHERITING module:recipe RecipeManager>RecipeManagerProtocol
  warning P4_DIRECT_WRITE module:recipe multiprocess_framework/modules/recipe/hook_contract.py::_check_empty_delta
  warning P4_DIRECT_WRITE module:recipe multiprocess_framework/modules/recipe/hook_contract.py::_check_hash_seed_determinism
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 44, из них тестов 21
  Plugins/sim/layer_preview/plugin.py:70
  Plugins/sim/scene_source/plugin.py:73
  multiprocess_framework/modules/app_module/builder.py:99
  multiprocess_framework/modules/state_store_module/recipes/recipe_engine.py:17
  multiprocess_prototype/adapters/catalogs/display_catalog_recipe.py:27
  multiprocess_prototype/adapters/recipe_canonical.py:39
  multiprocess_prototype/adapters/stores/recipe_store.py:30
  multiprocess_prototype/backend/launch.py:27
  multiprocess_prototype/backend/recipe_format_hook.py:24
  multiprocess_prototype/backend/state/recipes/migrations/v1_to_v2.py:25
  … ещё 13
  тесты: 21 файлов, первые 3: multiprocess_prototype/adapters/tests/test_display_catalog_session_blind.py, multiprocess_prototype/adapters/tests/test_recipe_canonical.py, multiprocess_prototype/adapters/tests/test_recipe_store.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 2
  П2 docstring Google у публичного API: 75 из 75
  П3 __all__ у interfaces.py и __init__.py: 2 из 2
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 2
````

### card registers_module

Команда: `atlas card registers_module`

````text
Модуль registers_module — framework, ярус optional
Назначение: Рантайм именованных регистров: подписки на поля, карта маршрутов, отправка; сюда — менять регистры
API (1): IRegistersManager
Открытые задачи (2 планов, 42 задач):
  gui-service — 11: 1.4, 1b.2b, 1b.2c, 1b.3, 1b.4, 2.1, … ещё 5
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
Коммиты (19 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  005df13 2026-10-13 merge: lifecycle-owner-scope 1.2b-2 — кодмод 23 классов в _on_shutdown, срок второго вызо…
  68fb2e6 2026-10-02 chore(merge): Task 5.5 — зелёный набор фреймворка и гейт /dev:ship в main
  a6984d4 2026-10-02 refactor(data_schema): refusal_text — публичный вход модуля, без приватного импорта
  a38756a 2026-10-02 fix(registers): set_field_value на регистре без apply_values возвращает кортеж
Находки (3):
  warning P1_IMPL_NOT_INHERITING module:registers_module RegistersManager>IRegistersManager
  warning P2_DOCSTRING module:registers_module RegistersManager.initialize
  info INTERFACE_WITHOUT_TEST interface:registers_module:IRegistersManager -
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 60, из них тестов 34
  multiprocess_framework/__init__.py:115
  multiprocess_framework/modules/frontend_module/application/frontend_manager.py:18
  multiprocess_framework/modules/process_module/commands/builtin_commands.py:996
  multiprocess_framework/modules/process_module/generic/plugin_orchestrator.py:776
  multiprocess_framework/modules/process_module/plugins/__init__.py:23
  multiprocess_prototype/adapters/stores/registers_backend.py:46
  multiprocess_prototype/frontend/app.py:290
  multiprocess_prototype/frontend/app_services_factory.py:54
  multiprocess_prototype/frontend/forms/factory/__init__.py:23
  multiprocess_prototype/frontend/forms/factory/_common.py:12
  … ещё 16
  тесты: 34 файлов, первые 3: Plugins/processing/word_layout/tests/test_word_source_chain.py, Plugins/processing/word_layout/tests/test_word_source_order.py, Plugins/processing/word_layout/tests/test_word_source_order_author.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 1
  П2 docstring Google у публичного API: 55 из 56
  П3 __all__ у interfaces.py и __init__.py: 2 из 2
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card router_module

Команда: `atlas card router_module`

````text
Модуль router_module — framework, ярус core
Назначение: Маршрутизация сообщений между процессами через RouterManager; сюда — менять каналы и правила доставки
API (2): IMessageChannel, IRouterManager
Открытые задачи (7 планов, 64 задач):
  transport-router-hub — 9: P0.1, P0.2, P0.3, P1.1, P1.2, P1.3, … ещё 3
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  gui-service — 11: 1.4, 1b.2b, 1b.2c, 1b.3, 1b.4, 2.1, … ещё 5
  observation-port — 2: 0.2, 2.4
  recipe-orchestrator-unify — 4: 1.2, 2.0, 2.1, 2.3
  … ещё 2 планов
Коммиты (90 всего, последние 5):
  f2304d4 2026-11-24 merge: fix/lane-t-win-baseline — красные Windows/Python 3.12 исправлены по причине, отчёт…
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  b5adf82 2026-10-27 merge: полоса С — C-53, C-54 импорты framework, C-55a venv-guard, C-55b ассеты ml_inferen…
  4d2a2f5 2026-10-26 merge: Task 1.9b — PM на ExecutorManager, стоп не глохнет (L-9)
  6c4fc76 2026-10-21 merge: feat/lifecycle-keyed-executor в main — Task 1.9a, KeyedExecutor и развилка «на мес…
Находки (16):
  warning P1_IMPL_NOT_INHERITING module:router_module RouterManager>IRouterManager
  warning P2_DOCSTRING module:router_module QueueChannel.channel_type
  warning P2_DOCSTRING module:router_module QueueChannel.get_info
  warning P2_DOCSTRING module:router_module QueueChannel.name
  warning P2_DOCSTRING module:router_module RouterManager.add_handler_to_message_scenario
  warning P2_DOCSTRING module:router_module RouterManager.add_message_callback
  warning P2_DOCSTRING module:router_module RouterManager.add_receive_middleware
  warning P2_DOCSTRING module:router_module RouterManager.add_send_middleware
  warning P2_DOCSTRING module:router_module RouterManager.clear_middleware
  warning P2_DOCSTRING module:router_module RouterManager.initialize
  … ещё 6
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 82, из них тестов 54
  Plugins/_shared/fanin/join_inspector_manager.py:29
  Plugins/control/robot_control/plugin.py:53
  Plugins/io/frame_buffer/plugin.py:37
  Services/modbus/channels/modbus_channel.py:21
  Services/robot_comm/gui/line_source.py:37
  backend_ctl/transport.py:35
  multiprocess_framework/__init__.py:57
  multiprocess_framework/modules/frontend_module/bridge/remote_command_sender.py:58
  multiprocess_framework/modules/frontend_module/bridge/remote_frame_source.py:50
  multiprocess_framework/modules/frontend_module/bridge/remote_state_proxy.py:37
  … ещё 18
  тесты: 54 файлов, первые 3: Plugins/hub/device_hub/tests/test_reply_envelope_acceptance.py, Plugins/hub/device_hub/tests/test_spi_commands_acceptance.py, Plugins/io/frame_saver/tests/test_frame_saver.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 4 из 5
  П2 docstring Google у публичного API: 116 из 131
  П3 __all__ у interfaces.py и __init__.py: 8 из 8
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card service_module

Команда: `atlas card service_module`

````text
Модуль service_module — framework, ярус optional
Назначение: Реестр и жизненный цикл долгоживущих сервисов (камеры, БД, auth); сюда — менять учёт сервисов
API (2): IService, ServiceLifecycle
Открытые задачи (1 планов, 31 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
Коммиты (4 всего, последние 4):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  52f5e6c 2026-09-25 merge: gui-service Task 1b.5 в feat/gui-service — сервисы на хабе
  e83b0bf 2026-07-25 feat(framework): ярусная карта модулей + публичный API-контракт (Ф8 H.1, NEW-10)
  17a22a8 2026-05-25 Merge branch 'feat/service-registry' into main
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 29, из них тестов 11
  Services/auth/service.py:9
  Services/dataset_gen/service.py:15
  Services/hikvision_camera/service.py:10
  Services/ml_inference/service.py:17
  Services/ml_train/service.py:20
  Services/modbus/service.py:15
  Services/robot_comm/service.py:12
  Services/sql/service.py:9
  Services/vfd_comm/service.py:11
  multiprocess_prototype/adapters/catalogs/remote_service_manager.py:23
  … ещё 8
  тесты: 11 файлов, первые 3: Services/dataset_gen/tests/test_service.py, Services/ml_inference/tests/test_service.py, Services/ml_train/tests/test_service.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 19 из 19
  П3 __all__ у interfaces.py и __init__.py: 2 из 2
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card shared_resources_module

Команда: `atlas card shared_resources_module`

````text
Модуль shared_resources_module — framework, ярус core
Назначение: Pickle-safe реестр общих ресурсов для межпроцессного обмена; сюда — менять передачу ресурсов процессам
API (6): IConfigStore, IEventManager, IMemoryManager, IProcessStateRegistry, IQueueRegistry, ISharedResourcesManager
Открытые задачи (4 планов, 46 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  backend-ctl-proof-discipline — 8: 0.1, 0.2, 1.1, 1.2, 1.3, 1.4, … ещё 2
  lifecycle-graceful-stop — 1: 1.1
  replace-blueprint-hotswap — 6: 1, 2, 3, 4, 5, 7
Коммиты (52 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  b5adf82 2026-10-27 merge: полоса С — C-53, C-54 импорты framework, C-55a venv-guard, C-55b ассеты ml_inferen…
  005df13 2026-10-13 merge: lifecycle-owner-scope 1.2b-2 — кодмод 23 классов в _on_shutdown, срок второго вызо…
  92fd045 2026-10-05 merge: main в feat/lifecycle-owner-scope перед T1 (spawn на всех ОС, Атлас 0.8)
  68fb2e6 2026-10-02 chore(merge): Task 5.5 — зелёный набор фреймворка и гейт /dev:ship в main
Находки (70):
  warning P2_DOCSTRING module:shared_resources_module DataSchemaAdapter.data_manager
  warning P2_DOCSTRING module:shared_resources_module EventManager.emit_event
  warning P2_DOCSTRING module:shared_resources_module EventManager.get_event_queue
  warning P2_DOCSTRING module:shared_resources_module EventManager.get_new_event_event
  warning P2_DOCSTRING module:shared_resources_module EventManager.get_stats
  warning P2_DOCSTRING module:shared_resources_module EventManager.initialize
  warning P2_DOCSTRING module:shared_resources_module EventManager.router_manager
  warning P2_DOCSTRING module:shared_resources_module EventManager.set_router_manager
  warning P2_DOCSTRING module:shared_resources_module EventManager.subscribe
  warning P2_DOCSTRING module:shared_resources_module EventManager.unsubscribe
  … ещё 60
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 65, из них тестов 51
  multiprocess_framework/__init__.py:71
  multiprocess_framework/modules/config_module/core/config_manager.py:25
  multiprocess_framework/modules/data_schema_module/storage/storage_manager.py:23
  multiprocess_framework/modules/frontend_module/bridge/remote_frame_source.py:45
  multiprocess_framework/modules/frontend_module/bridge/wire_protocol.py:17
  multiprocess_framework/modules/process_manager_module/core/process_registry.py:31
  multiprocess_framework/modules/process_manager_module/launcher/spawner.py:16
  multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:51
  multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:34
  multiprocess_framework/modules/process_manager_module/runner/bundle_builder.py:6
  … ещё 4
  тесты: 51 файлов, первые 3: Plugins/io/frame_saver/tests/test_frame_saver.py, multiprocess_framework/modules/base_manager/tests/test_base_manager_template_hazards.py, multiprocess_framework/modules/base_manager/tests/test_process_status_unified.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 167 из 230
  П3 __all__ у interfaces.py и __init__.py: 31 из 31
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 1
````

### card state_store_module

Команда: `atlas card state_store_module`

````text
Модуль state_store_module — framework, ярус optional
Назначение: Реактивное иерархическое дерево состояния: сервер и клиентский кэш с подписками; сюда — менять общее состояние
API (4): IRouter, IStateProxy, IStateStore, IStateStoreManager
Открытые задачи (5 планов, 42 задач):
  observation-port — 2: 0.2, 2.4
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  truth-holes-closure — 1: 1.3
  recipe-orchestrator-unify — 4: 1.2, 2.0, 2.1, 2.3
  telemetry-delivery-simplification — 4: 1.2, 2.1, 3.1, 3.2
Коммиты (60 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  005df13 2026-10-13 merge: lifecycle-owner-scope 1.2b-2 — кодмод 23 классов в _on_shutdown, срок второго вызо…
  ab38cea 2026-08-24 fix(mixed): пять находок ревью Ф1+Ф2 — включая truthiness, внесённую самой Т.1
  48f63af 2026-08-24 fix(mixed): Т.3 — старт GUI перестал платить четырьмя таймаутами подписки
  0a842be 2026-08-24 test(mixed): красное ТЗ Т.3 — старт GUI платит четыре таймаута подписки
Находки (11):
  warning P1_IMPL_NOT_INHERITING module:state_store_module InMemoryRouter>IRouter
  warning P2_DOCSTRING module:state_store_module LoggingMiddleware.name
  warning P2_DOCSTRING module:state_store_module MetricsMiddleware.name
  warning P2_DOCSTRING module:state_store_module Selector.name
  warning P2_DOCSTRING module:state_store_module StateProxy.initialize
  warning P2_DOCSTRING module:state_store_module ThrottleMiddleware.name
  warning P2_DOCSTRING module:state_store_module ValidationMiddleware.name
  warning P4_DIRECT_WRITE module:state_store_module multiprocess_framework/modules/state_store_module/persistence/persistence_manager.py::PersistenceManager._save_file
  info INTERFACE_WITHOUT_TEST interface:state_store_module:IStateProxy -
  info INTERFACE_WITHOUT_TEST interface:state_store_module:IStateStore -
  … ещё 1
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 127, из них тестов 104
  Plugins/io/telemetry_sink/plugin.py:42
  Plugins/sim/scene_source/plugin.py:81
  backend_ctl/driver.py:36
  backend_ctl/probes/probe_observability_consumer_acceptance.py:75
  multiprocess_framework/__init__.py:119
  multiprocess_framework/modules/app_module/orchestrator.py:400
  multiprocess_framework/modules/frontend_module/bridge/remote_state_proxy.py:40
  multiprocess_framework/modules/process_module/configs/observation_policy.py:80
  multiprocess_framework/modules/process_module/core/process_module.py:15
  multiprocess_framework/modules/process_module/generic/generic_process.py:82
  … ещё 13
  тесты: 104 файлов, первые 3: Plugins/io/telemetry_sink/tests/test_f2_acceptance_writer_subtree_cleanup.py, Plugins/io/telemetry_sink/tests/test_sink_leaf_copy.py, Plugins/io/telemetry_sink/tests/test_telemetry_sink_plugin.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 5 из 6
  П2 docstring Google у публичного API: 203 из 209
  П3 __all__ у interfaces.py и __init__.py: 13 из 13
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 1
````

### card statistics_module

Команда: `atlas card statistics_module`

````text
Модуль statistics_module — framework, ярус core
Назначение: Менеджер статистики и метрик, третья плоскость наблюдаемости; сюда — менять сбор и вывод метрик
API (1): IStatsManager
Открытые задачи (4 планов, 48 задач):
  observation-port — 2: 0.2, 2.4
  telemetry-stage6 — 2: 1.2, 3.5
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
Коммиты (48 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  751ba0d 2026-10-21 merge: feat/lifecycle-executor-manager в main — Task 1.9m, ExecutorManager
  68a8ba2 2026-10-03 merge: Task 5.5c — весь make gate зелёный (ruff, pyright, bandit -ll, корневой pytest, те…
  b7babad 2026-09-08 merge: observability-closure (fcfbbdf7) в main — Ф0-Ф3 и две задачи Ф4 доставлены полосам
  9245c73 2026-09-07 fix(framework): голос о смене смысла stats.enabled переехал с разбора на действие
Находки (7):
  warning P2_DOCSTRING module:statistics_module FileStatsChannel.channel_type
  warning P2_DOCSTRING module:statistics_module FileStatsChannel.get_info
  warning P2_DOCSTRING module:statistics_module FileStatsChannel.name
  warning P2_DOCSTRING module:statistics_module LogStatsChannel.channel_type
  warning P2_DOCSTRING module:statistics_module LogStatsChannel.get_info
  warning P2_DOCSTRING module:statistics_module LogStatsChannel.name
  warning P2_DOCSTRING module:statistics_module StatsAdapter.is_initialized
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 36, из них тестов 27
  multiprocess_framework/__init__.py:66
  multiprocess_framework/modules/process_module/configs/managers_config.py:25
  multiprocess_framework/modules/process_module/configs/observability_config.py:37
  multiprocess_framework/modules/process_module/heartbeat/process_heartbeat.py:72
  multiprocess_framework/modules/process_module/heartbeat/telemetry.py:30
  multiprocess_framework/modules/process_module/managers/observability_wiring.py:584
  multiprocess_framework/modules/process_module/managers/process_managers.py:216
  multiprocess_framework/modules/process_module/plugins/base.py:26
  multiprocess_framework/modules/process_module/plugins/testing.py:44
  тесты: 27 файлов, первые 3: backend_ctl/tests/test_overview.py, multiprocess_framework/modules/channel_routing_module/tests/test_sink_control_symmetry.py, multiprocess_framework/modules/channel_routing_module/tests/test_task_3_1_hazards.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 1 из 1
  П2 docstring Google у публичного API: 66 из 73
  П3 __all__ у interfaces.py и __init__.py: 7 из 7
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card telemetry_readmodel_module

Команда: `atlas card telemetry_readmodel_module`

````text
Модуль telemetry_readmodel_module — framework, ярус optional
Назначение: Qt-free ядро read-model телеметрии: проекция значений и кольцевая история; сюда — менять чтение телеметрии
API (1): ITelemetryReadModel
Открытые задачи (3 планов, 14 задач):
  observation-port — 2: 0.2, 2.4
  telemetry-stage6 — 2: 1.2, 3.5
  backend-ctl-framework-module — 10: 1.1, 1.2, 2.1, 2.2, 2.3, 2.4, … ещё 4
Коммиты (13 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  05e4dd5 2026-08-20 test(framework): уборка теста сносила чужое объявление — красила соседа в совмещённом про…
  465c736 2026-08-20 fix(mixed): семь находок ревью Task 1.4 — сторожа догнали гарантии
  63077e0 2026-08-20 feat(mixed): читатели переехали на поддерево писателя — правило супервизии ожило
  868f1a0 2026-08-17 docs(plans): правда по приёмке 3.5, ADR закрытых находок и четыре новые строки очереди
Находки (1):
  warning P1_IMPL_NOT_INHERITING module:telemetry_readmodel_module TelemetryReadModel>ITelemetryReadModel
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 11, из них тестов 7
  backend_ctl/_node_read.py:20
  backend_ctl/driver.py:38
  backend_ctl/recorder.py:701
  multiprocess_framework/modules/frontend_module/state/telemetry_view_model.py:45
  тесты: 7 файлов, первые 3: multiprocess_framework/modules/process_module/tests/test_cycle_metrics_truth.py, multiprocess_framework/modules/process_module/tests/test_observation_port_readmodel_ghost_acceptance.py, multiprocess_framework/modules/state_store_module/tests/test_contract_freshness.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 1
  П2 docstring Google у публичного API: 26 из 26
  П3 __all__ у interfaces.py и __init__.py: 2 из 2
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card worker_module

Команда: `atlas card worker_module`

````text
Модуль worker_module — framework, ярус core
Назначение: Менеджер потоков-воркеров внутри процесса: старт, стоп, пауза, перезапуск; сюда — менять управление потоками
API (8): IExecutorManager, IExecutorRegistry, IWorkerLifecycle, IWorkerManager, IWorkerRegistry, OrderedExecutor, WorkerStatus, WorkerType
Открытые задачи (2 планов, 36 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  pipeline-live-control — 5: 2.1, 2.2, 3.1, 3.2, 3.3
Коммиты (18 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  4d2a2f5 2026-10-26 merge: Task 1.9b — PM на ExecutorManager, стоп не глохнет (L-9)
  751ba0d 2026-10-21 merge: feat/lifecycle-executor-manager в main — Task 1.9m, ExecutorManager
  6c4fc76 2026-10-21 merge: feat/lifecycle-keyed-executor в main — Task 1.9a, KeyedExecutor и развилка «на мес…
  005df13 2026-10-13 merge: lifecycle-owner-scope 1.2b-2 — кодмод 23 классов в _on_shutdown, срок второго вызо…
Находки (35):
  warning P1_IMPL_NOT_INHERITING module:worker_module ExecutorManager>IExecutorManager
  warning P1_IMPL_NOT_INHERITING module:worker_module KeyedExecutor>OrderedExecutor
  warning P1_IMPL_NOT_INHERITING module:worker_module WorkerAdapter>IWorkerLifecycle
  warning P1_IMPL_NOT_INHERITING module:worker_module WorkerManager>IWorkerLifecycle
  warning P2_DOCSTRING module:worker_module WorkerAdapter.get_stats
  warning P2_DOCSTRING module:worker_module WorkerAdapter.get_status
  warning P2_DOCSTRING module:worker_module WorkerAdapter.has_worker
  warning P2_DOCSTRING module:worker_module WorkerAdapter.is_running
  warning P2_DOCSTRING module:worker_module WorkerAdapter.list_application_workers
  warning P2_DOCSTRING module:worker_module WorkerAdapter.list_system_workers
  … ещё 25
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 62, из них тестов 48
  Services/camera_device/session.py:42
  multiprocess_framework/__init__.py:82
  multiprocess_framework/modules/chain_module/thread_pool/worker_pool_executor.py:41
  multiprocess_framework/modules/command_module/core/command_manager.py:14
  multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py:20
  multiprocess_framework/modules/process_module/commands/builtin_commands.py:463
  multiprocess_framework/modules/process_module/core/process_module.py:1102
  multiprocess_framework/modules/process_module/heartbeat/process_heartbeat.py:191
  multiprocess_framework/modules/process_module/managers/process_managers.py:217
  multiprocess_framework/modules/process_module/plugins/__init__.py:24
  … ещё 4
  тесты: 48 файлов, первые 3: Plugins/hub/device_hub/tests/test_spi_commands_acceptance.py, Plugins/sim/robot_host/tests/test_v2_real_worker_manager.py, Services/camera_device/tests/test_apply_params_bindings_refused.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 3 из 7
  П2 docstring Google у публичного API: 84 из 110
  П3 __all__ у interfaces.py и __init__.py: 8 из 8
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card services/auth

Команда: `atlas card services/auth`

````text
Модуль services/auth — services, ярус —
Назначение: Аутентификация и RBAC: хеши паролей, пользователи, роли; сюда — менять вход и права доступа
API (5): IAuditWriter, IAuthManager, IPasswordHasher, ISessionTracker, IUserStorage
Открытые задачи: нет
Коммиты (17 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  4bd81f4 2026-10-13 merge: lifecycle-owner-scope 1.2b-3 — Services и прототип на _on_shutdown, принуждение Р1…
  68a8ba2 2026-10-03 merge: Task 5.5c — весь make gate зелёный (ruff, pyright, bandit -ll, корневой pytest, те…
  e1396c4 2026-08-12 feat(services): env-ручки Services читаются парой, канон первым (5.2, Р-5а)
  bcabd29 2026-07-12 Merge branch 'feat/constructor-new-d1-tab-registry': NEW-D1 — TabRegistry во frontend_mod…
Находки (4):
  info INTERFACE_WITHOUT_TEST interface:services/auth:IAuditWriter -
  info INTERFACE_WITHOUT_TEST interface:services/auth:IPasswordHasher -
  info INTERFACE_WITHOUT_TEST interface:services/auth:ISessionTracker -
  info INTERFACE_WITHOUT_TEST interface:services/auth:IUserStorage -
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 21, из них тестов 7
  multiprocess_prototype/frontend/actions/bus_factory.py:28
  multiprocess_prototype/frontend/actions/handlers/role_update_handler.py:20
  multiprocess_prototype/frontend/actions/middleware/audit_middleware.py:27
  multiprocess_prototype/frontend/app.py:675
  multiprocess_prototype/frontend/auth_context.py:28
  multiprocess_prototype/frontend/permissions.py:18
  multiprocess_prototype/frontend/widgets/chrome/login_button.py:14
  multiprocess_prototype/frontend/widgets/dialogs/confirm_with_password.py:22
  multiprocess_prototype/frontend/widgets/dialogs/login_dialog.py:26
  multiprocess_prototype/frontend/widgets/tabs/settings/administration/audit_log_panel.py:34
  … ещё 4
  тесты: 7 файлов, первые 3: Services/tests/test_env_brand.py, multiprocess_prototype/frontend/actions/middleware/tests/test_audit_middleware.py, multiprocess_prototype/frontend/tests/test_permissions.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 4
  П2 docstring Google у публичного API: 102 из 102
  П3 __all__ у interfaces.py и __init__.py: 4 из 5
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card services/camera_device

Команда: `atlas card services/camera_device`

````text
Модуль services/camera_device — services, ярус —
Назначение: Общее ядро камер: контракт порта прибора и его фейк; сюда — менять порт, границу SDK и эмуляцию
API (0): —
Открытые задачи (2 планов, 27 задач):
  multicam-observability — 4: W1-a, W1-a2, W1-b, W1-c
  camera-device-service — 23: 1.2, 1.3, 1.4, 1.7, 2.3a, 2.3b, … ещё 17
Коммиты (14 всего, последние 5):
  f2e08bb 2026-11-25 merge: W1-a и W1-a2 — личность камеры и здоровье потока в integ/multicam-obs
  4a32d9d 2026-11-25 fix(camera_device): маска 0.0.0.0 — подсеть неизвестна
  28452e3 2026-11-25 test(camera_device): W1-a — личность не переходит в следующий цикл
  b004328 2026-11-25 test(camera_device): W1-a — поправки стендов слепых тестов и сверки
  6e93bb8 2026-11-25 feat(camera_device): W1-a — личность прибора и здоровье потока
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 12, из них тестов 9
  Services/hikvision_camera/driver.py:25
  Services/hikvision_camera/plugin/plugin.py:14
  Services/hikvision_camera/plugin/registers.py:13
  тесты: 9 файлов, первые 3: Services/hikvision_camera/tests/core_rig.py, Services/hikvision_camera/tests/test_4_2d_acceptance.py, Services/hikvision_camera/tests/test_capture_stamps.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 24 из 24
  П3 __all__ у interfaces.py и __init__.py: 1 из 1
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card services/code_reader

Команда: `atlas card services/code_reader`

````text
Модуль services/code_reader — services, ярус —
Назначение: Сервис считывателя кодов Hikrobot ID3000: приём результатов по TCP, разбор; сюда — менять чтение кодов
API (10): CodeQuality, CodeRead, CodeReaderSinkProtocol, ReadResult, ReadStatus, ResultHandler, SdkCodeReader, SdkFrame, decode_image, frame_from_raw
Открытые задачи (3 планов, 26 задач):
  multicam-observability — 4: W1-a, W1-a2, W1-b, W1-c
  qr-code-reader — 14: 0.1, 1.1, 1.2, 1.3, 1.4, 1.5, … ещё 8
  code-reader-gui — 8: 1.1, 1.2, 2.1, 2.2a, 2.2b, 2.3, … ещё 2
Коммиты (20 всего, последние 5):
  ea65a33 2026-11-25 merge: W1-b — тексты last_error и край отката триггера
  0ab83f6 2026-11-25 fix(code_reader): отказы откатываемого сеанса не считаются прежними
  3f61955 2026-11-25 fix(code_reader): хвосты last_error после take и отказы прошлого сеанса
  91193ab 2026-11-25 merge: W1-b — живая правка триггера считывателя в integ/multicam-obs
  b2cd5e3 2026-11-25 fix(code_reader): правка триггера по намерению, здоровье по фактам
Находки (3):
  info INTERFACE_WITHOUT_TEST interface:services/code_reader:CodeQuality -
  info INTERFACE_WITHOUT_TEST interface:services/code_reader:CodeRead -
  info INTERFACE_WITHOUT_TEST interface:services/code_reader:ResultHandler -
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 4, из них тестов 4
  тесты: 4 файлов, первые 3: multiprocess_prototype/recipes/tests/test_hikvision_id3013_quad_hw_recipe.py, multiprocess_prototype/recipes/tests/test_qr_reader_demo.py, multiprocess_prototype/recipes/tests/test_qr_reader_sdk_demo.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 1
  П2 docstring Google у публичного API: 18 из 20
  П3 __all__ у interfaces.py и __init__.py: 5 из 5
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 1 из 3
````

### card services/control_panel

Команда: `atlas card services/control_panel`

````text
Модуль services/control_panel — services, ярус —
Назначение: Сервис Пульт: GUI-контролы выдают значения на порты pipeline; сюда — менять контролы и их сигналы
API (2): ControlSpec, ControlType
Открытые задачи: нет
Коммиты (6 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  8166456 2026-06-16 feat(pult): выбор режима робота + стабильность телефона + dry_run off
  4a73c29 2026-06-15 feat(services): пульт Phase 5.1 — модель proxy-контрола (source/target)
  ee8d21d 2026-06-15 feat(mixed): кнопка «Рисовать» в phone_sketch — пульт → робот через pipeline
  693fc55 2026-06-15 docs(plans): пульт Phase 1-3 DONE + smoke verified
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 5, из них тестов 3
  multiprocess_prototype/frontend/widgets/tabs/services/control_panel/presenter.py:86
  multiprocess_prototype/frontend/widgets/tabs/services/control_panel/widget.py:30
  тесты: 3 файлов, первые 3: multiprocess_prototype/frontend/widgets/tabs/services/control_panel/tests/test_recipe_1_0.py, multiprocess_prototype/frontend/widgets/tabs/services/control_panel/tests/test_recipe_1_0_belt_monitors.py, multiprocess_prototype/frontend/widgets/tabs/services/control_panel/tests/test_recipe_1_0_word_dispatch.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 9 из 9
  П3 __all__ у interfaces.py и __init__.py: 2 из 2
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card services/dataset_gen

Команда: `atlas card services/dataset_gen`

````text
Модуль services/dataset_gen — services, ярус —
Назначение: Генератор синтетического датасета методом cut-and-paste; сюда — менять создание обучающих данных
API (1): SampleGenerator
Открытые задачи (1 планов, 7 задач):
  layer-render — 7: 3.1, 3.2, 4.1, 4.2, 5.1, 5.2, … ещё 1
Коммиты (19 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  8499ae6 2026-10-14 merge: layer-render 6.3 — CLI экспорта обучающих вырезов, секция train первого продукта, …
  59558a6 2026-10-14 test(dataset_gen): литерал выхода LayerSceneGenerator до Task 6.3
  91d595e 2026-10-14 merge: layer-render 6.2 — LayerSceneGenerator, обучающие сэмплы любого продукта из слоёв …
  6348d35 2026-10-14 feat(dataset_gen): LayerSceneGenerator — обучающие сэмплы из пресета слоёв, секция train
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 73, из них тестов 62
  Plugins/sim/scene_source/plugin.py:82
  Services/line_sim/tools/build_stand_assets.py:40
  Services/line_sim/tools/make_demo_catalog.py:26
  Services/line_sim/tools/make_font_letters.py:80
  Services/line_sim/tools/make_letter_catalog.py:31
  Services/line_sim/tools/make_seamless_texture.py:44
  Services/ml_train/data.py:201
  Services/ml_train/holdout_eval.py:34
  multiprocess_prototype/frontend/widgets/tabs/services/neural/dataset_gen_section.py:214
  multiprocess_prototype/frontend/widgets/tabs/services/neural/disk_cutter_section.py:66
  … ещё 1
  тесты: 62 файлов, первые 3: Plugins/sim/layer_preview/tests/test_acceptance_1_3h_c_sprites.py, Plugins/sim/layer_preview/tests/test_acceptance_1_3h_d_sprite_put.py, Plugins/sim/layer_preview/tests/test_acceptance_1_3h_layout.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 2
  П2 docstring Google у публичного API: 27 из 31
  П3 __all__ у interfaces.py и __init__.py: 2 из 3
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 4
````

### card services/device_hub

Команда: `atlas card services/device_hub`

````text
Модуль services/device_hub — services, ярус —
Назначение: Центральный реестр устройств и менеджер соединений; сюда — менять учёт и подключение устройств
API (0): —
Открытые задачи (2 планов, 16 задач):
  device-tree-recipe — 3: B2, E1, V1
  robot-protocol-v2 — 13: T0.3, T4.0, T4.1, T4.5, T4.6, T5.3, … ещё 7
Коммиты (39 всего, последние 5):
  a7952d2 2026-11-24 merge: feat/pult-belt-speed — память частоты ленты ПЧ, belt_freq в рецептах симулятора
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  009e35f 2026-11-08 feat(device_hub): слияние T5.5 — draw_polyline и подача на роботе v2
  695b9ee 2026-10-27 merge: T5.3e.1–3 — команда robot_park (штатное «домой» до process.stop) и стенд v2
  4d9cf4c 2026-10-26 merge: SPI хаба — Protocol драйвера, OpSpec, команды из таблицы видов, device_io
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 21, из них тестов 20
  Plugins/hub/device_hub/plugin.py:39
  тесты: 20 файлов, первые 3: Plugins/calibration/camera_robot/tests/test_sim_integration.py, Plugins/calibration/camera_robot/tests/test_v2_driver_contract.py, Plugins/hub/device_hub/tests/conftest.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 12 из 12
  П3 __all__ у interfaces.py и __init__.py: 4 из 4
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card services/documents

Команда: `atlas card services/documents`

````text
Модуль services/documents — services, ярус —
Назначение: Хранилище документов: аудит смен наблюдаемости и вердикты по детали; сюда — менять аудит и вердикты
API (4): IDocumentSink, IDocumentStore, KIND_AUDIT, KIND_VERDICT
Открытые задачи: нет
Коммиты (5 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  b7babad 2026-09-08 merge: observability-closure (fcfbbdf7) в main — Ф0-Ф3 и две задачи Ф4 доставлены полосам
  9245c73 2026-09-07 fix(framework): голос о смене смысла stats.enabled переехал с разбора на действие
  f1b5189 2026-08-11 fix(services): ретеншен документов возвращает байты ОС, а не только удаляет строки (3.1)
  23184cc 2026-08-09 feat(observability): merge — влить observability-unified-routing — Ф0–Ф8 наблюдаемости
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 3, из них тестов 1
  Plugins/control/robot_control/plugin.py:54
  backend_ctl/probes/probe_c3_document_plane.py:72
  тесты: 1 файлов, первые 3: Plugins/control/robot_control/tests/test_verdict_real_wiring.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 1
  П2 docstring Google у публичного API: 13 из 13
  П3 __all__ у interfaces.py и __init__.py: 2 из 2
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card services/frame_buffer

Команда: `atlas card services/frame_buffer`

````text
Модуль services/frame_buffer — services, ярус —
Назначение: Кольцо кадров по времени и формат сегмента; сюда — менять вытеснение, закрепление, формат записи
API (0): —
Открытые задачи: нет
Коммиты (1 всего, последние 1):
  47e9778 2026-11-24 merge: тракт кадров gui — ящик, насос, метрики, дешёвый кадр, отложенная копия T5, штампы…
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 1, из них тестов 0
  Plugins/io/frame_buffer/plugin.py:38
  тесты: 0 файлов
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 10 из 10
  П3 __all__ у interfaces.py и __init__.py: 1 из 1
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card services/hikvision_camera

Команда: `atlas card services/hikvision_camera`

````text
Модуль services/hikvision_camera — services, ярус —
Назначение: Сервис промышленной камеры Hikvision: SDK, логика, плагин; сюда — менять работу с камерой
API (1): HikvisionCameraProtocol
Открытые задачи (3 планов, 58 задач):
  camera-device-service — 23: 1.2, 1.3, 1.4, 1.7, 2.3a, 2.3b, … ещё 17
  multicam-observability — 4: W1-a, W1-a2, W1-b, W1-c
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
Коммиты (27 всего, последние 5):
  f2e08bb 2026-11-25 merge: W1-a и W1-a2 — личность камеры и здоровье потока в integ/multicam-obs
  e0c7e00 2026-11-25 fix(hikvision_camera): исключение SDK в open освобождает handle
  6d6660b 2026-11-25 feat(hikvision_camera): W1-a2 — порт mvs: личность и поля кадра
  47e9778 2026-11-24 merge: тракт кадров gui — ящик, насос, метрики, дешёвый кадр, отложенная копия T5, штампы…
  c27a8e2 2026-11-24 merge: docs/camera-4.2d-4.2e-status — рецепт hikvision_id3013_quad (4.2i): две камеры MVS…
Находки (1):
  info INTERFACE_WITHOUT_TEST interface:services/hikvision_camera:HikvisionCameraProtocol -
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 10, из них тестов 6
  Plugins/hub/device_hub/plugin.py:1260
  Plugins/sources/camera_service/backends/hikvision.py:17
  Services/code_reader/tools/id3000_discover.py:45
  Services/device_hub/drivers/hikvision_driver.py:40
  тесты: 6 файлов, первые 3: Services/device_hub/tests/test_hikvision_driver.py, multiprocess_prototype/frontend/widgets/tabs/services/hikvision/tests/test_hikvision_commands.py, multiprocess_prototype/frontend/widgets/tabs/services/hikvision/tests/test_hikvision_presenter_m3.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 1
  П2 docstring Google у публичного API: 18 из 25
  П3 __all__ у interfaces.py и __init__.py: 4 из 5
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card services/layer_render

Команда: `atlas card services/layer_render`

````text
Модуль services/layer_render — services, ярус —
Назначение: Слои сцены: фон, объект, пресет, каталог классов; сюда — менять сборку кадра из слоёв
API (2): ScrollingTile, SolidFill
Открытые задачи (1 планов, 7 задач):
  layer-render — 7: 3.1, 3.2, 4.1, 4.2, 5.1, 5.2, … ещё 1
Коммиты (16 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  91d595e 2026-10-14 merge: layer-render 6.2 — LayerSceneGenerator, обучающие сэмплы любого продукта из слоёв …
  6348d35 2026-10-14 feat(dataset_gen): LayerSceneGenerator — обучающие сэмплы из пресета слоёв, секция train
  4ce905e 2026-10-03 merge: layer-render волны 3–6 — Ф2 ядро layer_render закрыта (1.4, 2.2–2.5, 6.1, 6.4)
  0fbb79e 2026-10-03 feat(layer_render): Task 2.5 — render_scene, одна функция кадра; SceneCompositor делегиру…
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 29, из них тестов 10
  Plugins/processing/center_crop/plugin.py:28
  Plugins/sim/scene_source/plugin.py:83
  Services/dataset_gen/core/augment.py:29
  Services/dataset_gen/core/backgrounds.py:10
  Services/dataset_gen/core/catalog.py:9
  Services/dataset_gen/core/compose.py:11
  Services/dataset_gen/core/config.py:20
  Services/dataset_gen/core/layer_scene.py:40
  Services/dataset_gen/core/metadata.py:8
  Services/dataset_gen/core/symmetry.py:23
  … ещё 9
  тесты: 10 файлов, первые 3: Plugins/sim/scene_source/tests/test_scene_source_hazards_r1.py, Services/dataset_gen/tests/test_acceptance_6_2_layer_scene.py, Services/dataset_gen/tests/test_augment_equivalence.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 64 из 69
  П3 __all__ у interfaces.py и __init__.py: 1 из 2
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 2
````

### card services/line_sim

Команда: `atlas card services/line_sim`

````text
Модуль services/line_sim — services, ярус —
Назначение: Объект-агностичный движок сцены лента с объектами; сюда — менять симуляцию ленты
API (8): AUGMENT_FIELDS, LayerAugment, LayerMode, LayerSpec, ObjectPassport, RangeF, SceneCompositorProtocol, SpriteSource
Открытые задачи (3 планов, 12 задач):
  line-sim — 4: 4.1, 4.2, 4.3, 6.4
  layer-render — 7: 3.1, 3.2, 4.1, 4.2, 5.1, 5.2, … ещё 1
  letters-retrain — 1: 0.4
Коммиты (56 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  8499ae6 2026-10-14 merge: layer-render 6.3 — CLI экспорта обучающих вырезов, секция train первого продукта, …
  f80419f 2026-10-13 merge: line-sim 6.5 — ассеты стенда из закоммиченных фикстур одной командой, плитка 410x4…
  4ce905e 2026-10-03 merge: layer-render волны 3–6 — Ф2 ядро layer_render закрыта (1.4, 2.2–2.5, 6.1, 6.4)
  0fbb79e 2026-10-03 feat(layer_render): Task 2.5 — render_scene, одна функция кадра; SceneCompositor делегиру…
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 25, из них тестов 23
  Plugins/sim/layer_preview/plugin.py:72
  Plugins/sim/scene_source/plugin.py:84
  тесты: 23 файлов, первые 3: Plugins/sim/layer_preview/tests/test_acceptance_1_3h_c_sprites.py, Plugins/sim/layer_preview/tests/test_acceptance_1_3h_d_sprite_put.py, Plugins/sim/layer_preview/tests/test_acceptance_1_3h_layout.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 26 из 27
  П3 __all__ у interfaces.py и __init__.py: 3 из 3
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card services/ml_inference

Команда: `atlas card services/ml_inference`

````text
Модуль services/ml_inference — services, ярус —
Назначение: Инференс нейросетей для pipeline: кадр на входе, классы и confidence на выходе; сюда — менять инференс
API (2): InferenceBackend, ModelCatalog
Открытые задачи (1 планов, 1 задач):
  letters-retrain — 1: 0.4
Коммиты (12 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  2b4af02 2026-11-02 merge: C-64, C-66, C-79, C-65 — дефекты полосы Ф к приёмке 6а
  b5adf82 2026-10-27 merge: полоса С — C-53, C-54 импорты framework, C-55a venv-guard, C-55b ассеты ml_inferen…
  d39ca7b 2026-10-26 merge: C-40 — ml_inference распознаёт каждый кадр, inference_every_n убран
  7e6e7a1 2026-10-01 Merge branch 'main' into feat/layer-render
Находки (2):
  info INTERFACE_WITHOUT_TEST interface:services/ml_inference:InferenceBackend -
  info INTERFACE_WITHOUT_TEST interface:services/ml_inference:ModelCatalog -
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 7, из них тестов 3
  Services/ml_train/holdout_eval.py:37
  multiprocess_prototype/frontend/forms/model_picker.py:20
  multiprocess_prototype/frontend/widgets/tabs/services/neural/ml_inference_section.py:75
  scripts/letters_baseline.py:506
  тесты: 3 файлов, первые 3: Plugins/processing/word_layout/tests/test_c86a_silent_drop_acceptance.py, Plugins/processing/word_layout/tests/test_ml_chain_c40.py, Services/ml_train/tests/test_trainer_export.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 4
  П2 docstring Google у публичного API: 32 из 32
  П3 __all__ у interfaces.py и __init__.py: 3 из 4
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card services/ml_train

Команда: `atlas card services/ml_train`

````text
Модуль services/ml_train — services, ярус —
Назначение: Обучение классификаторов и выбор лучшей модели по метрикам; сюда — менять обучение и сравнение прогонов
API (3): ModelExporter, RunSource, TrainSample
Открытые задачи: нет
Коммиты (12 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  4ce905e 2026-10-03 merge: layer-render волны 3–6 — Ф2 ядро layer_render закрыта (1.4, 2.2–2.5, 6.1, 6.4)
  e18d22d 2026-10-02 feat(ml_train): слияние — Task 6.4 holdout_eval на формуле конвейера в feat/layer-render
  f9ef5c4 2026-10-02 merge: Task 6.1 — одна функция выреза crop.py для center_crop и holdout_eval (ревью ит.2 …
  23184cc 2026-08-09 feat(observability): merge — влить observability-unified-routing — Ф0–Ф8 наблюдаемости
Находки (3):
  info INTERFACE_WITHOUT_TEST interface:services/ml_train:ModelExporter -
  info INTERFACE_WITHOUT_TEST interface:services/ml_train:RunSource -
  info INTERFACE_WITHOUT_TEST interface:services/ml_train:TrainSample -
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 2, из них тестов 1
  multiprocess_prototype/frontend/widgets/tabs/services/neural/ml_train_section.py:117
  тесты: 1 файлов, первые 3: Services/dataset_gen/tests/test_acceptance_6_3_export_cli.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 3
  П2 docstring Google у публичного API: 17 из 19
  П3 __all__ у interfaces.py и __init__.py: 1 из 2
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 1 из 5
````

### card services/modbus

Команда: `atlas card services/modbus`

````text
Модуль services/modbus — services, ярус —
Назначение: Драйвер Modbus-TCP и RS485 для связи с PLC; сюда — менять обмен по Modbus
API (2): ModbusClientProtocol, RegisterTransport
Открытые задачи (2 планов, 16 задач):
  device-tree-recipe — 3: B2, E1, V1
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
Коммиты (13 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  3dc5d53 2026-10-21 merge: fix/c18-modbus-demo в main — C-18, удалён заброшенный рецепт modbus_demo
  dea6f4f 2026-08-12 fix(services): недоступное устройство уведомляет один раз, а не на каждой попытке
  6056aa0 2026-08-10 fix(observability): D7 — в консоли остаётся один писатель
  619562c 2026-06-12 fix: conn/io_peek через set (merge ломал доставку) + тихая консоль Modbus
Находки (1):
  info INTERFACE_WITHOUT_TEST interface:services/modbus:ModbusClientProtocol -
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 34, из них тестов 19
  Plugins/sim/robot_host/plugin.py:377
  Plugins/sinks/modbus_sink/plugin.py:29
  Services/device_hub/manager.py:961
  Services/device_hub/transports.py:20
  Services/robot_comm/__init__.py:32
  Services/robot_comm/core/client.py:28
  Services/robot_comm/core/config.py:13
  Services/robot_comm/core/registers.py:16
  Services/robot_comm/server/sim_core.py:27
  Services/robot_comm/server/sim_journal.py:72
  … ещё 5
  тесты: 19 файлов, первые 3: Plugins/sim/robot_host/tests/host_harness.py, Plugins/sim/robot_host/tests/test_job_done_wiring_lead.py, Plugins/sim/robot_host/tests/test_v2_host.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 2
  П2 docstring Google у публичного API: 64 из 64
  П3 __all__ у interfaces.py и __init__.py: 6 из 7
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card services/otel_export

Команда: `atlas card services/otel_export`

````text
Модуль services/otel_export — services, ярус —
Назначение: Экспорт записей наблюдаемости наружу по OTLP; сюда — менять маппинг и отправку данных наблюдаемости
API (8): ExportOutcome, FlushOutcome, LogExporter, MappedRecord, ObservabilityPort, RecordMapper, Resource, ResourceResolver
Открытые задачи (2 планов, 19 задач):
  otel-export — 8: 2.5, 3.1, 3.2, 3.3, 3.4, 4.1, … ещё 2
  gui-service — 11: 1.4, 1b.2b, 1b.2c, 1b.3, 1b.4, 2.1, … ещё 5
Коммиты (13 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  68a8ba2 2026-10-03 merge: Task 5.5c — весь make gate зелёный (ruff, pyright, bandit -ll, корневой pytest, те…
  a38756a 2026-10-02 fix(registers): set_field_value на регистре без apply_values возвращает кортеж
  c4dc0bc 2026-10-02 feat(data_schema): правила регистров данными в FieldMeta + атомарная запись
  da9219f 2026-09-08 merge: otel (97bb1c10) в main — Ф2 закрыта, доставка наружу наконец доказана
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 8, из них тестов 6
  Plugins/io/otel_export/plugin.py:102
  Plugins/io/otel_export/registers.py:41
  тесты: 6 файлов, первые 3: Plugins/io/otel_export/tests/conftest.py, Plugins/io/otel_export/tests/test_f2_task21_acceptance.py, Plugins/io/otel_export/tests/test_f2_task21_hazards.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 1
  П2 docstring Google у публичного API: 17 из 17
  П3 __all__ у interfaces.py и __init__.py: 1 из 1
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card services/phone_gateway

Команда: `atlas card services/phone_gateway`

````text
Модуль services/phone_gateway — services, ярус —
Назначение: Приём фото и слов с телефона по WiFi через браузер; сюда — менять приём данных с телефона
API (1): FrameSource
Открытые задачи: нет
Коммиты (3 всего, последние 3):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  8166456 2026-06-16 feat(pult): выбор режима робота + стабильность телефона + dry_run off
  68beb69 2026-06-15 feat(services): сервис phone_gateway — фото/слово/сигналы с телефона по WiFi
Находки (1):
  info INTERFACE_WITHOUT_TEST interface:services/phone_gateway:FrameSource -
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 2, из них тестов 1
  multiprocess_prototype/frontend/widgets/tabs/services/phone/section.py:20
  тесты: 1 файлов, первые 3: Plugins/processing/word_layout/tests/test_word_source_chain.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 1
  П2 docstring Google у публичного API: 16 из 16
  П3 __all__ у interfaces.py и __init__.py: 1 из 2
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card services/robot_comm

Команда: `atlas card services/robot_comm`

````text
Модуль services/robot_comm — services, ярус —
Назначение: Сервис робота Delta поверх Modbus: карта регистров, доменные методы; сюда — менять управление роботом
API (2): DeviceTransport, RobotClientProtocol
Открытые задачи (3 планов, 20 задач):
  line-sim — 4: 4.1, 4.2, 4.3, 6.4
  robot-protocol-v2 — 13: T0.3, T4.0, T4.1, T4.5, T4.6, T5.3, … ещё 7
  device-tree-recipe — 3: B2, E1, V1
Коммиты (52 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  a178e0b 2026-10-21 merge: fix/robot-v2-c11-logger в main — C-11, логгер line_source через logger_module
  b4a0084 2026-10-20 merge: feat/robot-v2-t53cd в main — T5.3c/d, команды робота v2 через хаб, живой стенд
  0a4b07a 2026-10-19 merge: feat/robot-v2-t53 в main — T5.3a+b, один владелец потоков робота и стоп под одним …
  7fc7c3b 2026-10-18 merge: feat/robot-v2-t38 в main — T3.8 вид робота из состояния линии (--line)
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 95, из них тестов 74
  Plugins/hub/device_hub/plugin.py:44
  Plugins/io/robot_draw/plugin.py:199
  Plugins/sim/robot_host/plugin.py:70
  Services/device_hub/drivers/exchange_log.py:45
  Services/device_hub/drivers/robot_driver.py:120
  Services/device_hub/drivers/robot_driver_v2/args.py:17
  Services/device_hub/drivers/robot_driver_v2/driver.py:102
  Services/device_hub/drivers/robot_driver_v2/jobs.py:23
  Services/device_hub/drivers/robot_driver_v2/jog.py:25
  Services/device_hub/drivers/robot_driver_v2/ops.py:48
  … ещё 11
  тесты: 74 файлов, первые 3: Plugins/calibration/camera_robot/tests/test_sim_integration.py, Plugins/calibration/camera_robot/tests/test_v2_driver_contract.py, Plugins/hub/device_hub/tests/conftest.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 3
  П2 docstring Google у публичного API: 95 из 95
  П3 __all__ у interfaces.py и __init__.py: 7 из 8
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 2
````

### card services/sql

Команда: `atlas card services/sql`

````text
Модуль services/sql — services, ярус —
Назначение: Универсальный SQL-менеджер на SQLAlchemy: PostgreSQL, MySQL, SQLite; сюда — менять доступ к БД
API (8): IAsyncEngineAdapter, IAsyncUnitOfWork, IEngineAdapter, IRepository, ISQLManager, ISchemaMapper, ISyncEngineAdapter, IUnitOfWork
Открытые задачи (1 планов, 31 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
Коммиты (20 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  4bd81f4 2026-10-13 merge: lifecycle-owner-scope 1.2b-3 — Services и прототип на _on_shutdown, принуждение Р1…
  68a8ba2 2026-10-03 merge: Task 5.5c — весь make gate зелёный (ruff, pyright, bandit -ll, корневой pytest, те…
  1619de7 2026-09-01 feat(observability): Task 1.3b — 46 адресов на один разъём; классы отказа; разводка имён …
  e1396c4 2026-08-12 feat(services): env-ручки Services читаются парой, канон первым (5.2, Р-5а)
Находки (8):
  info INTERFACE_WITHOUT_TEST interface:services/sql:IAsyncEngineAdapter -
  info INTERFACE_WITHOUT_TEST interface:services/sql:IAsyncUnitOfWork -
  info INTERFACE_WITHOUT_TEST interface:services/sql:IEngineAdapter -
  info INTERFACE_WITHOUT_TEST interface:services/sql:IRepository -
  info INTERFACE_WITHOUT_TEST interface:services/sql:ISQLManager -
  info INTERFACE_WITHOUT_TEST interface:services/sql:ISchemaMapper -
  info INTERFACE_WITHOUT_TEST interface:services/sql:ISyncEngineAdapter -
  info INTERFACE_WITHOUT_TEST interface:services/sql:IUnitOfWork -
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 10, из них тестов 5
  Plugins/io/database/plugin.py:34
  Plugins/io/telemetry_sink/plugin.py:44
  Services/auth/storage/audit_storage.py:34
  Services/documents/store.py:16
  Services/documents/wiring.py:24
  тесты: 5 файлов, первые 3: Plugins/io/database/tests/test_database_plugin.py, Plugins/io/telemetry_sink/tests/test_telemetry_sink_plugin.py, Services/documents/tests/test_contract.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 29
  П2 docstring Google у публичного API: 104 из 109
  П3 __all__ у interfaces.py и __init__.py: 7 из 8
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 4
````

### card services/vfd_comm

Команда: `atlas card services/vfd_comm`

````text
Модуль services/vfd_comm — services, ярус —
Назначение: Сервис частотного преобразователя INVT GD20, не зависит от транспорта; сюда — менять управление ПЧ
API (1): VfdClientProtocol
Открытые задачи: нет
Коммиты (5 всего, последние 5):
  a7952d2 2026-11-24 merge: feat/pult-belt-speed — память частоты ленты ПЧ, belt_freq в рецептах симулятора
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  9e2f349 2026-06-11 chore(services): удалить runtime-владение robot_comm и плагины vfd_control/robot_draw + d…
  32cdf2f 2026-06-11 feat(modbus): YAML-протоколы устройств — загрузчик RegisterMap + RegisterMeta
  669abbf 2026-06-11 feat(vfd_comm): сервис ПЧ GD20 поверх RegisterTransport (мост через робота)
Находки (1):
  info INTERFACE_WITHOUT_TEST interface:services/vfd_comm:VfdClientProtocol -
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 7, из них тестов 5
  Services/device_hub/drivers/vfd_driver.py:105
  Services/robot_comm/server/sim_core_v2.py:248
  тесты: 5 файлов, первые 3: Services/device_hub/tests/test_vfd_driver_reconnect.py, Services/robot_comm/tests/test_parity_universal3.py, Services/robot_comm/tests/test_sim_e2e_v2.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 1
  П2 docstring Google у публичного API: 29 из 29
  П3 __all__ у interfaces.py и __init__.py: 2 из 3
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card plugins/calibration

Команда: `atlas card plugins/calibration`

````text
Модуль plugins/calibration — plugins, ярус —
Назначение: Плагины калибровки (камера и робот и др.); сюда — менять калибровочные плагины
API (0): —
Открытые задачи (1 планов, 1 задач):
  camera-robot-calibration — 1: F7
Коммиты (6 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  1619de7 2026-09-01 feat(observability): Task 1.3b — 46 адресов на один разъём; классы отказа; разводка имён …
  2f4e212 2026-07-07 Merge branch 'feat/constructor-f2'
  3f984ac 2026-06-15 feat(calibration): 3-шаговый визард + замеры энкодера E0/E1/E2
  b37cf88 2026-06-14 feat(prototype): калибровка камера↔робот — координаты точек + телеметрия через push
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 1, из них тестов 0
  Plugins/processing/pixel_to_robot/plugin.py:100
  тесты: 0 файлов
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 0 из 0
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card plugins/control

Команда: `atlas card plugins/control`

````text
Модуль plugins/control — plugins, ярус —
Назначение: Плагины управления внешними устройствами: роботы, IO, реле; сюда — менять управляющие плагины
API (0): —
Открытые задачи (1 планов, 2 задач):
  telemetry-stage6 — 2: 1.2, 3.5
Коммиты (14 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  9d8e5df 2026-10-05 merge: main в feat/lifecycle-owner-scope перед ревью Task 0.2 и стартом 0.3/0.4
  236ec9e 2026-10-02 feat(transport): слияние Task 5.2 — контракт привода в ветку фазы 5
  166c069 2026-10-02 Merge branch 'main' into feat/gs-1b2d
  338b48c 2026-08-31 feat(observability): Task 1.4 — общий механизм окна голосов, восемь ручных копий 5.0 схло…
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 1, из них тестов 1
  тесты: 1 файлов, первые 3: Plugins/io/database/tests/test_database_plugin.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 0 из 0
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card plugins/filter

Команда: `atlas card plugins/filter`

````text
Модуль plugins/filter — plugins, ярус —
Назначение: Плагины фильтрации и анализа координат (виртуальная линия и др.); сюда — менять фильтры координат
API (0): —
Открытые задачи (1 планов, 11 задач):
  gui-service — 11: 1.4, 1b.2b, 1b.2c, 1b.3, 1b.4, 2.1, … ещё 5
Коммиты (5 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  31ae256 2026-10-26 merge: C-42 — line_filter zone_edge одно событие на проход диска
  c4dc0bc 2026-10-02 feat(data_schema): правила регистров данными в FieldMeta + атомарная запись
  8166456 2026-06-16 feat(pult): выбор режима робота + стабильность телефона + dry_run off
  dd70e2d 2026-06-08 feat(filter): фильтр виртуальной линии + Join-корреляция + рендер overlay
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 4, из них тестов 4
  тесты: 4 файлов, первые 3: Plugins/processing/word_layout/tests/test_c86a_silent_drop_acceptance.py, Plugins/processing/word_layout/tests/test_disk_identity_chain.py, Plugins/processing/word_layout/tests/test_ml_chain_c40.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 0 из 0
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card plugins/hub

Команда: `atlas card plugins/hub`

````text
Модуль plugins/hub — plugins, ярус —
Назначение: Плагины-хабы (always-on сервисы устройств, device_hub); сюда — менять хаб устройств и его IPC-клиент
API (0): —
Открытые задачи (1 планов, 3 задач):
  device-tree-recipe — 3: B2, E1, V1
Коммиты (35 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  009e35f 2026-11-08 feat(device_hub): слияние T5.5 — draw_polyline и подача на роботе v2
  695b9ee 2026-10-27 merge: T5.3e.1–3 — команда robot_park (штатное «домой» до process.stop) и стенд v2
  4d9cf4c 2026-10-26 merge: SPI хаба — Protocol драйвера, OpSpec, команды из таблицы видов, device_io
  26534c1 2026-10-25 merge: fix/robot-v2-c29 в main — C-29, «Отключить» прерывает connect робота v2
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 18, из них тестов 12
  Plugins/calibration/camera_robot/plugin.py:39
  Plugins/io/robot_draw/plugin.py:32
  Plugins/io/robot_io/plugin.py:31
  Plugins/sim/pult_web/plugin.py:71
  Plugins/sim/robot_host/plugin.py:69
  Plugins/sources/camera_service/plugin.py:250
  тесты: 12 файлов, первые 3: Plugins/sim/pult_web/tests/test_acceptance_1_3h_d_route.py, Plugins/sim/pult_web/tests/test_error_code_through_real_client_acceptance.py, Plugins/sim/robot_host/tests/test_v2_line_cycle.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 1 из 1
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card plugins/io

Команда: `atlas card plugins/io`

````text
Модуль plugins/io — plugins, ярус —
Назначение: Плагины ввода-вывода: запись в БД, выгрузка кадров, экспорт; сюда — менять ввод-вывод
API (0): —
Открытые задачи (3 планов, 21 задач):
  observation-port — 2: 0.2, 2.4
  otel-export — 8: 2.5, 3.1, 3.2, 3.3, 3.4, 4.1, … ещё 2
  gui-service — 11: 1.4, 1b.2b, 1b.2c, 1b.3, 1b.4, 2.1, … ещё 5
Коммиты (47 всего, последние 5):
  47e9778 2026-11-24 merge: тракт кадров gui — ящик, насос, метрики, дешёвый кадр, отложенная копия T5, штампы…
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  68a8ba2 2026-10-03 merge: Task 5.5c — весь make gate зелёный (ruff, pyright, bandit -ll, корневой pytest, те…
  a38756a 2026-10-02 fix(registers): set_field_value на регистре без apply_values возвращает кортеж
  c4dc0bc 2026-10-02 feat(data_schema): правила регистров данными в FieldMeta + атомарная запись
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 6, из них тестов 6
  тесты: 6 файлов, первые 3: Plugins/hub/device_hub/tests/test_t55_plugins_v2_acceptance.py, Plugins/processing/word_layout/tests/test_p3_hazards.py, Services/otel_export/tests/test_contract.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 4 из 4
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 2 из 4
````

### card plugins/processing

Команда: `atlas card plugins/processing`

````text
Модуль plugins/processing — plugins, ярус —
Назначение: Плагины обработки кадров: фильтры, детекторы, преобразования; сюда — менять обработку кадров
API (0): —
Открытые задачи (4 планов, 9 задач):
  camera-robot-calibration — 1: F7
  letters-retrain — 1: 0.4
  pipeline-live-control — 5: 2.1, 2.2, 3.1, 3.2, 3.3
  word-layout — 2: P3, P4
Коммиты (47 всего, последние 5):
  f2304d4 2026-11-24 merge: fix/lane-t-win-baseline — красные Windows/Python 3.12 исправлены по причине, отчёт…
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  d39ca7b 2026-10-26 merge: C-40 — ml_inference распознаёт каждый кадр, inference_every_n убран
  31ae256 2026-10-26 merge: C-42 — line_filter zone_edge одно событие на проход диска
  7ad7d31 2026-10-26 merge: C-37 — регистр target_word одно хранилище слова word_layout
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 9, из них тестов 8
  scripts/letters_baseline.py:358
  тесты: 8 файлов, первые 3: Plugins/sim/robot_host/tests/test_v2_letter_straight.py, Plugins/tests/test_health_report_sites.py, Services/layer_render/tests/test_acceptance_6_1_crop.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 2 из 2
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card plugins/render

Команда: `atlas card plugins/render`

````text
Модуль plugins/render — plugins, ярус —
Назначение: Плагины отрисовки overlay и композитинга кадров для GUI; сюда — менять отрисовку
API (0): —
Открытые задачи (1 планов, 8 задач):
  code-reader-gui — 8: 1.1, 1.2, 2.1, 2.2a, 2.2b, 2.3, … ещё 2
Коммиты (9 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  09a925a 2026-10-21 merge: fix/c16-collector в main — C-16/C-17, Port.join отдельно от optional, join у draw …
  7e1640c 2026-10-15 feat(code-reader): кадр с рамкой и надписями из рецепта через общий overlay_draw
  45000ea 2026-06-13 feat(plugins): pipeline сбора датасета кругов — маска→круги→линия→crop→save
  454c4ff 2026-06-08 fix(filter): overlay_draw пишет в frame (дисплей читает frame, не rendered_frame)
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 1, из них тестов 1
  тесты: 1 файлов, первые 3: multiprocess_prototype/recipes/tests/test_qr_reader_sdk_demo.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 0 из 0
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card plugins/runtime

Команда: `atlas card plugins/runtime`

````text
Модуль plugins/runtime — plugins, ярус —
Назначение: Плагины-исполнители pipeline: chain executor, пулы воркеров; сюда — менять исполнение pipeline
API (0): —
Открытые задачи: нет
Коммиты (9 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  68a8ba2 2026-10-03 merge: Task 5.5c — весь make gate зелёный (ruff, pyright, bandit -ll, корневой pytest, те…
  7e4790e 2026-08-11 fix(framework): суб-контекст несёт весь протокол, дорога документов судится (4.2)
  23184cc 2026-08-09 feat(observability): merge — влить observability-unified-routing — Ф0–Ф8 наблюдаемости
  c87ec83 2026-07-11 Merge branch 'refactor/constructor-c6-levers-b-c': C6 (b)+(c) — extras+frame_trace рычаги…
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 0, из них тестов 0
  тесты: 0 файлов
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 0 из 0
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card plugins/sim

Команда: `atlas card plugins/sim`

````text
Модуль plugins/sim — plugins, ярус —
Назначение: Плагины-хосты симулятора линии; сервис держит логику, плагин жизненный цикл; сюда — менять хост симуляции
API (0): —
Открытые задачи (2 планов, 11 задач):
  line-sim — 4: 4.1, 4.2, 4.3, 6.4
  layer-render — 7: 3.1, 3.2, 4.1, 4.2, 5.1, 5.2, … ещё 1
Коммиты (62 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  7fc7c3b 2026-10-18 merge: feat/robot-v2-t38 в main — T3.8 вид робота из состояния линии (--line)
  dc209d6 2026-10-14 merge: robot-protocol-v2 T3.7 — стенд линии на протоколе v2, enqueue_job/return_job у Rob…
  0c38542 2026-10-13 merge: robot-protocol-v2 T3.5b — тесты T2.4 хоста robot_host на клиент v2, водитель удалён
  1b69f4f 2026-10-12 merge: sim v2 на фреймворке — SC_RUN, CVT_JOB, таймер, мост ПЧ в ядре и хост protocol v2 …
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 5, из них тестов 5
  тесты: 5 файлов, первые 3: Plugins/hub/device_hub/tests/test_reply_envelope_acceptance.py, Services/robot_comm/tests/_t38_line_host.py, Services/robot_comm/tests/test_t38_line_view_acceptance.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 4 из 4
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card plugins/sinks

Команда: `atlas card plugins/sinks`

````text
Модуль plugins/sinks — plugins, ярус —
Назначение: Плагины-приёмники: вывод и экспорт данных из конца цепочки; сюда — менять приёмники данных
API (0): —
Открытые задачи: нет
Коммиты (6 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  1619de7 2026-09-01 feat(observability): Task 1.3b — 46 адресов на один разъём; классы отказа; разводка имён …
  2f4e212 2026-07-07 Merge branch 'feat/constructor-f2'
  4bf240d 2026-06-01 feat(prototype): рецепт color_inspect (цвет→контур→линия+площадь по Modbus) активным
  6985ac7 2026-06-01 feat(plugins): универсальный payload в modbus_sink (любые поля, u16/u32, редьюсеры)
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 0, из них тестов 0
  тесты: 0 файлов
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 0 из 0
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card plugins/sources

Команда: `atlas card plugins/sources`

````text
Модуль plugins/sources — plugins, ярус —
Назначение: Плагины источников данных: камеры, файлы, генераторы; сюда — менять источники
API (0): —
Открытые задачи (3 планов, 17 задач):
  telemetry-stage6 — 2: 1.2, 3.5
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
  observation-port — 2: 0.2, 2.4
Коммиты (26 всего, последние 5):
  47e9778 2026-11-24 merge: тракт кадров gui — ящик, насос, метрики, дешёвый кадр, отложенная копия T5, штампы…
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  68a8ba2 2026-10-03 merge: Task 5.5c — весь make gate зелёный (ruff, pyright, bandit -ll, корневой pytest, те…
  08b2251 2026-09-30 test: снять недействующие pytest.mark.timeout по репо (R-6)
  7448402 2026-09-22 merge: line-sim (c2bc060d) в main — Ф0–Ф2 на границе Ф2, шаг 0 очереди 09-22
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 7, из них тестов 5
  multiprocess_prototype/frontend/widgets/tabs/plugins/sandbox.py:525
  multiprocess_prototype/frontend/widgets/tabs/services/camera/widget.py:28
  тесты: 5 файлов, первые 3: backend_ctl/tests/test_probe_acceptance_profiles.py, multiprocess_framework/modules/process_module/tests/test_error_plane_one_connector_capture_acceptance.py, multiprocess_framework/modules/process_module/tests/test_observation_namespace_acceptance.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 1 из 1
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card plugins/utility

Команда: `atlas card plugins/utility`

````text
Модуль plugins/utility — plugins, ярус —
Назначение: Служебные и тестовые плагины (heartbeat, pilot_widgets и др.); сюда — менять служебные плагины
API (0): —
Открытые задачи: нет
Коммиты (6 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  0550f04 2026-05-15 feat(bridge): multi-target fan-out по FieldRouting.process_targets
  92d9ddc 2026-05-15 feat(plugins): pilot_widgets — стенд для всех видов виджетов
  f959b50 2026-05-15 feat(plugins): pilot_widgets — рабочий путь GUI↔plugin, FieldMeta.widget Literal
  6f1c24b 2026-05-15 fix(plugins): pilot_widgets реагирует на toggle через IPC (set_config)
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 0, из них тестов 0
  тесты: 0 файлов
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 0 из 0
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card framework_meta

Команда: `atlas card framework_meta`

````text
Модуль framework_meta — framework, ярус —
Назначение: Корневые файлы пакета фреймворка и его документация; сюда — менять версию, общие импорты, доки фреймворка
API (0): —
Открытые задачи (7 планов, 83 задач):
  observation-port — 2: 0.2, 2.4
  telemetry-stage6 — 2: 1.2, 3.5
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
  frontend-constructor — 18: T2.0, T3.0, T3.1, T3.2, T3.3, T3.4, … ещё 12
  … ещё 2 планов
Коммиты (108 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  287cb8d 2026-11-06 docs(recipe): C-30 1.3 — ADR-RCP-009/010, README/STATUS, OPEN_QUESTIONS, sync
  751ba0d 2026-10-21 merge: feat/lifecycle-executor-manager в main — Task 1.9m, ExecutorManager
  4bd81f4 2026-10-13 merge: lifecycle-owner-scope 1.2b-3 — Services и прототип на _on_shutdown, принуждение Р1…
  005df13 2026-10-13 merge: lifecycle-owner-scope 1.2b-2 — кодмод 23 классов в _on_shutdown, срок второго вызо…
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 65, из них тестов 37
  Services/documents/wiring.py:23
  multiprocess_framework/modules/base_manager/adapters/base_adapter.py:10
  multiprocess_framework/modules/base_manager/core/base_manager.py:9
  multiprocess_framework/modules/channel_routing_module/core/channel_registry.py:22
  multiprocess_framework/modules/channel_routing_module/core/channel_routing_manager.py:27
  multiprocess_framework/modules/channel_routing_module/observability/observability_store.py:42
  multiprocess_framework/modules/command_module/interfaces.py:11
  multiprocess_framework/modules/data_schema_module/core/field_meta.py:36
  multiprocess_framework/modules/data_schema_module/core/metrics.py:20
  multiprocess_framework/modules/dispatch_module/interfaces.py:11
  … ещё 18
  тесты: 37 файлов, первые 3: Plugins/io/otel_export/tests/conftest.py, Plugins/sim/robot_host/tests/conftest.py, Plugins/sources/capture/tests/test_plugin.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 1 из 1
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card services_shared

Команда: `atlas card services_shared`

````text
Модуль services_shared — services, ярус —
Назначение: Корневой пакет Services и его STATUS; общий уровень сервисов
API (0): —
Открытые задачи: нет
Коммиты (1 всего, последние 1):
  2e829a5 2026-04-30 clean: fresh start without large files in history
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 0, из них тестов 0
  тесты: 0 файлов
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 0 из 0
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card plugins_shared

Команда: `atlas card plugins_shared`

````text
Модуль plugins_shared — plugins, ярус —
Назначение: Общие доменные утилиты нескольких плагинов, сами не плагины; сюда — менять общий код плагинов
API (0): —
Открытые задачи (1 планов, 13 задач):
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
Коммиты (5 всего, последние 5):
  ddc5a0c 2026-10-01 Merge branch 'main' into feat/layer-render
  2942c94 2026-08-10 refactor(framework): D4 — фреймворк перестаёт быть инспектором
  f0968ca 2026-07-16 chore(main): слить feat/webcam-sketch-perf — Ф7 webcam + dev-тулинг
  c87ec83 2026-07-11 Merge branch 'refactor/constructor-c6-levers-b-c': C6 (b)+(c) — extras+frame_trace рычаги…
  45d70cc 2026-05-10 fix(tests): X.1 — переписать test_plugin_context_gets_state_proxy на новый PluginContext …
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 1, из них тестов 1
  тесты: 1 файлов, первые 3: multiprocess_prototype/frontend/widgets/tabs/plugins/tests/test_sandbox_e2e.py
Правила ADR-175 (рекомендация; находки не поднимаются):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 1 из 1
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card prototype/adapters

Команда: `atlas card prototype/adapters`

````text
Модуль prototype/adapters — prototype, ярус —
Назначение: Adapter-слой между domain Protocols и реестрами фреймворка; сюда — менять привязку domain к реестрам
API (0): —
Открытые задачи (4 планов, 48 задач):
  gui-service — 11: 1.4, 1b.2b, 1b.2c, 1b.3, 1b.4, 2.1, … ещё 5
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  lifecycle-stop-ownership — 2: T1.9c, T1.10
  recipe-orchestrator-unify — 4: 1.2, 2.0, 2.1, 2.3
Коммиты (53 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  976aa88 2026-11-06 merge: C-30 частичная волна — Save редактора владеет только своим, Камера пишет через мод…
  4e53312 2026-11-02 fix(recipes): C-30 1.14 — Save владеет только непротектед-процессами, rev раньше ссылок
  9e94f12 2026-10-28 feat(displays): C-30 1.11 — Дисплеи пишут рецепт с базой сессии
  b2e1298 2026-10-27 merge: C-30 промежуточно 11/17 — дельта-движок рецепта, канон, ревизия, Save одной записью
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 25, из них тестов 20
  multiprocess_prototype/frontend/actions/bus_factory.py:25
  multiprocess_prototype/frontend/actions/handlers/recipe_handler.py:11
  multiprocess_prototype/frontend/app.py:368
  multiprocess_prototype/frontend/app_services_factory.py:41
  multiprocess_prototype/recipes/save.py:371
  тесты: 20 файлов, первые 3: multiprocess_prototype/frontend/actions/tests/test_handlers.py, multiprocess_prototype/frontend/actions/tests/test_topology_mutation_handler.py, multiprocess_prototype/frontend/tests/test_action_bus_v2.py
Правила ADR-175: вне охвата (слой prototype)
````

### card prototype/backend

Команда: `atlas card prototype/backend`

````text
Модуль prototype/backend — prototype, ярус —
Назначение: Backend прототипа: конфигурация системы и топология процессов и плагинов; сюда — менять wiring системы
API (0): —
Открытые задачи (10 планов, 97 задач):
  telemetry-stage6 — 2: 1.2, 3.5
  observation-port — 2: 0.2, 2.4
  recipe-orchestrator-unify — 4: 1.2, 2.0, 2.1, 2.3
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
  … ещё 5 планов
Коммиты (136 всего, последние 5):
  a7952d2 2026-11-24 merge: feat/pult-belt-speed — память частоты ленты ПЧ, belt_freq в рецептах симулятора
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  6cb2122 2026-11-22 feat(camera): слияние К4' — плагин hikvision на ядре camera_device, цвет BGR, рецепты, вк…
  220bd75 2026-11-09 feat(prototype): влить Task 1.4m — манифест pre_stop в system.yaml, шаг «домой» robot_par…
  da3febe 2026-10-28 merge: C-76 — лаунчер Windows держит дерево приложения в Job Object, сирот нет
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 55, из них тестов 45
  backend_ctl/harness.py:114
  backend_ctl/probes/probe_5_11_subscription_broker.py:151
  backend_ctl/probes/probe_5_11h_watch_migration.py:131
  backend_ctl/probes/probe_5_13_orchestrator_layer.py:103
  multiprocess_prototype/frontend/app.py:50
  multiprocess_prototype/frontend/widgets/tabs/pipeline/recipe_io.py:29
  multiprocess_prototype/frontend/widgets/tabs/settings/system/presenter.py:32
  multiprocess_prototype/frontend/widgets/tabs/settings/yaml_io.py:15
  multiprocess_prototype/main.py:25
  multiprocess_prototype/orchestrator.py:29
  тесты: 45 файлов, первые 3: backend_ctl/tests/test_catalog_plugins_live.py, backend_ctl/tests/test_fault_injection_live.py, backend_ctl/tests/test_frame_bridge_live.py
Правила ADR-175: вне охвата (слой prototype)
````

### card prototype/domain

Команда: `atlas card prototype/domain`

````text
Модуль prototype/domain — prototype, ярус —
Назначение: Изолированный типизированный domain-слой: frozen-сущности и исключения; сюда — менять доменные сущности
API (0): —
Открытые задачи (3 планов, 45 задач):
  camera-robot-calibration — 1: F7
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
Коммиты (60 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  976aa88 2026-11-06 merge: C-30 частичная волна — Save редактора владеет только своим, Камера пишет через мод…
  5bdf8a2 2026-11-02 fix(recipes): C-30 1.14b — фундамент для Save определяется по именам manifest.base
  59c7ce6 2026-10-28 feat(session): C-30 1.12 — флаг layout_unsaved в диалоге закрытия
  cc4b18d 2026-10-28 merge: C-30 промежуточно 13/17 — базовый rev редактора в TopologySession, Устройства пишу…
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 136, из них тестов 84
  multiprocess_prototype/adapters/catalogs/display_catalog.py:28
  multiprocess_prototype/adapters/catalogs/display_catalog_recipe.py:32
  multiprocess_prototype/adapters/catalogs/plugin_catalog.py:27
  multiprocess_prototype/adapters/catalogs/remote_plugin_catalog.py:22
  multiprocess_prototype/adapters/catalogs/remote_service_manager.py:25
  multiprocess_prototype/adapters/catalogs/service_catalog.py:39
  multiprocess_prototype/adapters/dispatch/command_dispatcher.py:36
  multiprocess_prototype/adapters/dispatch/history.py:23
  multiprocess_prototype/adapters/dispatch/project_holder.py:19
  multiprocess_prototype/adapters/recipe_canonical.py:41
  … ещё 42
  тесты: 84 файлов, первые 3: multiprocess_prototype/adapters/tests/test_auth_facade.py, multiprocess_prototype/adapters/tests/test_catalogs.py, multiprocess_prototype/adapters/tests/test_command_dispatcher.py
Правила ADR-175: вне охвата (слой prototype)
````

### card prototype/frontend

Команда: `atlas card prototype/frontend`

````text
Модуль prototype/frontend — prototype, ярус —
Назначение: GUI-пакет прототипа: Qt-презентация PySide6 поверх бэкенда; сюда — менять экраны и GUI прототипа
API (0): —
Открытые задачи (15 планов, 128 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  observation-port — 2: 0.2, 2.4
  pipeline-live-control — 5: 2.1, 2.2, 3.1, 3.2, 3.3
  telemetry-self-publish-redesign — 2: 2, 3
  command-result-bridge — 1: P4
  … ещё 10 планов
Коммиты (222 всего, последние 5):
  47e9778 2026-11-24 merge: тракт кадров gui — ящик, насос, метрики, дешёвый кадр, отложенная копия T5, штампы…
  7552021 2026-11-24 merge: chore/qt-mcp-probe-hook — проба qt-mcp в gui, один путь QT_MCP_PROBE/QT_MCP_PORT
  4a62859 2026-11-23 feat(hikvision_camera): 4.2d — gain_auto и enabled_if у gain и exposure_time
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  6cb2122 2026-11-22 feat(camera): слияние К4' — плагин hikvision на ядре camera_device, цвет BGR, рецепты, вк…
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 67, из них тестов 37
  multiprocess_prototype/frontend/widgets/access/permission_gate.py:45
  multiprocess_prototype/frontend/widgets/chrome/login_button.py:15
  multiprocess_prototype/frontend/widgets/chrome/run_control.py:30
  multiprocess_prototype/frontend/widgets/dialogs/login_dialog.py:30
  multiprocess_prototype/frontend/widgets/dialogs/unsaved_changes.py:22
  multiprocess_prototype/frontend/widgets/tabs/__init__.py:17
  multiprocess_prototype/frontend/widgets/tabs/displays/tab.py:72
  multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/hikvision_embed.py:29
  multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/params_form_section.py:156
  multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py:35
  … ещё 20
  тесты: 37 файлов, первые 3: Services/auth/tests/test_role_update_handler.py, multiprocess_prototype/adapters/tests/test_catalog_registers_editing_acceptance.py, multiprocess_prototype/adapters/tests/test_display_catalog_session_blind.py
Правила ADR-175: вне охвата (слой prototype)
````

### card prototype/recipes

Команда: `atlas card prototype/recipes`

````text
Модуль prototype/recipes — prototype, ярус —
Назначение: Управление рецептами прототипа: RecipeManager и миграции форматов; сюда — менять рецепты прототипа
API (0): —
Открытые задачи (6 планов, 42 задач):
  qr-code-reader — 14: 0.1, 1.1, 1.2, 1.3, 1.4, 1.5, … ещё 8
  recipe-orchestrator-unify — 4: 1.2, 2.0, 2.1, 2.3
  camera-robot-calibration — 1: F7
  code-reader-gui — 8: 1.1, 1.2, 2.1, 2.2a, 2.2b, 2.3, … ещё 2
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
  … ещё 1 планов
Коммиты (105 всего, последние 5):
  47e9778 2026-11-24 merge: тракт кадров gui — ящик, насос, метрики, дешёвый кадр, отложенная копия T5, штампы…
  c27a8e2 2026-11-24 merge: docs/camera-4.2d-4.2e-status — рецепт hikvision_id3013_quad (4.2i): две камеры MVS…
  e1e4288 2026-11-24 merge: docs/camera-4.2d-4.2e-status — рецепт hikvision_id3013_view (4.2g): камера MVS + д…
  5680c9c 2026-11-24 merge: docs/camera-4.2d-4.2e-status — тестовый рецепт hikvision_id3013_test (4.2f), оценк…
  a7952d2 2026-11-24 merge: feat/pult-belt-speed — память частоты ленты ПЧ, belt_freq в рецептах симулятора
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 19, из них тестов 10
  multiprocess_prototype/adapters/stores/recipe_store.py:40
  multiprocess_prototype/backend/launch.py:585
  multiprocess_prototype/backend/orchestrator_hooks.py:59
  multiprocess_prototype/backend/recipe_format_hook.py:26
  multiprocess_prototype/frontend/app.py:140
  multiprocess_prototype/frontend/widgets/tabs/pipeline/layout_controller.py:452
  multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py:417
  multiprocess_prototype/frontend/widgets/tabs/services/camera/presenter.py:18
  multiprocess_prototype/frontend/widgets/topology/presenter.py:68
  тесты: 10 файлов, первые 3: multiprocess_prototype/adapters/tests/test_display_catalog_session_blind.py, multiprocess_prototype/adapters/tests/test_recipe_store.py, multiprocess_prototype/backend/state/recipes/tests/test_recipe_engine_wrapper.py
Правила ADR-175: вне охвата (слой prototype)
````

### card prototype/registers

Команда: `atlas card prototype/registers`

````text
Модуль prototype/registers — prototype, ярус —
Назначение: Общие регистры прототипа между плагинами и RegistersManager; сюда — менять shared-регистры
API (0): —
Открытые задачи: нет
Коммиты (14 всего, последние 5):
  4130d8b 2026-05-26 Merge branch 'feat/recipes-manager-v2': Phase 5 — Recipes Manager v2 + replace_blueprint
  f5634ec 2026-05-18 feat(prototype): factory binding-aware builders + callers на FormContext
  53a14cf 2026-05-15 refactor(registers): V2 функционал поглощён framework RegistersManager
  91534d5 2026-05-14 merge: ruff auto-fix (refactor/ruff-cleanup)
  d29f5f9 2026-05-12 merge: feature/design-tokens-system — Design Tokens System
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 13, из них тестов 7
  multiprocess_prototype/frontend/app.py:512
  multiprocess_prototype/frontend/bridge/command_catalog.py:224
  multiprocess_prototype/frontend/managers/theme_presets_manager.py:33
  multiprocess_prototype/frontend/styles/theme_loader.py:37
  multiprocess_prototype/frontend/widgets/tabs/settings/appearance/presenter.py:22
  multiprocess_prototype/frontend/widgets/tabs/settings/appearance/vars_editor.py:26
  тесты: 7 файлов, первые 3: multiprocess_prototype/backend/state/tests/test_bootstrap.py, multiprocess_prototype/frontend/tests/test_phase15_smoke.py, multiprocess_prototype/frontend/tests/test_theme_backward_compat.py
Правила ADR-175: вне охвата (слой prototype)
````

### card prototype_root

Команда: `atlas card prototype_root`

````text
Модуль prototype_root — prototype, ярус —
Назначение: Корень прототипа инспекции дефектов: запуск, оркестратор, app.yaml, документы; сюда — менять запуск прототипа
API (0): —
Открытые задачи (5 планов, 38 задач):
  recipe-orchestrator-unify — 4: 1.2, 2.0, 2.1, 2.3
  observation-port — 2: 0.2, 2.4
  camera-robot-calibration — 1: F7
  frontend-constructor — 18: T2.0, T3.0, T3.1, T3.2, T3.3, T3.4, … ещё 12
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
Коммиты (60 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  da3febe 2026-10-28 merge: C-76 — лаунчер Windows держит дерево приложения в Job Object, сирот нет
  07c9635 2026-10-27 merge: C-70 — лаунчер на Windows ждёт перезапущенное приложение и отдаёт его код
  b5adf82 2026-10-27 merge: полоса С — C-53, C-54 импорты framework, C-55a venv-guard, C-55b ассеты ml_inferen…
  4d2a2f5 2026-10-26 merge: Task 1.9b — PM на ExecutorManager, стоп не глохнет (L-9)
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 44, из них тестов 27
  backend_ctl/harness.py:120
  backend_ctl/probes/smoke_proof.py:41
  backend_ctl/probes/telemetry_probe.py:34
  backend_ctl/probes/telemetry_sink_proof.py:44
  multiprocess_prototype/frontend/app.py:186
  multiprocess_prototype/frontend/run.py:53
  multiprocess_prototype/frontend/widgets/tabs/plugins/presenter.py:201
  multiprocess_prototype/frontend/widgets/tabs/services/neural/dataset_gen_section.py:43
  multiprocess_prototype/frontend/widgets/tabs/services/neural/disk_cutter_section.py:42
  multiprocess_prototype/frontend/widgets/tabs/services/neural/ml_inference_section.py:26
  … ещё 7
  тесты: 27 файлов, первые 3: backend_ctl/tests/_hung_child_plugin.py, backend_ctl/tests/fixtures/c88/slow_exit_children.py, backend_ctl/tests/test_catalog_plugins_live.py
Правила ADR-175: вне охвата (слой prototype)
````

### card tools/backend_ctl

Команда: `atlas card tools/backend_ctl`

````text
Модуль tools/backend_ctl — tools, ярус —
Назначение: Headless-драйвер бэкенда по TCP, GUI по сокету, dev-инструмент; сюда — менять управление бэкендом
API (3): IBackendClient, IEventSource, ISubscriptionRegistry
Открытые задачи (9 планов, 83 задач):
  backend-ctl-proof-discipline — 8: 0.1, 0.2, 1.1, 1.2, 1.3, 1.4, … ещё 2
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  backend-ctl-framework-module — 10: 1.1, 1.2, 2.1, 2.2, 2.3, 2.4, … ещё 4
  telemetry-stage6 — 2: 1.2, 3.5
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
  … ещё 4 планов
Коммиты (200 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  809ba53 2026-10-27 merge: T1.10 честный outcome стопа (exited/terminated/killed/survived/handed_over) в main
  4f56e96 2026-10-25 merge: C-21(б) — последний активный рецепт в <stem>.state.yaml вне git, app.yaml — умолча…
  e08eec4 2026-10-20 merge: feat/gui-close-force-stop в main — Task 0.2, быстрый принудительный стоп backend_c…
  6b47bd0 2026-10-08 Merge pull request #25 from TWOKRAI/claude/kind-bohr-8tf51g
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 60, из них тестов 14
  backend_ctl/probes/f5_live_probe.py:37
  backend_ctl/probes/g1_perf_probe.py:31
  backend_ctl/probes/g7_dualcam_probe.py:26
  backend_ctl/probes/g7_fault_probe.py:34
  backend_ctl/probes/g7_soak_probe.py:33
  backend_ctl/probes/probe_16_tab_search_live.py:67
  backend_ctl/probes/probe_2_4_eviction_voice_live.py:41
  backend_ctl/probes/probe_3_1_no_receiver_live.py:66
  backend_ctl/probes/probe_3_4_snapshot_line_limit_live.py:58
  backend_ctl/probes/probe_4_4_point_intents_live.py:36
  … ещё 36
  тесты: 14 файлов, первые 3: Plugins/sim/scene_source/tests/test_acceptance_c87_live_step.py, Services/device_hub/tests/test_robot_v2_live_backend.py, apps/line_sim/tests/test_f1_task11_acceptance.py
Правила ADR-175: вне охвата (слой tools)
````

### card prototype/apps

Команда: `atlas card prototype/apps`

````text
Модуль prototype/apps — prototype, ярус —
Назначение: Готовые приложения на фреймворке (line_sim: симулятор линии); сюда — менять запуск и конфиги приложений
API (0): —
Открытые задачи (1 планов, 4 задач):
  line-sim — 4: 4.1, 4.2, 4.3, 6.4
Коммиты (26 всего, последние 5):
  f2304d4 2026-11-24 merge: fix/lane-t-win-baseline — красные Windows/Python 3.12 исправлены по причине, отчёт…
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  7fc7c3b 2026-10-18 merge: feat/robot-v2-t38 в main — T3.8 вид робота из состояния линии (--line)
  dc209d6 2026-10-14 merge: robot-protocol-v2 T3.7 — стенд линии на протоколе v2, enqueue_job/return_job у Rob…
  f80419f 2026-10-13 merge: line-sim 6.5 — ассеты стенда из закоммиченных фикстур одной командой, плитка 410x4…
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 0, из них тестов 0
  тесты: 0 файлов
Правила ADR-175: вне охвата (слой prototype)
````

### card tools/tools

Команда: `atlas card tools/tools`

````text
Модуль tools/tools — tools, ярус —
Назначение: Внешние стенды и вспомогательные инструменты (otel_stand: арбитр OTLP); сюда — менять стенды проверки
API (0): —
Открытые задачи (1 планов, 8 задач):
  otel-export — 8: 2.5, 3.1, 3.2, 3.3, 3.4, 4.1, … ещё 2
Коммиты (9 всего, последние 5):
  0112fbf 2026-09-08 merge: otel (29999d61) в main — числовая плоскость экспортёра проверена парой
  da9219f 2026-09-08 merge: otel (97bb1c10) в main — Ф2 закрыта, доставка наружу наконец доказана
  73fdc0a 2026-09-08 feat(otel): проба останова 2.4 — чёрная дыра, 5 из 5 на живом стенде
  5ec9f73 2026-09-08 fix(otel): Task 2.3 закрыта — страж петли предъявлен парой прогонов, адрес судится целиком
  817e61f 2026-09-07 fix(otel): проба 2.2 врала четырьмя способами — живая приёмка 10 из 10
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 0, из них тестов 0
  тесты: 0 файлов
Правила ADR-175: вне охвата (слой tools)
````

### card scripts

Команда: `atlas card scripts`

````text
Модуль scripts — scripts, ярус —
Назначение: Каталог утилит проекта; сюда — менять служебные скрипты репозитория
API (0): —
Открытые задачи (10 планов, 110 задач):
  plans-progress-dashboard — 9: 6.3, 6.4, 6.5, 8.0, 8.1, 8.2, … ещё 3
  observation-port — 2: 0.2, 2.4
  backend-ctl-framework-module — 10: 1.1, 1.2, 2.1, 2.2, 2.3, 2.4, … ещё 4
  commit-mechanism — 2: 3.1, 3.2
  framework-architecture-rework — 34: 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, … ещё 28
  … ещё 5 планов
Коммиты (126 всего, последние 5):
  7436417 2026-11-24 fix(frontend): гейты слияния — G6 для FramePump, пересборка оглавления ADR
  f2304d4 2026-11-24 merge: fix/lane-t-win-baseline — красные Windows/Python 3.12 исправлены по причине, отчёт…
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  6cb2122 2026-11-22 feat(camera): слияние К4' — плагин hikvision на ядре camera_device, цвет BGR, рецепты, вк…
  fdd2b63 2026-11-16 feat(camera_device): слияние W2 — ядро камер: план записи, срез на фейке, сеанс с воркера…
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 11, из них тестов 7
  scripts/atlas/adapters/code.py:22
  scripts/atlas/brief.py:27
  scripts/atlas/lint_brief.py:24
  scripts/atlas/views.py:28
  тесты: 7 файлов, первые 3: Services/code_reader/tests/test_thread_split_probe_scope.py, Services/otel_export/tests/test_contract_acceptance.py, multiprocess_framework/modules/logger_module/tests/test_seal.py
Правила ADR-175: вне охвата (слой scripts)
````

### card scripts/atlas

Команда: `atlas card scripts/atlas`

````text
Модуль scripts/atlas — scripts, ярус —
Назначение: Атлас: реестр доказанности и знаний из git, планов и modules.yaml; сюда — менять сборку карточек и страниц
API (0): —
Открытые задачи (1 планов, 6 задач):
  atlas — 6: 1.9g, 1.10b, 2.1, 2.4, 2.5, K1.1
Коммиты (22 всего, последние 5):
  f2304d4 2026-11-24 merge: fix/lane-t-win-baseline — красные Windows/Python 3.12 исправлены по причине, отчёт…
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  9d6a6dc 2026-10-12 merge: atlas — повтор переноса выгрузки при PermissionError на Windows (card больше не па…
  1f78f3a 2026-10-12 merge: atlas 1.9f — atlas metrics: M1–M4 по брифам плана и читатель отчёта ревью
  9820f07 2026-10-11 merge: atlas lint-brief — повтор команд FACTS/ACCEPTANCE, форма, REDS, injections.json, х…
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 1, из них тестов 0
  scripts/memory/tags.py:51
  тесты: 0 файлов
Правила ADR-175: вне охвата (слой scripts)
````

### card tools/utils

Команда: `atlas card tools/utils`

````text
Модуль tools/utils — tools, ярус —
Назначение: Мелкие общие утилиты: таймер, профилирование, fps_module, file_comments; сюда — менять отладочные помощники
API (0): —
Открытые задачи: нет
Коммиты (1 всего, последние 1):
  2e829a5 2026-04-30 clean: fresh start without large files in history
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 0, из них тестов 0
  тесты: 0 файлов
Правила ADR-175: вне охвата (слой tools)
````

### card prototype/robot

Команда: `atlas card prototype/robot`

````text
Модуль prototype/robot — prototype, ярус —
Назначение: Lua-программы и ПК-скрипты робота Delta SCARA (DRAStudio, Modbus); сюда — менять прошивку и пробы робота
API (0): —
Открытые задачи (2 планов, 14 задач):
  robot-protocol-v2 — 13: T0.3, T4.0, T4.1, T4.5, T4.6, T5.3, … ещё 7
  camera-robot-calibration — 1: F7
Коммиты (18 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  efaa394 2026-10-13 merge: robot-protocol-v2 T3.9 — стартовое состояние сценария в SC_RUN
  ca48fc2 2026-10-12 merge: robot-protocol-v2 T3.2 + T3.6 — client_v2: обёртки опкодов, wire_v2, run_chunks пи…
  4fd912c 2026-09-30 feat(robot): слияние feat/robot-v2-t12-t13 в main — инварианты delta_v2 (T1.2) и сборщик …
  c8494ee 2026-09-30 fix(robot): robot-protocol-v2 T1.3 — luacheck с конфигом, порядок запуска закреплён тестом
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 0, из них тестов 0
  тесты: 0 файлов
Правила ADR-175: вне охвата (слой prototype)
````

### card docs/examples

Команда: `atlas card docs/examples`

````text
Модуль docs/examples — docs, ярус —
Назначение: Пример приложения minimal_app, рыба-шаблон; сюда — смотреть образец использования фреймворка
API (0): —
Открытые задачи: нет
Коммиты (3 всего, последние 3):
  dfccfe8 2026-08-11 fix(framework): каталог логов не материализуется дефолтом — прогоны не кормят репозиторий…
  b8b6dae 2026-07-12 Merge branch 'feat/constructor-f5-13-minimal-app-ci': 5.13 — minimal_app живой IPC + CI-s…
  0b6d6a5 2026-07-12 Merge branch 'feat/constructor-f5-11-app-module': 5.11 — app_module «рыба» (run_app, Mani…
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 3, из них тестов 3
  тесты: 3 файлов, первые 3: multiprocess_framework/modules/app_module/tests/test_builder.py, multiprocess_framework/modules/app_module/tests/test_task15_legacy_builder_hazard.py, multiprocess_framework/modules/app_module/tests/test_task15_telemetry_gate_acceptance.py
Правила ADR-175: вне охвата (слой docs)
````

### card tools/backend_ctl/probes

Команда: `atlas card tools/backend_ctl/probes`

````text
Модуль tools/backend_ctl/probes — tools, ярус —
Назначение: Ручные live-пробники backend_ctl, не входят в обычный прогон тестов; сюда — менять пробники
API (0): —
Открытые задачи (5 планов, 59 задач):
  observability-review-remediation — 13: C1, D1, D2, D3, D4, D5, … ещё 7
  telemetry-stage6 — 2: 1.2, 3.5
  backend-ctl-proof-discipline — 8: 0.1, 0.2, 1.1, 1.2, 1.3, 1.4, … ещё 2
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  transport-single-policy — 5: 5.8a, 5.8b, 5.8s, 5.11, 5.12
Коммиты (35 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  9d8e5df 2026-10-05 merge: main в feat/lifecycle-owner-scope перед ревью Task 0.2 и стартом 0.3/0.4
  9979f26 2026-10-02 Merge branch 'main' into feat/layer-render
  94818d2 2026-09-23 merge: observability-closure (9f6ca3bc) в main — 4.4 точечные подписки переживают рестарт…
  7448402 2026-09-22 merge: line-sim (c2bc060d) в main — Ф0–Ф2 на границе Ф2, шаг 0 очереди 09-22
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 2, из них тестов 2
  тесты: 2 файлов, первые 3: backend_ctl/tests/test_g1_perf_probe.py, backend_ctl/tests/test_g7_soak_probe.py
Правила ADR-175: вне охвата (слой tools)
````

### card frontend_module/components

Команда: `atlas card frontend_module/components`

````text
Модуль frontend_module/components — framework, ярус —
Назначение: Примитивы контролов: Traits, Presenter, View, Facade; сюда — менять базовые контролы GUI
API (0): —
Открытые задачи: нет
Коммиты (10 всего, последние 5):
  4a1689d 2026-05-24 Merge branch 'feat/frontend-extract-bridge-primitives' into main
  6c2eeb1 2026-05-18 feat(framework): form_ctx kwarg во всех FW control facades
  82b87d4 2026-05-18 feat(combo): align combo/ with checkbox/ reference
  d67ca70 2026-05-15 refactor(actions): FormContext.write — явный ActionBus, удалён прокси-мост
  f959b50 2026-05-15 feat(plugins): pilot_widgets — рабочий путь GUI↔plugin, FieldMeta.widget Literal
Находки (2):
  warning P2_DOCSTRING module:frontend_module/components NumericPresenter.set_access_level
  warning P2_DOCSTRING module:frontend_module/components emit_access_denied
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 31, из них тестов 12
  multiprocess_framework/modules/frontend_module/__init__.py:94
  multiprocess_framework/modules/frontend_module/components/_examples/checkbox/adapter.py:16
  multiprocess_framework/modules/frontend_module/components/_examples/combo/adapter.py:17
  multiprocess_framework/modules/frontend_module/components/_examples/compound_mixed/adapter.py:16
  multiprocess_framework/modules/frontend_module/components/_examples/compound_numeric/adapter.py:16
  multiprocess_framework/modules/frontend_module/components/_examples/group/adapter.py:13
  multiprocess_framework/modules/frontend_module/components/_examples/label/adapter.py:13
  multiprocess_framework/modules/frontend_module/components/_examples/numeric/adapter.py:16
  multiprocess_framework/modules/frontend_module/components/_examples/slider/adapter.py:16
  multiprocess_framework/modules/frontend_module/components/_examples/spinbox/adapter.py:16
  … ещё 9
  тесты: 12 файлов, первые 3: multiprocess_framework/modules/frontend_module/tests/integration/test_form_context_integration.py, multiprocess_framework/modules/frontend_module/tests/test_checkbox_v2.py, multiprocess_framework/modules/frontend_module/tests/test_combo_form_ctx.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 82 из 84
  П3 __all__ у interfaces.py и __init__.py: 11 из 11
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card frontend_module/components/_examples

Команда: `atlas card frontend_module/components/_examples`

````text
Модуль frontend_module/components/_examples — framework, ярус —
Назначение: Учебные схемы и адаптеры к контролам; сюда — смотреть пример адаптера, не боевой код
API (0): —
Открытые задачи: нет
Коммиты (3 всего, последние 3):
  82b87d4 2026-05-18 feat(combo): align combo/ with checkbox/ reference
  3eca0d5 2026-05-11 refactor(facade): X.A+B — schema_adapter в frontend_module + дофасадить worker/registers …
  2e829a5 2026-04-30 clean: fresh start without large files in history
Находки (13):
  warning P2_DOCSTRING module:frontend_module/components/_examples compound_numeric_binding
  warning P2_DOCSTRING module:frontend_module/components/_examples compound_numeric_view_config_from_ui
  warning P2_DOCSTRING module:frontend_module/components/_examples create_example_compound_mixed
  warning P2_DOCSTRING module:frontend_module/components/_examples create_example_compound_numeric
  warning P2_DOCSTRING module:frontend_module/components/_examples create_example_group_row
  warning P2_DOCSTRING module:frontend_module/components/_examples create_example_label
  warning P2_DOCSTRING module:frontend_module/components/_examples create_example_numeric
  warning P2_DOCSTRING module:frontend_module/components/_examples create_example_spinbox
  warning P2_DOCSTRING module:frontend_module/components/_examples label_config_from_ui
  warning P2_DOCSTRING module:frontend_module/components/_examples numeric_binding
  … ещё 3
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 1, из них тестов 1
  тесты: 1 файлов, первые 3: multiprocess_framework/modules/frontend_module/tests/test_example_with_data_schema.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 28 из 41
  П3 __all__ у interfaces.py и __init__.py: 10 из 10
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card frontend_module/components/base

Команда: `atlas card frontend_module/components/base`

````text
Модуль frontend_module/components/base — framework, ярус —
Назначение: Базовый слой контролов: контракты, конфиг, мост к регистрам, traits; сюда — менять основу контролов
API (6): IControlView, IFieldBinding, INumericView, IRegisterPort, IRegistersManagerGui, RegistersManagerLike
Открытые задачи: нет
Коммиты (5 всего, последние 5):
  c8754ff 2026-05-14 refactor(components): конфиги компонентов dataclass → SchemaBase
  91534d5 2026-05-14 merge: ruff auto-fix (refactor/ruff-cleanup)
  b073abe 2026-05-11 Merge PR3: auth/RBAC permissions rollout
  ae2addd 2026-05-11 feat(frontend_module): RBAC — AccessContext.permissions + AccessTrait view/edit (Group C …
  2e829a5 2026-04-30 clean: fresh start without large files in history
Находки (19):
  warning P1_IMPL_NOT_INHERITING module:frontend_module/components/base BindingConfig>IFieldBinding
  warning P1_IMPL_NOT_INHERITING module:frontend_module/components/base RegisterAdapter>IRegisterPort
  warning P2_DOCSTRING module:frontend_module/components/base IRegisterPort.read
  warning P2_DOCSTRING module:frontend_module/components/base IRegisterPort.resolve_meta
  warning P2_DOCSTRING module:frontend_module/components/base IRegisterPort.subscribe
  warning P2_DOCSTRING module:frontend_module/components/base IRegisterPort.write
  warning P2_DOCSTRING module:frontend_module/components/base SchemaTrait.description
  warning P2_DOCSTRING module:frontend_module/components/base SchemaTrait.meta
  warning P2_DOCSTRING module:frontend_module/components/base SyncTrait.read
  warning P2_DOCSTRING module:frontend_module/components/base SyncTrait.subscribe
  … ещё 9
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 56, из них тестов 16
  multiprocess_framework/modules/frontend_module/components/__init__.py:14
  multiprocess_framework/modules/frontend_module/components/_examples/checkbox/adapter.py:13
  multiprocess_framework/modules/frontend_module/components/_examples/combo/adapter.py:14
  multiprocess_framework/modules/frontend_module/components/_examples/compound_mixed/adapter.py:9
  multiprocess_framework/modules/frontend_module/components/_examples/compound_numeric/adapter.py:13
  multiprocess_framework/modules/frontend_module/components/_examples/numeric/adapter.py:9
  multiprocess_framework/modules/frontend_module/components/_examples/slider/adapter.py:13
  multiprocess_framework/modules/frontend_module/components/_examples/spinbox/adapter.py:13
  multiprocess_framework/modules/frontend_module/components/checkbox/config.py:12
  multiprocess_framework/modules/frontend_module/components/checkbox/facade.py:20
  … ещё 30
  тесты: 16 файлов, первые 3: multiprocess_framework/modules/frontend_module/tests/integration/test_form_context_integration.py, multiprocess_framework/modules/frontend_module/tests/test_access_trait.py, multiprocess_framework/modules/frontend_module/tests/test_base_widget_auth_source.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 2
  П2 docstring Google у публичного API: 58 из 70
  П3 __all__ у interfaces.py и __init__.py: 4 из 4
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card frontend_module/core

Команда: `atlas card frontend_module/core`

````text
Модуль frontend_module/core — framework, ярус —
Назначение: Базовые классы frontend_module без Qt: маршрутизация команд, мост регистров; сюда — менять ядро GUI-фреймворка
API (0): —
Открытые задачи (1 планов, 18 задач):
  frontend-constructor — 18: T2.0, T3.0, T3.1, T3.2, T3.3, T3.4, … ещё 12
Коммиты (20 всего, последние 5):
  c2afd1f 2026-10-06 fix(process): T1 ревью р2 — install внутри suspend не теряет политику, откат gen2 как в C…
  978e912 2026-10-06 fix(process): T1 р2 — тик по порогам с ограничением gen2, мёртвая политика, заморозка гра…
  1392d49 2026-10-06 fix: T1 гейт — логгер через get_std_logger в lifetime/subscribers/qt_lifetime
  8e39ef5 2026-10-06 docs(process_module): ADR-PM-053 — сборкой владеет поток-исполнитель (T1)
  6f6d35a 2026-10-06 feat(process_module): T1 — сборкой gc владеет поток-исполнитель, политика памяти GUI
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 93, из них тестов 8
  multiprocess_framework/modules/conftest.py:40
  multiprocess_framework/modules/frontend_module/application/__init__.py:18
  multiprocess_framework/modules/frontend_module/application/frontend_manager.py:17
  multiprocess_framework/modules/frontend_module/application/process_attached_frontend.py:40
  multiprocess_framework/modules/frontend_module/application/thread_manager.py:11
  multiprocess_framework/modules/frontend_module/application/window_manager.py:15
  multiprocess_framework/modules/frontend_module/bridge/command_sender.py:159
  multiprocess_framework/modules/frontend_module/bridge/wire_monitor.py:188
  multiprocess_framework/modules/frontend_module/components/base/traits/debounce_trait.py:11
  multiprocess_framework/modules/frontend_module/components/checkbox/facade.py:27
  … ещё 75
  тесты: 8 файлов, первые 3: multiprocess_framework/modules/frontend_module/tests/test_app_identity.py, multiprocess_framework/modules/frontend_module/tests/test_base_widget_auth_source.py, multiprocess_framework/modules/frontend_module/tests/test_qt_gc_policy.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 0 из 0
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card frontend_module/widgets

Команда: `atlas card frontend_module/widgets`

````text
Модуль frontend_module/widgets — framework, ярус —
Назначение: Составные UI-компоненты: вкладки, таблицы, шапка, клавиатура; сюда — менять составные виджеты
API (0): —
Открытые задачи: нет
Коммиты (10 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  23184cc 2026-08-09 feat(observability): merge — влить observability-unified-routing — Ф0–Ф8 наблюдаемости
  937bc54 2026-07-17 chore(main): слить feat/telemetry-dashboard-followups — ниты ревью #3/#4
  1f3fd08 2026-07-17 chore(main): слить feat/telemetry-dashboard — PyQtGraph-дашборд телеметрии
  4a1689d 2026-05-24 Merge branch 'feat/frontend-extract-bridge-primitives' into main
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 14, из них тестов 4
  multiprocess_framework/modules/frontend_module/__init__.py:94
  multiprocess_framework/modules/frontend_module/components/slider/view.py:66
  multiprocess_framework/modules/frontend_module/components/spinbox/view.py:44
  multiprocess_framework/modules/frontend_module/core/diagnostics.py:15
  multiprocess_framework/modules/frontend_module/widgets/chrome/app_header/widget.py:35
  multiprocess_framework/modules/frontend_module/widgets/tabs/mvp_facade.py:17
  multiprocess_framework/modules/frontend_module/widgets/tabs/numeric_bind_or_lineedit.py:73
  multiprocess_framework/modules/frontend_module/widgets/tabs/tab_widget.py:19
  multiprocess_prototype/frontend/widgets/tabs/processes/_panels.py:44
  multiprocess_prototype/frontend/widgets/tabs/processes/_system_dashboard.py:21
  тесты: 4 файлов, первые 3: multiprocess_framework/modules/frontend_module/tests/test_telemetry_chart.py, multiprocess_framework/modules/frontend_module/tests/test_telemetry_chart_series_points_acceptance.py, multiprocess_framework/modules/frontend_module/tests/test_touch_keyboard.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 4 из 4
  П3 __all__ у interfaces.py и __init__.py: 7 из 7
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card frontend_module/widgets/chrome

Команда: `atlas card frontend_module/widgets/chrome`

````text
Модуль frontend_module/widgets/chrome — framework, ярус —
Назначение: Заголовок приложения, боковые панели и оверлеи; сюда — менять обрамление окна
API (0): —
Открытые задачи: нет
Коммиты (4 всего, последние 4):
  4a1689d 2026-05-24 Merge branch 'feat/frontend-extract-bridge-primitives' into main
  91534d5 2026-05-14 merge: ruff auto-fix (refactor/ruff-cleanup)
  3eca0d5 2026-05-11 refactor(facade): X.A+B — schema_adapter в frontend_module + дофасадить worker/registers …
  8759c34 2026-05-01 feat(fw): chrome widgets — Wave 2B перенос во фреймворк
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 1, из них тестов 0
  multiprocess_framework/modules/frontend_module/widgets/__init__.py:143
  тесты: 0 файлов
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 0 из 0
  П3 __all__ у interfaces.py и __init__.py: 7 из 7
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card frontend_module/widgets/tabs

Команда: `atlas card frontend_module/widgets/tabs`

````text
Модуль frontend_module/widgets/tabs — framework, ярус —
Назначение: Вкладки: TabWidget, BaseTab, MVP-база, привязка к регистрам; сюда — менять каркас вкладок
API (0): —
Открытые задачи: нет
Коммиты (11 всего, последние 5):
  23184cc 2026-08-09 feat(observability): merge — влить observability-unified-routing — Ф0–Ф8 наблюдаемости
  a9e6fec 2026-07-17 chore(main): слить feat/telemetry-coherence — Task 1.4 cap-детекция + Ф4.1 GUI-контролы
  171f1d8 2026-05-29 feat(prototype): G.4.4 — domain undo/redo UX + единая шина undo + phantom-cleanup
  4a1689d 2026-05-24 Merge branch 'feat/frontend-extract-bridge-primitives' into main
  c24033c 2026-05-18 Merge branch 'main' of https://github.com/TWOKRAI/Inspector_bottles
Находки (18):
  warning P2_DOCSTRING module:frontend_module/widgets/tabs BaseTab.on_tab_deselected
  warning P2_DOCSTRING module:frontend_module/widgets/tabs BaseTab.on_tab_selected
  warning P2_DOCSTRING module:frontend_module/widgets/tabs CurrentPageStack.minimumSizeHint
  warning P2_DOCSTRING module:frontend_module/widgets/tabs CurrentPageStack.sizeHint
  warning P2_DOCSTRING module:frontend_module/widgets/tabs DiffScrollTabLayout.eventFilter
  warning P2_DOCSTRING module:frontend_module/widgets/tabs DiffScrollTabLayout.resizeEvent
  warning P2_DOCSTRING module:frontend_module/widgets/tabs RegisterBindingContext.can_bind
  warning P2_DOCSTRING module:frontend_module/widgets/tabs SectionProtocol.action_buttons
  warning P2_DOCSTRING module:frontend_module/widgets/tabs SectionProtocol.key
  warning P2_DOCSTRING module:frontend_module/widgets/tabs SectionProtocol.on_activated
  … ещё 8
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 43, из них тестов 8
  multiprocess_framework/modules/frontend_module/widgets/__init__.py:26
  multiprocess_framework/modules/frontend_module/widgets/base_widget/base_widget.py:27
  multiprocess_prototype/frontend/widgets/primitives/diff_scroll_tab_layout.py:4
  multiprocess_prototype/frontend/widgets/primitives/standard_tab_layout.py:3
  multiprocess_prototype/frontend/widgets/tabs/displays/tab.py:69
  multiprocess_prototype/frontend/widgets/tabs/observability/observability_tabs.py:26
  multiprocess_prototype/frontend/widgets/tabs/plugins/_sections.py:33
  multiprocess_prototype/frontend/widgets/tabs/plugins/tab.py:44
  multiprocess_prototype/frontend/widgets/tabs/processes/tab.py:25
  multiprocess_prototype/frontend/widgets/tabs/recipes/tab.py:27
  … ещё 25
  тесты: 8 файлов, первые 3: multiprocess_framework/modules/frontend_module/tests/test_base_columnar_tab.py, multiprocess_framework/modules/frontend_module/tests/test_base_list_nav_tab.py, multiprocess_framework/modules/frontend_module/tests/test_base_tree_nav_tab.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 109 из 127
  П3 __all__ у interfaces.py и __init__.py: 2 из 2
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card process_module/generic

Команда: `atlas card process_module/generic`

````text
Модуль process_module/generic — framework, ярус —
Назначение: GenericProcess: конфиг-драйвен процесс с загрузкой плагинов из конфига; сюда — менять универсальный процесс
API (0): —
Открытые задачи (9 планов, 85 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  observation-port — 2: 0.2, 2.4
  pipeline-live-control — 5: 2.1, 2.2, 3.1, 3.2, 3.3
  telemetry-self-publish-redesign — 2: 2, 3
  transport-router-hub — 9: P0.1, P0.2, P0.3, P1.1, P1.2, P1.3, … ещё 3
  … ещё 4 планов
Коммиты (93 всего, последние 5):
  47e9778 2026-11-24 merge: тракт кадров gui — ящик, насос, метрики, дешёвый кадр, отложенная копия T5, штампы…
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  116ed69 2026-11-01 merge: C-60 — плагин узнаёт о стопе процесса раньше ожидания воркеров и исполнителей
  5ae0b39 2026-10-12 merge: lifecycle-owner-scope 1.2a — корень процесса с барьерами, stop() = cancel(), один …
  9d8e5df 2026-10-05 merge: main в feat/lifecycle-owner-scope перед ревью Task 0.2 и стартом 0.3/0.4
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 138, из них тестов 120
  Plugins/_shared/fanin/factory.py:20
  Plugins/processing/region_split/plugin.py:12
  Plugins/processing/stitcher/plugin.py:16
  Plugins/runtime/chain_executor/plugin.py:30
  Plugins/runtime/worker_pool/plugin.py:27
  Services/hikvision_camera/plugin/config.py:9
  multiprocess_framework/modules/process_manager_module/topology/blueprint.py:34
  multiprocess_framework/modules/process_module/__init__.py:87
  multiprocess_framework/modules/process_module/commands/builtin_commands.py:446
  multiprocess_framework/modules/process_module/core/process_module.py:1053
  … ещё 8
  тесты: 120 файлов, первые 3: Plugins/_shared/fanin/tests/test_factory.py, Plugins/control/robot_control/tests/test_t47d4_marker_policy.py, Plugins/control/robot_control/tests/test_t52_actuation_contract.py
Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):
  П1 реализации с явным наследованием: 0 из 0
  П2 docstring Google у публичного API: 73 из 73
  П3 __all__ у interfaces.py и __init__.py: 1 из 1
  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 0 из 0
````

### card prototype/frontend/widgets

Команда: `atlas card prototype/frontend/widgets`

````text
Модуль prototype/frontend/widgets — prototype, ярус —
Назначение: Виджеты GUI прототипа по доменам: вкладки, дисплеи, диалоги, камера; сюда — менять экраны и компоненты UI
API (0): —
Открытые задачи (3 планов, 62 задач):
  camera-device-service — 23: 1.2, 1.3, 1.4, 1.7, 2.3a, 2.3b, … ещё 17
  code-reader-gui — 8: 1.1, 1.2, 2.1, 2.2a, 2.2b, 2.3, … ещё 2
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
Коммиты (67 всего, последние 5):
  47e9778 2026-11-24 merge: тракт кадров gui — ящик, насос, метрики, дешёвый кадр, отложенная копия T5, штампы…
  4a62859 2026-11-23 feat(hikvision_camera): 4.2d — gain_auto и enabled_if у gain и exposure_time
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  681d5e7 2026-10-19 feat(prototype): логотип шапки — Square721 Bold Extended, растяжение, обводка
  cbffb90 2026-10-18 merge: feat/camera-device-service в main — план и ядро камер, фиксы code-reader, рецепты,…
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 36, из них тестов 15
  multiprocess_prototype/frontend/app.py:26
  multiprocess_prototype/frontend/widgets/tabs/displays/presenter.py:31
  multiprocess_prototype/frontend/widgets/tabs/displays/tab.py:74
  multiprocess_prototype/frontend/widgets/tabs/observability/observability_tabs.py:30
  multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py:140
  multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py:37
  multiprocess_prototype/frontend/widgets/tabs/plugins/_sections.py:218
  multiprocess_prototype/frontend/widgets/tabs/plugins/tab.py:52
  multiprocess_prototype/frontend/widgets/tabs/processes/_panels.py:54
  multiprocess_prototype/frontend/widgets/tabs/processes/tab.py:30
  … ещё 11
  тесты: 15 файлов, первые 3: multiprocess_prototype/frontend/tests/test_bridge.py, multiprocess_prototype/frontend/tests/test_camera_view.py, multiprocess_prototype/frontend/tests/test_close_path_hypotheses.py
Правила ADR-175: вне охвата (слой prototype)
````

### card prototype/frontend/widgets/tabs

Команда: `atlas card prototype/frontend/widgets/tabs`

````text
Модуль prototype/frontend/widgets/tabs — prototype, ярус —
Назначение: Вкладки приложения: реестр фабрик вкладок из единого списка TABS; сюда — менять состав вкладок
API (0): —
Открытые задачи (8 планов, 55 задач):
  observation-port — 2: 0.2, 2.4
  telemetry-stage6 — 2: 1.2, 3.5
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  telemetry-self-publish-redesign — 2: 2, 3
  pipeline-live-control — 5: 2.1, 2.2, 3.1, 3.2, 3.3
  … ещё 3 планов
Коммиты (106 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  976aa88 2026-11-06 merge: C-30 частичная волна — Save редактора владеет только своим, Камера пишет через мод…
  5bdf8a2 2026-11-02 fix(recipes): C-30 1.14b — фундамент для Save определяется по именам manifest.base
  4e53312 2026-11-02 fix(recipes): C-30 1.14 — Save владеет только непротектед-процессами, rev раньше ссылок
  9e94f12 2026-10-28 feat(displays): C-30 1.11 — Дисплеи пишут рецепт с базой сессии
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 14, из них тестов 10
  backend_ctl/probes/probe_16_tab_search_live.py:205
  multiprocess_prototype/frontend/app.py:554
  multiprocess_prototype/frontend/tab_factory.py:32
  multiprocess_prototype/frontend/tabs_registry.py:46
  тесты: 10 файлов, первые 3: multiprocess_prototype/backend/config/tests/test_telemetry_section.py, multiprocess_prototype/backend/tests/test_rt2_config_flip_acceptance.py, multiprocess_prototype/frontend/tests/test_phase10_integration.py
Правила ADR-175: вне охвата (слой prototype)
````

### card prototype/frontend/widgets/tabs/pipeline

Команда: `atlas card prototype/frontend/widgets/tabs/pipeline`

````text
Модуль prototype/frontend/widgets/tabs/pipeline — prototype, ярус —
Назначение: Вкладка визуального конструктора pipeline: граф, палитра плагинов, инспектор; сюда — менять редактор pipeline
API (0): —
Открытые задачи (7 планов, 48 задач):
  constructor-master — 31: AU6, F8-3, F8-4, F8-5, F8-6, F9-0, … ещё 25
  observation-port — 2: 0.2, 2.4
  command-result-bridge — 1: P4
  device-tree-recipe — 3: B2, E1, V1
  pipeline-live-control — 5: 2.1, 2.2, 3.1, 3.2, 3.3
  … ещё 2 планов
Коммиты (93 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  62c79df 2026-11-07 fix(save): C-30 1.16 — Save не пишет пустой граф при неизвестной ревизии; причина отказа …
  976aa88 2026-11-06 merge: C-30 частичная волна — Save редактора владеет только своим, Камера пишет через мод…
  5bdf8a2 2026-11-02 fix(recipes): C-30 1.14b — фундамент для Save определяется по именам manifest.base
  4e53312 2026-11-02 fix(recipes): C-30 1.14 — Save владеет только непротектед-процессами, rev раньше ссылок
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 4, из них тестов 2
  multiprocess_prototype/frontend/tabs_registry.py:70
  multiprocess_prototype/frontend/widgets/tabs/services/devices_common/master_detail.py:122
  тесты: 2 файлов, первые 3: multiprocess_prototype/frontend/tests/test_topology_events_wiring.py, multiprocess_prototype/recipes/tests/test_save_noise_save.py
Правила ADR-175: вне охвата (слой prototype)
````

### card prototype/frontend/widgets/tabs/services

Команда: `atlas card prototype/frontend/widgets/tabs/services`

````text
Модуль prototype/frontend/widgets/tabs/services — prototype, ярус —
Назначение: Вкладка управления сервисами: секции из реестра, запуск/остановка, пути; сюда — менять экран сервисов
API (0): —
Открытые задачи (3 планов, 27 задач):
  device-tree-recipe — 3: B2, E1, V1
  camera-device-service — 23: 1.2, 1.3, 1.4, 1.7, 2.3a, 2.3b, … ещё 17
  camera-robot-calibration — 1: F7
Коммиты (58 всего, последние 5):
  a7952d2 2026-11-24 merge: feat/pult-belt-speed — память частоты ленты ПЧ, belt_freq в рецептах симулятора
  c7a2ccc 2026-11-23 feat(frontend): 4.2e — «Применить» вкладки Hikvision обновляет GUI-регистр
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  6cb2122 2026-11-22 feat(camera): слияние К4' — плагин hikvision на ядре camera_device, цвет BGR, рецепты, вк…
  62c79df 2026-11-07 fix(save): C-30 1.16 — Save не пишет пустой граф при неизвестной ревизии; причина отказа …
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 4, из них тестов 2
  multiprocess_prototype/frontend/tabs_registry.py:58
  multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/hikvision_embed.py:31
  тесты: 2 файлов, первые 3: multiprocess_prototype/domain/tests/test_fakes_contract.py, multiprocess_prototype/recipes/tests/test_save_noise_store.py
Правила ADR-175: вне охвата (слой prototype)
````

### card prototype/frontend/widgets/tabs/settings

Команда: `atlas card prototype/frontend/widgets/tabs/settings`

````text
Модуль prototype/frontend/widgets/tabs/settings — prototype, ярус —
Назначение: Пилотная вкладка Settings, сквозной пример таба; сюда — менять вкладку настроек
API (0): —
Открытые задачи (1 планов, 18 задач):
  frontend-constructor — 18: T2.0, T3.0, T3.1, T3.2, T3.3, T3.4, … ещё 12
Коммиты (35 всего, последние 5):
  b57349f 2026-11-23 merge: origin/main (1202 коммита) в локальный main
  23184cc 2026-08-09 feat(observability): merge — влить observability-unified-routing — Ф0–Ф8 наблюдаемости
  c8e8046 2026-07-19 test(framework): убрать инверсию слоёв в frontend_module/tests (Ф1 T1.4)
  249b5cd 2026-07-10 Merge branch 'feat/observability-followup': 5.21 наблюдаемость + 5.8 RuntimeDeps + 5.18 д…
  9a5f4b8 2026-07-06 Merge fix/topology-switch-hardening: топология switch/restart — hardening 7/7
Находки (0):
Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы роутера не видны): файлов 2, из них тестов 0
  multiprocess_prototype/frontend/app.py:999
  multiprocess_prototype/frontend/tabs_registry.py:40
  тесты: 0 файлов
Правила ADR-175: вне охвата (слой prototype)
````
