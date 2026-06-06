"""
ProcessManagerProcess — процесс-оркестратор (Refactored).

Наследуется от ProcessModule. Использует композицию:
    ProcessRegistry + ProcessPriority + ProcessStatusMonitor + ProcessMonitor.

Порядок shutdown:
    ProcessMonitor → ProcessRegistry.stop_all → WorkerManager → ConsoleManager → super
"""

import copy
import time
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
        # Дебаунс hot-swap: in-flight guard + cooldown (см. replace_blueprint).
        self._replace_in_progress: bool = False
        self._last_replace_ts: float = 0.0
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
        # ОБЩИЙ system-wide stop: PM наблюдает его в lifecycle (run_process_function)
        # и пробрасывает детям через ProcessRegistry — любой процесс взвёл → все гаснут.
        # Берём из shared_resources (НЕ из custom: custom рассылается монитором через
        # Queue, а сырой mp.Event на Windows-spawn пиклится только через inheritance).
        self._system_stop_event = self.shared_resources.get_system_stop_event() if self.shared_resources else None

        queue_registry = self._resolve_queue_registry()

        platform_adapter = get_platform_adapter()

        self._process_registry = ProcessRegistry(
            logger=self,
            queue_registry=queue_registry,
            config_manager=None,
            shared_resources=self.shared_resources,
            system_stop_event=self._system_stop_event,
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

            # Router endpoint: другие процессы могут слать команды через Router (AD-8).
            # P4.4.1 (B2): process.command — обычная команда CommandManager (kind-router
            # по type=command зовёт CM). manages_own_reply=True: handler строит свой
            # process.command.response сам → транспортный авто-reply пропускается.
            if self.command_manager:
                self.command_manager.register_command(
                    "process.command",
                    self._handle_process_command,
                    expects_full_message=True,
                    metadata={"description": "Router endpoint: вложенная команда PM", "manages_own_reply": True},
                    tags=["system"],
                )
            elif self.router_manager:  # fallback (нет CommandManager) — прежний прямой путь
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

    def _cleanup_process_resources(self, name: str) -> None:
        """Снять остановленный процесс с реестра и освободить его SHM.

        Cleanup-фаза hot-swap (стоп-фаза вынесена в ``ProcessRegistry.stop_many`` —
        параллельная остановка всех процессов разом). Не бросает исключений.

        Args:
            name: имя уже остановленного процесса.
        """
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

    def _build_proc_dicts(self, new_blueprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Трансформировать raw-blueprint в proc_dict'ы ТЕМ ЖЕ путём, что boot.

        Корень бага «переключает, но картинка не меняется»: raw recipe-process
        (``process_name``/``process_class``/``chain_targets``/``plugins`` на ВЕРХНЕМ
        уровне) передавался в ``create_and_register`` как есть, а процесс ждёт
        ВЛОЖЕННЫЙ ключ ``config`` (``plugins``/``chain_targets``/``queues``). Без
        трансформации горячо поднятые процессы стартуют ПУСТЫМИ (PluginOrchestrator
        не создаётся, chain_targets=[], нет очереди data) → данные не текут в GUI.

        Повторяет boot (``SystemLauncher.build``, launch.py:243-276):
        ``SystemBlueprint.model_validate → build_configs() → process(cfg)`` → proc_dict
        с вложенным ``config``. Лишние поля blueprint (``displays``/``wires``)
        игнорируются (SchemaBase ``extra='ignore'``). Registry-независимо: рецепты
        используют полные ``plugin_class`` пути (резолв через import, не PluginRegistry,
        который в orchestrator-процессе не наполнен).

        Lazy-импорт фреймворк-сиблингов — избегаем цикла на загрузке модуля.

        Args:
            new_blueprint: raw dict рецепта (секция ``blueprint``).

        Returns:
            ``{process_name: proc_dict}`` в каноническом формате (как boot).

        Raises:
            Exception: при невалидном blueprint (ловится в replace_blueprint → ошибка).
        """
        from multiprocess_framework.modules.process_module.generic.blueprint import (
            SystemBlueprint,
        )
        from multiprocess_framework.modules.data_schema_module import process

        topology = SystemBlueprint.model_validate(new_blueprint or {})
        result: dict[str, dict[str, Any]] = {}
        for cfg in topology.build_configs():
            name, proc_dict = process(cfg)
            result[name] = proc_dict
        return result

    def replace_blueprint(self, new_blueprint: dict[str, Any] | None) -> dict[str, Any]:
        """Дебаунс-обёртка над заменой blueprint — единая точка коалесинга hot-swap.

        3 GUI-точки входа (Recipes «Загрузить», Pipeline «Запустить»/«Перезапустить»)
        сходятся сюда через IPC ``blueprint.replace``. Чтобы повторные/наложенные клики
        не «тасовали» процессы:
          - in-flight guard: пока замена идёт — новые запросы отклоняются;
          - cooldown ``replace_debounce_s`` (config, дефолт 0): запрос в пределах окна
            ПОСЛЕ ЗАВЕРШЕНИЯ предыдущей замены отклоняется. Меряется от завершения:
            IPC-сообщения читаются последовательно уже после долгой (секунды) замены,
            поэтому двойной клик приходит на обработку именно по её завершении.

        Тесты не задают ``replace_debounce_s`` → 0 → дебаунс выключен (паритет поведения).
        """
        # getattr-дефолты: make_pm в тестах обходит __init__ (атрибутов может не быть).
        if getattr(self, "_replace_in_progress", False):
            self._log_warning("replace_blueprint: замена уже выполняется — запрос пропущен (debounce)")
            return {
                "success": False,
                "replaced": [],
                "skipped_protected": [],
                "error": "замена уже выполняется",
                "rolled_back": False,
                "debounced": True,
            }
        cooldown = float(self.get_config("replace_debounce_s") or 0.0)
        if cooldown > 0.0 and (time.monotonic() - getattr(self, "_last_replace_ts", 0.0)) < cooldown:
            self._log_info("replace_blueprint: запрос в пределах cooldown — пропущен (debounce)")
            return {
                "success": False,
                "replaced": [],
                "skipped_protected": [],
                "error": "debounce cooldown",
                "rolled_back": False,
                "debounced": True,
            }
        self._replace_in_progress = True
        try:
            return self._replace_blueprint_impl(new_blueprint)
        finally:
            self._replace_in_progress = False
            self._last_replace_ts = time.monotonic()

    def _replace_blueprint_impl(self, new_blueprint: dict[str, Any] | None) -> dict[str, Any]:
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

        # 4.5 Трансформировать raw-blueprint → proc_dict'ы (как boot) ДО остановки:
        #     невалидный blueprint должен упасть БЕЗ teardown работающей системы.
        try:
            built_proc_dicts = self._build_proc_dicts(new_blueprint)
        except Exception as exc:  # noqa: BLE001
            self._log_error(f"replace_blueprint: невалидный blueprint, замена отменена: {exc}")
            self._resume_monitor(monitor_was_running=False)  # монитор ещё не паузили
            return {
                "success": False,
                "replaced": [],
                "skipped_protected": skipped_protected,
                "error": f"Невалидный blueprint: {exc}",
                "rolled_back": False,
            }

        # 5. Pause ProcessMonitor (безопасно при повторном вызове)
        monitor_was_running = getattr(self._process_monitor, "_monitoring", False)
        if monitor_was_running:
            try:
                self._process_monitor.stop()
            except Exception as exc:
                self._log_warning(f"replace_blueprint: ошибка остановки ProcessMonitor: {exc}")

        stop_timeout = float(self.get_config("stop_process_timeout") or 5.0)

        # 6. Остановить ВСЕ незащищённые процессы ПАРАЛЛЕЛЬНО (один общий дедлайн,
        #    ~stop_timeout суммарно вместо N×stop_timeout), затем cleanup каждого.
        stop_results = self._process_registry.stop_many(list(to_replace.keys()), stop_timeout)
        for proc_name in list(to_replace.keys()):
            if not stop_results.get(proc_name, False):
                # Процесс не остановлен (не найден в реестре) — rollback
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
            self._cleanup_process_resources(proc_name)
            replaced_names.append(proc_name)
            # Удалить конфиг (будет обновлён из нового blueprint)
            self._process_configs.pop(proc_name, None)

        # 7. Зарегистрировать и запустить новые процессы (не-protected) ДВУХФАЗНО — как boot
        #    (_create_processes_from_config): СНАЧАЛА очереди ВСЕХ процессов, ПОТОМ create+start.
        #    Иначе процесс, стартующий раньше (напр. camera_0 в color_inspect — первый в рецепте),
        #    получает spawn-bundle (snapshot shared_resources) ДО регистрации очередей более
        #    позднего consumer'а (detector) → шлёт кадры в «пустоту», данные не доходят (P0
        #    hot-swap blocker: на boot двухфазно — работает, в ad-hoc replace было однофазно).
        #    Используем proc_dict'ы из _build_proc_dicts (канонический формат с вложенным config).

        # Фаза 1: register_process (очереди) ВСЕХ новых non-protected процессов ДО любого старта.
        to_start: list[tuple[str, dict[str, Any], str]] = []  # (name, proc_dict, priority)
        for pname, proc_dict in built_proc_dicts.items():
            if pname in protected:
                continue
            # build() уже выставил внутренний ключ class из process_class.
            class_path = str(proc_dict.get("class", ""))
            if not class_path:
                self._log_error(f"replace_blueprint: process_class отсутствует для '{pname}', rollback")
                self._restore_from_snapshot(old_configs)
                self._resume_monitor(monitor_was_running)
                return {
                    "success": False,
                    "replaced": replaced_names,
                    "skipped_protected": skipped_protected,
                    "error": f"process_class отсутствует в blueprint для '{pname}'",
                    "rolled_back": True,
                }
            priority = str(proc_dict.get("priority", "normal"))
            # Зарегистрировать в shared_resources КАНОНИЧЕСКИЙ proc_dict (создаёт очереди).
            if self.shared_resources:
                self.shared_resources.register_process(pname, proc_dict)
            to_start.append((pname, proc_dict, priority))

        # Фаза 2: create_and_register + start (очереди всех новых процессов уже зарегистрированы,
        #    поэтому каждый spawn-bundle видит очереди всех остальных → доставка кадров не рвётся).
        started_names: list[str] = []
        for pname, proc_dict, priority in to_start:
            try:
                class_path = str(proc_dict.get("class", ""))
                process = self._process_registry.create_and_register(pname, class_path, proc_dict, priority)
                if not process:
                    raise RuntimeError(f"create_and_register вернул None для '{pname}'")
                process.start()
                self._priority.apply_priority(process)
                self._priority.register_priority(pname, priority)

                # _process_configs хранит канонический proc_dict (с class + config) —
                # downstream (restart_process, snapshot-rollback, broadcast_full_status,
                # _get_protected_names) читает class/protected консистентно.
                self._process_configs[pname] = copy.deepcopy(proc_dict)
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

        Формат ответа (дженерик ``reply_to_request``, ADR-COMM-005)::

            {
                "type": "response",
                "command": "process.command.response",
                "request_id": "<correlation>",   # top-level (driver/инициатор)
                "success": True/False,
                "result": {...}                  # результат вложенной команды
            }
        """
        data = msg.get("data") or {}
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

                # Определяем success. Приоритет — явному self-report команды
                # (``result["success"]``): PM-методы (``replace_blueprint``,
                # lifecycle) кладут ``"error": None`` даже на успехе, из-за чего
                # эвристика ``"error" not in result`` ложно дала бы success=False
                # (успешная горячая замена транслировалась бы как ошибка —
                # ломает command-result-bridge «GUI узнаёт результат»). Эвристика
                # остаётся фолбэком для результатов без явного ``"success"``.
                if isinstance(result, dict):
                    if "success" in result:
                        success = bool(result["success"])
                    else:
                        success = "error" not in result and result.get("status") != "error"
                else:
                    success = True

        except Exception as exc:
            self._log_error(f"Router process.command ошибка при выполнении '{cmd}': {exc}")
            result = {"status": "error", "reason": str(exc)}
            success = False

        # Ответ инициатору через дженерик reply_to_request (absorb bespoke-reply,
        # comm-system §9.4 / ADR-COMM-005). Корреляция — _extract_correlation_id:
        # top-level request_id (driver) → data.correlation_id (legacy-обёртка). No-op
        # без correlation (GUI fire-and-forget, паритет). Адресат — data.reply_to /
        # reply_to / sender. manages_own_reply=True у регистрации команды → kind-router
        # НЕ авто-reply'ит (иначе двойной ответ).
        if self.router_manager:
            try:
                self.router_manager.reply_to_request(
                    msg, result, success=success, response_command="process.command.response"
                )
            except Exception as send_exc:
                self._log_error(f"Не удалось отправить process.command.response: {send_exc}")

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
