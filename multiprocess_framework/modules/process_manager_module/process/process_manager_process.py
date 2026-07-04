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
        # Дебаунс hot-swap: in-flight guard + cooldown (см. apply_topology).
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
        """Создать TopologyManager с 5 сидами + observability-менеджерами.

        Вызывается в initialize() ПОСЛЕ super().initialize() — менеджеры
        logger_manager / error_manager / stats_manager уже готовы (шаг 3
        ProcessModule._init_managers).

        Сиды (single-purpose, Task 2.0):
            _topology_stop      — halt
            _topology_cleanup   — free (registry + SHM + config)
            _topology_provision — очереди + SHM
            _topology_create    — instantiate (без start)
            _topology_start     — run

        """
        self._topology_manager = TopologyManager(
            create_process_fn=self._topology_create,
            stop_process_fn=self._topology_stop,
            stop_all_process_fn=self._topology_stop_all,
            cleanup_process_fn=self._topology_cleanup,
            provision_process_fn=self._topology_provision,
            start_process_fn=self._topology_start,
            logger=getattr(self, "logger_manager", None),
            error=getattr(self, "error_manager", None),
            stats=getattr(self, "stats_manager", None),
        )
        self._topology_manager.initialize()

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
            "process.relay": (
                self._cmd_process_relay,
                "Relay: доставить команду в целевой процесс через свежий PSR PM",
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
        """Применить новую топологию процессов.

        Маршрутизирует в ``apply_topology`` (не напрямую в менеджер) —
        чтобы транзакция, snapshot, rollback и debounce не обходились.
        """
        args = _merge_cmd_args(data, kwargs)
        td = args.get("topology_dict")
        if td is None:
            return {"error": "topology_dict required"}
        return self.apply_topology(td)

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
    # Protected / cleanup / rollback / snapshot — общие хелперы topology
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
        """Снять остановленный процесс с реестров и освободить его ресурсы.

        Три явных шага:
        1. ProcessRegistry — Process-объект + stop_event.
        2. ``SharedResourcesManager.unregister_process`` — SHM + запись PSR
           (очереди/события/метаданные) + конфиг ConfigStore. Единая точка
           снятия, симметрия к ``register_process`` (ADR-SRM-009) — раньше
           PSR чистился побочным эффектом release_process_memory.
        3. Хвосты монитора (heartbeat-таймер, счётчик рестартов, статусы) —
           иначе новый процесс с тем же именем наследует чужую историю.

        Используется сидом ``_topology_cleanup`` и ``_rollback_to_snapshot``.
        Не бросает исключений.

        Args:
            name: имя уже остановленного процесса.
        """
        try:
            self._process_registry.remove_process(name)
        except Exception as exc:
            self._log_warning(f"cleanup_process_resources: ошибка удаления '{name}' из реестра: {exc}")

        if self.shared_resources is not None:
            try:
                self.shared_resources.unregister_process(name)
            except Exception as exc:
                self._log_warning(f"cleanup_process_resources: SRM unregister '{name}' не удался: {exc}")

        monitor = getattr(self, "_process_monitor", None)
        forget_fn = getattr(monitor, "forget_process", None)
        if callable(forget_fn):
            try:
                forget_fn(name)
            except Exception as exc:
                self._log_warning(f"cleanup_process_resources: monitor.forget '{name}' не удался: {exc}")

    def _collect_partial_new(
        self,
        applied_results: list[dict] | None,
        desired_blueprint: dict | None,
        snapshot_names: set[str],
    ) -> set[str]:
        """Имена частично-созданных НОВЫХ процессов при провале apply.

        Стратегия:
        1. Из ``applied_results`` (если есть) — точный список имён, для
           которых успешно прошли provision/create/start.
        2. Fallback (``None`` — состояние исполнения неизвестно) — «новые
           non-protected» из desired blueprint, пересечённые с тем, что уже
           попало в ``_process_configs`` / registry.

        Args:
            applied_results: ``result["results"]`` из TopologyManager.apply
                (None при exception вне manager.apply).
            desired_blueprint: blueprint, переданный в apply_topology.
            snapshot_names: имена процессов, которые были ДО apply.
        """
        new_names: set[str] = set()
        protected = self._get_protected_names()

        if applied_results:
            # Точный путь: только то, что реально исполнялось
            for r in applied_results:
                cmd = r.get("cmd", "")
                name = r.get("process_name", "")
                if not name:
                    continue
                if cmd in ("process.provision", "process.create", "process.start"):
                    if name not in snapshot_names and name not in protected:
                        new_names.add(name)
        elif desired_blueprint:
            # Fallback: вычислить «новые» из desired blueprint
            try:
                from multiprocess_framework.modules.process_module.generic.blueprint import (
                    SystemBlueprint,
                )
                from multiprocess_framework.modules.data_schema_module import process

                topology = SystemBlueprint.model_validate(desired_blueprint or {})
                for cfg in topology.build_configs():
                    name, _ = process(cfg)
                    if name not in snapshot_names and name not in protected:
                        # Только если уже появился в _process_configs или registry
                        if name in self._process_configs or self._process_registry.get_process_by_name(name):
                            new_names.add(name)
            except Exception as exc:
                self._log_error(f"rollback: fallback-парсинг blueprint не удался: {exc}")

        return new_names

    def _rollback_to_snapshot(
        self,
        snapshot: dict[str, dict],
        applied_results: list[dict] | None,
        desired_blueprint: dict | None,
    ) -> None:
        """Откатить провал apply к snapshot-топологии ТЕМ ЖЕ 5-фазным порядком
        side-effect'ов, что и прямое применение: stop_all → cleanup →
        provision (все) → create (все) → start (все).

        Замена прежней паре ``_teardown_partial`` + ``_restore_from_snapshot``,
        у которой было два дефекта:
        1. Восстановление НЕ проверяло, живы ли процессы. При провале ДО
           stop-фазы (например BlueprintInvalid в валидации планировщика)
           поверх работающих процессов стартовали вторые копии, а
           ``remove_process`` выбрасывал stop_event живого оригинала —
           дубли + неуправляемые зомби до конца сессии.
        2. Восстановление шло register→create→start ПО ОДНОМУ процессу:
           routing_map первых восстановленных не содержал очередей
           последующих — старая топология возвращалась полусвязанной.

        Каждая фаза best-effort (rollback не прерывается), НО имя, чью
        остановку не удалось ПОДТВЕРДИТЬ (Task 1.1: результат stop_many —
        факт смерти), исключается из cleanup/пересоздания: дубль хуже
        отсутствия, а Process/stop_event/конфиг остаются в реестрах —
        следующий switch повторит попытку остановки.

        Args:
            snapshot: ``{name: proc_config}`` non-protected процессов до apply.
            applied_results: результаты исполненных команд (None — неизвестно).
            desired_blueprint: целевой blueprint провалившегося apply.
        """
        snapshot_names = set(snapshot.keys())
        partial_new = self._collect_partial_new(applied_results, desired_blueprint, snapshot_names)
        to_stop = sorted(snapshot_names | partial_new)
        self._log_info(
            f"rollback: восстановление {sorted(snapshot_names)} "
            f"(снос частично-созданных: {sorted(partial_new) or 'нет'})"
        )

        # --- Фаза A: bulk-остановка всего, что могло остаться живым ---
        # Семантика ensure stopped (Task 1.1): «нет в реестре / не жив» — успех.
        stop_results: dict[str, bool] = {}
        if to_stop:
            timeout = float(self.get_config("stop_process_timeout") or 5.0)
            try:
                stop_results = self._process_registry.stop_many(list(to_stop), timeout)
            except Exception as exc:
                self._log_error(f"rollback: stop_many не удался: {exc}")
        unstoppable = {n for n in to_stop if not stop_results.get(n, False)}
        if unstoppable:
            self._log_error(
                f"rollback: остановка НЕ подтверждена для {sorted(unstoppable)} — "
                f"имена исключены из пересоздания (защита от дублей), retry на следующем switch"
            )

        # --- Фаза B: cleanup (реестр + SHM + PSR + конфиг) ---
        for name in to_stop:
            if name in unstoppable:
                continue
            try:
                self._topology_cleanup(name)
            except Exception as exc:
                self._log_error(f"rollback: cleanup '{name}' не удался: {exc}")

        # --- Фазы C/D/E: provision → create → start (двухфазно, как boot) ---
        restore = {n: cfg for n, cfg in snapshot.items() if n not in unstoppable}
        for name, cfg in restore.items():
            try:
                self._topology_provision(name, cfg)
            except Exception as exc:
                self._log_error(f"rollback: provision '{name}' не удался: {exc}")

        created: list[str] = []
        for name, cfg in restore.items():
            try:
                if self._topology_create(name, cfg):
                    created.append(name)
                else:
                    self._log_error(f"rollback: create '{name}' не удался")
            except Exception as exc:
                self._log_error(f"rollback: create '{name}' не удался: {exc}")

        for name in created:
            try:
                if self._topology_start(name):
                    self._log_info(f"rollback: процесс '{name}' восстановлен")
                else:
                    self._log_error(f"rollback: start '{name}' не удался")
            except Exception as exc:
                self._log_error(f"rollback: start '{name}' не удался: {exc}")

    def _resume_monitor(self, was_running: bool) -> None:
        """Безопасно возобновить ProcessMonitor если он был запущен."""
        if was_running:
            try:
                self._process_monitor.start()
            except Exception as exc:
                self._log_warning(f"apply_topology: ошибка возобновления ProcessMonitor: {exc}")

    # -------------------------------------------------------------------------
    # Router endpoint — приём команд от других процессов (AD-8)
    # -------------------------------------------------------------------------

    def _cmd_process_relay(self, data=None, **kwargs) -> dict:
        """Relay команды в целевой процесс через АКТУАЛЬНЫЙ PSR PM.

        Зачем: GUI (protected) НЕ пересоздаётся при hot-swap рецепта и держит
        стейл-копию маршрутов (своя pickle-копия PSR с очередями убитых процессов).
        Прямой GUI→процесс ``send_command`` после switch кладёт билет в мёртвую
        очередь → ``put_nowait`` возвращает True → ТИХАЯ потеря. PM провижинит
        процессы и держит СВЕЖИЕ очереди, поэтому доставка идёт через него:
        ``GUI → process.relay → PM.send_message(target, inner)`` (тот же путь
        доставки, что и у прямой отправки, но на актуальном реестре).

        Контракт ``data``::

            {"target_process": "vision", "inner_message": {<полный билет>}}

        ``inner_message`` доставляется приёмнику «как есть» — контракт до плагина
        (CommandManager target → handler) не меняется. Результат возвращается
        штатным ``reply_to_request`` (process.command.response, ADR-COMM-005):
        потеря/ошибка ВИДИМА инициатору, а не тихий дроп.
        """
        if isinstance(data, dict):
            kwargs.update(data)
        target = kwargs.get("target_process") or ""
        inner = kwargs.get("inner_message")
        if not target or not isinstance(inner, dict):
            return {"success": False, "error": "process.relay: нужны target_process и inner_message (dict)"}

        # Существование цели по СВЕЖЕМУ реестру PM — видимая ошибка вместо тихого дропа.
        pd = self.shared_resources.get_process_data(target) if self.shared_resources else None
        if pd is None:
            return {"success": False, "error": f"process.relay: процесс '{target}' не зарегистрирован в PM"}

        try:
            # send_message PM → ProcessCommunication → RouterManager → queue_registry
            # на АКТУАЛЬНОМ PSR PM (qtype выбирает роутер, как при обычной доставке).
            self.send_message(target, inner)
        except Exception as exc:  # noqa: BLE001 — вернуть видимую ошибку инициатору
            self._log_error(f"process.relay в '{target}' не удался: {exc}")
            return {"success": False, "error": str(exc)}
        return {"success": True, "target_process": target}

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
        """Двухфазно: очереди для всех, затем create + start.

        Провал create → конфиг и provisioned-ресурсы (очереди/PSR) процесса
        откатываются: «призрак» (конфиг без Process-объекта) не должен
        попадать в ``_topology_current_names``/stop-фазу, а его очереди —
        в routing_map остальных детей.
        """
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
            else:
                self._log_error(f"boot: создание '{name}' не удалось — конфиг и ресурсы откатываются (не призрак)")
                self._cleanup_process_resources(name)
                self._process_configs.pop(name, None)

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
        """Создать и зарегистрировать процесс.

        Конфиг пишется в ``_process_configs`` ТОЛЬКО после успешного
        создания — иначе остаётся «призрак» (конфиг без Process-объекта),
        который попадает в ``_topology_current_names`` и в stop-фазу switch.
        """
        process = self._process_registry.create_and_register(name, class_path, config, priority)
        if process:
            merged = copy.deepcopy(config) if config else {}
            merged["class"] = class_path
            self._process_configs[name] = merged
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

    # -------------------------------------------------------------------------
    # Snapshot / current — хелперы для apply_topology и планировщика
    # -------------------------------------------------------------------------

    def _snapshot_processes(self) -> dict[str, dict]:
        """Вернуть deep-copy конфигов non-protected процессов (для rollback).

        Вынос инлайн-паттерна из ``replace_blueprint`` (``old_configs =
        copy.deepcopy(to_replace)``). Protected исключаются — их не нужно
        откатывать (они не трогаются при замене).
        """
        protected = self._get_protected_names()
        return copy.deepcopy({name: cfg for name, cfg in self._process_configs.items() if name not in protected})

    def _topology_current_names(self) -> set[str]:
        """Живые non-protected имена процессов (current_provider для планировщика).

        Источник истины «что снести» при switch: PM._process_configs
        минус protected. Нельзя брать из
        TopologyManager._current_topology — на первом switch она None
        (boot шёл дорогой A).
        """
        return set(self._process_configs) - self._get_protected_names()

    # -------------------------------------------------------------------------
    # apply_topology — транзакционная обёртка (Task 2.2)
    # -------------------------------------------------------------------------

    def apply_topology(self, blueprint: dict | None) -> dict:
        """Транзакционно применить топологию: snapshot → pause → apply → rollback-on-fail → resume.

        **Единственный владелец побочных эффектов** замены процессов.
        ``_cmd_topology_apply`` маршрутизирует сюда, а не напрямую
        в ``TopologyManager.apply`` — чтобы debounce, snapshot и rollback
        не обходились.

        Debounce (in-flight guard + cooldown) — единственная точка коалесинга.
        GUI вызывает через ``topology.apply`` (IPC) → ``_cmd_topology_apply`` → сюда.

        Args:
            blueprint: dict-представление топологии (или None → пустая).

        Returns:
            dict с ключами ``success``, ``rolled_back``, ``debounced``, ``error``
            и полями результата ``TopologyManager.apply``.
        """
        # --- Debounce: in-flight guard ---
        if getattr(self, "_replace_in_progress", False):
            self._log_warning("apply_topology: замена уже выполняется — запрос пропущен (debounce)")
            return {
                "success": False,
                "debounced": True,
                "error": "замена уже выполняется",
                "rolled_back": False,
            }

        # --- Debounce: cooldown ---
        cooldown = float(self.get_config("replace_debounce_s") or 0.0)
        if cooldown > 0.0 and (time.monotonic() - getattr(self, "_last_replace_ts", 0.0)) < cooldown:
            self._log_info("apply_topology: запрос в пределах cooldown — пропущен (debounce)")
            return {
                "success": False,
                "debounced": True,
                "error": "debounce cooldown",
                "rolled_back": False,
            }

        # --- Проверка конфигурации ---
        if self._topology_manager is None:
            return {"success": False, "error": "TopologyManager not initialized"}
        if self._topology_manager._commands_fn is None:
            return {"success": False, "error": "topology not configured (no commands_fn)"}

        self._replace_in_progress = True
        try:
            # Snapshot (non-protected) для rollback
            snapshot = self._snapshot_processes()

            # Pause monitor
            monitor_was_running = getattr(self._process_monitor, "_monitoring", False)
            if monitor_was_running:
                try:
                    self._process_monitor.stop()
                except Exception as exc:
                    self._log_warning(f"apply_topology: ошибка остановки ProcessMonitor: {exc}")

            try:
                result = self._topology_manager.apply(blueprint or {})

                if not result.get("success"):
                    executed = result.get("results") or []
                    if executed:
                        # Часть команд исполнилась — откат тем же 5-фазным
                        # конвейером (stop живых → cleanup → provision →
                        # create → start, см. _rollback_to_snapshot)
                        self._rollback_to_snapshot(snapshot, executed, blueprint)
                    else:
                        # Провал ДО исполнения команд (валидация blueprint,
                        # BlueprintInvalid и т.п.) — топология НЕ тронута,
                        # старые процессы работают: откат не требуется.
                        # Прежний код здесь пересоздавал ЖИВЫЕ процессы
                        # поверх самих себя (дубли + зомби).
                        self._log_info(
                            "apply_topology: провал до исполнения команд — "
                            "топология не тронута, откат не требуется"
                        )
                    return {
                        "success": False,
                        "rolled_back": True,
                        **{k: v for k, v in result.items() if k != "success"},
                    }

                # Успех: readiness-барьер (Task 2.2) + ответ, совместимый с GUI
                ready = self._wait_started_ready(result.get("results") or [])
                response = {
                    "success": True,
                    "rolled_back": False,
                    "ready": ready,
                    **{k: v for k, v in result.items() if k != "success"},
                }
                not_ready = sorted(n for n, ok in ready.items() if not ok)
                if not_ready:
                    self._log_error(
                        f"apply_topology: процессы умерли на старте (initialize-провал?): {not_ready} "
                        f"— топология применена, но эти процессы НЕ работают"
                    )
                return response

            except Exception as exc:
                self._log_error(f"apply_topology: exception в manager.apply: {exc}")
                # Состояние исполнения неизвестно (exception вне manager.apply,
                # который свои ошибки ловит сам) — консервативный полный откат:
                # stop живых → cleanup → пересоздание snapshot двухфазно.
                self._rollback_to_snapshot(snapshot, None, blueprint)
                if hasattr(self, "error_manager") and self.error_manager:
                    try:
                        self.error_manager.track_error(exc, {"phase": "apply_topology"})
                    except Exception:
                        pass
                return {
                    "success": False,
                    "rolled_back": True,
                    "error": str(exc),
                }

            finally:
                self._resume_monitor(monitor_was_running)

        finally:
            self._replace_in_progress = False
            self._last_replace_ts = time.monotonic()

    def _wait_started_ready(self, applied_results: list[dict]) -> dict[str, bool]:
        """Readiness-барьер после start-фазы: death-watch запущенных процессов.

        Ребёнок, упавший в ``initialize()``, выходит с exitcode 0 — до этого
        барьера switch выглядел успешным, хотя процесс мёртв (типовой случай:
        камера ещё занята предыдущим владельцем). Барьер ждёт
        ``start_ready_timeout_s`` (конфиг, дефолт 2.0; 0 → выключен) и следит
        за ``is_alive`` каждого запущенного имени.

        Семантика результата:
        - ``False`` — процесс ПОДТВЕРЖДЁННО умер в окне барьера;
        - ``True`` — жив на дедлайне (готовность в строгом смысле не
          подтверждается: heartbeat здесь ждать НЕЛЬЗЯ — и heartbeat, и
          ``topology.apply`` обрабатываются ОДНИМ message_processor-потоком,
          ожидание заблокировало бы само себя. Медленный initialize-провал
          (тяжёлые импорты) поймает ProcessMonitor как crashed после resume).

        Args:
            applied_results: ``result["results"]`` успешного TopologyManager.apply.

        Returns:
            ``{name: bool}`` по именам команд ``process.start`` (пустой dict —
            барьер выключен или нечего проверять).
        """
        started = [
            r.get("process_name", "")
            for r in applied_results
            if r.get("cmd") == "process.start" and r.get("success") and r.get("process_name")
        ]
        if not started:
            return {}
        # НЕ «or 2.0»: явный 0 в конфиге = барьер выключен, or съел бы его
        raw_timeout = self.get_config("start_ready_timeout_s")
        timeout_s = 2.0 if raw_timeout is None else float(raw_timeout)
        if timeout_s <= 0:
            return {}

        ready: dict[str, bool] = {}
        pending = set(started)
        deadline = time.monotonic() + timeout_s
        while pending and time.monotonic() < deadline:
            for name in list(pending):
                proc = self._process_registry.get_process_by_name(name)
                if proc is None or not proc.is_alive():
                    ready[name] = False
                    pending.discard(name)
            if pending:
                time.sleep(0.05)
        for name in pending:
            ready[name] = True  # жив весь барьер — работает
        return ready

    # -------------------------------------------------------------------------
    # Сиды TopologyManager — single-purpose методы (Task 2.0)
    #
    # Каждый метод мутирует РОВНО ОДНУ вещь. Wiring в _setup_topology_manager
    # делается в Task 2.2 — здесь только определения.
    # -------------------------------------------------------------------------

    def _topology_stop(self, name: str) -> bool:
        """Сид stop: остановить один процесс (halt).

        Делегирует в ``stop_process`` (per-process stop через stop_event).
        """
        return self.stop_process(name)

    def _topology_stop_all(self, names: list[str]) -> bool:
        """Сид stop_all: остановить несколько процессов ПАРАЛЛЕЛЬНО (bulk).

        Паритет дороги B: ``stop_many`` с одним общим таймаутом на все
        процессы, а не N×timeout последовательно. Без этого switch
        рецепта занимает N×5с (4 процесса → 20с вместо ~5с).

        Семантика «ensure stopped» (контракт stop_many): «нет в реестре /
        не был жив» — успех (идемпотентно); ``False`` только если процесс
        ПОДТВЕРЖДЁННО жив после эскалации stop_event → terminate → kill —
        тогда cleanup/provision небезопасны и switch обязан остановиться.
        """
        if not names:
            return True
        timeout = float(self.get_config("stop_process_timeout") or 5.0)
        results = self._process_registry.stop_many(list(names), timeout)
        failed = sorted(n for n in names if not results.get(n, False))
        if failed:
            self._log_error(f"topology stop_all: остановка НЕ подтверждена для {failed}; карта результатов: {results}")
            return False
        return True

    def _topology_cleanup(self, name: str) -> bool:
        """Сид cleanup: снять с реестра + освободить SHM + удалить конфиг.

        Единственная мутация: удаление процесса из реестра, освобождение
        его SHM-ресурсов и удаление записи из ``_process_configs``.
        """
        self._cleanup_process_resources(name)
        self._process_configs.pop(name, None)
        return True

    def _topology_provision(self, name: str, proc_dict: dict) -> bool:
        """Сид provision: зарегистрировать очереди + аллоцировать SHM.

        Двухфазная регистрация (урок Task 7 / 5cd23192): очереди ВСЕХ
        процессов регистрируются ДО старта любого из них. SHM аллоцируется
        здесь же, в фазе provision, а НЕ при create.

        НЕ стартует процесс, НЕ создаёт экземпляр.
        """
        # Очереди
        if self.shared_resources:
            self.shared_resources.register_process(name, proc_dict)

        # SHM (если секция memory задана)
        memory = proc_dict.get("memory")
        if memory and self.shared_resources:
            mm = getattr(self.shared_resources, "memory_manager", None)
            if mm and hasattr(mm, "create_memory_dict"):
                try:
                    mem_names = {k: v for k, v in memory.items() if k != "coll"}
                    coll = memory.get("coll", 2)
                    if mem_names:
                        mm.create_memory_dict(name, mem_names, coll)
                except Exception as exc:
                    self._log_warning(f"topology_provision: SHM-аллокация для '{name}' не удалась: {exc}")
        return True

    def _topology_create(self, name: str, proc_dict: dict) -> bool:
        """Сид create: создать экземпляр процесса БЕЗ старта.

        Регистрирует процесс в ``ProcessRegistry``, применяет приоритет,
        сохраняет конфиг в ``_process_configs``.

        НЕ стартует процесс (это ``_topology_start``).
        НЕ аллоцирует SHM (это ``_topology_provision``).
        """
        class_path = proc_dict.get("class", "")
        priority = proc_dict.get("priority", "normal")
        process = self._process_registry.create_and_register(name, class_path, proc_dict, priority)
        if not process:
            return False
        self._priority.apply_priority(process)
        self._priority.register_priority(name, priority)
        self._process_configs[name] = copy.deepcopy(proc_dict)
        return True

    def _topology_start(self, name: str) -> bool:
        """Сид start: запустить ранее созданный процесс.

        Делегирует в ``start_process`` (находит в реестре, зовёт process.start).
        """
        return self.start_process(name)
