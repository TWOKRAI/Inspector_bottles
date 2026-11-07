# Спецификация юнитов

Сгенерировано `scripts/arch_map/build.py` (commit `1dc6c71b7`, schema 1). Не править руками.
fan-in / fan-out — число других юнитов по рёбрам hard+lazy (tc не считается); I = fan-out / (fan-in + fan-out).
Тесты — число файлов `test_*.py` юнита; в LOC и files они не входят.

## Слой `multiprocess_framework` — юнитов: 28

| unit | tier | contour | purpose | команд | в рецептах | LOC | files | tests | fan-in | fan-out | I | interfaces | findings |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| `multiprocess_framework.__root__` | — | — | — | 0 | 0 | 770 | 5 | 0 | 10 | 20 | 0.67 | — | deep-import 1 |
| `multiprocess_framework.modules.actions_module` | optional | — | actions -- строительные блоки undo/redo фреймворка (под контракт UndoRedoController). | 0 | 0 | 912 | 11 | 6 | 4 | 2 | 0.33 | IRegistersManagerGui | unit-undeclared 1 |
| `multiprocess_framework.modules.app_module` | optional | — | ``app_module`` — «рыба-шаблон» приложения: generic composition root (ярус 2, Ф5.11). | 0 | 0 | 1715 | 9 | 17 | 4 | 6 | 0.6 | BlueprintLoader, ProcDictsBuilder, StateBootstrap, ThrottleRules +2 | deep-import 22, unit-undeclared 1 |
| `multiprocess_framework.modules.base_manager` | core | — | base_manager — основа для всех менеджеров системы. | 0 | 0 | 3232 | 21 | 19 | 25 | 5 | 0.17 | IBaseManager, IBaseAdapter, IObservableMixin, Stoppable +4 | unit-cycle 1, deep-import 5, private-import 2, unit-undeclared 1 |
| `multiprocess_framework.modules.chain_module` | core | — | chain_module — DAG/Chain execution engine для многопроцессных приложений. | 0 | 0 | 1605 | 20 | 8 | 2 | 2 | 0.5 | INodeConnection, IStepNode, IStepNodeWithWorker, IExecutionStep +3 | unit-undeclared 1 |
| `multiprocess_framework.modules.channel_routing_module` | core | — | channel_routing_module — базовый модуль маршрутизации по каналам. | 0 | 0 | 5189 | 24 | 34 | 11 | 4 | 0.27 | IChannel, IBufferStrategy, IChannelRoutingManager | unit-cycle 1, deep-import 3, private-import 3, unit-undeclared 1 |
| `multiprocess_framework.modules.command_module` | core | — | Command Module (Refactored) - Модуль управления командами. | 0 | 0 | 903 | 9 | 8 | 4 | 4 | 0.5 | ICommandManager | deep-import 1, unit-undeclared 1 |
| `multiprocess_framework.modules.config_module` | core | — | Config Module — управление конфигурациями в рантайме. | 0 | 0 | 1638 | 17 | 12 | 7 | 3 | 0.3 | IConfigObserver, IConfig, IConfigManager | deep-import 4, unit-undeclared 1 |
| `multiprocess_framework.modules.console_module` | core | — | console_module — менеджер терминальных окон процесса. | 1 | 0 | 1349 | 19 | 8 | 3 | 3 | 0.5 | IPlatformConsole, IConsoleManager | deep-import 1, unit-undeclared 1 |
| `multiprocess_framework.modules.data_schema_module` | core | — | data_schema_module — ядро описания структур данных для многопроцессного фреймворка. | 0 | 0 | 8072 | 60 | 31 | 30 | 1 | 0.03 | ISchema, ISchemaAdapter, HasBuild, IDataValidator +11 | unit-cycle 1, deep-import 2, unit-undeclared 1, unresolved-relative 1 |
| `multiprocess_framework.modules.dispatch_module` | core | — | Dispatch Module (Refactored) - Модуль диспетчеризации сообщений. | 0 | 0 | 1838 | 17 | 6 | 3 | 2 | 0.4 | IDispatcher | unit-undeclared 1 |
| `multiprocess_framework.modules.display_module` | optional | — | display_module — реестр именованных SHM-каналов для отображения кадров. | 0 | 0 | 523 | 3 | 1 | 3 | 0 | 0.0 | DisplayEntry, IDisplayChannel, IDisplayRegistry | unit-undeclared 1 |
| `multiprocess_framework.modules.error_module` | core | — | Error Module (Refactored) — специализированный менеджер ошибок. | 0 | 0 | 908 | 8 | 13 | 9 | 3 | 0.25 | IErrorManager | unit-cycle 1, deep-import 6, unit-undeclared 1 |
| `multiprocess_framework.modules.event_module` | optional | — | event_module — generic typed in-proc pub/sub (события-факты). | 0 | 0 | 368 | 4 | 3 | 2 | 2 | 0.5 | Subscription, EventBusProtocol | unit-undeclared 1 |
| `multiprocess_framework.modules.frontend_module` | optional | — | Frontend Module — модуль UI-фреймворка (конструктор PySide6-приложений). | 0 | 0 | 21156 | 254 | 57 | 2 | 11 | 0.85 | SupportsCommandMessage, IRouterLike, IRegistersManager, IRegistersManagerGui +6 | deep-import 10, unit-undeclared 1 |
| `multiprocess_framework.modules.logger_module` | core | — | Logger Module (Refactored) - Модуль системы логирования. | 0 | 0 | 7088 | 24 | 70 | 38 | 4 | 0.1 | ILogChannel, ILoggerManager | unit-cycle 1, deep-import 4, private-import 4, unit-undeclared 1 |
| `multiprocess_framework.modules.message_module` | core | — | message_module — универсальный транспортный протокол системы. | 0 | 0 | 1785 | 25 | 7 | 9 | 1 | 0.1 | IMessage | unit-undeclared 1 |
| `multiprocess_framework.modules.process_manager_module` | core | — | Process Manager Module (Refactored) — модуль управления процессами. | 1 | 0 | 12330 | 36 | 96 | 7 | 13 | 0.65 | ISystemLauncher, IProcessManagerProcess, IProcessRegistry | unit-cycle 1, deep-import 38, private-import 6, unit-undeclared 1 |
| `multiprocess_framework.modules.process_module` | core | — | Process Module (Refactored) — базовый модуль процессов. | 10 | 0 | 28892 | 80 | 262 | 76 | 18 | 0.19 | IProcessModule, ISharedResources, IProcessCommunication | unit-cycle 1, deep-import 77, private-import 4, unit-undeclared 1 |
| `multiprocess_framework.modules.recipe` | optional | — | recipe — управление рецептами (snapshot config-ветвей, detect, миграции, CRUD). | 0 | 0 | 2788 | 12 | 15 | 9 | 1 | 0.1 | StoreProtocol, RecipeEngineProtocol, RecipeManagerProtocol | unit-undeclared 1 |
| `multiprocess_framework.modules.registers_module` | optional | — | Модуль регистров: менеджер, карта маршрутизации, отправка по роутеру. | 0 | 0 | 965 | 7 | 8 | 5 | 3 | 0.38 | IRegistersManager | unit-undeclared 1 |
| `multiprocess_framework.modules.router_module` | core | — | router_module — менеджер маршрутизации сообщений. | 0 | 0 | 5915 | 24 | 55 | 11 | 10 | 0.48 | IRouterManager, IMessageChannel | deep-import 4, private-import 1, unit-undeclared 1 |
| `multiprocess_framework.modules.service_module` | optional | — | service_module — реестр и жизненный цикл long-running сервисов. | 0 | 0 | 633 | 5 | 4 | 14 | 0 | 0.0 | ServiceLifecycle, IService | unit-undeclared 1 |
| `multiprocess_framework.modules.shared_resources_module` | core | — | SharedResources Module — менеджер общих ресурсов для межпроцессного взаимодействия. | 0 | 0 | 5428 | 56 | 39 | 5 | 4 | 0.44 | ISharedResourcesManager | deep-import 5, unit-undeclared 1 |
| `multiprocess_framework.modules.state_store_module` | optional | — | state_store_module — реактивное дерево состояния для многопроцессных приложений. | 0 | 0 | 6184 | 35 | 27 | 7 | 4 | 0.36 | IRouter, IStateStore, IStateProxy, IStateStoreManager | deep-import 2, unit-undeclared 1 |
| `multiprocess_framework.modules.statistics_module` | core | — | statistics_module — менеджер статистики и метрик. | 5 | 0 | 3931 | 18 | 29 | 2 | 6 | 0.75 | IStatsManager | unit-cycle 1, deep-import 7, unit-undeclared 1 |
| `multiprocess_framework.modules.telemetry_readmodel_module` | optional | — | telemetry_readmodel_module — generic Qt-free ядро read-model телеметрии. | 0 | 0 | 487 | 3 | 3 | 2 | 0 | 0.0 | ITelemetryReadModel | unit-undeclared 1 |
| `multiprocess_framework.modules.worker_module` | core | — | worker_module — менеджер жизненного цикла потоков-воркеров. | 0 | 0 | 2360 | 19 | 11 | 5 | 3 | 0.38 | OrderedExecutor, IExecutorRegistry, IExecutorManager, IWorkerRegistry +2 | deep-import 1, unit-undeclared 1 |

## Слой `Services` — юнитов: 19

| unit | tier | contour | purpose | команд | в рецептах | LOC | files | tests | fan-in | fan-out | I | interfaces | findings |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| `Services.__root__` | — | — | — | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0.0 | — | — |
| `Services.auth` | — | — | Services/auth — модуль аутентификации и RBAC. | 0 | 0 | 2757 | 19 | 13 | 1 | 4 | 0.8 | IPasswordHasher, IUserStorage, IAuthManager, IAuditWriter +1 | deep-import 2, unit-undeclared 1 |
| `Services.camera_device` | — | — | Общее ядро камер: контракт порта прибора. Внешние модули зависят только от `interface.py`. | 0 | 0 | 472 | 4 | 3 | 0 | 0 | 0.0 | — | unit-hygiene 1, unit-undeclared 1, registry-drift 1 |
| `Services.code_reader` | — | — | Сервис промышленного считывателя кодов Hikrobot ID3000 (MV-ID3013PM-06M). | 6 | 4 | 4380 | 27 | 19 | 0 | 4 | 1.0 | CodeReaderSinkProtocol | deep-import 3, unit-undeclared 1, unresolved-absolute 1 |
| `Services.control_panel` | — | — | Services.control_panel — сервис «Пульт»: GUI-контролы → сигналы в pipeline. | 6 | 3 | 360 | 7 | 2 | 1 | 1 | 0.5 | ControlSpec | unit-undeclared 1 |
| `Services.dataset_gen` | — | — | dataset_gen — универсальный генератор синтетического датасета (cut-and-paste). | 0 | 0 | 1995 | 23 | 18 | 4 | 3 | 0.43 | SampleGenerator | deep-import 13, private-import 1, unit-undeclared 1 |
| `Services.device_hub` | — | — | device_hub — центральный реестр устройств и менеджер соединений. | 0 | 0 | 7203 | 30 | 36 | 1 | 6 | 0.86 | — | deep-import 36, unit-hygiene 1, unit-undeclared 1 |
| `Services.documents` | — | — | Плоскость документов: аудит смен наблюдаемости и вердикты о качестве детали. | 0 | 0 | 549 | 5 | 4 | 2 | 3 | 0.6 | IDocumentSink, IDocumentStore | deep-import 4, private-import 1, unit-undeclared 1 |
| `Services.hikvision_camera` | — | — | Services.hikvision_camera -- рефакторинг модуля Hikvision камеры. | 13 | 5 | 3636 | 22 | 10 | 4 | 4 | 0.5 | HikvisionCameraProtocol | deep-import 4, unit-undeclared 1 |
| `Services.layer_render` | — | — | `layer_render` — стек слоёв фона для сцены (Task 1.1), геометрия/композиция и Windows-safe I/O (Task 2.1), | 0 | 0 | 2227 | 15 | 15 | 5 | 0 | 0.0 | SolidFill, ScrollingTile | unit-undeclared 1 |
| `Services.line_sim` | — | — | line_sim — объект-агностичный движок сцены «лента с объектами». | 0 | 0 | 2396 | 19 | 48 | 2 | 3 | 0.6 | ObjectPassport, SceneCompositorProtocol | deep-import 18, private-import 1, unit-undeclared 1 |
| `Services.ml_inference` | — | — | ml_inference — сервис инференса нейросетей (вход кадр → классы + confidence). | 3 | 5 | 1441 | 17 | 12 | 2 | 3 | 0.6 | InferenceBackend, ModelCatalog | unit-undeclared 1 |
| `Services.ml_train` | — | — | ml_train — универсальный сервис обучения и выбора моделей. | 0 | 0 | 1820 | 12 | 9 | 1 | 5 | 0.83 | TrainSample, RunSource, ModelExporter | deep-import 3, unit-undeclared 1 |
| `Services.modbus` | — | — | modbus — универсальный драйвер Modbus-TCP / RS485 (RTU). | 5 | 0 | 2315 | 24 | 14 | 5 | 4 | 0.44 | RegisterTransport, ModbusClientProtocol | deep-import 1, unit-undeclared 1 |
| `Services.otel_export` | — | — | Services/otel_export — SDK экспорта записей наблюдаемости наружу по OTLP. | 0 | 0 | 1470 | 6 | 11 | 1 | 3 | 0.75 | Resource, MappedRecord, ExportOutcome, FlushOutcome +4 | deep-import 4, unit-undeclared 1 |
| `Services.phone_gateway` | — | — | Services.phone_gateway -- приём фото и текста с телефона по WiFi. | 6 | 6 | 1027 | 11 | 5 | 1 | 1 | 0.5 | FrameSource | unit-undeclared 1 |
| `Services.robot_comm` | — | — | robot_comm — сервис устройства «робот Delta» поверх Services/modbus. | 0 | 0 | 11508 | 41 | 69 | 5 | 7 | 0.58 | DeviceTransport, RobotClientProtocol | deep-import 16, unit-undeclared 1 |
| `Services.sql` | — | — | sql_module — универсальный SQL-менеджер для multiprocess framework. | 0 | 0 | 2742 | 31 | 8 | 4 | 5 | 0.56 | IEngineAdapter, ISyncEngineAdapter, IAsyncEngineAdapter, IRepository +4 | deep-import 4, unit-undeclared 1 |
| `Services.vfd_comm` | — | — | vfd_comm — сервис устройства «ПЧ INVT GD20», транспорт-агностик. | 0 | 0 | 386 | 9 | 2 | 2 | 2 | 0.5 | VfdClientProtocol | deep-import 1, unit-undeclared 1 |

## Слой `Plugins` — юнитов: 73

> Внимание: fan-in и fan-out считают только импорты. Плагины подключаются конфигом, строками `plugin_class:` в рецептах (`*.yaml`/`*.yml` по всему репозиторию), поэтому fan-in 0 не значит «не используется». Колонка «в рецептах» считает только живые рецепты (без путей с `tests`, `fixtures`, `archive`; они лежат в `spec.recipes_inactive`).

| unit | tier | contour | purpose | команд | в рецептах | LOC | files | tests | fan-in | fan-out | I | interfaces | findings |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| `Plugins.__root__` | — | — | — | 0 | 0 | 14 | 1 | 0 | 0 | 2 | 1.0 | — | private-import 1 |
| `Plugins._shared.__root__` | — | — | — | 0 | 0 | 4 | 1 | 0 | 1 | 0 | 0.0 | — | — |
| `Plugins._shared.fanin` | — | — | fanin — доменные корреляционные буферы DataReceiver (fan-in / join). | 0 | 0 | 355 | 4 | 4 | 1 | 2 | 0.67 | — | deep-import 2, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.calibration.__root__` | — | — | — | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0.0 | — | — |
| `Plugins.calibration.camera_robot` | — | — | camera_robot_calibration — оркестратор калибровки камера↔робот↔энкодер. | 10 | 1 | 856 | 6 | 4 | 1 | 2 | 0.67 | — | deep-import 1, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.control.__root__` | — | — | — | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0.0 | — | — |
| `Plugins.control.robot_control` | — | — | RobotControlPlugin — управление отбраковкой по результатам детекции. | 5 | 2 | 605 | 4 | 11 | 0 | 3 | 1.0 | — | deep-import 1, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.filter.__root__` | — | — | — | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0.0 | — | — |
| `Plugins.filter.line_filter` | — | — | LineFilter — фильтр виртуальной линии (virtual tripwire / line-crossing). | 0 | 7 | 554 | 6 | 4 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.hub.__root__` | — | — | — | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0.0 | — | — |
| `Plugins.hub.device_hub` | — | — | device_hub плагин — always-on хаб устройств в процессе devices. | 17 | 9 | 1132 | 5 | 22 | 6 | 7 | 0.54 | — | deep-import 8, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.io.__root__` | — | — | — | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0.0 | — | — |
| `Plugins.io.database` | — | — | Database plugin — хранение результатов детекции в SQLite (через Services/sql). | 4 | 2 | 281 | 5 | 1 | 0 | 3 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.io.drawing_io` | — | — | Plugins.io.drawing_io — сохранение/загрузка карты точек рисунка (JSON + PNG). | 2 | 2 | 280 | 5 | 2 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.io.frame_saver` | — | — | Frame Saver plugin — периодическое сохранение кадров на диск. | 2 | 3 | 525 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.io.otel_export` | — | — | otel_export — хост экспортёра OTLP: плагин в GenericProcessApp. | 2 | 1 | 1157 | 4 | 6 | 0 | 5 | 1.0 | — | deep-import 9, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.io.robot_draw` | — | — | robot_draw — приёмник точек рисования: pipeline → devices (robot_draw_polyline). | 1 | 2 | 326 | 4 | 1 | 0 | 4 | 1.0 | — | deep-import 4, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.io.robot_io` | — | — | robot_io v2 — тонкий job-форвардер: координаты из pipeline -> devices (DeviceHubClient). | 0 | 5 | 279 | 4 | 1 | 0 | 3 | 1.0 | — | deep-import 1, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.io.telemetry_sink` | — | — | telemetry_sink — сток истории телеметрии StateStore в SQLite (через Services/sql). | 3 | 2 | 430 | 5 | 3 | 0 | 3 | 1.0 | — | deep-import 1, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.__root__` | — | — | — | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0.0 | — | — |
| `Plugins.processing.blob_detector` | — | — | BlobDetectorPlugin — детекция цветных контуров по HSV-маске. | 3 | 5 | 218 | 4 | 4 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.blob_filter` | — | — | blob_filter — удаление мелких/крупных связных областей (blob) по площади. | 0 | 2 | 97 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.blur` | — | — | BlurPlugin — размытие BGR-кадра через cv2.GaussianBlur. | 0 | 0 | 89 | 3 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.center_crop` | — | — | CenterCropPlugin — динамический квадратный crop вокруг найденного центра. | 1 | 6 | 296 | 4 | 1 | 0 | 2 | 1.0 | — | deep-import 1, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.circle_detector` | — | — | CircleDetectorPlugin — детекция окружностей через cv2.HoughCircles. | 4 | 6 | 416 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.color_convert` | — | — | color_convert — processing-плагин конвертации цветовых каналов (BGR ↔ RGB). | 0 | 8 | 126 | 4 | 0 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.color_mask` | — | — | ColorMaskPlugin — HSV-маска по цвету. | 1 | 4 | 169 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.contour_draw` | — | — | contour_draw — атомарный плагин отрисовки линии контура вокруг найденного цвета. | 0 | 1 | 87 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.contour_finder` | — | — | contour_finder — атомарный плагин поиска контуров и площади по бинарной маске. | 0 | 2 | 104 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.crop` | — | — | Plugins.processing.crop — обрезка кадра по прямоугольнику [x,y,w,h] + resize. | 0 | 2 | 153 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.edge_detection` | — | — | edge_detection — детекция линий портрета нейросетью TEED (line-art). | 0 | 2 | 503 | 10 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.flip` | — | — | FlipPlugin — вертикальный переворот кадра. | 0 | 1 | 54 | 3 | 0 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.grayscale` | — | — | GrayscalePlugin — конвертация BGR → GRAY. | 0 | 2 | 59 | 3 | 0 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.hsv_mask` | — | — | hsv_mask — атомарный плагин HSV-маски по цвету (кадр сохраняется). | 0 | 7 | 111 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.image_adjust` | — | — | image_adjust — коррекция кадра: яркость, контраст, насыщенность, гамма. | 0 | 2 | 126 | 5 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.mask_to_frame` | — | — | MaskToFramePlugin — мост: одноканальная маска → BGR-кадр для дисплея. | 0 | 7 | 75 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.morphology` | — | — | morphology — атомарный плагин морфологии бинарной маски (open/close/erode/dilate). | 0 | 6 | 145 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.negative` | — | — | NegativePlugin — инверсия цвета (негатив). | 0 | 1 | 54 | 3 | 0 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.pixel_to_robot` | — | — | Plugins.processing.pixel_to_robot — применение калибровки px → мм робота (забор). | 1 | 4 | 313 | 5 | 1 | 0 | 2 | 1.0 | — | deep-import 2, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.points_render` | — | — | points_render — карта точек робота (точки + путь pen-down/pen-up) на холсте. | 0 | 2 | 253 | 5 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.region_split` | — | — | RegionSplitPlugin — нарезка кадра на регионы с fan-out маршрутизацией. | 0 | 1 | 139 | 3 | 0 | 0 | 1 | 1.0 | — | deep-import 1, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.resize` | — | — | ResizePlugin — масштабирование кадра. | 0 | 1 | 153 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.robot_scale` | — | — | Plugins.processing.robot_scale — масштаб пути px → реальные координаты робота. | 0 | 2 | 201 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.roi_crop` | — | — | RoiCropPlugin — вырез одного прямоугольного ROI скалярными live-полями. | 0 | 7 | 104 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.segmentation` | — | — | segmentation — удаление фона (человек на белом) через MediaPipe selfie segmenter. | 0 | 2 | 177 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.stitcher` | — | — | StitcherPlugin — склейка регионов в единый кадр. | 0 | 1 | 142 | 3 | 0 | 0 | 1 | 1.0 | — | deep-import 1, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.strokes_to_points` | — | — | strokes_to_points — линия→точки для робота (контуры, прореживание, scale+offset, перо). | 0 | 2 | 800 | 5 | 3 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.text_vector` | — | — | Plugins.processing.text_vector — векторный однолинейный генератор текста/сердца → draw_points. | 0 | 2 | 446 | 6 | 2 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.processing.word_layout` | — | — | Plugins.processing.word_layout — планировщик раскладки слова для робота-сортировщика. | 1 | 4 | 808 | 6 | 12 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.render.__root__` | — | — | — | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0.0 | — | — |
| `Plugins.render.circle_draw` | — | — | CircleDrawPlugin — рисует окружности (detections) на кадре для дисплея. | 0 | 6 | 103 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.render.overlay_draw` | — | — | OverlayDrawPlugin — рисовальщик draw-params (линии/полосы/точки) на кадре. | 0 | 10 | 309 | 5 | 4 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.render.render_overlay` | — | — | RenderOverlayPlugin — наложение маски и bounding boxes на кадр. | 3 | 3 | 232 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.render.renderer_compositor` | — | — | RendererCompositorPlugin — compositing нескольких кадров в один. | 2 | 1 | 270 | 4 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.runtime.__root__` | — | — | — | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0.0 | — | — |
| `Plugins.runtime.chain_executor` | — | — | ChainExecutorPlugin — оркестрация цепочки sub-плагинов. | 4 | 0 | 304 | 4 | 1 | 0 | 2 | 1.0 | — | deep-import 1, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.runtime.worker_pool` | — | — | WorkerPoolPlugin — параллельная обработка items через пул потоков. | 2 | 0 | 248 | 4 | 1 | 0 | 2 | 1.0 | — | deep-import 1, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.sim.__root__` | — | — | — | 0 | 0 | 9 | 1 | 0 | 0 | 0 | 0.0 | — | — |
| `Plugins.sim.layer_preview` | — | — | layer_preview — превью пресета слоёв в своём процессе ``layers`` (план line-sim-layer-editor, | 4 | 1 | 336 | 2 | 9 | 0 | 3 | 1.0 | — | deep-import 3, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.sim.mjpeg_sink` | — | — | mjpeg_sink — раздача последнего кадра по HTTP MJPEG (Ф1 плана ``line-sim``). | 0 | 1 | 285 | 3 | 1 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.sim.pult_web` | — | — | pult_web — веб-пульт ленты (Task 2.3b плана ``line-sim``). | 0 | 1 | 2026 | 2 | 26 | 0 | 2 | 1.0 | — | deep-import 1, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.sim.robot_host` | — | — | robot_host — хост ``SimRobotServer`` (Modbus TCP) для процесса ``robot`` сима. | 12 | 1 | 1130 | 2 | 20 | 0 | 4 | 1.0 | — | deep-import 7, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.sim.scene_source` | — | — | Плагины-хосты симулятора линии; сервис держит логику, плагин жизненный цикл; сюда — менять хост симуляции | 10 | 1 | 931 | 2 | 22 | 0 | 6 | 1.0 | — | deep-import 6, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.sinks.__root__` | — | — | — | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0.0 | — | — |
| `Plugins.sinks.modbus_sink` | — | — | modbus_sink — sink-плагин вывода метаданных кадра по Modbus (тест/симуляция). | 0 | 1 | 273 | 4 | 1 | 0 | 2 | 1.0 | — | deep-import 1, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.sources.__root__` | — | — | — | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0.0 | — | — |
| `Plugins.sources.camera_service` | — | — | CameraServicePlugin — multi-backend камера (simulator/webcam/hikvision/file). | 18 | 11 | 1563 | 12 | 9 | 1 | 3 | 0.75 | — | deep-import 5, unit-hygiene 1, unit-undeclared 1 |
| `Plugins.sources.capture` | — | — | CapturePlugin — захват кадров с вебкамеры через cv2.VideoCapture → SHM ring-buffer. | 6 | 7 | 364 | 3 | 3 | 0 | 2 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.sources.frame_counter` | — | — | FrameCounterPlugin — простой приёмник кадров для проверки IPC frame flow. | 0 | 3 | 68 | 3 | 0 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.sources.heartbeat` | — | — | Heartbeat plugin — периодический лог для проверки работоспособности системы. | 0 | 0 | 72 | 3 | 0 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.sources.synthetic_frame_source` | — | — | SyntheticFrameSourcePlugin — генератор кадров без реального железа (Ф7 G.1 baseline). | 0 | 4 | 80 | 2 | 0 | 0 | 1 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |
| `Plugins.utility.__root__` | — | — | — | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0.0 | — | — |
| `Plugins.utility.pilot_widgets` | — | — | pilot_widgets — тестовый плагин для проверки framework-фасадов form-фабрики. | 0 | 1 | 305 | 3 | 0 | 0 | 2 | 1.0 | — | unit-hygiene 1, unit-undeclared 1 |

## Слой `multiprocess_prototype` — юнитов: 7

| unit | tier | contour | purpose | команд | в рецептах | LOC | files | tests | fan-in | fan-out | I | interfaces | findings |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| `multiprocess_prototype.__root__` | — | — | — | 0 | 0 | 611 | 6 | 0 | 2 | 5 | 0.71 | — | deep-import 12 |
| `multiprocess_prototype.adapters` | — | — | multiprocess_prototype.adapters — adapter-слой между domain Protocols и реальными реестрами. | 0 | 0 | 2174 | 20 | 19 | 2 | 7 | 0.78 | — | deep-import 39, private-import 1, unit-hygiene 1, unit-undeclared 1 |
| `multiprocess_prototype.backend` | — | — | Backend-зона прототипа: декларативная конфигурация и wiring системы. | 0 | 0 | 3766 | 31 | 56 | 3 | 11 | 0.79 | — | deep-import 19, unit-hygiene 1, unit-undeclared 1 |
| `multiprocess_prototype.domain` | — | — | multiprocess_prototype.domain — изолированный типизированный domain-слой. | 0 | 0 | 3454 | 27 | 13 | 2 | 4 | 0.67 | — | unit-hygiene 1, unit-undeclared 1 |
| `multiprocess_prototype.frontend` | — | — | GUI-пакет прототипа: Qt-презентация PySide6 поверх бэкенда; сюда — менять экраны и GUI прототипа | 0 | 0 | 38877 | 280 | 206 | 1 | 29 | 0.97 | — | deep-import 201, private-import 1, unit-hygiene 1, unit-undeclared 1 |
| `multiprocess_prototype.recipes` | — | — | recipes — пакет управления рецептами (blueprint v2). | 0 | 0 | 1180 | 11 | 19 | 2 | 4 | 0.67 | — | deep-import 8, unit-hygiene 1, unit-undeclared 1 |
| `multiprocess_prototype.registers` | — | — | Регистры прототипа v2. | 0 | 0 | 945 | 5 | 2 | 1 | 2 | 0.67 | — | unit-hygiene 1, unit-undeclared 1 |

## Слой `backend_ctl` — юнитов: 1

| unit | tier | contour | purpose | команд | в рецептах | LOC | files | tests | fan-in | fan-out | I | interfaces | findings |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| `backend_ctl.__root__` | — | — | backend_ctl — тонкий внешний driver управления бэкендом по TCP (dev-инструмент). | 1 | 1 | 20279 | 71 | 100 | 0 | 14 | 1.0 | — | unit-undeclared 1 |

## Зависимости юнитов

### Слой `multiprocess_framework`

- `multiprocess_framework.__root__`
  - зависит от: `multiprocess_framework.modules.actions_module` (hard 1); `multiprocess_framework.modules.base_manager` (hard 2); `multiprocess_framework.modules.chain_module` (hard 1); `multiprocess_framework.modules.channel_routing_module` (hard 1); `multiprocess_framework.modules.command_module` (hard 1); `multiprocess_framework.modules.config_module` (hard 1); `multiprocess_framework.modules.console_module` (hard 1); `multiprocess_framework.modules.data_schema_module` (hard 1); `multiprocess_framework.modules.dispatch_module` (hard 1); `multiprocess_framework.modules.error_module` (hard 1); `multiprocess_framework.modules.logger_module` (hard 1, lazy 1); `multiprocess_framework.modules.message_module` (hard 1); `multiprocess_framework.modules.process_manager_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 1); `multiprocess_framework.modules.registers_module` (hard 1); `multiprocess_framework.modules.router_module` (hard 1); `multiprocess_framework.modules.shared_resources_module` (hard 1); `multiprocess_framework.modules.state_store_module` (hard 2); `multiprocess_framework.modules.statistics_module` (hard 1); `multiprocess_framework.modules.worker_module` (hard 1)
  - используют: `Services.documents` (hard 1); `multiprocess_framework.modules.base_manager` (hard 2); `multiprocess_framework.modules.channel_routing_module` (hard 3); `multiprocess_framework.modules.command_module` (hard 1); `multiprocess_framework.modules.dispatch_module` (hard 1); `multiprocess_framework.modules.logger_module` (hard 4); `multiprocess_framework.modules.process_manager_module` (hard 1, lazy 4); `multiprocess_framework.modules.process_module` (hard 7, lazy 4); `multiprocess_framework.modules.router_module` (hard 1); `multiprocess_framework.modules.statistics_module` (hard 2)
- `multiprocess_framework.modules.actions_module`
  - зависит от: `multiprocess_framework.modules.data_schema_module` (hard 1); `multiprocess_framework.modules.logger_module` (hard 3)
  - используют: `Services.sql` (hard 3, tc 1); `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.frontend_module` (tc 1); `multiprocess_prototype.adapters` (hard 1); `multiprocess_prototype.frontend` (hard 10, tc 3)
- `multiprocess_framework.modules.app_module`
  - зависит от: `multiprocess_framework.modules.config_module` (lazy 1); `multiprocess_framework.modules.data_schema_module` (lazy 2); `multiprocess_framework.modules.process_manager_module` (hard 1, lazy 3, tc 3); `multiprocess_framework.modules.process_module` (lazy 11); `multiprocess_framework.modules.recipe` (lazy 1); `multiprocess_framework.modules.state_store_module` (lazy 3)
  - используют: `backend_ctl.__root__` (lazy 1); `multiprocess_prototype.__root__` (hard 1, lazy 4); `multiprocess_prototype.backend` (lazy 4, tc 1); `multiprocess_prototype.frontend` (lazy 1)
- `multiprocess_framework.modules.base_manager`
  - зависит от: `multiprocess_framework.__root__` (hard 2); `multiprocess_framework.modules.channel_routing_module` (lazy 1); `multiprocess_framework.modules.data_schema_module` (hard 1); `multiprocess_framework.modules.error_module` (lazy 1); `multiprocess_framework.modules.logger_module` (lazy 3)
  - используют: `Plugins.hub.device_hub` (hard 2); `Services.auth` (hard 2); `Services.code_reader` (hard 1); `Services.device_hub` (hard 5); `Services.sql` (hard 1); `backend_ctl.__root__` (lazy 1); `multiprocess_framework.__root__` (hard 2); `multiprocess_framework.modules.chain_module` (hard 3); `multiprocess_framework.modules.channel_routing_module` (hard 2); `multiprocess_framework.modules.command_module` (hard 3); `multiprocess_framework.modules.config_module` (hard 2); `multiprocess_framework.modules.console_module` (hard 3); `multiprocess_framework.modules.dispatch_module` (hard 1); `multiprocess_framework.modules.event_module` (hard 1); `multiprocess_framework.modules.frontend_module` (hard 2); `multiprocess_framework.modules.logger_module` (hard 1); `multiprocess_framework.modules.process_manager_module` (hard 3); `multiprocess_framework.modules.process_module` (hard 5, lazy 2, tc 1); `multiprocess_framework.modules.registers_module` (hard 1); `multiprocess_framework.modules.router_module` (hard 1); `multiprocess_framework.modules.shared_resources_module` (hard 5); `multiprocess_framework.modules.state_store_module` (hard 2); `multiprocess_framework.modules.statistics_module` (hard 1); `multiprocess_framework.modules.worker_module` (hard 4); `multiprocess_prototype.backend` (hard 1)
- `multiprocess_framework.modules.chain_module`
  - зависит от: `multiprocess_framework.modules.base_manager` (hard 3); `multiprocess_framework.modules.worker_module` (hard 1)
  - используют: `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.process_module` (hard 1)
- `multiprocess_framework.modules.channel_routing_module`
  - зависит от: `multiprocess_framework.__root__` (hard 3); `multiprocess_framework.modules.base_manager` (hard 2); `multiprocess_framework.modules.data_schema_module` (hard 3); `multiprocess_framework.modules.logger_module` (lazy 3)
  - используют: `Plugins.io.otel_export` (hard 2); `Services.otel_export` (hard 3); `backend_ctl.__root__` (hard 2); `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.base_manager` (lazy 1); `multiprocess_framework.modules.error_module` (hard 3); `multiprocess_framework.modules.logger_module` (hard 9); `multiprocess_framework.modules.process_module` (hard 6, lazy 1); `multiprocess_framework.modules.router_module` (hard 2); `multiprocess_framework.modules.statistics_module` (hard 11); `multiprocess_prototype.frontend` (hard 1, lazy 1)
- `multiprocess_framework.modules.command_module`
  - зависит от: `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.base_manager` (hard 3); `multiprocess_framework.modules.data_schema_module` (hard 1); `multiprocess_framework.modules.dispatch_module` (hard 1); `multiprocess_framework.modules.worker_module` (tc 1)
  - используют: `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.process_manager_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 1, lazy 2); `multiprocess_framework.modules.router_module` (lazy 1)
- `multiprocess_framework.modules.config_module`
  - зависит от: `multiprocess_framework.modules.base_manager` (hard 2); `multiprocess_framework.modules.data_schema_module` (hard 3, lazy 2); `multiprocess_framework.modules.logger_module` (hard 1); `multiprocess_framework.modules.shared_resources_module` (tc 1)
  - используют: `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.app_module` (lazy 1); `multiprocess_framework.modules.process_manager_module` (hard 2, lazy 2); `multiprocess_framework.modules.process_module` (hard 4, lazy 5, tc 2); `multiprocess_framework.modules.router_module` (hard 1, lazy 1); `multiprocess_framework.modules.shared_resources_module` (lazy 1); `multiprocess_prototype.frontend` (lazy 2)
- `multiprocess_framework.modules.console_module`
  - зависит от: `multiprocess_framework.modules.base_manager` (hard 3); `multiprocess_framework.modules.data_schema_module` (hard 1); `multiprocess_framework.modules.logger_module` (hard 1)
  - используют: `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.process_manager_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 2, lazy 3)
- `multiprocess_framework.modules.data_schema_module`
  - зависит от: `multiprocess_framework.modules.logger_module` (lazy 4); `multiprocess_framework.modules.process_module` (tc 1); `multiprocess_framework.modules.shared_resources_module` (tc 1)
  - используют: `Plugins.io.database` (hard 1); `Plugins.io.telemetry_sink` (hard 1); `Plugins.utility.pilot_widgets` (hard 1); `Services.auth` (hard 2); `Services.documents` (hard 1); `Services.hikvision_camera` (hard 5); `Services.robot_comm` (hard 1); `Services.sql` (hard 4); `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.actions_module` (hard 1); `multiprocess_framework.modules.app_module` (lazy 2); `multiprocess_framework.modules.base_manager` (hard 1); `multiprocess_framework.modules.channel_routing_module` (hard 3); `multiprocess_framework.modules.command_module` (hard 1); `multiprocess_framework.modules.config_module` (hard 3, lazy 2); `multiprocess_framework.modules.console_module` (hard 1); `multiprocess_framework.modules.error_module` (hard 1, lazy 1); `multiprocess_framework.modules.frontend_module` (hard 13); `multiprocess_framework.modules.logger_module` (hard 1); `multiprocess_framework.modules.message_module` (hard 3); `multiprocess_framework.modules.process_manager_module` (hard 3, lazy 4); `multiprocess_framework.modules.process_module` (hard 10, lazy 10); `multiprocess_framework.modules.registers_module` (hard 3); `multiprocess_framework.modules.router_module` (hard 1); `multiprocess_framework.modules.shared_resources_module` (hard 1, lazy 1); `multiprocess_framework.modules.statistics_module` (hard 2); `multiprocess_framework.modules.worker_module` (hard 3); `multiprocess_prototype.backend` (hard 3, lazy 2); `multiprocess_prototype.domain` (hard 8, lazy 1); `multiprocess_prototype.frontend` (tc 1); `multiprocess_prototype.registers` (hard 1)
- `multiprocess_framework.modules.dispatch_module`
  - зависит от: `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.base_manager` (hard 1)
  - используют: `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.command_module` (hard 1); `multiprocess_framework.modules.router_module` (hard 1)
- `multiprocess_framework.modules.display_module`
  - используют: `multiprocess_prototype.adapters` (hard 2); `multiprocess_prototype.backend` (hard 2, lazy 1, tc 1); `multiprocess_prototype.frontend` (hard 1, lazy 2, tc 1)
- `multiprocess_framework.modules.error_module`
  - зависит от: `multiprocess_framework.modules.channel_routing_module` (hard 3); `multiprocess_framework.modules.data_schema_module` (hard 1, lazy 1); `multiprocess_framework.modules.logger_module` (hard 4)
  - используют: `Plugins.hub.device_hub` (hard 1); `Plugins.io.robot_draw` (hard 1); `Plugins.io.robot_io` (hard 1); `Plugins.sources.capture` (hard 1); `backend_ctl.__root__` (lazy 1); `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.base_manager` (lazy 1); `multiprocess_framework.modules.process_manager_module` (hard 2, lazy 2); `multiprocess_framework.modules.process_module` (hard 1, lazy 1)
- `multiprocess_framework.modules.event_module`
  - зависит от: `multiprocess_framework.modules.base_manager` (hard 1); `multiprocess_framework.modules.logger_module` (hard 2)
  - используют: `multiprocess_framework.modules.frontend_module` (hard 1); `multiprocess_prototype.domain` (hard 2)
- `multiprocess_framework.modules.frontend_module`
  - зависит от: `multiprocess_framework.modules.actions_module` (tc 1); `multiprocess_framework.modules.base_manager` (hard 2); `multiprocess_framework.modules.data_schema_module` (hard 13); `multiprocess_framework.modules.event_module` (hard 1); `multiprocess_framework.modules.logger_module` (hard 23, lazy 2); `multiprocess_framework.modules.message_module` (hard 3); `multiprocess_framework.modules.process_module` (hard 1); `multiprocess_framework.modules.registers_module` (hard 1); `multiprocess_framework.modules.router_module` (hard 2, tc 1); `multiprocess_framework.modules.shared_resources_module` (hard 2); `multiprocess_framework.modules.state_store_module` (hard 1); `multiprocess_framework.modules.telemetry_readmodel_module` (hard 1)
  - используют: `Services.robot_comm` (hard 1); `multiprocess_prototype.frontend` (hard 80, lazy 18, tc 10)
- `multiprocess_framework.modules.logger_module`
  - зависит от: `multiprocess_framework.__root__` (hard 4); `multiprocess_framework.modules.base_manager` (hard 1); `multiprocess_framework.modules.channel_routing_module` (hard 9); `multiprocess_framework.modules.data_schema_module` (hard 1)
  - используют: `Plugins.io.otel_export` (hard 1); `Plugins.runtime.chain_executor` (hard 1); `Plugins.runtime.worker_pool` (hard 1); `Services.code_reader` (hard 1); `Services.dataset_gen` (hard 1); `Services.device_hub` (hard 3); `Services.hikvision_camera` (hard 1); `Services.ml_inference` (hard 7); `Services.ml_train` (hard 4); `Services.modbus` (hard 1); `Services.otel_export` (hard 1); `Services.robot_comm` (hard 3); `Services.sql` (hard 3); `backend_ctl.__root__` (lazy 1); `multiprocess_framework.__root__` (hard 1, lazy 1); `multiprocess_framework.modules.actions_module` (hard 3); `multiprocess_framework.modules.base_manager` (lazy 3); `multiprocess_framework.modules.channel_routing_module` (lazy 3); `multiprocess_framework.modules.config_module` (hard 1); `multiprocess_framework.modules.console_module` (hard 1); `multiprocess_framework.modules.data_schema_module` (lazy 4); `multiprocess_framework.modules.error_module` (hard 4); `multiprocess_framework.modules.event_module` (hard 2); `multiprocess_framework.modules.frontend_module` (hard 23, lazy 2); `multiprocess_framework.modules.process_manager_module` (hard 8, lazy 2); `multiprocess_framework.modules.process_module` (hard 9, lazy 17); `multiprocess_framework.modules.recipe` (hard 1); `multiprocess_framework.modules.registers_module` (hard 1); `multiprocess_framework.modules.router_module` (hard 1); `multiprocess_framework.modules.shared_resources_module` (hard 4); `multiprocess_framework.modules.state_store_module` (hard 1); `multiprocess_framework.modules.statistics_module` (hard 3, lazy 1); `multiprocess_framework.modules.worker_module` (hard 1); `multiprocess_prototype.adapters` (hard 5); `multiprocess_prototype.backend` (hard 4); `multiprocess_prototype.domain` (hard 1, lazy 1); `multiprocess_prototype.frontend` (hard 51, lazy 1); `multiprocess_prototype.recipes` (hard 4)
- `multiprocess_framework.modules.message_module`
  - зависит от: `multiprocess_framework.modules.data_schema_module` (hard 3)
  - используют: `Plugins.hub.device_hub` (lazy 2); `Plugins.io.otel_export` (hard 1); `backend_ctl.__root__` (hard 1); `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.frontend_module` (hard 3); `multiprocess_framework.modules.process_manager_module` (lazy 4); `multiprocess_framework.modules.process_module` (hard 1, lazy 3, tc 1); `multiprocess_framework.modules.router_module` (hard 3, lazy 1, tc 3); `multiprocess_prototype.frontend` (lazy 1)
- `multiprocess_framework.modules.process_manager_module`
  - зависит от: `multiprocess_framework.__root__` (hard 1, lazy 4); `multiprocess_framework.modules.base_manager` (hard 3); `multiprocess_framework.modules.command_module` (hard 1); `multiprocess_framework.modules.config_module` (hard 2, lazy 2); `multiprocess_framework.modules.console_module` (hard 1); `multiprocess_framework.modules.data_schema_module` (hard 3, lazy 4); `multiprocess_framework.modules.error_module` (hard 2, lazy 2); `multiprocess_framework.modules.logger_module` (hard 8, lazy 2); `multiprocess_framework.modules.message_module` (lazy 4); `multiprocess_framework.modules.process_module` (hard 10, lazy 13); `multiprocess_framework.modules.router_module` (hard 2); `multiprocess_framework.modules.shared_resources_module` (hard 6, lazy 6); `multiprocess_framework.modules.worker_module` (hard 1)
  - используют: `backend_ctl.__root__` (hard 1, tc 1); `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.app_module` (hard 1, lazy 3, tc 3); `multiprocess_framework.modules.process_module` (lazy 3); `multiprocess_prototype.__root__` (tc 1); `multiprocess_prototype.backend` (hard 2, lazy 1, tc 1); `multiprocess_prototype.frontend` (hard 1); `multiprocess_prototype.recipes` (lazy 1)
- `multiprocess_framework.modules.process_module`
  - зависит от: `multiprocess_framework.__root__` (hard 7, lazy 4); `multiprocess_framework.modules.base_manager` (hard 5, lazy 2, tc 1); `multiprocess_framework.modules.chain_module` (hard 1); `multiprocess_framework.modules.channel_routing_module` (hard 6, lazy 1); `multiprocess_framework.modules.command_module` (hard 1, lazy 2); `multiprocess_framework.modules.config_module` (hard 4, lazy 5, tc 2); `multiprocess_framework.modules.console_module` (hard 2, lazy 3); `multiprocess_framework.modules.data_schema_module` (hard 10, lazy 10); `multiprocess_framework.modules.error_module` (hard 1, lazy 1); `multiprocess_framework.modules.logger_module` (hard 9, lazy 17); `multiprocess_framework.modules.message_module` (hard 1, lazy 3, tc 1); `multiprocess_framework.modules.process_manager_module` (lazy 3); `multiprocess_framework.modules.registers_module` (hard 1, lazy 2); `multiprocess_framework.modules.router_module` (hard 11, lazy 3); `multiprocess_framework.modules.shared_resources_module` (hard 1); `multiprocess_framework.modules.state_store_module` (hard 2, lazy 1, tc 1); `multiprocess_framework.modules.statistics_module` (hard 5, lazy 7); `multiprocess_framework.modules.worker_module` (hard 1, lazy 8)
  - используют: `Plugins._shared.fanin` (hard 1); `Plugins.calibration.camera_robot` (hard 3); `Plugins.control.robot_control` (hard 9); `Plugins.filter.line_filter` (hard 7); `Plugins.hub.device_hub` (hard 3); `Plugins.io.database` (hard 10); `Plugins.io.drawing_io` (hard 3); `Plugins.io.frame_saver` (hard 9); `Plugins.io.otel_export` (hard 3); `Plugins.io.robot_draw` (hard 3); `Plugins.io.robot_io` (hard 3); `Plugins.io.telemetry_sink` (hard 7); `Plugins.processing.blob_detector` (hard 9); `Plugins.processing.blob_filter` (hard 3); `Plugins.processing.blur` (hard 5); `Plugins.processing.center_crop` (hard 7); `Plugins.processing.circle_detector` (hard 9); `Plugins.processing.color_convert` (hard 3); `Plugins.processing.color_mask` (hard 9); `Plugins.processing.contour_draw` (hard 3); `Plugins.processing.contour_finder` (hard 3); `Plugins.processing.crop` (hard 3); `Plugins.processing.edge_detection` (hard 3); `Plugins.processing.flip` (hard 5); `Plugins.processing.grayscale` (hard 5); `Plugins.processing.hsv_mask` (hard 3); `Plugins.processing.image_adjust` (hard 3); `Plugins.processing.mask_to_frame` (hard 3); `Plugins.processing.morphology` (hard 3); `Plugins.processing.negative` (hard 5); `Plugins.processing.pixel_to_robot` (hard 3); `Plugins.processing.points_render` (hard 3); `Plugins.processing.region_split` (hard 6); `Plugins.processing.resize` (hard 9); `Plugins.processing.robot_scale` (hard 3); `Plugins.processing.roi_crop` (hard 3); `Plugins.processing.segmentation` (hard 3); `Plugins.processing.stitcher` (hard 6); `Plugins.processing.strokes_to_points` (hard 3); `Plugins.processing.text_vector` (hard 3); `Plugins.processing.word_layout` (hard 3); `Plugins.render.circle_draw` (hard 3); `Plugins.render.overlay_draw` (hard 7); `Plugins.render.render_overlay` (hard 9); `Plugins.render.renderer_compositor` (hard 9); `Plugins.runtime.chain_executor` (hard 10); `Plugins.runtime.worker_pool` (hard 10); `Plugins.sim.layer_preview` (hard 1); `Plugins.sim.mjpeg_sink` (hard 4); `Plugins.sim.pult_web` (hard 1); `Plugins.sim.robot_host` (hard 1); `Plugins.sim.scene_source` (hard 1); `Plugins.sinks.modbus_sink` (hard 3); `Plugins.sources.camera_service` (hard 10); `Plugins.sources.capture` (hard 4); `Plugins.sources.frame_counter` (hard 6); `Plugins.sources.heartbeat` (hard 6); `Plugins.sources.synthetic_frame_source` (hard 1); `Plugins.utility.pilot_widgets` (hard 1); `Services.code_reader` (hard 6); `Services.control_panel` (hard 11); `Services.hikvision_camera` (hard 4); `Services.ml_inference` (hard 3); `Services.modbus` (hard 3); `Services.otel_export` (hard 1); `Services.phone_gateway` (hard 11); `backend_ctl.__root__` (hard 3, lazy 5); `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.app_module` (lazy 11); `multiprocess_framework.modules.data_schema_module` (tc 1); `multiprocess_framework.modules.frontend_module` (hard 1); `multiprocess_framework.modules.process_manager_module` (hard 10, lazy 13); `multiprocess_framework.modules.statistics_module` (lazy 2); `multiprocess_prototype.__root__` (hard 1); `multiprocess_prototype.adapters` (hard 1); `multiprocess_prototype.backend` (hard 3, lazy 2); `multiprocess_prototype.frontend` (hard 7, lazy 4)
- `multiprocess_framework.modules.recipe`
  - зависит от: `multiprocess_framework.modules.logger_module` (hard 1)
  - используют: `Plugins.sim.layer_preview` (hard 1); `Plugins.sim.scene_source` (hard 2); `multiprocess_framework.modules.app_module` (lazy 1); `multiprocess_framework.modules.state_store_module` (hard 1); `multiprocess_prototype.__root__` (lazy 1); `multiprocess_prototype.adapters` (hard 4); `multiprocess_prototype.backend` (hard 4); `multiprocess_prototype.frontend` (hard 4, lazy 4); `multiprocess_prototype.recipes` (hard 7)
- `multiprocess_framework.modules.registers_module`
  - зависит от: `multiprocess_framework.modules.base_manager` (hard 1); `multiprocess_framework.modules.data_schema_module` (hard 3); `multiprocess_framework.modules.logger_module` (hard 1)
  - используют: `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.frontend_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 1, lazy 2); `multiprocess_prototype.adapters` (tc 1); `multiprocess_prototype.frontend` (hard 10, lazy 1, tc 9); `multiprocess_prototype.registers` (hard 1)
- `multiprocess_framework.modules.router_module`
  - зависит от: `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.base_manager` (hard 1); `multiprocess_framework.modules.channel_routing_module` (hard 2); `multiprocess_framework.modules.command_module` (lazy 1); `multiprocess_framework.modules.config_module` (hard 1, lazy 1); `multiprocess_framework.modules.data_schema_module` (hard 1); `multiprocess_framework.modules.dispatch_module` (hard 1); `multiprocess_framework.modules.logger_module` (hard 1); `multiprocess_framework.modules.message_module` (hard 3, lazy 1, tc 3); `multiprocess_framework.modules.shared_resources_module` (lazy 4)
  - используют: `Plugins._shared.fanin` (hard 1); `Plugins.control.robot_control` (hard 1); `Services.modbus` (hard 1); `Services.robot_comm` (hard 1); `backend_ctl.__root__` (hard 1); `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.frontend_module` (hard 2, tc 1); `multiprocess_framework.modules.process_manager_module` (hard 2); `multiprocess_framework.modules.process_module` (hard 11, lazy 3); `multiprocess_framework.modules.state_store_module` (hard 1); `multiprocess_prototype.backend` (tc 1); `multiprocess_prototype.frontend` (hard 1, tc 2)
- `multiprocess_framework.modules.service_module`
  - используют: `Services.auth` (hard 1); `Services.dataset_gen` (hard 1); `Services.hikvision_camera` (hard 1); `Services.ml_inference` (hard 1); `Services.ml_train` (hard 1); `Services.modbus` (hard 1); `Services.robot_comm` (hard 1); `Services.sql` (hard 1); `Services.vfd_comm` (hard 1); `multiprocess_prototype.__root__` (lazy 1); `multiprocess_prototype.adapters` (hard 4); `multiprocess_prototype.backend` (hard 1); `multiprocess_prototype.domain` (hard 1); `multiprocess_prototype.frontend` (hard 2, lazy 2, tc 1)
- `multiprocess_framework.modules.shared_resources_module`
  - зависит от: `multiprocess_framework.modules.base_manager` (hard 5); `multiprocess_framework.modules.config_module` (lazy 1); `multiprocess_framework.modules.data_schema_module` (hard 1, lazy 1); `multiprocess_framework.modules.logger_module` (hard 4)
  - используют: `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.config_module` (tc 1); `multiprocess_framework.modules.data_schema_module` (tc 1); `multiprocess_framework.modules.frontend_module` (hard 2); `multiprocess_framework.modules.process_manager_module` (hard 6, lazy 6); `multiprocess_framework.modules.process_module` (hard 1); `multiprocess_framework.modules.router_module` (lazy 4)
- `multiprocess_framework.modules.state_store_module`
  - зависит от: `multiprocess_framework.modules.base_manager` (hard 2); `multiprocess_framework.modules.logger_module` (hard 1); `multiprocess_framework.modules.recipe` (hard 1); `multiprocess_framework.modules.router_module` (hard 1)
  - используют: `Plugins.io.telemetry_sink` (tc 1); `Plugins.sim.scene_source` (hard 1, tc 1); `multiprocess_framework.__root__` (hard 2); `multiprocess_framework.modules.app_module` (lazy 3); `multiprocess_framework.modules.frontend_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 2, lazy 1, tc 1); `multiprocess_prototype.backend` (hard 10); `multiprocess_prototype.frontend` (hard 2, lazy 2)
- `multiprocess_framework.modules.statistics_module`
  - зависит от: `multiprocess_framework.__root__` (hard 2); `multiprocess_framework.modules.base_manager` (hard 1); `multiprocess_framework.modules.channel_routing_module` (hard 11); `multiprocess_framework.modules.data_schema_module` (hard 2); `multiprocess_framework.modules.logger_module` (hard 3, lazy 1); `multiprocess_framework.modules.process_module` (lazy 2)
  - используют: `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.process_module` (hard 5, lazy 7)
- `multiprocess_framework.modules.telemetry_readmodel_module`
  - используют: `backend_ctl.__root__` (hard 1, lazy 1); `multiprocess_framework.modules.frontend_module` (hard 1)
- `multiprocess_framework.modules.worker_module`
  - зависит от: `multiprocess_framework.modules.base_manager` (hard 4); `multiprocess_framework.modules.data_schema_module` (hard 3); `multiprocess_framework.modules.logger_module` (hard 1)
  - используют: `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.chain_module` (hard 1); `multiprocess_framework.modules.command_module` (tc 1); `multiprocess_framework.modules.process_manager_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 1, lazy 8); `multiprocess_prototype.frontend` (hard 2)

### Слой `Services`

- `Services.auth`
  - зависит от: `Services.sql` (hard 4); `multiprocess_framework.modules.base_manager` (hard 2); `multiprocess_framework.modules.data_schema_module` (hard 2); `multiprocess_framework.modules.service_module` (hard 1)
  - используют: `multiprocess_prototype.frontend` (hard 6, lazy 1, tc 9)
- `Services.code_reader`
  - зависит от: `Services.hikvision_camera` (lazy 3); `multiprocess_framework.modules.base_manager` (hard 1); `multiprocess_framework.modules.logger_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 6)
- `Services.control_panel`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 11)
  - используют: `multiprocess_prototype.frontend` (lazy 1)
- `Services.dataset_gen`
  - зависит от: `Services.layer_render` (hard 14); `multiprocess_framework.modules.logger_module` (hard 1); `multiprocess_framework.modules.service_module` (hard 1)
  - используют: `Plugins.sim.scene_source` (hard 1); `Services.line_sim` (hard 5); `Services.ml_train` (hard 2, lazy 2); `multiprocess_prototype.frontend` (lazy 5)
- `Services.device_hub`
  - зависит от: `Services.hikvision_camera` (lazy 6); `Services.modbus` (lazy 4, tc 1); `Services.robot_comm` (hard 37, lazy 5, tc 1); `Services.vfd_comm` (lazy 1); `multiprocess_framework.modules.base_manager` (hard 5); `multiprocess_framework.modules.logger_module` (hard 3)
  - используют: `Plugins.hub.device_hub` (hard 5)
- `Services.documents`
  - зависит от: `Services.sql` (hard 4, lazy 1); `multiprocess_framework.__root__` (hard 1); `multiprocess_framework.modules.data_schema_module` (hard 1)
  - используют: `Plugins.control.robot_control` (hard 1); `backend_ctl.__root__` (lazy 1)
- `Services.hikvision_camera`
  - зависит от: `multiprocess_framework.modules.data_schema_module` (hard 5); `multiprocess_framework.modules.logger_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 4); `multiprocess_framework.modules.service_module` (hard 1)
  - используют: `Plugins.hub.device_hub` (lazy 1); `Plugins.sources.camera_service` (hard 4); `Services.code_reader` (lazy 3); `Services.device_hub` (lazy 6)
- `Services.layer_render`
  - используют: `Plugins.processing.center_crop` (hard 1); `Plugins.sim.scene_source` (hard 1); `Services.dataset_gen` (hard 14); `Services.line_sim` (hard 14); `Services.ml_train` (hard 1)
- `Services.line_sim`
  - зависит от: `Services.dataset_gen` (hard 5); `Services.layer_render` (hard 14); `Services.robot_comm` (hard 1)
  - используют: `Plugins.sim.layer_preview` (hard 4); `Plugins.sim.scene_source` (hard 3)
- `Services.ml_inference`
  - зависит от: `multiprocess_framework.modules.logger_module` (hard 7); `multiprocess_framework.modules.process_module` (hard 3); `multiprocess_framework.modules.service_module` (hard 1)
  - используют: `Services.ml_train` (hard 1); `multiprocess_prototype.frontend` (hard 1, lazy 1)
- `Services.ml_train`
  - зависит от: `Services.dataset_gen` (hard 2, lazy 2); `Services.layer_render` (hard 1); `Services.ml_inference` (hard 1); `multiprocess_framework.modules.logger_module` (hard 4); `multiprocess_framework.modules.service_module` (hard 1)
  - используют: `multiprocess_prototype.frontend` (lazy 2)
- `Services.modbus`
  - зависит от: `multiprocess_framework.modules.logger_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 3); `multiprocess_framework.modules.router_module` (hard 1); `multiprocess_framework.modules.service_module` (hard 1)
  - используют: `Plugins.sim.robot_host` (lazy 1); `Plugins.sinks.modbus_sink` (hard 2); `Services.device_hub` (lazy 4, tc 1); `Services.robot_comm` (hard 8, tc 1); `Services.vfd_comm` (hard 3, tc 1)
- `Services.otel_export`
  - зависит от: `multiprocess_framework.modules.channel_routing_module` (hard 3); `multiprocess_framework.modules.logger_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 1)
  - используют: `Plugins.io.otel_export` (hard 6)
- `Services.phone_gateway`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 11)
  - используют: `multiprocess_prototype.frontend` (hard 2)
- `Services.robot_comm`
  - зависит от: `Services.modbus` (hard 8, tc 1); `Services.vfd_comm` (hard 10); `multiprocess_framework.modules.data_schema_module` (hard 1); `multiprocess_framework.modules.frontend_module` (hard 1); `multiprocess_framework.modules.logger_module` (hard 3); `multiprocess_framework.modules.router_module` (hard 1); `multiprocess_framework.modules.service_module` (hard 1)
  - используют: `Plugins.hub.device_hub` (hard 1); `Plugins.io.robot_draw` (lazy 3); `Plugins.sim.robot_host` (hard 3, lazy 2); `Services.device_hub` (hard 37, lazy 5, tc 1); `Services.line_sim` (hard 1)
- `Services.sql`
  - зависит от: `multiprocess_framework.modules.actions_module` (hard 3, tc 1); `multiprocess_framework.modules.base_manager` (hard 1); `multiprocess_framework.modules.data_schema_module` (hard 4); `multiprocess_framework.modules.logger_module` (hard 3); `multiprocess_framework.modules.service_module` (hard 1)
  - используют: `Plugins.io.database` (hard 1); `Plugins.io.telemetry_sink` (hard 1); `Services.auth` (hard 4); `Services.documents` (hard 4, lazy 1)
- `Services.vfd_comm`
  - зависит от: `Services.modbus` (hard 3, tc 1); `multiprocess_framework.modules.service_module` (hard 1)
  - используют: `Services.device_hub` (lazy 1); `Services.robot_comm` (hard 10)

### Слой `Plugins`

- `Plugins.__root__`
  - зависит от: `Plugins._shared.__root__` (hard 1); `Plugins._shared.fanin` (hard 1)
- `Plugins._shared.__root__`
  - используют: `Plugins.__root__` (hard 1)
- `Plugins._shared.fanin`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 1); `multiprocess_framework.modules.router_module` (hard 1)
  - используют: `Plugins.__root__` (hard 1)
- `Plugins.calibration.camera_robot`
  - зависит от: `Plugins.hub.device_hub` (hard 1); `multiprocess_framework.modules.process_module` (hard 3)
  - используют: `Plugins.processing.pixel_to_robot` (lazy 2)
- `Plugins.control.robot_control`
  - зависит от: `Services.documents` (hard 1); `multiprocess_framework.modules.process_module` (hard 9); `multiprocess_framework.modules.router_module` (hard 1)
- `Plugins.filter.line_filter`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 7)
- `Plugins.hub.device_hub`
  - зависит от: `Services.device_hub` (hard 5); `Services.hikvision_camera` (lazy 1); `Services.robot_comm` (hard 1); `multiprocess_framework.modules.base_manager` (hard 2); `multiprocess_framework.modules.error_module` (hard 1); `multiprocess_framework.modules.message_module` (lazy 2); `multiprocess_framework.modules.process_module` (hard 3)
  - используют: `Plugins.calibration.camera_robot` (hard 1); `Plugins.io.robot_draw` (hard 1); `Plugins.io.robot_io` (hard 1); `Plugins.sim.pult_web` (hard 1); `Plugins.sim.robot_host` (hard 1); `Plugins.sources.camera_service` (lazy 1)
- `Plugins.io.database`
  - зависит от: `Services.sql` (hard 1); `multiprocess_framework.modules.data_schema_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 10)
- `Plugins.io.drawing_io`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.io.frame_saver`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 9)
- `Plugins.io.otel_export`
  - зависит от: `Services.otel_export` (hard 6); `multiprocess_framework.modules.channel_routing_module` (hard 2); `multiprocess_framework.modules.logger_module` (hard 1); `multiprocess_framework.modules.message_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.io.robot_draw`
  - зависит от: `Plugins.hub.device_hub` (hard 1); `Services.robot_comm` (lazy 3); `multiprocess_framework.modules.error_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.io.robot_io`
  - зависит от: `Plugins.hub.device_hub` (hard 1); `multiprocess_framework.modules.error_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.io.telemetry_sink`
  - зависит от: `Services.sql` (hard 1); `multiprocess_framework.modules.data_schema_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 7); `multiprocess_framework.modules.state_store_module` (tc 1)
- `Plugins.processing.blob_detector`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 9)
- `Plugins.processing.blob_filter`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.blur`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 5)
- `Plugins.processing.center_crop`
  - зависит от: `Services.layer_render` (hard 1); `multiprocess_framework.modules.process_module` (hard 7)
- `Plugins.processing.circle_detector`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 9)
- `Plugins.processing.color_convert`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.color_mask`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 9)
- `Plugins.processing.contour_draw`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.contour_finder`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.crop`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.edge_detection`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.flip`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 5)
- `Plugins.processing.grayscale`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 5)
- `Plugins.processing.hsv_mask`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.image_adjust`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.mask_to_frame`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.morphology`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.negative`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 5)
- `Plugins.processing.pixel_to_robot`
  - зависит от: `Plugins.calibration.camera_robot` (lazy 2); `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.points_render`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.region_split`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 6)
- `Plugins.processing.resize`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 9)
- `Plugins.processing.robot_scale`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.roi_crop`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.segmentation`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.stitcher`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 6)
- `Plugins.processing.strokes_to_points`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.text_vector`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.processing.word_layout`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.render.circle_draw`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.render.overlay_draw`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 7)
- `Plugins.render.render_overlay`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 9)
- `Plugins.render.renderer_compositor`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 9)
- `Plugins.runtime.chain_executor`
  - зависит от: `multiprocess_framework.modules.logger_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 10)
- `Plugins.runtime.worker_pool`
  - зависит от: `multiprocess_framework.modules.logger_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 10)
- `Plugins.sim.layer_preview`
  - зависит от: `Services.line_sim` (hard 4); `multiprocess_framework.modules.process_module` (hard 1); `multiprocess_framework.modules.recipe` (hard 1)
- `Plugins.sim.mjpeg_sink`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 4)
- `Plugins.sim.pult_web`
  - зависит от: `Plugins.hub.device_hub` (hard 1); `multiprocess_framework.modules.process_module` (hard 1)
- `Plugins.sim.robot_host`
  - зависит от: `Plugins.hub.device_hub` (hard 1); `Services.modbus` (lazy 1); `Services.robot_comm` (hard 3, lazy 2); `multiprocess_framework.modules.process_module` (hard 1)
- `Plugins.sim.scene_source`
  - зависит от: `Services.dataset_gen` (hard 1); `Services.layer_render` (hard 1); `Services.line_sim` (hard 3); `multiprocess_framework.modules.process_module` (hard 1); `multiprocess_framework.modules.recipe` (hard 2); `multiprocess_framework.modules.state_store_module` (hard 1, tc 1)
- `Plugins.sinks.modbus_sink`
  - зависит от: `Services.modbus` (hard 2); `multiprocess_framework.modules.process_module` (hard 3)
- `Plugins.sources.camera_service`
  - зависит от: `Plugins.hub.device_hub` (lazy 1); `Services.hikvision_camera` (hard 4); `multiprocess_framework.modules.process_module` (hard 10)
  - используют: `multiprocess_prototype.frontend` (hard 1, lazy 1)
- `Plugins.sources.capture`
  - зависит от: `multiprocess_framework.modules.error_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 4)
- `Plugins.sources.frame_counter`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 6)
- `Plugins.sources.heartbeat`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 6)
- `Plugins.sources.synthetic_frame_source`
  - зависит от: `multiprocess_framework.modules.process_module` (hard 1)
- `Plugins.utility.pilot_widgets`
  - зависит от: `multiprocess_framework.modules.data_schema_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 1)

### Слой `multiprocess_prototype`

- `multiprocess_prototype.__root__`
  - зависит от: `multiprocess_framework.modules.app_module` (hard 1, lazy 4); `multiprocess_framework.modules.process_manager_module` (tc 1); `multiprocess_framework.modules.process_module` (hard 1); `multiprocess_framework.modules.recipe` (lazy 1); `multiprocess_framework.modules.service_module` (lazy 1); `multiprocess_prototype.backend` (hard 1, lazy 6, tc 1)
  - используют: `backend_ctl.__root__` (lazy 4); `multiprocess_prototype.frontend` (hard 5, lazy 6)
- `multiprocess_prototype.adapters`
  - зависит от: `multiprocess_framework.modules.actions_module` (hard 1); `multiprocess_framework.modules.display_module` (hard 2); `multiprocess_framework.modules.logger_module` (hard 5); `multiprocess_framework.modules.process_module` (hard 1); `multiprocess_framework.modules.recipe` (hard 4); `multiprocess_framework.modules.registers_module` (tc 1); `multiprocess_framework.modules.service_module` (hard 4); `multiprocess_prototype.domain` (hard 31, tc 4); `multiprocess_prototype.recipes` (tc 1)
  - используют: `multiprocess_prototype.frontend` (hard 1, lazy 1, tc 3); `multiprocess_prototype.recipes` (lazy 1)
- `multiprocess_prototype.backend`
  - зависит от: `multiprocess_framework.modules.app_module` (lazy 4, tc 1); `multiprocess_framework.modules.base_manager` (hard 1); `multiprocess_framework.modules.data_schema_module` (hard 3, lazy 2); `multiprocess_framework.modules.display_module` (hard 2, lazy 1, tc 1); `multiprocess_framework.modules.logger_module` (hard 4); `multiprocess_framework.modules.process_manager_module` (hard 2, lazy 1, tc 1); `multiprocess_framework.modules.process_module` (hard 3, lazy 2); `multiprocess_framework.modules.recipe` (hard 4); `multiprocess_framework.modules.router_module` (tc 1); `multiprocess_framework.modules.service_module` (hard 1); `multiprocess_framework.modules.state_store_module` (hard 10); `multiprocess_prototype.recipes` (hard 3, lazy 2)
  - используют: `backend_ctl.__root__` (lazy 5); `multiprocess_prototype.__root__` (hard 1, lazy 6, tc 1); `multiprocess_prototype.frontend` (hard 2, lazy 10, tc 1)
- `multiprocess_prototype.domain`
  - зависит от: `multiprocess_framework.modules.data_schema_module` (hard 8, lazy 1); `multiprocess_framework.modules.event_module` (hard 2); `multiprocess_framework.modules.logger_module` (hard 1, lazy 1); `multiprocess_framework.modules.service_module` (hard 1)
  - используют: `multiprocess_prototype.adapters` (hard 31, tc 4); `multiprocess_prototype.frontend` (hard 31, lazy 8, tc 23)
- `multiprocess_prototype.frontend`
  - зависит от: `Plugins.sources.camera_service` (hard 1, lazy 1); `Services.auth` (hard 6, lazy 1, tc 9); `Services.control_panel` (lazy 1); `Services.dataset_gen` (lazy 5); `Services.ml_inference` (hard 1, lazy 1); `Services.ml_train` (lazy 2); `Services.phone_gateway` (hard 2); `multiprocess_framework.modules.actions_module` (hard 10, tc 3); `multiprocess_framework.modules.app_module` (lazy 1); `multiprocess_framework.modules.channel_routing_module` (hard 1, lazy 1); `multiprocess_framework.modules.config_module` (lazy 2); `multiprocess_framework.modules.data_schema_module` (tc 1); `multiprocess_framework.modules.display_module` (hard 1, lazy 2, tc 1); `multiprocess_framework.modules.frontend_module` (hard 80, lazy 18, tc 10); `multiprocess_framework.modules.logger_module` (hard 51, lazy 1); `multiprocess_framework.modules.message_module` (lazy 1); `multiprocess_framework.modules.process_manager_module` (hard 1); `multiprocess_framework.modules.process_module` (hard 7, lazy 4); `multiprocess_framework.modules.recipe` (hard 4, lazy 4); `multiprocess_framework.modules.registers_module` (hard 10, lazy 1, tc 9); `multiprocess_framework.modules.router_module` (hard 1, tc 2); `multiprocess_framework.modules.service_module` (hard 2, lazy 2, tc 1); `multiprocess_framework.modules.state_store_module` (hard 2, lazy 2); `multiprocess_framework.modules.worker_module` (hard 2); `multiprocess_prototype.__root__` (hard 5, lazy 6); `multiprocess_prototype.adapters` (hard 1, lazy 1, tc 3); `multiprocess_prototype.backend` (hard 2, lazy 10, tc 1); `multiprocess_prototype.domain` (hard 31, lazy 8, tc 23); `multiprocess_prototype.recipes` (lazy 7); `multiprocess_prototype.registers` (hard 3, lazy 3)
  - используют: `backend_ctl.__root__` (lazy 2)
- `multiprocess_prototype.recipes`
  - зависит от: `multiprocess_framework.modules.logger_module` (hard 4); `multiprocess_framework.modules.process_manager_module` (lazy 1); `multiprocess_framework.modules.recipe` (hard 7); `multiprocess_prototype.adapters` (lazy 1)
  - используют: `multiprocess_prototype.adapters` (tc 1); `multiprocess_prototype.backend` (hard 3, lazy 2); `multiprocess_prototype.frontend` (lazy 7)
- `multiprocess_prototype.registers`
  - зависит от: `multiprocess_framework.modules.data_schema_module` (hard 1); `multiprocess_framework.modules.registers_module` (hard 1)
  - используют: `multiprocess_prototype.frontend` (hard 3, lazy 3)

### Слой `backend_ctl`

- `backend_ctl.__root__`
  - зависит от: `Services.documents` (lazy 1); `multiprocess_framework.modules.app_module` (lazy 1); `multiprocess_framework.modules.base_manager` (lazy 1); `multiprocess_framework.modules.channel_routing_module` (hard 2); `multiprocess_framework.modules.error_module` (lazy 1); `multiprocess_framework.modules.logger_module` (lazy 1); `multiprocess_framework.modules.message_module` (hard 1); `multiprocess_framework.modules.process_manager_module` (hard 1, tc 1); `multiprocess_framework.modules.process_module` (hard 3, lazy 5); `multiprocess_framework.modules.router_module` (hard 1); `multiprocess_framework.modules.telemetry_readmodel_module` (hard 1, lazy 1); `multiprocess_prototype.__root__` (lazy 4); `multiprocess_prototype.backend` (lazy 5); `multiprocess_prototype.frontend` (lazy 2)

## Юниты без объявленных полей — 111 из 111

- `multiprocess_framework.modules.actions_module`: contour
- `multiprocess_framework.modules.app_module`: contour
- `multiprocess_framework.modules.base_manager`: contour
- `multiprocess_framework.modules.chain_module`: contour
- `multiprocess_framework.modules.channel_routing_module`: contour
- `multiprocess_framework.modules.command_module`: contour
- `multiprocess_framework.modules.config_module`: contour
- `multiprocess_framework.modules.console_module`: contour
- `multiprocess_framework.modules.data_schema_module`: contour
- `multiprocess_framework.modules.dispatch_module`: contour
- `multiprocess_framework.modules.display_module`: contour
- `multiprocess_framework.modules.error_module`: contour
- `multiprocess_framework.modules.event_module`: contour
- `multiprocess_framework.modules.frontend_module`: contour
- `multiprocess_framework.modules.logger_module`: contour
- `multiprocess_framework.modules.message_module`: contour
- `multiprocess_framework.modules.process_manager_module`: contour
- `multiprocess_framework.modules.process_module`: contour
- `multiprocess_framework.modules.recipe`: contour
- `multiprocess_framework.modules.registers_module`: contour
- `multiprocess_framework.modules.router_module`: contour
- `multiprocess_framework.modules.service_module`: contour
- `multiprocess_framework.modules.shared_resources_module`: contour
- `multiprocess_framework.modules.state_store_module`: contour
- `multiprocess_framework.modules.statistics_module`: contour
- `multiprocess_framework.modules.telemetry_readmodel_module`: contour
- `multiprocess_framework.modules.worker_module`: contour
- `Services.auth`: tier, contour
- `Services.camera_device`: tier, contour
- `Services.code_reader`: tier, contour
- `Services.control_panel`: tier, contour
- `Services.dataset_gen`: tier, contour
- `Services.device_hub`: tier, contour
- `Services.documents`: tier, contour
- `Services.hikvision_camera`: tier, contour
- `Services.layer_render`: tier, contour
- `Services.line_sim`: tier, contour
- `Services.ml_inference`: tier, contour
- `Services.ml_train`: tier, contour
- `Services.modbus`: tier, contour
- `Services.otel_export`: tier, contour
- `Services.phone_gateway`: tier, contour
- `Services.robot_comm`: tier, contour
- `Services.sql`: tier, contour
- `Services.vfd_comm`: tier, contour
- `Plugins._shared.fanin`: tier, contour
- `Plugins.calibration.camera_robot`: tier, contour
- `Plugins.control.robot_control`: tier, contour
- `Plugins.filter.line_filter`: tier, contour
- `Plugins.hub.device_hub`: tier, contour
- `Plugins.io.database`: tier, contour
- `Plugins.io.drawing_io`: tier, contour
- `Plugins.io.frame_saver`: tier, contour
- `Plugins.io.otel_export`: tier, contour
- `Plugins.io.robot_draw`: tier, contour
- `Plugins.io.robot_io`: tier, contour
- `Plugins.io.telemetry_sink`: tier, contour
- `Plugins.processing.blob_detector`: tier, contour
- `Plugins.processing.blob_filter`: tier, contour
- `Plugins.processing.blur`: tier, contour
- `Plugins.processing.center_crop`: tier, contour
- `Plugins.processing.circle_detector`: tier, contour
- `Plugins.processing.color_convert`: tier, contour
- `Plugins.processing.color_mask`: tier, contour
- `Plugins.processing.contour_draw`: tier, contour
- `Plugins.processing.contour_finder`: tier, contour
- `Plugins.processing.crop`: tier, contour
- `Plugins.processing.edge_detection`: tier, contour
- `Plugins.processing.flip`: tier, contour
- `Plugins.processing.grayscale`: tier, contour
- `Plugins.processing.hsv_mask`: tier, contour
- `Plugins.processing.image_adjust`: tier, contour
- `Plugins.processing.mask_to_frame`: tier, contour
- `Plugins.processing.morphology`: tier, contour
- `Plugins.processing.negative`: tier, contour
- `Plugins.processing.pixel_to_robot`: tier, contour
- `Plugins.processing.points_render`: tier, contour
- `Plugins.processing.region_split`: tier, contour
- `Plugins.processing.resize`: tier, contour
- `Plugins.processing.robot_scale`: tier, contour
- `Plugins.processing.roi_crop`: tier, contour
- `Plugins.processing.segmentation`: tier, contour
- `Plugins.processing.stitcher`: tier, contour
- `Plugins.processing.strokes_to_points`: tier, contour
- `Plugins.processing.text_vector`: tier, contour
- `Plugins.processing.word_layout`: tier, contour
- `Plugins.render.circle_draw`: tier, contour
- `Plugins.render.overlay_draw`: tier, contour
- `Plugins.render.render_overlay`: tier, contour
- `Plugins.render.renderer_compositor`: tier, contour
- `Plugins.runtime.chain_executor`: tier, contour
- `Plugins.runtime.worker_pool`: tier, contour
- `Plugins.sim.layer_preview`: tier, contour
- `Plugins.sim.mjpeg_sink`: tier, contour
- `Plugins.sim.pult_web`: tier, contour
- `Plugins.sim.robot_host`: tier, contour
- `Plugins.sim.scene_source`: tier, contour
- `Plugins.sinks.modbus_sink`: tier, contour
- `Plugins.sources.camera_service`: tier, contour
- `Plugins.sources.capture`: tier, contour
- `Plugins.sources.frame_counter`: tier, contour
- `Plugins.sources.heartbeat`: tier, contour
- `Plugins.sources.synthetic_frame_source`: tier, contour
- `Plugins.utility.pilot_widgets`: tier, contour
- `multiprocess_prototype.adapters`: tier, contour
- `multiprocess_prototype.backend`: tier, contour
- `multiprocess_prototype.domain`: tier, contour
- `multiprocess_prototype.frontend`: tier, contour
- `multiprocess_prototype.recipes`: tier, contour
- `multiprocess_prototype.registers`: tier, contour
- `backend_ctl.__root__`: tier, contour

## Внешний инструмент `backend_ctl`

Импортирует слои: `multiprocess_framework` (hard 9, lazy 10, tc 1); `Services` (lazy 1); `multiprocess_prototype` (lazy 11)
Его импортируют: никто
