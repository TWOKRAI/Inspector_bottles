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
  IChannelRoutingManager (6), IBufferStrategy (5), IChannel (5), channel_accepted
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
  классы: AccessContext, AccessContextSource, ActionBuilderProtocol, CommandSender, CommandSenderTap, CommandValidator, ConfigSnapshotManager, FormContext, FrontendLaunchHooks, FrontendManager, FrontendManagerConfig, ICommandCatalog, IProcess, IRequestingProcess, IRouterLike, ISignalProvider, IWidgetFactory, IWindowRegistry, LazyTab, LoadingWindow, ProcessDiff, QtEventBus, RecipeManagerProtocol, RegisterBinding, RegisterFieldMeta, RemoteCommandSender, RemoteFrameSource, RemoteFrameSourceError, RemoteStateProxy, ResolvedMeta, SettingsProfileManagerProtocol, ShmConfig, SupportsCommandMessage, TabRegistry, TabSpec, TelemetryHistorySource, TelemetryPoller, TelemetryViewModel, ThemeManager, ThemePresetsManager, ThreadEntry, ThreadManager, ThreadManagerConfig, TopologyDiff, UiEventTap, ValidationResult, WidgetDescriptor, WindowConfig, WindowManager, WindowManagerConfig, WireConfig, WireDiff, WireMetrics, WireStatus, WireStatusMonitor, YamlPersistenceStore
logger_module — Менеджер логирования: каналы записи, сбор логов процессов; сюда — менять вывод и хранение логов
  ILoggerManager (19), ILogChannel (2), LogLevel, LogScope, ScopeName
  классы: ConsoleChannel, ErrorFloor, FileChannel, FrameTraceChannel, HttpChannel, LogChannel, LogRecord, LoggerChannelSchema, LoggerCore, LoggerManager, LoggerManagerConfig, LoggerRuleSchema, LoggerScopeSchema, MemoryChannel, NameHierarchy, NullChannel, ProcessHooks, RateSampler, RouterPushChannel, SealFormatter, SecretRedactor, StdLoggerFacade, WindowedVoices
message_module — Транспортный протокол сообщений между менеджерами и процессами; сюда — менять формат сообщений
  IMessage (12)
  классы: AddressValidationError, CommandMessageSchema, ContractCheck, LogLevel, LogMessageSchema, Message, MessageAdapter, MessageContract, MessageContractRegistry, MessageType, MessageValidationError, Priority
process_manager_module — Оркестратор процессов: запуск системы, реестр, приоритеты, мониторинг; сюда — менять управление процессами
  ISystemLauncher (9), IProcessManagerProcess (7), IProcessRegistry (7)
  классы: AlertRule, ChildProcessStop, ObservabilitySubscriptionBroker, PreStopStep, ProcessConfig, ProcessManagerProcess, ProcessMonitor, ProcessPriority, ProcessRegistry, ProcessSchemaAdapter, ProcessSpawner, ProcessStatusMonitor, ProcessTreeGuard, RestartPolicy, SpawnBackend, StubPlatformAdapter, SystemBlueprint, SystemLauncher, TopologyManager, Wire
process_module — Базовый класс процесса: создание, инициализация, управление, мониторинг; сюда — менять жизнь процесса
  IProcessModule (14), IProcessCommunication (11), ISharedResources (5), ProcessStatsDict
  классы: BreakerState, BuiltinCommands, CircuitBreaker, CollectionExecutor, ConfigReloadParams, ConsoleProcessConfig, CpuClock, DiagThreadRaiseParams, DiagWarnParams, FlightRecorder, GcCollectionOwner, GcDiscipline, GcOwnerStats, HealthField, HealthReportParams, HealthReporter, HealthSelfTestError, HealthState, HealthStatus, IActuationScheduler, IHealthReporter, IPluginCommandManager, IPluginMemoryManager, IPluginRouter, IPluginStatsManager, IPluginWorkerManager, IProcessServices, IoPeekPublisher, LastErrorKey, LogTailSubscribeParams, LogTailUnsubscribeParams, LoggerSinkParams, LoggerSinkTailParams, ManagerType, ManagersBundle, ManagersConfig, MetricRule, MockCommandManager, MockDocumentSink, MockProcessServices, MockStatsManager, MockWorkerManager, NoParams, ObservabilityAudit, ObservabilityCommandsConfig, ObservabilityConfig, ObservabilityDocumentsConfig, ObservabilityErrorsConfig, ObservabilityEventsConfig, ObservabilityFlightConfig, ObservabilityHistoryConfig, ObservabilityIntrospectParams, ObservabilityLayers, ObservabilityPersistParams, ObservabilityStatsConfig, ObservabilityTailBrokerParams, ObservabilityTailSubscribeParams, ObservabilityTailUnsubscribeParams, ObservabilityVoicesConfig, ObservationPolicy, ObservationPolicyConfig, PluginCategory, PluginContext, PluginDiscoveryResult, PluginEntry, PluginLevels, PluginManager, PluginMetrics, PluginState, PluginTestBench, PolicyDecision, Port, PortValidationError, ProcessAdapter, ProcessCommunication, ProcessConfigDict, ProcessConfigHandler, ProcessHeartbeat, ProcessIO, ProcessLaunchConfig, ProcessLifecycle, ProcessManagers, ProcessMetadataDict, ProcessModule, ProcessModulePlugin, ProcessPriorityLevel, ProcessState, QueueType, RouterRelayParams, RoutingProbeParams, RoutingRefreshParams, SchemaAdapter, SubPluginContext, SystemThreads, TelemetryGate, TelemetryPublishConfig, TelemetryReconfigureParams, WideEventSelector, WireConfigureParams, WireDeconfigureParams, WorkerCreateParams, WorkerNameParams
recipe — Управление рецептами: снимки конфигурации, определение формата, миграции, CRUD; сюда — менять рецепты
  RecipeManagerProtocol (15), RecipeEngineProtocol (10), StoreProtocol (3)
  классы: RecipeConflict, RecipeEngine, RecipeFormatError, RecipeFormatHook, RecipeLockTimeout, RecipeManager, RecipeService, YamlPatchConflict, YamlWriteRefused
registers_module — Рантайм именованных регистров: подписки на поля, карта маршрутов, отправка; сюда — менять регистры
  IRegistersManager (15)
  классы: FieldInfo, RegistersManager
router_module — Маршрутизация сообщений между процессами через RouterManager; сюда — менять каналы и правила доставки
  IRouterManager (21), IMessageChannel (9)
  классы: AsyncReceiver, AsyncSender, FrameShmMiddleware, MessageChannel, MiddlewarePipeline, QueueChannel, RouteDecision, RouterAdapter, RouterManager, RouterManagerConfig, RouterReentrantRequestError, RouterSchemaAdapter, RouterSendError, SocketBridgeAdapter, SocketChannel, SocketClient, SocketConnectionLost, UnknownMessageTypeError
service_module — Реестр и жизненный цикл долгоживущих сервисов (камеры, БД, auth); сюда — менять учёт сервисов
  IService (3), ServiceLifecycle (0)
  классы: DiscoveryResult, ServiceEntry, ServiceHost, ServiceRegistry
shared_resources_module — Pickle-safe реестр общих ресурсов для межпроцессного обмена; сюда — менять передачу ресурсов процессам
  IConfigStore, IEventManager, IMemoryManager, IProcessStateRegistry, IQueueRegistry, … ещё 1
  классы: ConfigStore, DataSchemaAdapter, EventHandle, EventManager, EventType, EventsProxy, FramePool, FrameReader, ISharedResourcesManager, LoanLedger, LoanTicket, ManagerStatsMixin, MemoryAccessStatus, MemoryConfigDict, MemoryHandle, MemoryManager, PoolStats, ProcessData, ProcessDataDict, ProcessDataKeys, ProcessHandle, ProcessStateRegistry, QoSProfile, QueueConfigDict, QueueHandle, QueueRegistry, QueuesProxy, ReaderGoneQueue, ResourceType, RingBufferReader, RingBufferWriter, SharedResourcesManager, SharedResourcesManagerConfig, ShmFrameReader, ShmRegistry
state_store_module — Реактивное иерархическое дерево состояния: сервер и клиентский кэш с подписками; сюда — менять общее состояние
  IStateProxy (7), IStateStore (6), IStateStoreManager (5), IRouter (3)
  классы: Delta, DeltaDispatcher, GuiStateProxy, HealthMonitor, IStateAdapter, InMemoryRouter, LoggingMiddleware, MetricsMiddleware, MiddlewarePipeline, PersistenceManager, PersistenceMiddleware, Selector, SelectorRegistry, StateAdapterBase, StateInspector, StateMiddleware, StateProxy, StateStoreManager, StateWriter, Subscription, SubscriptionManager, ThrottleMiddleware, TopologyGateMiddleware, Transaction, TreeStore, ValidationMiddleware, WatchedProcess
statistics_module — Менеджер статистики и метрик, третья плоскость наблюдаемости; сюда — менять сбор и вывод метрик
  IStatsManager (9)
  классы: AggregationWindow, CardinalityGuard, FileStatsChannel, HubStatsChannel, LogStatsChannel, MetricRecord, MetricType, NumbersGate, ObservationManager, ObservationPort, ObservationRecord, PathSchedule, PluginObservationHandle, StatsAdapter, StatsManager, StatsManagerConfig
telemetry_readmodel_module — Qt-free ядро read-model телеметрии: проекция значений и кольцевая история; сюда — менять чтение телеметрии
  ITelemetryReadModel (9)
  классы: TelemetryReadModel
worker_module — Менеджер потоков-воркеров внутри процесса: старт, стоп, пауза, перезапуск; сюда — менять управление потоками
  IWorkerManager (22), IWorkerRegistry (8), IExecutorManager (6), IWorkerLifecycle (4), OrderedExecutor (4), … ещё 3
  классы: ExecutionMode, ExecutorManager, ExecutorSpec, IExecutorRegistry, KeyedExecutor, ThreadConfig, ThreadPriority, ThreadWorkerConfig, WorkerAdapter, WorkerInfo, WorkerLifecycle, WorkerManager, WorkerManagerConfig, WorkerRegistry, WorkerSchemaAdapter, WorkerStatus, WorkerType
services/auth — Аутентификация и RBAC: хеши паролей, пользователи, роли; сюда — менять вход и права доступа
  IAuthManager (12), IUserStorage (5), IPasswordHasher (2), ISessionTracker (2), IAuditWriter (1)
  классы: AccountLocked, AuditEntry, AuditImmutableError, AuditWriter, AuthConfig, AuthError, AuthManager, AuthService, BcryptHasher, DevPasswordRequired, InvalidCredentials, LastAdminError, LockoutPolicy, LockoutTracker, PasswordPolicy, PermissionDenied, PermissionDescriptor, PermissionsRegistry, Role, RoleNotFound, SessionEntry, SessionExpired, SessionTracker, SqliteAuditStorage, StorageCorrupted, User, UserAlreadyExists, UserNotFound, WeakPassword, YamlUserStorage
services/camera_device — Общее ядро камер: контракт порта прибора и его фейк; сюда — менять порт, границу SDK и эмуляцию
  классы: Binding, DeviceIdentity, DevicePort, DeviceSdk, FakePort, ParamInfo, PortError, RawFrame
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
services/hikvision_camera — Сервис промышленной камеры Hikvision: SDK, логика, плагин; сюда — менять работу с камерой
  HikvisionCameraProtocol (6)
  классы: CameraParameters, CameraState, DeviceEntry, DeviceInfo, FakeBackend, FakeMvCamera, FrameConverter, HikvisionCamera, HikvisionCameraConfig, HikvisionCameraPlugin, HikvisionCameraRegisters, HikvisionCameraService, HikvisionCameraWindow, MVCC_ENUMENTRY, MVCC_ENUMVALUE, MVCC_FLOATVALUE, MVCC_INTVALUE, MVCC_INTVALUE_EX, MVCC_STRINGVALUE, MV_CC_DEVICE_INFO, MV_CC_DEVICE_INFO_LIST, MV_FRAME_OUT, MV_FRAME_OUT_INFO, MV_GIGE_DEVICE_INFO, MV_USB3_DEVICE_INFO, MvCamera, MvsBackend, PixelType, ProbeError, SdkError, Session
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
  классы: DatabasePlugin, DatabasePluginConfig, DatabaseRegisters, DetectionSchema, DrawingIoPlugin, DrawingIoPluginConfig, DrawingIoRegisters, FrameSaverPlugin, FrameSaverPluginConfig, FrameSaverRegisters, OtelExportPlugin, OtelExportPluginConfig, OtelExportRegisters, OtelExportSubscribeError, RobotDrawPlugin, RobotDrawPluginConfig, RobotDrawRegisters, RobotIoPlugin, RobotIoPluginConfig, RobotIoRegisters, TelemetrySinkPlugin, TelemetrySinkPluginConfig, TelemetrySinkRegisters, TelemetrySnapshot
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
  классы: AuditLog, BackendDriver, BackendHarness, BackendUnavailable, Capabilities, DeliveryWindow, DriverSession, EventHub, MCPNotInstalled, MemoryStats, ObservabilityCounters, ProcessCapabilities, QueueDepths, RecordWriter, Recorder, Recording, RecordingError, RegisterOps, ReplayPlayer, RouterStats, SDKToolServer, ToolSpec, WatchController, WorkerStatus
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
  классы: ActuationScheduler, AllocProfiler, CycleMetricsRecorder, DataReceiver, FramePacer, GenericProcess, GenericProcessConfig, IdleWorker, ItemCollector, LatencyProbes, PassThroughCollector, PipelineExecutor, PipelineStepNode, PluginConfig, PluginOperationStep, PluginOrchestrator, PluginRunner, SourceProducer, SuspectTagStep
prototype/frontend/widgets — Виджеты GUI прототипа по доменам: вкладки, дисплеи, диалоги, камера; сюда — менять экраны и компоненты UI
prototype/frontend/widgets/tabs — Вкладки приложения: реестр фабрик вкладок из единого списка TABS; сюда — менять состав вкладок
prototype/frontend/widgets/tabs/pipeline — Вкладка визуального конструктора pipeline: граф, палитра плагинов, инспектор; сюда — менять редактор pipeline
prototype/frontend/widgets/tabs/services — Вкладка управления сервисами: секции из реестра, запуск/остановка, пути; сюда — менять экран сервисов
prototype/frontend/widgets/tabs/settings — Пилотная вкладка Settings, сквозной пример таба; сюда — менять вкладку настроек
