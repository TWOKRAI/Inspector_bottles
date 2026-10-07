# Индекс проекта — собран командой `python -m scripts.atlas index --write`, руками не править
actions_module — Action-шина с undo/redo и объединением правок для GUI; сюда — менять откат и повтор действий
  IRegistersManagerGui (1), IActionLogRepository, IActionLogWriter
app_module — Шаблон приложения (composition root): общая сборка многопроцессного приложения; сюда — менять каркас запуска
  ManifestStoreProtocol (2), BlueprintLoader (0), LauncherFactory (0), ProcDictsBuilder (0), StateBootstrap (0), … ещё 1
base_manager — Базовый менеджер: жизненный цикл, адаптеры, наблюдаемость; сюда — менять фундамент всех менеджеров
  IObservableMixin (12), IScope (11), IBaseManager (9), CloseReport (3), IHandle (3), … ещё 5
chain_module — Движок исполнения цепочек и DAG-pipeline, в т.ч. между процессами; сюда — менять порядок и шаги исполнения
  IChainLogger (3), IExecutionStep (2), IChainRunnable (1), IRemoteExecutable (1), INodeConnection (0), … ещё 2
channel_routing_module — Базовая маршрутизация по каналам для роутера, логгера и ошибок; сюда — менять общую логику каналов
  IChannelRoutingManager (6), IBufferStrategy (5), IChannel (5), channel_accepted
command_module — Менеджер команд над dispatch_module: регистрация обработчиков по имени; сюда — менять приём команд
  ICommandManager (9)
config_module — Управление конфигурациями в рантайме: схемы, контейнер, менеджер; сюда — менять загрузку и хранение конфигов
  IConfig (9), IConfigManager (7), IConfigObserver (0)
console_module — Менеджер терминальных окон процесса: показ, перехват вывода, ввод; сюда — менять консоль процесса
  IConsoleManager (10), IPlatformConsole (8)
data_schema_module — Ядро описания структур данных на Pydantic: схемы, поля, маршрутизация; сюда — менять схемы и валидацию
  HasBuild, IAsyncRegisterStorage, IAsyncSchemaStorage, IDataConverter, IDataValidator, … ещё 12
dispatch_module — Диспетчеризация входящих сообщений к обработчикам внутри процесса; сюда — менять стратегии обработки
  IDispatcher (7), DispatchStrategy
display_module — Реестр именованных SHM-каналов для вывода кадров; сюда — менять каналы отображения кадров
  IDisplayRegistry (6), IDisplayChannel (4), DisplayEntry (0)
error_module — Менеджер ошибок на базе логгера: каналы по уровням, traceback; сюда — менять обработку и запись ошибок
  IErrorManager (8), DeviceOpenFailed, FrameworkFailure, ObservabilityMisuse, ResourceUnavailable, … ещё 1
event_module — Типизированная шина событий-фактов внутри процесса; сюда — менять подписки и публикацию событий
  EventBusProtocol (2), Subscription (1)
frontend_module — UI-фреймворк: конструктор PySide6-приложений из виджетов и регистров; сюда — менять GUI-каркас
  IFrontendManager (6), IConfigurableWidget (4), IRegistersManager (3), IRegistersManagerGui (3), IWidgetRegistry (3), … ещё 20
logger_module — Менеджер логирования: каналы записи, сбор логов процессов; сюда — менять вывод и хранение логов
  ILoggerManager (19), ILogChannel (2), LogLevel, LogScope, ScopeName
message_module — Транспортный протокол сообщений между менеджерами и процессами; сюда — менять формат сообщений
  IMessage (12)
process_manager_module — Оркестратор процессов: запуск системы, реестр, приоритеты, мониторинг; сюда — менять управление процессами
  ISystemLauncher (9), IProcessManagerProcess (7), IProcessRegistry (7)
process_module — Базовый класс процесса: создание, инициализация, управление, мониторинг; сюда — менять жизнь процесса
  IProcessModule (12), IProcessCommunication (11), ISharedResources (5), ProcessStatsDict
recipe — Управление рецептами: снимки конфигурации, определение формата, миграции, CRUD; сюда — менять рецепты
  RecipeManagerProtocol (11), RecipeEngineProtocol (10), StoreProtocol (3)
registers_module — Рантайм именованных регистров: подписки на поля, карта маршрутов, отправка; сюда — менять регистры
  IRegistersManager (15)
router_module — Маршрутизация сообщений между процессами через RouterManager; сюда — менять каналы и правила доставки
  IRouterManager (21), IMessageChannel (9)
service_module — Реестр и жизненный цикл долгоживущих сервисов (камеры, БД, auth); сюда — менять учёт сервисов
  IService (3), ServiceLifecycle (0)
shared_resources_module — Pickle-safe реестр общих ресурсов для межпроцессного обмена; сюда — менять передачу ресурсов процессам
  IConfigStore, IEventManager, IMemoryManager, IProcessStateRegistry, IQueueRegistry, … ещё 1
state_store_module — Реактивное иерархическое дерево состояния: сервер и клиентский кэш с подписками; сюда — менять общее состояние
  IStateProxy (7), IStateStore (6), IStateStoreManager (5), IRouter (3)
statistics_module — Менеджер статистики и метрик, третья плоскость наблюдаемости; сюда — менять сбор и вывод метрик
  IStatsManager (9)
telemetry_readmodel_module — Qt-free ядро read-model телеметрии: проекция значений и кольцевая история; сюда — менять чтение телеметрии
  ITelemetryReadModel (9)
worker_module — Менеджер потоков-воркеров внутри процесса: старт, стоп, пауза, перезапуск; сюда — менять управление потоками
  IWorkerManager (22), IWorkerRegistry (8), IWorkerLifecycle (4), WorkerStatus, WorkerType
framework_meta — Корневые файлы пакета фреймворка и его документация; сюда — менять версию, общие импорты, доки фреймворка
services/auth — Аутентификация и RBAC: хеши паролей, пользователи, роли; сюда — менять вход и права доступа
  IAuthManager (12), IUserStorage (5), IPasswordHasher (2), ISessionTracker (2), IAuditWriter (1)
services/code_reader — Сервис считывателя кодов Hikrobot ID3000: приём результатов по TCP, разбор; сюда — менять чтение кодов
  CodeReaderSinkProtocol (6), CodeQuality, CodeRead, ReadResult, ReadStatus, … ещё 5
services/control_panel — Сервис Пульт: GUI-контролы выдают значения на порты pipeline; сюда — менять контролы и их сигналы
  ControlSpec, ControlType
services/dataset_gen — Генератор синтетического датасета методом cut-and-paste; сюда — менять создание обучающих данных
  SampleGenerator (4)
services/device_hub — Центральный реестр устройств и менеджер соединений; сюда — менять учёт и подключение устройств
services/documents — Хранилище документов: аудит смен наблюдаемости и вердикты по детали; сюда — менять аудит и вердикты
  IDocumentStore (3), IDocumentSink (1), KIND_AUDIT, KIND_VERDICT
services/hikvision_camera — Сервис промышленной камеры Hikvision: SDK, логика, плагин; сюда — менять работу с камерой
  HikvisionCameraProtocol (6)
services/layer_render — Слои сцены: фон, объект, пресет, каталог классов; сюда — менять сборку кадра из слоёв
  ScrollingTile (0), SolidFill (0)
services/line_sim — Объект-агностичный движок сцены лента с объектами; сюда — менять симуляцию ленты
  SceneCompositorProtocol (3), ObjectPassport (2), AUGMENT_FIELDS, LayerAugment, LayerMode, … ещё 3
services/ml_inference — Инференс нейросетей для pipeline: кадр на входе, классы и confidence на выходе; сюда — менять инференс
  InferenceBackend (5), ModelCatalog (3)
services/ml_train — Обучение классификаторов и выбор лучшей модели по метрикам; сюда — менять обучение и сравнение прогонов
  RunSource (2), ModelExporter (0), TrainSample (0)
services/modbus — Драйвер Modbus-TCP и RS485 для связи с PLC; сюда — менять обмен по Modbus
  ModbusClientProtocol (9), RegisterTransport (3)
services/otel_export — Экспорт записей наблюдаемости наружу по OTLP; сюда — менять маппинг и отправку данных наблюдаемости
  ObservabilityPort (5), LogExporter (2), RecordMapper (1), ResourceResolver (1), ExportOutcome (0), … ещё 3
services/phone_gateway — Приём фото и слов с телефона по WiFi через браузер; сюда — менять приём данных с телефона
  FrameSource (2)
services/robot_comm — Сервис робота Delta поверх Modbus: карта регистров, доменные методы; сюда — менять управление роботом
  RobotClientProtocol (18), DeviceTransport (6)
services/sql — Универсальный SQL-менеджер на SQLAlchemy: PostgreSQL, MySQL, SQLite; сюда — менять доступ к БД
  ISQLManager (8), IRepository (7), IAsyncEngineAdapter (3), IEngineAdapter (3), ISchemaMapper (3), … ещё 3
services/vfd_comm — Сервис частотного преобразователя INVT GD20, не зависит от транспорта; сюда — менять управление ПЧ
  VfdClientProtocol (7)
services_shared — Корневой пакет Services и его STATUS; общий уровень сервисов
plugins/calibration — Плагины калибровки (камера и робот и др.); сюда — менять калибровочные плагины
plugins/control — Плагины управления внешними устройствами: роботы, IO, реле; сюда — менять управляющие плагины
plugins/filter — Плагины фильтрации и анализа координат (виртуальная линия и др.); сюда — менять фильтры координат
plugins/hub — Плагины категории hub в каталоге Plugins; описания в источниках нет
plugins/io — Плагины ввода-вывода: запись в БД, выгрузка кадров, экспорт; сюда — менять ввод-вывод
plugins/processing — Плагины обработки кадров: фильтры, детекторы, преобразования; сюда — менять обработку кадров
plugins/render — Плагины отрисовки overlay и композитинга кадров для GUI; сюда — менять отрисовку
plugins/runtime — Плагины-исполнители pipeline: chain executor, пулы воркеров; сюда — менять исполнение pipeline
plugins/sim — Плагины-хосты симулятора линии; сервис держит логику, плагин жизненный цикл; сюда — менять хост симуляции
plugins/sinks — Плагины-приёмники: вывод и экспорт данных из конца цепочки; сюда — менять приёмники данных
plugins/sources — Плагины источников данных: камеры, файлы, генераторы; сюда — менять источники
plugins/utility — Служебные и тестовые плагины (heartbeat, pilot_widgets и др.); сюда — менять служебные плагины
plugins_shared — Общие доменные утилиты нескольких плагинов, сами не плагины; сюда — менять общий код плагинов
prototype/adapters — Adapter-слой между domain Protocols и реестрами фреймворка; сюда — менять привязку domain к реестрам
prototype/backend — Backend прототипа: конфигурация системы и топология процессов и плагинов; сюда — менять wiring системы
prototype/domain — Изолированный типизированный domain-слой: frozen-сущности и исключения; сюда — менять доменные сущности
prototype/frontend — GUI-пакет прототипа: Qt-презентация PySide6 поверх бэкенда; сюда — менять экраны и GUI прототипа
prototype/recipes — Управление рецептами прототипа: RecipeManager и миграции форматов; сюда — менять рецепты прототипа
prototype/registers — Общие регистры прототипа между плагинами и RegistersManager; сюда — менять shared-регистры
prototype_root — Корень прототипа инспекции дефектов: запуск, оркестратор, app.yaml, документы; сюда — менять запуск прототипа
tools/backend_ctl — Headless-драйвер бэкенда по TCP, GUI по сокету, dev-инструмент; сюда — менять управление бэкендом
  IBackendClient (7), ISubscriptionRegistry (5), IEventSource (3)
prototype/apps — Каталог apps в корне репозитория; описания в источниках нет
tools/tools — Каталог tools в корне репозитория; описания в источниках нет
scripts — Каталог утилит проекта; сюда — менять служебные скрипты репозитория
tools/utils — Каталог Utils в корне репозитория; описания в источниках нет
prototype/robot — Каталог robot в корне репозитория; описания в источниках нет
docs/examples — Пример приложения minimal_app, рыба-шаблон; сюда — смотреть образец использования фреймворка
tools/backend_ctl/probes — Ручные live-пробники backend_ctl, не входят в обычный прогон тестов; сюда — менять пробники
frontend_module/components — Примитивы контролов: Traits, Presenter, View, Facade; сюда — менять базовые контролы GUI
frontend_module/components/_examples — Учебные схемы и адаптеры к контролам; сюда — смотреть пример адаптера, не боевой код
frontend_module/components/base — Базовый слой контролов: контракты, конфиг, мост к регистрам, traits; сюда — менять основу контролов
  IControlView (8), INumericView (4), IRegisterPort (4), IFieldBinding (0), IRegistersManagerGui, … ещё 1
frontend_module/core — Базовые классы frontend_module без Qt: маршрутизация команд, мост регистров; сюда — менять ядро GUI-фреймворка
frontend_module/widgets — Составные UI-компоненты: вкладки, таблицы, шапка, клавиатура; сюда — менять составные виджеты
frontend_module/widgets/chrome — Заголовок приложения, боковые панели и оверлеи; сюда — менять обрамление окна
frontend_module/widgets/tabs — Вкладки: TabWidget, BaseTab, MVP-база, привязка к регистрам; сюда — менять каркас вкладок
process_module/generic — GenericProcess: конфиг-драйвен процесс с загрузкой плагинов из конфига; сюда — менять универсальный процесс
prototype/frontend/widgets — Каталог widgets GUI прототипа; описания в источниках нет
prototype/frontend/widgets/tabs — Вкладки приложения: реестр фабрик вкладок из единого списка TABS; сюда — менять состав вкладок
prototype/frontend/widgets/tabs/pipeline — Вкладка pipeline GUI прототипа; описания в источниках нет
prototype/frontend/widgets/tabs/services — Вкладка services GUI прототипа; описания в источниках нет
prototype/frontend/widgets/tabs/settings — Пилотная вкладка Settings, сквозной пример таба; сюда — менять вкладку настроек
