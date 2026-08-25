"""
Управление менеджерами процесса.

Создание менеджеров и возврат ManagersBundle (ADR-PM-009: return-based composition).
Composition-объект ЧИТАЕТ из process, но НЕ ПИШЕТ в его атрибуты.
Lazy imports в методах создания менеджеров.
"""

from typing import Any, Dict

from ..types import ManagersBundle


class ProcessManagers:
    """
    Управление менеджерами процесса.

    Инкапсулирует логику создания менеджеров.
    Зависимости передаются через process (DI-контейнер).

    Контракт: создаёт менеджеры и возвращает ManagersBundle.
    ProcessModule сам присваивает атрибуты из bundle (ADR-PM-009).
    """

    def __init__(self, process):
        """
        Args:
            process: Ссылка на ProcessModule
        """
        self.process = process

    def create_all(self) -> ManagersBundle:
        """Создать все менеджеры процесса и вернуть bundle.

        Порядок создания менеджеров определён зависимостями:
        worker → logger → error → router(нужен logger) →
        stats(нужен logger) → observation(нужен logger) →
        command(нужен logger, stats) → console.

        Returns:
            ManagersBundle — контейнер созданных менеджеров.
        """
        managers_config = self._managers_config_for_creation()

        worker = self._create_worker_manager()
        logger = self._create_logger_manager(managers_config)
        error = self._create_error_manager(managers_config)
        router = self._create_router_manager(managers_config, logger=logger)
        stats = self._create_stats_manager(managers_config, logger=logger)
        observation = self._create_observation_manager(logger=logger)
        command = self._create_command_manager(
            managers_config,
            logger=logger,
            stats=stats,
        )
        console, console_enabled = self._create_console_manager(managers_config)

        return ManagersBundle(
            worker=worker,
            logger=logger,
            router=router,
            command=command,
            stats=stats,
            console=console,
            error=error,
            observation=observation,
            config_manager=self.process.config_manager,
            console_enabled=console_enabled,
        )

    def _managers_config_for_creation(self) -> Dict[str, Any]:
        """Секция менеджеров для СОЗДАНИЯ — из слоёв, если ассемблер её не собрал.

        Task 2.3 (находка Н-7). Секция приезжает готовой только тем процессам,
        которых собирал ассемблер; **оркестратор спавнится другим кодом, и ключа
        ``managers`` в его bundle нет вовсе** (``spawner.launch_orchestrator``).
        Из-за этого его менеджеры РОЖДАЛИСЬ на дефолтах L0, и первым, что делал
        ``StatsManager`` оркестратора на каждом старте, было предупреждение о
        собственном конфиге::

            [stats_ProcessManager] stats.aggregation_interval=5.0 ниже пола
            stats.flush_interval=10.0 — действует 10.0 с.

        При том что ``system.yaml`` задавал ``aggregation_interval: 10.0``. Дети
        того же стенда молчали — им конфиг доезжал. Предупреждение было ПРАВДОЙ
        про менеджер и ЛОЖЬЮ про систему: значения доносила пересборка на boot
        (``_apply_boot_observability_layers``) секундой позже.

        **Почему это не «просто шум».** Воспроизведено на расходящейся паре
        (``aggregation_interval: 10.0`` + ``flush_interval: 2.0``): при создании
        менеджер получал ``agg=5.0, flush=10.0``, и его readback показывал
        ``agg=10.0`` — совпадение, потому что действующий темп это
        ``max(flush, agg)``, а ``max(5,10) == max(10,10)``. Разошёлся СОСЕД:
        ``flush_interval`` — действующий ПОЛ темпа — был 10.0 против заданных
        2.0, то есть впятеро. Совпадение констант прятало, доезжает ли конфиг
        вообще; различает их только пара, где ветки расходятся.

        Признак **структурный** — «секция пуста», а не «имя равно
        ProcessManager»: тот же довод, по которому он выбран в
        :meth:`~..core.process_module.ProcessModule._apply_boot_observability_layers`.
        Починка по имени закрыла бы одного адресата и оставила бы дефект ждать
        следующего процесса, поднятого без готовой секции.

        **Молчащие слои ничего не дают** (:func:`layers_are_silent`): пустая
        секция при молчащих слоях остаётся пустой. ``expand_observability({})``
        — это не пустота, а полный набор дефолтов L0, и подстановка его здесь
        затёрла бы конфиг, собранный встройщиком программно.

        Что осталось за пересборкой на boot и почему её не сняли: она обслуживает
        ВТОРУЮ ветку — спутник рецепта, записанный ``observability.persist``
        (его на момент создания менеджеров ещё не читали). Эта функция закрывает
        только «родиться правильным»; «дочитать спутник» по-прежнему её работа.
        """
        declared = self.process.config_handler.get_managers_config()
        if declared:
            return declared

        from ..configs.observability_config import expand_observability
        from ..configs.observability_layers import layers_are_silent, process_observability_layers

        layers = process_observability_layers(self.process)
        if layers_are_silent(layers):
            return declared
        return expand_observability(layers.resolve())

    def register_all(self, bundle: ManagersBundle, process) -> None:
        """Зарегистрировать менеджеры из bundle через ObservableMixin.

        Args:
            bundle: ManagersBundle с созданными менеджерами.
            process: ProcessModule — хост (владелец атрибутов).
        """
        process.register_manager("worker", bundle.worker, enabled=True)
        process.register_manager("logger", bundle.logger, enabled=True)
        process.register_manager("stats", bundle.stats, enabled=True)
        # Ф3, задача 3.1: порт наблюдений — четвёртый канонический слот.
        #
        # Регистрация БЕЗУСЛОВНАЯ, как у logger/stats, а не условная, как у
        # error ниже. Развилка настоящая, и выбор такой: error бывает НЕ СОЗДАН
        # (его секции нет в конфиге — ``_create_error_manager`` возвращает
        # None), а порт наблюдений своей секции не имеет вовсе и создаётся
        # всегда. Условие ``if bundle.observation is not None`` сторожило бы
        # случай, которого сборка не производит, и в тот день, когда порт
        # перестал бы создаваться из-за дефекта, оно превратило бы отказ в
        # тихий фолбэк — ровно тот класс, который эта фаза и разбирает.
        #
        # ``None`` в слоте при этом безопасен: ``ManagerRegistry.register``
        # ставит ``_enabled = enabled and manager is not None``, а ``has()``
        # отвечает False на None-менеджер. Bundle, собранный вручную без этого
        # поля (тесты соседних модулей), остаётся рабочим.
        process.register_manager("observation", bundle.observation, enabled=True)
        process.register_manager("command", bundle.command, enabled=True)
        process.register_manager("router", bundle.router, enabled=True)
        process.register_manager("console", bundle.console, enabled=bundle.console_enabled)
        if bundle.error is not None:
            # Task 5.14: каноничное имя error-гнезда — "error" (совпадает с
            # ObservableMixin._track_error, которое пробует именно "error").
            process.register_manager("error", bundle.error, enabled=True)

    def attach_adapters(self, bundle: ManagersBundle, process) -> None:
        """Создать адаптеры и привязать их к менеджерам.

        У `logger` адаптера НЕТ (2.2): прежний `LoggerAdapter` не имел ни одного
        потребителя, зато нёс вторую таблицу «уровень → scope», расходившуюся с
        канонической по DEBUG. Именованная точка входа к логгеру — `get_std_logger`.

        Args:
            bundle: ManagersBundle с созданными менеджерами.
            process: ProcessModule — хост (передаётся в адаптеры).
        """
        from ...command_module import CommandAdapter
        from ...console_module.adapters.console_adapter import ConsoleAdapter
        from ...router_module import RouterAdapter
        from ...statistics_module import StatsAdapter
        from ...worker_module.adapters.worker_adapter import WorkerAdapter

        worker_adapter = WorkerAdapter(bundle.worker, process)
        stats_adapter = StatsAdapter(bundle.stats, process)
        command_adapter = CommandAdapter(bundle.command, process)
        router_adapter = RouterAdapter(bundle.router, process)
        console_adapter = ConsoleAdapter(bundle.console, process)

        bundle.worker.attach_adapter(worker_adapter, name="process")
        bundle.stats.attach_adapter(stats_adapter, name="process")
        bundle.command.attach_adapter(command_adapter, name="process")
        bundle.router.attach_adapter(router_adapter, name="process")
        bundle.console.attach_adapter(console_adapter, name="process")

        stats_adapter.setup()
        console_adapter.setup()

    def connect_event_manager(self, process) -> None:
        """Подключить event_manager из shared_resources к router_manager.

        Вызывается после _apply_managers_bundle, когда process.router_manager уже назначен.

        Args:
            process: ProcessModule с назначенным router_manager.
        """
        if (
            process.shared_resources
            and hasattr(process.shared_resources, "event_manager")
            and process.shared_resources.event_manager
        ):
            process.shared_resources.event_manager.set_router_manager(process.router_manager)

    # ========================================================================
    # ПРИВАТНЫЕ МЕТОДЫ СОЗДАНИЯ МЕНЕДЖЕРОВ
    # Каждый метод ЧИТАЕТ из self.process (name, config_handler, etc.)
    # и ВОЗВРАЩАЕТ созданный менеджер. Запись в self.process.* запрещена.
    # ========================================================================

    def _create_worker_manager(self) -> Any:
        from ...worker_module import WorkerManager

        worker = WorkerManager(
            manager_name=self.process.name,
            process=self.process,
        )
        worker.initialize()
        return worker

    def _create_logger_manager(self, managers_config: Dict[str, Any]) -> Any:
        from ...logger_module import LoggerManager, LoggerManagerConfig

        logger_config = managers_config.get("logger", {})
        if isinstance(logger_config, dict):
            merged = {
                **logger_config,
                "app_name": logger_config.get("app_name", self.process.name),
            }
            log_config = LoggerManagerConfig.model_validate(merged)
        else:
            log_config = LoggerManagerConfig(app_name=self.process.name)

        logger = LoggerManager(
            manager_name=f"logger_{self.process.name}",
            config=log_config,
            process=self.process,
            config_manager=self.process.config_manager,
        )
        logger.initialize()
        return logger

    def _create_error_manager(self, managers_config: Dict[str, Any]) -> Any | None:
        error_config_dict = managers_config.get("error", {})
        if isinstance(error_config_dict, dict) and error_config_dict:
            from ...error_module import ErrorManager, ErrorManagerConfig

            error_config = ErrorManagerConfig.model_validate(error_config_dict)
            # B3, находка живого прогона (со второго захода): имя ставится
            # В КОНФИГ, а не только аргументом, и дефолт схемы считается
            # «не названо».
            #
            # Почему так. Машинная раскладка (`managers_payload_for_proc`)
            # МАТЕРИАЛИЗУЕТ дефолт: в словаре всегда лежит
            # `manager_name: "ErrorManager"`, хотя оператор ничего не писал.
            # На стороне менеджера имя конфига сильнее аргумента — и живьём это
            # давало шесть плоскостей ошибок с одним именем на весь стенд:
            # предупреждение «приёмники не приняли ни одной записи за прогон»
            # приходило шесть раз одинаковым, без адреса процесса. Первая
            # редакция этой правки проверяла только пустоту ключа и на стенде
            # не изменила НИЧЕГО — поймано повторным живым прогоном, а не
            # чтением.
            #
            # Дефолт читается из схемы, а не литералом: вторая копия строки
            # разошлась бы с первой молча.
            _schema_name = ErrorManagerConfig.model_fields["manager_name"].default
            if str(error_config_dict.get("manager_name") or "") in ("", str(_schema_name)):
                error_config.manager_name = f"error_{self.process.name}"
            error = ErrorManager(
                manager_name=f"error_{self.process.name}",
                config=error_config,
                process=self.process,
            )
            error.initialize()
            return error

        return None

    def _create_router_manager(
        self,
        managers_config: Dict[str, Any],
        logger: Any,
    ) -> Any:
        from ...router_module import RouterManager

        router_config = managers_config.get("router", {}) or {}
        duplicate_messages = router_config.get("duplicate_messages_to_logger", False)

        # Option A frame-trace: per-process snapshot последнего кадра в файл
        # (overwrite по seq_id) через LoggerManager-канал. Включается MULTIPROCESS_FRAME_TRACE=1.
        from ..generic.frame_trace import _env_frame_trace_on

        frame_trace_on = _env_frame_trace_on()

        router = RouterManager(
            manager_name=f"router_{self.process.name}",
            process=self.process,
            queue_registry=self.process.queue_registry,
            logger=logger,
            # F3 (ревью G.2): проводим декларативный флаг из router_config —
            # конфиг-путь use_kind_channels был мёртв (env/ctor только). Приоритет
            # ctor > env > конфиг разрешается в RouterManager._resolve_use_kind_channels.
            use_kind_channels_config=bool(router_config.get("use_kind_channels", False)),
        )
        router.initialize()

        if logger and (duplicate_messages or frame_trace_on):

            def _log_message_middleware(msg):
                try:
                    log_parts = [
                        msg.get("type", "?"),
                        msg.get("sender", "?"),
                        "->",
                        str(msg.get("targets", [])),
                    ]
                    if msg.get("data_type"):
                        log_parts.append(f" data_type={msg.get('data_type')}")
                    if msg.get("command"):
                        log_parts.append(f" cmd={msg.get('command')}")
                    if msg.get("event_type"):
                        log_parts.append(f" event={msg.get('event_type')}")
                    line = " ".join(log_parts)
                    # DEBUG, не INFO: per-message дубль — основной источник «бесконечного
                    # терминала». На DEBUG он остаётся доступен в LoggerManager, но не флудит INFO.
                    if duplicate_messages:
                        logger.debug(line, module="router_messages")
                    # Frame-trace: только кадровые сообщения (с seq_id) → overwrite-канал.
                    if frame_trace_on:
                        seq = msg.get("seq_id")
                        if seq is None and isinstance(msg.get("data"), dict):
                            seq = msg["data"].get("seq_id")
                        if seq is not None:
                            logger.frame_trace(line, seq)
                except Exception:  # nosec B110 — диагностический middleware: сбой логирования не должен ронять роутинг
                    pass
                return msg

            router._send_mw.add(_log_message_middleware)

        return router

    def _create_stats_manager(
        self,
        managers_config: Dict[str, Any],
        logger: Any,
    ) -> Any:
        from ...statistics_module import StatsManager, StatsManagerConfig

        stats_config_dict = managers_config.get("stats", {})
        stats_config = StatsManagerConfig()
        if isinstance(stats_config_dict, dict):
            for key, value in stats_config_dict.items():
                if hasattr(stats_config, key):
                    setattr(stats_config, key, value)

        stats = StatsManager(
            manager_name=f"stats_{self.process.name}",
            config=stats_config,
            process=self.process,
            managers={"logger": logger},
        )
        stats.initialize()
        return stats

    def _create_observation_manager(self, logger: Any) -> Any:
        """Порт наблюдений процесса (Ф3, задача 3.1).

        Конфига у порта пока нет и секции в ``managers`` он не читает: частоту
        публикации уровней задаёт publisher-гейт (``telemetry.publish``), а
        каналы придут в задаче 3.2. Пустая секция, заведённая «на будущее», была
        бы ручкой, которая ничего не делает, — а такие ручки выглядят
        применёнными.

        Хранилище уровней здесь НЕ создаётся, и не создаётся дальше ничем, кроме
        ПУБЛИКАЦИИ: менеджер резолвит держателя на каждом обращении, а заводит
        хранилище только по ``create=True`` (см. ``ObservationManager.levels``).
        У процесса без плагинов оно так и не появится — ни на старте, ни на
        тиках heartbeat, — и «атрибута нет» останется отличимым от «атрибут
        пуст». Сторожится парой тестов через настоящий ``ProcessHeartbeat``
        (``statistics_module/tests/test_observation_port_hazards.py``, класс про
        флаг ``create``): до правки ревью 2026-08-25 первый же тик поднимал
        хранилище именно на боевой раскладке — со слотом.
        """
        from ...statistics_module.observation.observation_manager import ObservationManager

        observation = ObservationManager(
            manager_name=f"observation_{self.process.name}",
            process=self.process,
            managers={"logger": logger},
        )
        observation.initialize()
        return observation

    def _create_command_manager(
        self,
        managers_config: Dict[str, Any],
        logger: Any,
        stats: Any,
    ) -> Any:
        from ...command_module import CommandManager

        command_config = managers_config.get("command", {})
        command = CommandManager(
            self.process.name,
            managers={
                "logger": logger,
                "stats": stats,
            },
            config={
                "logger": command_config.get("enable_logging", True),
                "stats": command_config.get("enable_statistics", True),
                # observability.commands.log_success доезжает сюда через
                # expand_observability()["command"] + merge_managers (тот же
                # путь, что enable_logging/enable_statistics выше).
                "log_success": command_config.get("log_success", False),
            },
            config_manager=self.process.config_manager,
        )
        return command

    def _create_console_manager(
        self,
        managers_config: Dict[str, Any],
    ) -> tuple[Any, bool]:
        """Создать ConsoleManager.

        Returns:
            tuple(console_manager, console_enabled)
        """
        from ...console_module import ConsoleManager
        from ...console_module.configs.console_config import ConsoleConfig

        console_cfg_dict = managers_config.get("console", {})
        console_config = (
            ConsoleConfig(**console_cfg_dict)
            if isinstance(console_cfg_dict, dict) and console_cfg_dict
            else ConsoleConfig()
        )

        console = ConsoleManager(
            manager_name=f"console_{self.process.name}",
            config=console_config,
            process=self.process,
        )
        console.initialize()

        enabled = console_config.enabled if console_config is not None else False
        return console, enabled
