"""
ProcessManagerProcess — процесс-оркестратор (Refactored).

Наследуется от ProcessModule. Использует композицию:
    ProcessRegistry + ProcessPriority + ProcessStatusMonitor + ProcessMonitor.

Порядок shutdown:
    ProcessMonitor → ProcessRegistry.stop_all → WorkerManager → ConsoleManager → super
"""

import copy
import uuid
from typing import Any

from ...console_module import ConsoleManager
from ...process_module import ProcessModule
from ...shared_resources_module import QueueRegistry
from ..core.process_priority import ProcessPriority
from ..core.process_registry import ProcessRegistry
from ..core.process_status import ProcessStatusMonitor
from ..monitor import ProcessMonitor
from ..platforms import get_platform_adapter
from .backend_ctl_endpoint import (
    setup_backend_ctl_channel,
    teardown_backend_ctl_channel,
)
from .topology_manager import TopologyManager


def _merge_cmd_args(data: dict | None, kwargs: dict) -> dict:
    """Унифицировать вызов из Dispatcher(data_dict) и прямой(kwargs)."""
    if isinstance(data, dict):
        kwargs.update(data)
    return kwargs


class ProcessManagerProcess(ProcessModule):
    """
    Процесс-оркестратор: управляет всеми процессами системы.

    Реализует IProcessManagerProcess.
    Композиция: ProcessRegistry + ProcessPriority + ProcessStatusMonitor + ProcessMonitor.

    Жизненный цикл:
        __init__  → _create_components()
        initialize() → super().initialize() → _create_processes_from_config() → monitor.start()
        shutdown() → monitor.stop() → registry.stop_all() → console.shutdown() → super()
    """

    def __init__(
        self,
        name: str = "ProcessManager",
        shared_resources=None,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name, shared_resources, config or {})
        self._process_configs: dict[str, dict[str, Any]] = {}
        # Трекинг активных wire-каналов (wire_key → метаданные)
        self._active_wires: dict[str, dict[str, Any]] = {}
        self._create_components()

    def _create_components(self) -> None:
        """Создать внутренние компоненты оркестратора."""
        process_data = self.shared_resources.get_process_data(self.name) if self.shared_resources else None
        custom = process_data.custom if process_data and process_data.custom else {}
        from multiprocessing import Event as _MpEvent

        self.stop_event = custom.get("stop_event") or _MpEvent()
        # Event для сигнализации готовности системы (ADR-116).
        # Выставляется в конце initialize() — SystemLauncher ждёт его в wait_until_ready().
        self._system_ready_event = custom.get("system_ready_event")

        queue_registry = self._resolve_queue_registry()

        platform_adapter = get_platform_adapter()

        self._process_registry = ProcessRegistry(
            logger=self,
            queue_registry=queue_registry,
            config_manager=None,
            shared_resources=self.shared_resources,
        )
        self._priority = ProcessPriority(logger=self, platform_adapter=platform_adapter)
        self._status = ProcessStatusMonitor(self._process_registry.os_processes)

        # Настройки монитора из конфига ProcessManager
        monitor_poll = float(self.get_config("monitor_poll_interval") or 0.5)
        heartbeat_timeout = float(self.get_config("heartbeat_timeout") or 15.0)

        # RestartPolicy из конфига (dict -> SchemaBase) или default
        restart_cfg = self.get_config("restart_policy")
        if isinstance(restart_cfg, dict):
            from ..core.restart_policy import RestartPolicy

            restart_policy = RestartPolicy(**restart_cfg)
        else:
            restart_policy = None

        self._process_monitor = ProcessMonitor(
            self,
            poll_interval=monitor_poll,
            heartbeat_timeout=heartbeat_timeout,
            restart_policy=restart_policy,
        )
        self._console_manager: ConsoleManager | None = None
        self._topology_manager: TopologyManager | None = None
        self._state_store_manager = None
        # backend-control endpoint (SocketChannel), поднимается при BACKEND_CTL=1
        self._backend_ctl_channel = None

    def _resolve_queue_registry(self):
        """Получить QueueRegistry из shared_resources или создать новый."""
        if self.shared_resources:
            try:
                if hasattr(self.shared_resources, "queue_registry"):
                    return self.shared_resources.queue_registry
                registry = getattr(self.shared_resources, "process_state_registry", None)
                if registry and hasattr(registry, "queue_registry"):
                    return registry.queue_registry
            except Exception:  # nosec B110 — fallback к локальному QueueRegistry
                pass
        # Fallback: создать локальный QueueRegistry
        queue_registry = QueueRegistry(
            manager_name="queue_registry",
            process_state_registry=(self.shared_resources.process_state_registry if self.shared_resources else None),
        )
        queue_registry.initialize()
        return queue_registry

    def _setup_console_manager(self) -> None:
        """Создать ConsoleManager только если включён в конфиге."""
        console_enabled = self.get_config("console_enabled")
        if not console_enabled:
            return
        logger = self.logger_manager if hasattr(self, "logger_manager") else None
        self._console_manager = ConsoleManager(
            manager_name="console_manager",
            managers={"logger": logger} if logger else {},
        )

    def initialize(self) -> bool:
        """Инициализация: ProcessModule + создание процессов из config + запуск монитора."""
        try:
            # Регистрация ProcessManager для приёма команд (system.shutdown от GUI и др.)
            if self.shared_resources:
                self.shared_resources.register_process(
                    self.name,
                    {"queues": {"system": {"maxsize": 100}, "data": {"maxsize": 50}}},
                )

            if not super().initialize():
                return False

            self._setup_console_manager()
            self._setup_topology_manager()
            self._setup_state_store()
            self._register_builtin_commands()

            processes_config = self.get_config("processes_config") or {}
            if isinstance(processes_config, dict) and processes_config:
                self._create_processes_from_config(processes_config)

            self._process_monitor.start()

            # Router endpoint: другие процессы могут слать команды через Router (AD-8)
            if self.router_manager:
                self.router_manager.register_message_handler("process.command", self._handle_process_command)

            # backend-control endpoint (dev-инструмент): гейт = system.yaml
            # backend_ctl.enabled ИЛИ env BACKEND_CTL=1. Внешний driver подключается
            # по TCP и шлёт router-сообщения как GUI.
            self._backend_ctl_channel = setup_backend_ctl_channel(
                self.router_manager,
                config=self.get_config("backend_ctl"),
                log_info=self._log_info,
                log_error=self._log_error,
            )

            # Сигнализируем SystemLauncher, что инициализация завершена (ADR-116).
            # К этому моменту: все дочерние процессы spawned и started,
            # ProcessMonitor запущен.
            if self._system_ready_event is not None:
                self._system_ready_event.set()
                self._log_info("system_ready_event выставлен — система готова")

            return True
        except Exception as exc:
            self._handle_critical_error(exc, "initialize")
            return False

    def _setup_state_store(self) -> None:
        """Хук: создать StateStoreManager. Переопределяется в прототипе."""
        pass

    def _setup_topology_manager(self) -> None:
        """Создать TopologyManager с callback'ами в PM."""
        allocate_shm = None
        if self.shared_resources:
            mm = getattr(self.shared_resources, "memory_manager", None)
            if mm and hasattr(mm, "create_memory_dict"):
                allocate_shm = mm.create_memory_dict

        self._topology_manager = TopologyManager(
            create_process_fn=self._cmd_process_create,
            stop_process_fn=self.stop_process,
            allocate_shm_fn=allocate_shm,
        )

    def _register_builtin_commands(self) -> None:
        """Зарегистрировать встроенные команды системы."""
        if not self.command_manager:
            return

        commands = {
            "process.list": (self._cmd_process_list, "Список всех процессов и статусов"),
            "process.create": (self._cmd_process_create, "Создать процесс из inline-конфига"),
            "process.start": (self._cmd_process_start, "Запустить именованный процесс"),
            "process.stop": (self._cmd_process_stop, "Остановить именованный процесс"),
            "process.pause": (self._cmd_process_pause, "Поставить процесс на паузу"),
            "process.resume": (self._cmd_process_resume, "Возобновить процесс"),
            "process.restart": (self._cmd_process_restart, "Перезапустить именованный процесс"),
            "process.status": (self._cmd_process_status, "Статус именованного процесса"),
            "system.shutdown": (self._cmd_system_shutdown, "Завершить систему"),
            "system.stats": (self._cmd_system_stats, "Статистика системы"),
            "topology.apply": (self._cmd_topology_apply, "Применить топологию процессов"),
            "topology.get": (self._cmd_topology_get, "Получить текущую топологию"),
            "topology.diff": (self._cmd_topology_diff, "Вычислить diff топологии (dry-run)"),
            "wire.setup": (self._cmd_wire_setup, "Настроить wire-канал (SHM + routes)"),
            "wire.teardown": (self._cmd_wire_teardown, "Разобрать wire-канал"),
            "wire.status": (self._cmd_wire_status, "Статусы wire-каналов"),
            "blueprint.replace": (
                self._cmd_blueprint_replace,
                "Заменить blueprint (горячая замена процессов)",
            ),
        }

        for cmd_name, (handler, description) in commands.items():
            self.command_manager.register_command(
                cmd_name,
                handler,
                metadata={"description": description},
                tags=["system"],
            )

    # -------------------------------------------------------------------------
    # Обработчики встроенных команд
    # -------------------------------------------------------------------------

    def _cmd_process_list(self, data=None, **kwargs) -> dict:
        """Вернуть список всех процессов и их статусы + конфиг.

        Поддерживает вызов через Dispatcher(data_dict) и прямой вызов(kwargs).
        Параметр data принимается но не используется — команда не требует аргументов.
        """
        # Вместо формирования ответа (он всё равно теряется в Router) —
        # запускаем немедленный broadcast через ProcessMonitor.
        # GUI получит данные через существующий push-канал process_full_status.
        if getattr(self, "_process_monitor", None):
            self._process_monitor.broadcast_full_status()
        return {"success": True, "triggered_broadcast": True}

    def _cmd_process_create(self, data=None, **kwargs) -> dict:
        """Создать процесс из inline-конфига (AD-8).

        Поддерживает два формата вызова:
          - Из Dispatcher: _cmd_process_create(data_dict) — dict как первый аргумент
          - Прямой вызов: _cmd_process_create(process_name="foo", class_path="bar")
          - Из TopologyManager: _cmd_process_create(process_name=..., class_path=...)

        Позволяет динамически создавать процессы через CommandManager или
        Router-endpoint без предварительной записи в _process_configs.
        """
        # Поддержка вызова из Dispatcher(data_dict)
        if isinstance(data, dict):
            kwargs.update(data)
        process_name = kwargs.get("process_name", "")
        class_path = kwargs.get("class_path", "")
        config = kwargs.get("config")
        priority = kwargs.get("priority", "normal")

        if not process_name:
            return {"error": "process_name required"}
        if not class_path:
            return {"error": "class_path required"}
        process = self.create_process(process_name, class_path, config, priority)
        if not process:
            return {"success": False, "process_name": process_name}
        # Автостарт отключён: пользователь запускает вручную через process.start
        auto_start = kwargs.get("auto_start", False)
        if auto_start:
            try:
                process.start()
                self._priority.apply_priority(process)
            except Exception as exc:
                self._log_error(f"Автостарт процесса '{process_name}' не удался: {exc}")
                return {"success": False, "process_name": process_name, "error": str(exc)}
        return {
            "success": True,
            "process_name": process_name,
        }

    def _cmd_process_start(self, data=None, **kwargs) -> dict:
        """Запустить именованный процесс."""
        args = _merge_cmd_args(data, kwargs)
        if not (pn := args.get("process_name")):
            return {"error": "process_name required"}
        return {"success": self.start_process(pn), "process_name": pn}

    def _cmd_process_stop(self, data=None, **kwargs) -> dict:
        """Остановить именованный процесс."""
        args = _merge_cmd_args(data, kwargs)
        if not (pn := args.get("process_name")):
            return {"error": "process_name required"}
        return {"success": self.stop_process(pn), "process_name": pn}

    def _cmd_process_pause(self, data=None, **kwargs) -> dict:
        """Поставить именованный процесс на паузу."""
        args = _merge_cmd_args(data, kwargs)
        if not (pn := args.get("process_name")):
            return {"error": "process_name required"}
        return {"success": self.pause_process(pn), "process_name": pn}

    def _cmd_process_resume(self, data=None, **kwargs) -> dict:
        """Возобновить именованный процесс."""
        args = _merge_cmd_args(data, kwargs)
        if not (pn := args.get("process_name")):
            return {"error": "process_name required"}
        return {"success": self.resume_process(pn), "process_name": pn}

    def _cmd_process_restart(self, data=None, **kwargs) -> dict:
        """Перезапустить именованный процесс."""
        args = _merge_cmd_args(data, kwargs)
        if not (pn := args.get("process_name")):
            return {"error": "process_name required"}
        return {"success": self.restart_process(pn), "process_name": pn}

    def _cmd_process_status(self, data=None, **kwargs) -> dict:
        """Статус именованного процесса."""
        args = _merge_cmd_args(data, kwargs)
        if not (pn := args.get("process_name")):
            return {"error": "process_name required"}
        return self.get_process_status(pn)

    def _cmd_system_shutdown(self, data=None, **kwargs) -> dict:
        """Запустить завершение системы.

        Параметр data принимается но не используется — команда не требует аргументов.
        """
        self._log_info("System shutdown requested via command")
        self.stop_event.set()
        return {"success": True, "message": "Shutdown initiated"}

    def _cmd_system_stats(self, data=None, **kwargs) -> dict:
        """Статистика системы.

        Параметр data принимается но не используется — команда не требует аргументов.
        """
        stats: dict = {}
        if hasattr(self, "_process_monitor"):
            stats["monitor"] = self._process_monitor.get_stats()
        stats["processes"] = self.get_all_processes_status()
        return stats

    # -------------------------------------------------------------------------
    # Topology commands
    # -------------------------------------------------------------------------

    def _cmd_topology_apply(self, data=None, **kwargs) -> dict:
        """Применить новую топологию процессов."""
        args = _merge_cmd_args(data, kwargs)
        if not (td := args.get("topology_dict")):
            return {"error": "topology_dict required"}
        if self._topology_manager is None:
            return {"error": "TopologyManager not initialized"}
        return self._topology_manager.apply(td)

    def _cmd_topology_get(self, data=None, **kwargs) -> dict:
        """Получить текущую топологию.

        Параметр data принимается но не используется — команда не требует аргументов.
        """
        if self._topology_manager is None:
            return {"error": "TopologyManager not initialized"}
        return self._topology_manager.get()

    def _cmd_topology_diff(self, data=None, **kwargs) -> dict:
        """Dry-run: вычислить diff без применения."""
        args = _merge_cmd_args(data, kwargs)
        if not (td := args.get("topology_dict")):
            return {"error": "topology_dict required"}
        if self._topology_manager is None:
            return {"error": "TopologyManager not initialized"}
        return self._topology_manager.diff(td)

    # -------------------------------------------------------------------------
    # Wire commands — runtime-настройка SHM-каналов между процессами
    # -------------------------------------------------------------------------

    def _cmd_wire_setup(self, data=None, **kwargs) -> dict:
        """Настроить wire-канал: аллоцировать SHM и отправить wire.configure в процессы.

        Поддерживает вызов через Dispatcher(data_dict) и прямой вызов(kwargs).

        Параметры в data:
            wire_key: уникальный ключ wire (например "camera→processor")
            source_process: имя процесса-отправителя
            target_process: имя процесса-получателя
            transport: тип транспорта ("router" для SHM)
            shm_config: dict с параметрами SHM (shm_name, buffer_slots, owner_process)
        """
        kwargs = _merge_cmd_args(data, kwargs)

        wire_key = kwargs.get("wire_key", "")
        source_process = kwargs.get("source_process", "")
        target_process = kwargs.get("target_process", "")
        transport = kwargs.get("transport", "router")
        shm_config = kwargs.get("shm_config") or {}

        if not wire_key:
            return {"error": "wire_key required"}
        if not source_process or not target_process:
            return {"error": "source_process и target_process обязательны"}

        # SHM аллокация (если transport == "router")
        shm_name = shm_config.get("shm_name", wire_key)
        buffer_slots = shm_config.get("buffer_slots", 4)
        owner = shm_config.get("owner_process", source_process)

        if transport == "router":
            mm = getattr(self.shared_resources, "memory_manager", None) if self.shared_resources else None
            if mm and hasattr(mm, "create_memory_dict"):
                try:
                    frame_shape = tuple(shm_config.get("frame_shape", (480, 640, 3)))
                    dtype = shm_config.get("dtype", "uint8")
                    mm.create_memory_dict(
                        owner,
                        {shm_name: (1, frame_shape, dtype)},
                        buffer_slots,
                    )
                    self._log_info(
                        f"wire.setup: SHM аллоцирован — owner={owner}, slot={shm_name}, buffer_slots={buffer_slots}"
                    )
                except Exception as exc:
                    self._log_error(f"wire.setup: SHM аллокация не удалась: {exc}")
                    return {"success": False, "wire_key": wire_key, "error": str(exc)}
            else:
                self._log_warning("wire.setup: memory_manager недоступен, SHM не аллоцирован")

        # Сохранить wire в трекер
        self._active_wires[wire_key] = {
            "source_process": source_process,
            "target_process": target_process,
            "transport": transport,
            "shm_config": {
                "shm_name": shm_name,
                "buffer_slots": buffer_slots,
                "owner_process": owner,
            },
            "status": "pending",
        }

        # IPC в source process: wire.configure (role=sender)
        configure_base = {
            "wire_key": wire_key,
            "shm_name": shm_name,
            "shm_owner": owner,
            "buffer_slots": buffer_slots,
        }

        source_cmd = {
            "type": "system",
            "command": "wire.configure",
            "sender": self.name,
            "data": {**configure_base, "role": "sender"},
        }
        try:
            self.send_message(source_process, source_cmd)
        except Exception as exc:
            self._log_error(f"wire.setup: не удалось отправить wire.configure в {source_process}: {exc}")

        # IPC в target process: wire.configure (role=receiver)
        target_cmd = {
            "type": "system",
            "command": "wire.configure",
            "sender": self.name,
            "data": {**configure_base, "role": "receiver"},
        }
        try:
            self.send_message(target_process, target_cmd)
        except Exception as exc:
            self._log_error(f"wire.setup: не удалось отправить wire.configure в {target_process}: {exc}")

        self._active_wires[wire_key]["status"] = "active"
        self._log_info(f"wire.setup: канал '{wire_key}' настроен ({source_process} → {target_process})")
        return {"success": True, "wire_key": wire_key}

    def _cmd_wire_teardown(self, data=None, **kwargs) -> dict:
        """Разобрать wire-канал: отправить wire.deconfigure в процессы и удалить из трекера.

        Поддерживает вызов через Dispatcher(data_dict) и прямой вызов(kwargs).

        Параметры в data:
            wire_key: ключ wire для удаления
            source_process: имя процесса-отправителя
            target_process: имя процесса-получателя
        """
        kwargs = _merge_cmd_args(data, kwargs)

        wire_key = kwargs.get("wire_key", "")
        if not wire_key:
            return {"error": "wire_key required"}

        wire_info = self._active_wires.get(wire_key)
        # Позволяем переопределить процессы из kwargs (для гибкости)
        source_process = kwargs.get("source_process") or (wire_info or {}).get("source_process", "")
        target_process = kwargs.get("target_process") or (wire_info or {}).get("target_process", "")

        # IPC wire.deconfigure в source + target
        deconfigure_cmd_base = {
            "type": "system",
            "command": "wire.deconfigure",
            "sender": self.name,
            "data": {"wire_key": wire_key},
        }

        for process_name in (source_process, target_process):
            if process_name:
                try:
                    self.send_message(process_name, deconfigure_cmd_base)
                except Exception as exc:
                    self._log_error(f"wire.teardown: не удалось отправить wire.deconfigure в {process_name}: {exc}")

        # Удалить из трекера
        self._active_wires.pop(wire_key, None)
        self._log_info(f"wire.teardown: канал '{wire_key}' разобран")
        return {"success": True, "wire_key": wire_key}

    def _cmd_wire_status(self, data=None, **kwargs) -> dict:
        """Статусы wire-каналов.

        Параметр data принимается но не используется — команда не требует аргументов.
        """
        result = {}
        for wire_key, info in self._active_wires.items():
            result[wire_key] = {
                "status": info.get("status", "idle"),
                "source_process": info.get("source_process", ""),
                "target_process": info.get("target_process", ""),
                "transport": info.get("transport", ""),
            }
        return {"success": True, "wires": result}

    # -------------------------------------------------------------------------
    # Blueprint replace — горячая замена незащищённых процессов (Phase 5)
    # -------------------------------------------------------------------------

    def _get_protected_names(self) -> set[str]:
        """Вернуть множество имён процессов, которые нельзя перезапускать.

        Protected-процессы определяются по ключу ``"protected": True``
        в ``_process_configs``.  ProcessManager всегда защищает себя.
        """
        protected: set[str] = {self.name}
        for proc_name, cfg in self._process_configs.items():
            if isinstance(cfg, dict) and cfg.get("protected"):
                protected.add(proc_name)
        return protected

    def _stop_and_cleanup_process(self, name: str, timeout: float) -> bool:
        """Остановить процесс, снять с реестра и освободить SHM.

        Не бросает исключений — при ошибке логирует и возвращает False.

        Args:
            name: имя процесса.
            timeout: таймаут остановки (секунды).

        Returns:
            True если процесс остановлен успешно, False при ошибке.
        """
        try:
            # Остановить процесс через registry (graceful → terminate → kill)
            stopped = self._process_registry.stop_one(name, timeout)
            if not stopped:
                self._log_warning(
                    f"replace_blueprint: stop_one вернул False для '{name}', возможно процесс не найден в реестре"
                )
                return False
        except Exception as exc:
            self._log_error(f"replace_blueprint: ошибка остановки '{name}': {exc}")
            return False

        try:
            self._process_registry.remove_process(name)
        except Exception as exc:
            self._log_warning(f"replace_blueprint: ошибка удаления '{name}' из реестра: {exc}")

        # Cleanup SHM-сегментов процесса
        if self.shared_resources is not None:
            mm = getattr(self.shared_resources, "memory_manager", None)
            if mm is not None:
                release_fn = getattr(mm, "release_process_memory", None)
                if release_fn is not None:
                    try:
                        release_fn(name)
                    except Exception as exc:
                        self._log_warning(f"replace_blueprint: SHM cleanup для '{name}' не удался: {exc}")
                else:
                    self._log_warning(
                        f"replace_blueprint: memory_manager не имеет release_process_memory, SHM для '{name}' не очищен"
                    )

        return True

    def _restore_from_snapshot(self, snapshot_configs: dict[str, dict]) -> None:
        """Восстановить процессы из snapshot-конфигов (rollback).

        Для каждой записи: удаляет текущую запись в реестре (если есть),
        пересоздаёт и запускает процесс.  При ошибке — логирует и
        продолжает (rollback не прерывается).

        Args:
            snapshot_configs: ``{process_name: proc_config}`` — конфиги
                до начала replace.
        """
        for proc_name, cfg in snapshot_configs.items():
            try:
                # Убрать остатки (если процесс был частично создан)
                self._process_registry.remove_process(proc_name)

                # Зарегистрировать процесс в shared_resources
                if self.shared_resources:
                    self.shared_resources.register_process(proc_name, cfg)

                class_path = cfg.get("class", "")
                priority = cfg.get("priority", "normal")
                process = self._process_registry.create_and_register(proc_name, class_path, cfg, priority)
                if process:
                    process.start()
                    self._priority.apply_priority(process)
                    self._log_info(f"replace_blueprint rollback: процесс '{proc_name}' восстановлен")
                else:
                    self._log_error(f"replace_blueprint rollback: не удалось пересоздать '{proc_name}'")
            except Exception as exc:
                self._log_error(f"replace_blueprint rollback: ошибка восстановления '{proc_name}': {exc}")

        # Восстановить _process_configs из snapshot
        for proc_name, cfg in snapshot_configs.items():
            self._process_configs[proc_name] = copy.deepcopy(cfg)

    def replace_blueprint(self, new_blueprint: dict[str, Any] | None) -> dict[str, Any]:
        """Заменить blueprint: остановить незащищённые процессы, поднять новые.

        Dict at Boundary: принимает dict, не Pydantic-модель.

        Алгоритм:
            1. Извлечь список процессов из ``new_blueprint["processes"]``.
            2. Вычислить protected (``_get_protected_names``).
            3. Вычислить ``to_replace`` — текущие незащищённые процессы.
            4. Snapshot ``copy.deepcopy(to_replace)``.
            5. Pause ProcessMonitor.
            6. Stop+cleanup каждого ``to_replace``; при ошибке → rollback.
            7. Register+start новых процессов; при ошибке → rollback.
            8. Обновить ``_process_configs``, resume monitor.
            9. Вернуть результат.

        Args:
            new_blueprint: dict-представление SystemBlueprint.  Если ``None``
                или ``{}`` — трактуется как пустой blueprint.

        Returns:
            dict с ключами ``success``, ``replaced``, ``skipped_protected``,
            ``error``, ``rolled_back``.
        """
        # --- Edge case: None → пустой dict ---
        if new_blueprint is None:
            new_blueprint = {}

        # 1. Извлечь список новых процессов (graceful при отсутствии ключа)
        new_processes_list: list[dict[str, Any]] = new_blueprint.get("processes") or []

        # Индексируем новые процессы по имени
        new_by_name: dict[str, dict[str, Any]] = {}
        for proc_cfg in new_processes_list:
            pname = proc_cfg.get("process_name") or proc_cfg.get("name", "")
            if pname:
                new_by_name[pname] = proc_cfg

        # 2. Protected-процессы
        protected = self._get_protected_names()

        # 3. Текущие незащищённые процессы (кандидаты на замену)
        to_replace: dict[str, dict[str, Any]] = {
            name: cfg for name, cfg in self._process_configs.items() if name not in protected
        }

        # 4. Snapshot
        old_configs = copy.deepcopy(to_replace)

        skipped_protected = sorted(name for name in self._process_configs if name in protected)
        replaced_names: list[str] = []

        self._log_info(
            f"replace_blueprint: начало замены. "
            f"to_replace={list(to_replace.keys())}, "
            f"protected={skipped_protected}, "
            f"new_processes={list(new_by_name.keys())}"
        )

        # 5. Pause ProcessMonitor (безопасно при повторном вызове)
        monitor_was_running = getattr(self._process_monitor, "_monitoring", False)
        if monitor_was_running:
            try:
                self._process_monitor.stop()
            except Exception as exc:
                self._log_warning(f"replace_blueprint: ошибка остановки ProcessMonitor: {exc}")

        stop_timeout = float(self.get_config("stop_process_timeout") or 5.0)

        # 6. Остановить и cleanup каждого незащищённого процесса
        for proc_name in list(to_replace.keys()):
            ok = self._stop_and_cleanup_process(proc_name, stop_timeout)
            if ok:
                replaced_names.append(proc_name)
                # Удалить конфиг (будет обновлён из нового blueprint)
                self._process_configs.pop(proc_name, None)
            else:
                # Partial failure — rollback
                self._log_error(f"replace_blueprint: не удалось остановить '{proc_name}', rollback")
                self._restore_from_snapshot(old_configs)
                self._resume_monitor(monitor_was_running)
                return {
                    "success": False,
                    "replaced": replaced_names,
                    "skipped_protected": skipped_protected,
                    "error": f"Не удалось остановить процесс '{proc_name}'",
                    "rolled_back": True,
                }

        # 7. Зарегистрировать и запустить новые процессы (не-protected)
        started_names: list[str] = []
        for pname, pcfg in new_by_name.items():
            if pname in protected:
                continue
            try:
                # Зарегистрировать в shared_resources
                if self.shared_resources:
                    self.shared_resources.register_process(pname, pcfg)

                class_path = pcfg.get("class", "")
                priority = pcfg.get("priority", "normal")
                process = self._process_registry.create_and_register(pname, class_path, pcfg, priority)
                if not process:
                    raise RuntimeError(f"create_and_register вернул None для '{pname}'")
                process.start()
                self._priority.apply_priority(process)
                self._priority.register_priority(pname, priority)

                # Обновить _process_configs
                self._process_configs[pname] = copy.deepcopy(pcfg)
                started_names.append(pname)
                self._log_info(f"replace_blueprint: процесс '{pname}' запущен")

            except Exception as exc:
                self._log_error(f"replace_blueprint: ошибка старта '{pname}': {exc}, rollback")
                # Откатить уже запущенные новые процессы
                for started in started_names:
                    try:
                        self._process_registry.stop_one(started, stop_timeout)
                        self._process_registry.remove_process(started)
                    except Exception as cleanup_exc:  # noqa: PERF203
                        self._log_warning(f"replace_blueprint: cleanup '{started}' при rollback: {cleanup_exc}")
                    self._process_configs.pop(started, None)

                self._restore_from_snapshot(old_configs)
                self._resume_monitor(monitor_was_running)
                return {
                    "success": False,
                    "replaced": replaced_names,
                    "skipped_protected": skipped_protected,
                    "error": f"Ошибка старта процесса '{pname}': {exc}",
                    "rolled_back": True,
                }

        # 8. Resume ProcessMonitor
        self._resume_monitor(monitor_was_running)

        self._log_info(
            f"replace_blueprint: завершено. "
            f"stopped={replaced_names}, started={started_names}, "
            f"protected={skipped_protected}"
        )

        return {
            "success": True,
            "replaced": replaced_names,
            "skipped_protected": skipped_protected,
            "error": None,
            "rolled_back": False,
        }

    def _resume_monitor(self, was_running: bool) -> None:
        """Безопасно возобновить ProcessMonitor если он был запущен."""
        if was_running:
            try:
                self._process_monitor.start()
            except Exception as exc:
                self._log_warning(f"replace_blueprint: ошибка возобновления ProcessMonitor: {exc}")

    def _cmd_blueprint_replace(self, data=None, **kwargs) -> dict:
        """Команда CommandManager: заменить blueprint (горячая замена процессов)."""
        args = _merge_cmd_args(data, kwargs)
        new_blueprint = args.get("blueprint")
        if new_blueprint is None and "blueprint" not in args:
            return {"error": "blueprint required"}
        return self.replace_blueprint(new_blueprint)

    # -------------------------------------------------------------------------
    # Router endpoint — приём команд от других процессов (AD-8)
    # -------------------------------------------------------------------------

    def _handle_process_command(self, msg: dict) -> None:
        """Обработчик Router-сообщений с command='process.command'.

        Извлекает вложенную команду из msg['data'], делегирует в CommandManager
        и отправляет ответ обратно через Router.

        Формат запроса::

            {
                "command": "process.command",
                "data": {
                    "cmd": "process.start",
                    "process_name": "camera_3",
                    "config": {...},            # опционально, для process.create
                    "correlation_id": "uuid"    # для сопоставления ответа
                }
            }

        Формат ответа::

            {
                "command": "process.command.response",
                "data": {
                    "correlation_id": "uuid",
                    "success": True/False,
                    "result": {...}
                }
            }
        """
        data = msg.get("data") or {}
        correlation_id = data.get("correlation_id") or str(uuid.uuid4())
        cmd = data.get("cmd", "")

        try:
            if not cmd:
                result = {"status": "error", "reason": "поле 'cmd' обязательно"}
                success = False
            elif not self.command_manager:
                result = {"status": "error", "reason": "command_manager недоступен"}
                success = False
            else:
                # Собираем внутреннее сообщение для CommandManager
                inner_msg: dict[str, Any] = {"command": cmd, "data": {}}
                # Пробрасываем все поля кроме служебных
                for key, value in data.items():
                    if key not in ("cmd", "correlation_id"):
                        inner_msg["data"][key] = value

                result = self.command_manager.handle_command(inner_msg)

                # Определяем success: если result — dict с "error" или status="error"
                if isinstance(result, dict):
                    success = "error" not in result and result.get("status") != "error"
                else:
                    success = True

        except Exception as exc:
            self._log_error(f"Router process.command ошибка при выполнении '{cmd}': {exc}")
            result = {"status": "error", "reason": str(exc)}
            success = False

        # Отправить ответ через Router (P0.5: адресуем отправителю — раньше
        # ответ шёл без targets и терялся). Адресат: data.reply_to или sender
        # входящего билета. request_id (top-level) + data.correlation_id —
        # чтобы резолвер инициатора (RouterManager._resolve_pending) совпал.
        reply_target = data.get("reply_to") or msg.get("sender")
        response = {
            "type": "response",
            "command": "process.command.response",
            "sender": self.name,
            "targets": [reply_target] if reply_target else [],
            "queue_type": "system",
            "request_id": correlation_id,
            "success": success,
            "result": result,
            "data": {
                "correlation_id": correlation_id,
                "success": success,
                "result": result,
            },
        }
        if self.router_manager and reply_target:
            try:
                self.router_manager.send(response)
            except Exception as send_exc:
                self._log_error(f"Не удалось отправить process.command.response: {send_exc}")
        elif not reply_target:
            self._log_debug(
                f"process.command.response не отправлен: во входящем билете нет sender "
                f"(cmd={cmd!r}, correlation_id={correlation_id})"
            )

    def _handle_critical_error(self, exc: Exception, context: str) -> None:
        """Логировать критическую ошибку через error_module и запустить shutdown."""
        error_manager = self._get_error_manager()
        if error_manager:
            error_manager.log_exception(
                exc,
                f"Critical error in ProcessManagerProcess.{context}",
                module="process_manager",
            )
        else:
            import traceback

            self._log_error(f"Critical error in {context}: {exc}")
            traceback.print_exc()
        self.shutdown()

    def _get_error_manager(self):
        """Получить ErrorManager из shared_resources если доступен."""
        if not self.shared_resources:
            return None
        try:
            process_data = self.shared_resources.get_process_data(self.name)
            if process_data and process_data.custom:
                return process_data.custom.get("error_manager")
        except Exception:  # nosec B110 — error_manager опционален, None безопасен
            pass
        return None

    def _create_processes_from_config(self, processes_config: dict[str, dict[str, Any]]) -> None:
        """Двухфазно: очереди для всех, затем create + start."""
        valid = [(n, c) for n, c in processes_config.items() if isinstance(c, dict) and c.get("class")]
        if not valid:
            return

        for name, proc_config in valid:
            self._process_configs[name] = copy.deepcopy(proc_config)
            if self.shared_resources:
                self.shared_resources.register_process(name, proc_config)

        for name, proc_config in valid:
            priority = proc_config.get("priority", "normal")
            if self._process_registry.create_and_register(name, proc_config["class"], proc_config, priority):
                self._priority.register_priority(name, priority)
                process = self._process_registry.get_process_by_name(name)
                if process:
                    process.start()
                    self._priority.apply_priority(process)

    def shutdown(self) -> bool:
        """
        Завершение с явным порядком:
            1. ProcessMonitor
            2. ProcessRegistry.stop_all (дочерние процессы)
            3. ConsoleManager
            4. super().shutdown() (WorkerManager, RouterManager и т.д.)
        """
        # backend-control endpoint (PID-specific остановка, без глобального kill).
        # getattr: shutdown может вызываться на частично сконструированном PM (тесты/ошибки init).
        teardown_backend_ctl_channel(
            getattr(self, "_backend_ctl_channel", None),
            getattr(self, "router_manager", None),
        )
        self._backend_ctl_channel = None

        self._process_monitor.stop()
        shutdown_timeout = self.get_config("shutdown_timeout") or 5.0
        self._process_registry.stop_all(timeout=shutdown_timeout)
        if self._console_manager is not None:
            if hasattr(self._console_manager, "close_all"):
                self._console_manager.close_all()
            elif hasattr(self._console_manager, "shutdown"):
                self._console_manager.shutdown()
        return super().shutdown()

    def create_process(
        self,
        name: str,
        class_path: str,
        config: dict[str, Any] | None = None,
        priority: str = "normal",
    ):
        """Создать и зарегистрировать процесс."""
        merged = copy.deepcopy(config) if config else {}
        merged["class"] = class_path
        self._process_configs[name] = merged
        process = self._process_registry.create_and_register(name, class_path, config, priority)
        if process:
            self._priority.register_priority(name, priority)
        return process

    def start_process(self, process_name: str | None = None) -> bool:
        """Запустить процесс или все."""
        if process_name:
            process = self._process_registry.get_process_by_name(process_name)
            if not process:
                return False
            if process.is_alive():
                self._log_warning(f"Процесс '{process_name}' уже запущен")
                return True
            # Нельзя стартовать процесс повторно (multiprocessing ограничение)
            if process.pid is not None:
                self._log_warning(
                    f"Процесс '{process_name}' уже был запущен ранее (pid={process.pid}), "
                    f"для перезапуска используйте process.restart"
                )
                return False
            process.start()
            self._priority.apply_priority(process)
            return True
        self._process_registry.start_all()
        for process in self._process_registry.os_processes:
            self._priority.apply_priority(process)
        return True

    def stop_process(self, process_name: str | None = None) -> bool:
        """
        Остановить один процесс (per-process stop_event) или все.
        """
        if process_name:
            process = self._process_registry.get_process_by_name(process_name)
            if not process:
                return True
            if not process.is_alive():
                return True
            stop_timeout = float(self.get_config("stop_process_timeout") or 5.0)
            return self._process_registry.stop_one(process_name, stop_timeout)
        shutdown_timeout = float(self.get_config("shutdown_timeout") or 5.0)
        self._process_registry.stop_all(timeout=shutdown_timeout)
        return True

    def restart_process(self, process_name: str) -> bool:
        """Перезапустить процесс: stop → снять с реестра → create → start."""
        config = self._process_configs.get(process_name)
        if not config:
            self._log_error(f"No saved config for '{process_name}'")
            return False
        if not self.stop_process(process_name):
            return False
        self._process_registry.remove_process(process_name)
        if self.shared_resources:
            self.shared_resources.register_process(process_name, config)
        priority = config.get("priority", "normal")
        process = self._process_registry.create_and_register(process_name, config["class"], config, priority)
        if not process:
            self._log_error(f"Failed to recreate process '{process_name}'")
            return False
        process.start()
        self._priority.register_priority(process_name, priority)
        self._priority.apply_priority(process)
        self._log_info(f"Process '{process_name}' restarted")
        return True

    def _send_worker_command(self, process_name: str, command: str) -> bool:
        """Отправить worker-команду процессу (pause/resume/etc).

        Проверяет что процесс существует и жив, отправляет IPC-команду.
        """
        process = self._process_registry.get_process_by_name(process_name)
        if not process:
            self._log_warning(f"{command}: процесс '{process_name}' не найден")
            return False
        if not process.is_alive():
            self._log_warning(f"{command}: процесс '{process_name}' не жив")
            return False
        cmd = {"type": "system", "command": command, "sender": self.name}
        try:
            self.send_message(process_name, cmd)
            self._log_info(f"Команда {command} отправлена процессу '{process_name}'")
            return True
        except Exception as exc:
            self._log_error(f"Не удалось отправить {command} процессу '{process_name}': {exc}")
            return False

    def pause_process(self, process_name: str) -> bool:
        """Поставить процесс на паузу через IPC-команду worker.pause_all."""
        return self._send_worker_command(process_name, "worker.pause_all")

    def resume_process(self, process_name: str) -> bool:
        """Возобновить процесс через IPC-команду worker.resume_all."""
        return self._send_worker_command(process_name, "worker.resume_all")

    def get_process_status(self, process_name: str | None = None) -> dict[str, Any]:
        """Статус процесса или всех."""
        if process_name:
            process = self._process_registry.get_process_by_name(process_name)
            if not process:
                return {}
            status = self._status.get_status_for_process(process)
            if self.shared_resources:
                process_data = self.shared_resources.get_process_data(process_name)
                if process_data:
                    status["state"] = process_data.to_dict() if hasattr(process_data, "to_dict") else {}
            return status
        return self._status.get_all_status()

    def get_all_processes_status(self) -> dict[str, dict[str, Any]]:
        """Статусы всех процессов."""
        return self._status.get_all_status()
