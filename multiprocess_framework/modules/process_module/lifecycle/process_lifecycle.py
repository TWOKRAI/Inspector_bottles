"""
Жизненный цикл процесса.

Helper-функции для инициализации и завершения работы (ADR-PM-009).
Оркестрация перенесена в ProcessModule.initialize().

Контракт: init_configuration() и init_queues() ЧИТАЮТ из self.process,
создают объекты и ВОЗВРАЩАЮТ результат. ProcessModule сам присваивает атрибуты.
"""

import time

from ..._fallback import emergency_log

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
        #: Запись ``planes/logger`` отработала: reporter пишет только аварийным выходом.
        self.logger_down = False

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

    # Task 1.2a (ADR-PM-054): прозаический ``shutdown()`` удалён — его шаги стали
    # записями корня процесса (``ProcessModule._register_*``), порядок держит корень.

    def stop_logger(self) -> None:
        """Запись ``planes/logger`` — последней: снять контекст, погасить логгер.

        Исключение тела ``LoggerManager._on_shutdown`` сюда не доходит: шаблон
        ``BaseManager.shutdown()`` гасит его в ``False`` и пишет свою строку через
        вид — она заменяет аварийный выход (Task 1.2b-2, ADR-BM-009). Аварийным
        выходом пишется только исключение самого ``shutdown()`` (жаловаться через
        сам логгер нельзя). После вызова reporter корня пишет только в аварийный выход.
        """
        process = self.process
        logger = process.logger_manager
        try:
            if logger is not None and hasattr(logger, "clear_base_context"):
                logger.clear_base_context()
        except Exception as exc:  # noqa: BLE001 — снятие контекста не срывает гашение
            emergency_log(_EMERGENCY_NAME, "warning", f"[{process.name}] снятие контекста логгера: {exc}")
        try:
            if logger is not None:
                logger.shutdown()
        except Exception as exc:  # noqa: BLE001 — отказ гашения обязан быть слышен
            emergency_log(
                _EMERGENCY_NAME,
                "error",
                f"[{process.name}] гашение логгера не удалось: {exc}; приёмники могли остаться незакрытыми",
            )
        finally:
            self.logger_down = True

    def report(self, report) -> None:
        """Reporter корня процесса: строка только при ``not ok`` или доставках после закрытия.

        Пока логгер жив — им, после записи ``logger`` — аварийным выходом. Не бросает.
        """
        try:
            if report.ok and not report.emits_after_close:
                return
            text = (
                f"[{self.process.name}] root close {report.path}: survivors={list(report.survivors)} "
                f"killed={list(report.killed)} errors={list(report.errors)} "
                f"emits_after_close={report.emits_after_close} complete={report.complete} "
                f"elapsed={report.elapsed_s:.3f}s"
            )
            if not getattr(self, "logger_down", False):
                try:
                    self.process._log_warning(text, module="lifecycle")
                    return
                except Exception:  # noqa: BLE001 — живой логгер отказал: аварийный выход
                    pass
            emergency_log(_EMERGENCY_NAME, "warning", text)
        except Exception:  # noqa: BLE001 — reporter не бросает (контракт Reporter)
            pass


class _WorkersStop:
    """Stoppable воркеров процесса в сегменте ``work`` (Task 1.2a, О2).

    ``request_stop`` — ничего: у ``WorkerManager`` нет неблокирующего «стоп всем»
    (это 1.3). ``join_until`` — ``stop_all_workers`` с остатком срока; остановлен,
    только если ни у одного воркера поток не жив (``is_alive``, а не статус:
    ``stop_all_workers`` пишет STOPPED безусловно). Менеджер читается поздно —
    в момент закрытия.
    """

    def __init__(self, process) -> None:
        self._process = process

    def request_stop(self) -> None:
        return None

    def join_until(self, deadline: float) -> bool:
        manager = getattr(self._process, "worker_manager", None)
        if manager is None:
            return True
        manager.stop_all_workers(timeout=max(0.0, deadline - time.monotonic()))
        for name in list(manager.list_workers()):
            status = manager.get_worker_status(name)
            if status and status.get("is_alive"):
                return False
        return True
