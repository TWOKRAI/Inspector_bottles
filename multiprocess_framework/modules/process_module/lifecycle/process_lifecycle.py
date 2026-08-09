"""
Жизненный цикл процесса.

Helper-функции для инициализации и завершения работы (ADR-PM-009).
Оркестрация перенесена в ProcessModule.initialize().

Контракт: init_configuration() и init_queues() ЧИТАЮТ из self.process,
создают объекты и ВОЗВРАЩАЮТ результат. ProcessModule сам присваивает атрибуты.
"""

from ..._fallback import emergency_log
from ..types import ProcessStatus

#: Имя stdlib-логгера аварийного выхода — ровно имя этого модуля, чтобы записи
#: об отказе гашения искались там, где они и происходят.
_EMERGENCY_NAME = __name__


class ProcessLifecycle:
    """
    Helper-класс жизненного цикла процесса.

    Инкапсулирует логику инициализации конфигурации, очередей и завершения работы.
    Оркестрация (порядок вызовов) — ответственность ProcessModule.
    """

    def __init__(self, process):
        """
        Инициализация жизненного цикла.

        Args:
            process: Ссылка на ProcessModule
        """
        self.process = process

    def init_configuration(self) -> tuple:
        """Инициализация конфигурации процесса (return-based, ADR-PM-009).

        Читает из self.process (name, shared_resources, config).
        НЕ пишет в self.process.*.

        Returns:
            tuple: (config_handler, config_manager, config_dict)
        """
        from ..configs import ProcessConfigHandler
        from ...config_module import ConfigManager

        config_handler = ProcessConfigHandler(
            self.process.name,
            self.process.shared_resources,
            self.process.config,
        )
        config_manager = ConfigManager()
        config_handler.config_manager = config_manager
        config_dict = config_handler.data if config_handler else {}

        return config_handler, config_manager, config_dict

    def init_queues(self) -> tuple:
        """Инициализация очередей процесса (return-based, ADR-PM-009).

        Основной путь: очереди уже созданы через
        SharedResourcesManager.register_process() → QueueRegistry.create_and_register_queues()
        и хранятся в ProcessData. Здесь они просто извлекаются.

        Fallback: если shared_resources не передан (тесты, standalone),
        создаются локальные multiprocessing.Queue.

        Читает из self.process (name, shared_resources).
        НЕ пишет в self.process.*.

        Returns:
            tuple: (queues, queue_registry, memory_manager)
        """
        process_data = None
        if self.process.shared_resources:
            process_data = self.process.shared_resources.get_process_data(self.process.name)

        if process_data and process_data.queues:
            queues_dict = {}
            for queue_type in process_data.queues.keys():
                queue = process_data.get_queue(queue_type)
                if queue:
                    queues_dict[queue_type] = queue
            queues = queues_dict if queues_dict else None
        else:
            queues = None

        # Fallback: создать локальные очереди если не получены из SRM
        if not queues:
            from multiprocessing import Queue

            queues = {
                "system": Queue(maxsize=100),
                "data": Queue(maxsize=50),
                "broadcast": Queue(maxsize=20),
                "custom": Queue(maxsize=20),
            }

        if self.process.shared_resources:
            queue_registry = getattr(self.process.shared_resources, "queue_registry", None)
            memory_manager = getattr(self.process.shared_resources, "memory_manager", None)
        else:
            queue_registry = None
            memory_manager = None

        return queues, queue_registry, memory_manager

    # P4.4.1 (B2): register_commands_with_router + _make_command_handler УДАЛЕНЫ.
    # Раньше они КОПИРОВАЛИ все команды CommandManager в router.event_dispatcher
    # (через generic-closure с reply_to_request). После kind-router'а команды
    # (type=="command") диспатчатся напрямую в CommandManager из RouterManager.receive()
    # (`_dispatch_command`), а reply делает транспорт по request_id — копии в
    # event_dispatcher больше не нужны (дупликация реестра устранена). CommandManager —
    # единственный владелец командных ключей.

    def shutdown(self) -> bool:
        """
        Завершение работы процесса.

        Returns:
            bool: True если завершение успешно
        """
        try:
            # 1. Устанавливаем флаг остановки
            self.process._stop_requested = True

            # 1b. Снять контекст логирования (парно к set_base_context на старте, Ф0.5)
            logger = self.process.get_manager("logger")
            if logger and hasattr(logger, "clear_base_context"):
                logger.clear_base_context()

            # 2. Останавливаем системные потоки
            self.process._stop_system_threads()

            # 3. Останавливаем воркеры
            if self.process.worker_manager:
                self.process.worker_manager.stop_all_workers()

            # 3b. Завершаем SharedResourcesManager (unlink SharedMemory на macOS/Linux)
            if self.process.shared_resources and hasattr(self.process.shared_resources, "shutdown"):
                try:
                    self.process.shared_resources.shutdown()
                except Exception as e:
                    self.process._log_error(f"SRM shutdown error: {e}")

            # 4. Завершаем менеджеры. Порядок — часть контракта, а не привычка (B3).
            #
            # Логгер стоял здесь ТРЕТЬИМ, а после него шли command/router, смена
            # статуса и запись «shut down successfully»: всё, что уборка говорит
            # на INFO/WARNING, терялось ВСЕГДА (floor подстраховывает только
            # ERROR/CRITICAL). Воспроизведено ревью 2026-08-09: unresolved=6,
            # floor=1, предупреждение однократно — «дальше считаем молча».
            #
            # error/stats не гасились НИГДЕ (grep по репозиторию — пусто), то
            # есть финальный сброс двух плоскостей из трёх оставался на совести
            # ОС. Оба наследуют `shutdown` от CRM: flush() → buffer.stop()
            # (финальный сброс окна агрегации) → _close_all_channels().
            #
            # stats гасится ДО логгера не по алфавиту: его канал `log_stats`
            # пишет ЧЕРЕЗ логгер, и обратный порядок отправил бы финальный
            # снапшот метрик в уже закрытый приёмник.
            if self.process.console_manager:
                self.process.console_manager.shutdown()
            if self.process.command_manager:
                self.process.command_manager.shutdown()
            if self.process.router_manager:
                self.process.router_manager.shutdown()
            stopped_planes = []
            if self.process.error_manager:
                self.process.error_manager.shutdown()
                stopped_planes.append("error")
            if self.process.stats_manager:
                self.process.stats_manager.shutdown()
                stopped_planes.append("stats")
            # Названо ФАКТИЧЕСКОЕ, а не заявленное: список собирается из того,
            # что действительно погашено. Без этой строки гашение младших
            # плоскостей не наблюдаемо в журнале вовсе — собственная запись
            # плоскости ошибок идёт по её же маршруту, а INFO по нему не ездит
            # (пороги severity), то есть «погасили» и «не погасили» выглядели бы
            # одинаково.
            if stopped_planes:
                self.process._log_info(
                    f"Process '{self.process.name}' observability planes stopped: {', '.join(stopped_planes)}"
                )

            # 5. Статус и итоговая запись — пока логгер ЖИВ.
            self.process.update_process_state(status=ProcessStatus.STOPPED.value)

            self.process.is_initialized = False
            self.process._log_info(f"Process '{self.process.name}' shut down successfully")

            # 6. Логгер — последним. Его собственный отказ писать через него же
            # нельзя (предмет претензии — он), поэтому named-исключение:
            # аварийный выход в stdlib. Останов при этом состоялся — подменять
            # успех останова отказом закрытия приёмника значило бы соврать в
            # другую сторону.
            if self.process.logger_manager:
                try:
                    self.process.logger_manager.shutdown()
                except Exception as exc:  # noqa: BLE001 — отказ гашения обязан быть слышен
                    emergency_log(
                        _EMERGENCY_NAME,
                        "error",
                        f"[{self.process.name}] гашение логгера не удалось: {exc}; "
                        "приёмники могли остаться незакрытыми",
                    )
            return True

        except Exception as e:
            self.process._log_error(f"Error during shutdown of process '{self.process.name}': {e}")
            return False
