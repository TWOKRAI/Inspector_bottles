# DECISIONS.md — Журнал архитектурных решений

Этот файл фиксирует все принятые архитектурные решения, чтобы новые
нейронки/разработчики не открывали уже закрытые вопросы.

Формат записи:
```
## ADR-NNN: Заголовок
- Дата: YYYY-MM-DD
- Статус: принято | отклонено | устарело
- Контекст: почему вопрос возник
- Решение: что решили
- Причина: почему именно так
- Отклонённые альтернативы: что рассматривали и отвергли
```

---

## ADR-001: ObservableMixin остаётся
- Дата: 2026-03-11
- Статус: принято
- Контекст: Рассматривалось удаление ObservableMixin как избыточного усложнения.
- Решение: ObservableMixin остаётся как часть BaseManager.
- Причина: Связывает logger, stats, error менеджеры через прокси-методы. Удаление потребует ручного прокидывания зависимостей во всех менеджерах.
- Отклонённые альтернативы: Прямое внедрение зависимостей через конструктор — отклонено из-за слишком большого количества изменений.

---

## ADR-002: registers_module остаётся (runtime != schema)
- Дата: 2026-03-11
- Статус: принято
- Контекст: Рассматривалось объединение registers_module с data_schema_module.
- Решение: registers_module остаётся отдельным модулем.
- Причина: data_schema_module — статические схемы (чертежи). registers_module — runtime-контейнер живых экземпляров схем + routing map. Разные ответственности.
- Отклонённые альтернативы: Объединение в один модуль — отклонено из-за нарушения SRP.

---

## ADR-003: data_schema_module — «живое ДНК»
- Дата: 2026-03-11
- Статус: принято
- Контекст: Вопрос о том, нужны ли схемы после запуска приложения или только для конфигурации.
- Решение: Схемы не выбрасываются после build(). Хранятся и обновляются в runtime.
- Причина: Позволяет запрашивать структуру данных любого процесса без дополнительной документации. Каждый процесс — хозяин своих данных.
- Отклонённые альтернативы: Только статическая конфигурация — отклонено как недостаточно гибко.

---

## ADR-004: Синхронизация ДНК через connection bundle
- Дата: 2026-03-11
- Статус: принято
- Контекст: Как обмениваться структурой данных между процессами.
- Решение:
  - Каталог (phone book): статическая структура {process_name: {fields, types, routing}} — формируется ProcessManager при старте, передаётся через connection bundle.
  - Живые данные: текущие значения хранятся только локально в процессе-хозяине.
  - Запрос данных: через Router → CommandManager → handler `get_field` → ответ.
- Причина: Избегает гонок данных. Каждый процесс владеет своими данными.
- Отклонённые альтернативы: Shared memory — отклонено из-за сложности синхронизации.

---

## ADR-005: Request-response через correlation_id
- Дата: 2026-03-11
- Статус: принято
- Контекст: Как реализовать синхронный запрос-ответ между процессами.
- Решение:
  - При отправке: генерируется message_id (UUID), добавляется reply_to.
  - При ответе: correlation_id = message_id из запроса.
  - В Router: метод `request(message, timeout)` — отправляет и ждёт ответ с matching correlation_id.
- Причина: Простой и понятный механизм. Не требует дополнительной инфраструктуры.
- Отклонённые альтернативы: Async callback — отклонено как избыточно сложный на этом этапе.

---

## ADR-006: Базы данных как отдельный ProcessModule
- Дата: 2026-03-11
- Статус: принято
- Контекст: Где реализовать работу с БД.
- Решение: DatabaseProcess — обычный ProcessModule, не часть фреймворка. Добавится позже.
- Причина: Фреймворк должен оставаться независимым от конкретных технологий хранения данных.
- Отклонённые альтернативы: Встроить в shared_resources_module — отклонено как нарушение SRP.

---

## ADR-007: ProcessPriority — Windows-only stub
- Дата: 2026-03-11
- Статус: принято
- Контекст: Управление приоритетами процессов на разных ОС.
- Решение: StubPlatformAdapter достаточен. Windows-only реализация через psutil/win32.
- Причина: Не критично для работоспособности системы на первом этапе.
- Отклонённые альтернативы: Кросс-платформенная реализация — отклонено как избыточно.

---

## ADR-008: Dict at Boundary (передача данных через границы процессов)
- Дата: 2026-03-11
- Статус: принято
- Контекст: Как передавать данные между процессами — через Pydantic модели или словари.
- Решение: На границах процессов используются dict. Внутри процесса — Pydantic модели допустимы.
- Причина: Pydantic модели не всегда сериализуются для multiprocessing.Queue. Dict гарантированно pickle-able.
- Отклонённые альтернативы: Pydantic модели везде — отклонено из-за проблем с сериализацией.

---

## ADR-009: gui_module пропускается
- Дата: 2026-03-11
- Статус: принято
- Контекст: Нужен ли GUI в рамках текущего рефакторинга.
- Решение: gui_module пропускается, не включается в план рефакторинга.
- Причина: Не критично для базовой функциональности фреймворка.

---

## ADR-010: console_module — менеджер терминальных окон
- Дата: 2026-03-14 (обновлено)
- Статус: реализовано
- Контекст: ConsoleManager управляет терминальным I/O процесса.
- Решение: Полноценный модуль с IPlatformConsole, ConsoleLogChannel, ConsoleAdapter.
  Три уровня: пассивный, активный, God Mode. Кроссплатформенность через WindowsConsole/UnixConsole.
- Причина: Нужен для отладки, мониторинга и интерактивного управления.

---

## ADR-011: Подход сверху вниз (top-down)
- Дата: 2026-03-11
- Статус: принято
- Контекст: Предыдущие итерации шли снизу вверх и не приводили к рабочей системе.
- Решение: Берём тестовое приложение multiprocess_prototype, запускаем его и чиним модули по мере столкновения с проблемами.
- Причина: Гарантирует рабочий результат на каждом этапе. Позволяет приоритизировать только нужное.
- Отклонённые альтернативы: Bottom-up (сначала все модули, потом интеграция) — отклонено как неэффективно.

---

## ADR-012: Unit-тесты достаточны (без integration на первом этапе)
- Дата: 2026-03-11
- Статус: принято
- Контекст: Какой уровень тестирования нужен.
- Решение: Unit-тесты для каждого модуля. Integration тесты — на этапе 7 при необходимости.
- Причина: multiprocess_prototype сам является интеграционным тестом.

---

## ADR-013: channel_routing_module — базовый класс для всех менеджеров с каналами
- Дата: 2026-03-12
- Статус: принято
- Контекст: RouterManager, LoggerManager, ErrorManager независимо реализовывали один паттерн
  (реестр каналов, диспетчер, буфер, lifecycle). Три раза один код = три источника ошибок.
- Решение: Создать `ChannelRoutingManager(BaseManager, ObservableMixin)` в новом `channel_routing_module`.
  В него переносится: `ChannelRegistry` (thread-safe), `Dispatcher` (key→handler), `IBufferStrategy`
  (pluggable), `normalize_config()` (Dict at Boundary), `ChannelRoutingConfig(RegisterBase)`.
- Причина: DRY. Исправление ошибки в registry / buffer теперь применяется ко всем менеджерам сразу.
  Новый менеджер = наследование CRM, а не копирование кода.
- Отклонённые альтернативы:
  - Миксин-классы (ChannelRegistryMixin, BufferMixin) — отклонено как источник MRO-конфликтов.
  - Вынести логику в отдельный helper-класс без наследования — отклонено: manager.registry.register()
    читается хуже, чем manager.register_channel().

---

## ADR-014: IChannel — единый базовый интерфейс каналов
- Дата: 2026-03-12
- Статус: принято
- Контекст: `IMessageChannel` и `ILogChannel` — несовместимые иерархии. `ChannelRegistry` в CRM
  требует единый тип.
- Решение: `IChannel` определён в `channel_routing_module.interfaces`. `ILogChannel(IChannel)` —
  добавлены `name`, `channel_type` как properties. `IMessageChannel(IChannel)` — добавлен `write()`
  как alias для `send()`.
- Причина: Единый `ChannelRegistry[IChannel]` хранит каналы всех типов. `isinstance(ch, IChannel)`
  как гарантия совместимости. Нет дублирования контракта `close()` / `get_info()`.
- Отклонённые альтернативы:
  - Три независимых реестра под каждый тип — отклонено как усиление фрагментации.
  - Protocol (structural typing) вместо ABC — отклонено: теряется явная ошибка при неполной реализации.

---

## ADR-015: AsyncSender остаётся в RouterManager (не заменяется AsyncSenderBuffer)
- Дата: 2026-03-12
- Статус: принято
- Контекст: CRM предоставляет `AsyncSenderBuffer(send_fn)` как pluggable буфер. Казалось логичным
  заменить `AsyncSender` в RouterManager на него.
- Решение: `AsyncSender` остаётся внутри `RouterManager` как специализированный компонент.
  `RouterManager(ChannelRoutingManager)` передаёт `buffer_strategy=None`.
- Причина: `AsyncSenderBuffer.enqueue(channel_name, data)` работает с уже resolved каналом.
  `AsyncSender` буферизует ВЕСЬ pipeline: `enqueue(msg) → apply_middleware(msg) → resolve_channels(msg)
  → write_to_channel`. Middleware-трансформации должны происходить ДО резолюции канала.
  Заменить AsyncSender на AsyncSenderBuffer = потеря middleware pipeline.
- Отклонённые альтернативы:
  - Обогатить `IBufferStrategy` поддержкой middleware — отклонено как нарушение SRP буфера.
  - Переместить middleware в channel.write() — отклонено: middleware в RouterManager привязано
    к маршруту, а не к каналу.

---

## ADR-016: ChannelRoutingConfig(RegisterBase) — базовый конфиг через наследование
- Дата: 2026-03-12
- Статус: принято
- Контекст: Конфиги менеджеров существовали в трёх форматах: dataclass (LogConfig), RegisterBase
  (ErrorManagerConfig), отсутствует (RouterManager). Нужна унификация без потери гибкости.
- Решение: `ChannelRoutingConfig(RegisterBase)` содержит общие поля `manager_name`, `channels`.
  `build()` → `(name, dict)`. `ErrorManagerConfig(ChannelRoutingConfig)` наследует и расширяет.
  `normalize_config()` принимает `None | dict | RegisterBase` и всегда возвращает `dict`.
- Причина: RegisterBase — уже принятый стандарт в framework (ADR-003). `build()` совместим с
  `normalize_config()`. Наследование позволяет добавлять специфичные поля (severity paths, batch_size)
  без потери общего API. Все конфиги попадают в `data_schema_module` через `@register_schema`.
- Отклонённые альтернативы:
  - Pydantic BaseModel напрямую (без RegisterBase) — отклонено: теряется интеграция с registers_module.
  - Единый монолитный конфиг со всеми полями всех менеджеров — отклонено как нарушение OCP.

---

## ADR-017: ConfigStore отдельно от ProcessData
- Дата: 2026-03-13
- Статус: принято
- Контекст: Конфиги процессов хранились в `ProcessData.custom["process_config"]`, смешиваясь с
  runtime-данными (статус, очереди, события). Это нарушало SRP и усложняло сериализацию.
- Решение: `ConfigStore` — отдельный pickle-safe компонент SRM. `ProcessData.custom` — только
  пользовательские runtime-данные. Конфиги статичны, ProcessData динамична.
- Причина: Разные жизненные циклы. Конфиг создаётся один раз при `register_process()`.
  ProcessData меняется в течение всего времени жизни процесса.
- Отклонённые альтернативы:
  - Конфиги в отдельном поле ProcessData — отклонено: ProcessData уже перегружен.

---

## ADR-018: SRM.register_process() — единая точка регистрации
- Дата: 2026-03-13
- Статус: принято
- Контекст: ProcessManager вручную вызывал 5+ методов для регистрации процесса:
  `register_process_state()`, `queue_registry.create_and_register_queues()`, `add_event()` и т.д.
  Любое изменение формата требовало правок в ProcessManager.
- Решение: `SRM.register_process(name, config_dict)` — один вызов. SRM сам создаёт Queue, Event,
  сохраняет конфиг, инициализирует SharedMemory.
- Причина: Инкапсуляция. ProcessManager не должен знать КАК создаются ресурсы.
  Изменение внутренней структуры не ломает вызывающий код.
- Отклонённые альтернативы:
  - Builder pattern — отклонено как избыточный для текущего масштаба.

---

## ADR-019: SharedMemory по именам (pickle-safe)
- Дата: 2026-03-13
- Статус: принято
- Контекст: `SharedMemory` объекты не pickle-able. Предыдущий код хранил их в `ProcessData.custom`,
  что делало pickle SRM невозможным.
- Решение: Хранить только `shm.name` строки в `ProcessData.custom["memory_names"]`.
  SharedMemory объекты живут в `MemoryManager._local_handles` (не pickle-able, пересоздаются).
  Owner process: `create=True`, `unlink()` при shutdown.
  Consumer process: `create=False`, `close()` при shutdown.
- Причина: Строки pickle-safe. OS-level shared memory доступна по имени из любого процесса.
- Отклонённые альтернативы:
  - `multiprocessing.Manager().dict()` — отклонено: требует Manager process, overhead.

---

## ADR-020: reinitialize_in_child() для восстановления после unpickle
- Дата: 2026-03-13
- Статус: принято
- Контекст: После unpickle SRM в дочернем процессе `EventManager._event_queue = None`,
  `MemoryManager._local_handles = {}`. Без восстановления они нефункциональны.
- Решение: Явный метод `SRM.reinitialize_in_child()`. Вызывается в `ProcessModule.initialize()`.
  НЕ автоматически в `__setstate__` — явное лучше неявного.
- Причина: Явный вызов даёт контроль над порядком инициализации. `__setstate__` вызывается
  в неопределённом контексте (может быть до инициализации других компонентов).
- Отклонённые альтернативы:
  - Автовосстановление в `__setstate__` — отклонено: скрытая логика, трудно дебажить.

---

## ADR-021: Прямой pickle SRM вместо ad-hoc bundle dict
- Дата: 2026-03-13
- Статус: принято
- Контекст: `run_process_function` получал `bundle = {"queues": {}, "config": ..., "custom": {...}}`
  и вручную пересоздавал SRM с нуля, копируя данные из bundle (~190 строк кода).
  Routing map строилась ad-hoc. Хрупко, дублирует логику.
- Решение: SRM pickle-ируется напрямую. Все Queue/Event ссылки сохраняются через OS pipe fd.
  `run_process_function` получает готовый SRM, вызывает `reinitialize_in_child()` (~30 строк).
- Причина: `multiprocessing.Queue` и `Event` нативно pickle-safe. Прямая передача SRM
  исключает дублирование логики создания ресурсов и делает код масштабируемым.
- Отклонённые альтернативы:
  - Сохранить bundle подход с улучшенной валидацией — отклонено: фундаментально хрупкий паттерн.

---

## ADR-023: config_module — тонкая обёртка над data_schema_module
- Дата: 2026-03-15
- Статус: принято
- Контекст: config_module на этапе 0/8, дублировал функционал data_schema_module
  (собственная валидация, _deep_update, мёртвая зависимость на StorageManager).
  Вопрос: нужен ли отдельный модуль или достаточно data_schema_module + ConfigStore?
- Решение: config_module остаётся. Переписан как тонкая обёртка:
  - `data_schema_module` = ЧТО (схемы, валидация, merge_with_defaults)
  - `config_module` = КАК (runtime доступ, dot-notation, подписки, секции, env-fallback)
  - `ConfigStore` (SRM) = ГДЕ (pickle-safe cross-process хранение)
  - StorageManager и EventManager удалены из ConfigManager — не нужны
  - `ConfigManagerConfig(SchemaBase)` через `@register_schema("config_manager")`
  - Импорты между модулями: абсолютные (pythonpath = refactored/modules)
- Причина: Runtime config management (подписки, секции, env fallback, dot-notation)
  — отдельная ответственность, которую не покрывает ни data_schema_module, ни ConfigStore.
- Отклонённые альтернативы:
  - Удаление config_module — отклонено: потеря runtime-API (уже интегрирован в spawner.py,
    process_module.py, process_registry.py).
  - Объединение с data_schema_module — отклонено: нарушает SRP.

---

## ADR-022: StatsManager — прямой наследник ChannelRoutingManager (не LoggerManager)
- Дата: 2026-03-15
- Статус: принято
- Контекст: Нужен менеджер статистики и метрик по аналогии с logger_module и error_module.
  Рассматривалось наследование от LoggerManager (как ErrorManager).
- Решение: `StatsManager(ChannelRoutingManager, IStatsManager)` — прямой наследник CRM.
  Буфер: `AggregationWindow(IBufferStrategy)` с агрегацией (counter, gauge, timing, histogram).
  Каналы: `LogStatsChannel` → LoggerManager.performance(), `FileStatsChannel` → JSON/CSV.
  Конфиг: `StatsManagerConfig(ChannelRoutingConfig)` через `@register_schema`.
- Причина: LoggerManager добавляет scope/level — не нужны для метрик. StatsManager имеет свою
  специфику: агрегация, flush-таймер, типы метрик. CRM даёт каналы и буфер без лишнего.
- Отклонённые альтернативы:
  - StatsManager(LoggerManager) — отклонено: scope/level избыточны для метрик.

---

## ADR-024: channel_types в receive() — разделение system и data очередей
- Дата: 2026-03-15
- Статус: принято
- Контекст: message_processor (system thread) и worker-потоки оба вызывали router.receive().
  DATA/EVENT сообщения потреблялись system thread и терялись — GUI не получал кадры.
- Решение:
  - `RouterManager.receive(channel_types=['system']|['data']|None)` — фильтр по типу канала
  - System thread опрашивает только `channel_types=['system']`
  - Worker-потоки (Processor, Renderer, GUI) — `channel_types=['data']`
  - Robot (только команды) — `channel_types=['system']`, без system thread
- Причина: Разделение ответственности: system — команды и управление, data — поток кадров и событий.
- Отклонённые альтернативы:
  - Отдельные очереди без фильтра — уже есть, но receive() читал из всех.

---

## ADR-025: multiprocess_prototype — ProcessConfigBase, config-driven memory, logging
- Дата: 2026-03-15
- Статус: принято
- Контекст: Рефакторинг тестового приложения Inspector Prototype после этапов 0–6.
- Решение:
  - **ProcessConfigBase** — базовый класс конфигов с `_build_proc_dict(class_path, queues, priority, memory)`
  - **Config-driven SharedMemory** — Camera/Renderer создают память из `config["memory"]` в build()
  - **Logging** — console channel, INSPECTOR_LOG_LEVEL, push_context(proc_name) в ProcessLifecycle
  - **MessageAdapter** — все процессы используют MessageAdapter для DATA/COMMAND/EVENT
- Причина: Устранение дублирования, единая точка конфигурации, отладочные логи в консоли.

---

## ADR-026: SharedMemory pipeline — unlink при shutdown, stale cleanup, print fallback
- Дата: 2026-03-15
- Статус: принято
- Контекст: На macOS POSIX shm сегменты не удаляются при Ctrl+C/crash. Следующий запуск падал с
  FileExistsError при create=True. MemoryManager._log_error шёл в ObservableMixin без logger → silent NO-OP.
  write_images возвращал None, GUI показывал "Waiting for frames...".
- Решение:
  1. **ProcessLifecycle.shutdown()** — вызов `shared_resources.shutdown()` для unlink SharedMemory
  2. **MemoryManager._create_shm_blocks** — перед create=True попытка открыть+unlink устаревший сегмент
  3. **print() fallback** — в _create_shm_blocks, _validate_memory_access, write_images при критических ошибках
  4. **run.sh** — preamble очистки stale shm (camera_frame_0/1, rendered_frame_0/1)
  5. **CameraProcess** — auto_start=False, в _cmd_start явный start_worker если не запущен
- Причина: POSIX shm персистит до unlink/reboot. Без SRM.shutdown() MemoryManager.shutdown() не вызывался.
  print() гарантирует видимость ошибок при отсутствии logger.

---

## ADR-027: rendered_frame_ready — два изображения (original + mask)
- Дата: 2026-03-15
- Статус: принято
- Контекст: multiprocess_prototype расширен: два изображения (оригинал с контурами и маска),
  чекбоксы отправляют команды в Renderer.
- Решение:
  - `rendered_frame_ready` содержит два блока: `shm_actual_name`/`shm_index` для rendered_frame,
    `mask_shm_actual_name`/`mask_shm_index` для mask_frame
  - Дополнительно: `show_original`, `show_mask`, `draw_contours` — состояние отображения
  - Processor owner `processor_mask`, Renderer owner `rendered_frame` и `mask_frame`
- Причина: Явное разделение original/mask в одном сообщении. Dict at Boundary.
