"""
ProcessManagerProcess — процесс-оркестратор (Refactored).

Наследуется от ProcessModule. Использует композицию:
    ProcessRegistry + ProcessPriority + ProcessStatusMonitor + ProcessMonitor.

Порядок shutdown:
    ProcessMonitor → ProcessRegistry.stop_all → WorkerManager → ConsoleManager → super
"""

import copy
import os
import threading
import time
from typing import Any

from ...config_module.feature_flags import is_enabled
from ...console_module import ConsoleManager
from ...process_module import ProcessModule
from ...process_module.configs.observability_layers import ORCHESTRATOR_PROCESS_NAME
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
        name: str = ORCHESTRATOR_PROCESS_NAME,
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
        # Ф3.1 (routing-epoch): монотонный epoch рассылок + авторитетная карта
        # incarnation'ов процессов. Под _routing_lock (мутируется из handler'ов и
        # lifecycle-путей). См. _bump_routing_epoch / _broadcast_routing_refresh.
        self._routing_epoch: int = 0
        self._incarnations: dict[str, int] = {}
        self._routing_lock = threading.Lock()
        # Поколения рассылок (R4/ревью-1): «этот конверт ещё последний?». Здесь же,
        # а не только лениво, чтобы первое касание было заведомо однопоточным.
        self.__dict__["_broadcast_generations_map"] = {}
        self.__dict__["_broadcast_generations_lock_obj"] = threading.Lock()
        # Ф2 Task 2.1 (правда supervision): замена инстанса видима БЕЗ участия
        # incarnation. При reuse-очередей (дефолт) incarnation осознанно не растёт
        # (DECISIONS PMM:311-333), поэтому маркер «до/после рестарта» — пара
        # pid + instance_restarts: pid берётся из ОС в момент запроса,
        # instance_restarts инкрементируется на КАЖДЫЙ успешный restart_process.
        # Имя честное: сюда попадают И ручные рестарты, И авто-рестарты
        # supervision — монитор перезапускает упавшего той же командой
        # ``process.restart`` (process_monitor: _dispatch_due_restarts), поэтому
        # «manual» было бы ложью. Отличие от restart_count монитора: тот считает
        # краш-рестарты в окне (история монитора), этот — фактические замены
        # инстанса, выполненные оркестратором.
        self._instance_restarts: dict[str, int] = {}
        self._instance_started_at: dict[str, float] = {}
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
            routing_meta_fn=self._routing_meta_snapshot,
        )
        self._priority = ProcessPriority(logger=self, platform_adapter=platform_adapter)
        self._status = ProcessStatusMonitor(self._process_registry.os_processes)

        # Настройки монитора из конфига ProcessManager
        monitor_poll = float(self.get_config("monitor_poll_interval") or 0.5)
        heartbeat_timeout = float(self.get_config("heartbeat_timeout") or 15.0)

        # RestartPolicy из конфига (dict -> SchemaBase) или default.
        # Ф4-добор (владелец 2026-07-08): авто-рестарт ВСЕХ процессов по умолчанию —
        # конвейер работает только целиком, частичная живучесть = ложная надёжность.
        # Глобальный дефолт enabled=True (protected gui/PM монитор всё равно skip;
        # per-process рецепт перекрывает; окно give-up Ф3.6 ловит crash-loop).
        # Безопасность обеспечивают ГРОМКИЕ supervisor-события (не прячут баг).
        # Откат: env FW_AUTORESTART=0 или restart_policy.enabled в конфиге.
        from ..core.restart_policy import RestartPolicy

        restart_cfg = self.get_config("restart_policy")
        if isinstance(restart_cfg, dict):
            restart_policy = RestartPolicy(**restart_cfg)
        else:
            _autorestart_on = is_enabled("FW_AUTORESTART")
            restart_policy = RestartPolicy(enabled=_autorestart_on)

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

    def _log_active_feature_flags(self) -> None:
        """Boot-лог активных ``FW_*``-маркеров движка (наблюдаемость, раз на старте).

        Единая точка: оркестратор пишет в штатный LoggerManager, какие маркеры
        отклонены от дефолта (и откуда — env/alias), чтобы активная конфигурация
        dark-launch была видна в логах и сводилась в мониторинг. Advisory
        requires-нарушения (напр. zero-copy без handle-cache) — WARNING; жёсткое
        enforcement остаётся у владельца ресурса. НЕ на hot-path, boot не роняет.
        """
        try:
            from ...config_module.feature_flags import list_flags, validate

            states = list_flags()
            active = [s for s in states if s.value != s.default]
            if active:
                summary = ", ".join(f"{s.name}={s.value}({s.source})" for s in active)
                self._log_info(f"FW_*-маркеры (не дефолт): {summary}")
            else:
                self._log_info("FW_*-маркеры: все на дефолте")
            for problem in validate({s.name: s.value for s in states}):
                self._log_warning(f"FW_*-маркер: {problem}")
        except Exception as exc:  # noqa: BLE001 — наблюдаемость не должна ронять boot
            self._log_error(f"feature_flags boot-log: {exc}")

    def initialize(self) -> bool:
        """Инициализация: ProcessModule + создание процессов из config + запуск монитора."""
        try:
            # Регистрация ProcessManager для приёма команд (system.shutdown от GUI и др.)
            if self.shared_resources:
                self.shared_resources.register_process(
                    self.name,
                    # "state" аддитивно: очередь/канал возникают из
                    # конфига, при OFF пусты. У PM подписчиков state.changed нет, но
                    # держим паритет раскладки очередей с дочерними процессами.
                    {"queues": {"system": {"maxsize": 100}, "data": {"maxsize": 50}, "state": {"maxsize": 8}}},
                )

            if not super().initialize():
                return False

            self._setup_console_manager()
            self._setup_topology_manager()
            self._setup_state_store()
            self._register_builtin_commands()
            self._log_active_feature_flags()

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
                # 5.11-R1: внешний подписчик адресуется как "<sender>.<session>" и
                # умирает вместе с сокетом. Закрытие соединения — единственный сигнал
                # об этом ПО ФАКТУ: имени старой сессии после реконнекта не знает уже
                # никто, а шов инкарнации иначе воскрешал бы мёртвую подписку на
                # каждом свежем процессе.
                on_session_closed=self._forget_observability_session,
            )

            # Ф3.2: boot-барьер — дождаться self-reported ready стартованных детей
            # ПЕРЕД сигналом SystemLauncher. Это initialize-поток PM (НЕ
            # message_processor) → блокирующее ожидание допустимо и дедлока нет.
            # По таймауту всё равно сигналим готовность (boot не блокировать
            # навсегда) + WARNING со списком не-ready.
            self._wait_boot_ready()

            # Сигнализируем SystemLauncher, что инициализация завершена (ADR-116).
            # К этому моменту: все дочерние процессы spawned, started и (Ф3.2)
            # сообщили о готовности либо истёк boot_ready_timeout_s.
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
            "supervision.status": (
                self._cmd_supervision_status,
                "Supervision-снимок: epoch + per-process incarnation/restart_count/last_exit/"
                "status/pid/started_at/instance_restarts. Маркер замены инстанса = pid+instance_restarts "
                "(считает и ручные, и авто-рестарты supervision — они идут той же process.restart). "
                "incarnation растёт только при смене identity очередей; restart_count — краш-рестарты монитора",
            ),
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
            "telemetry.broadcast": (
                self._cmd_telemetry_broadcast,
                "Телеметрия через PM: publish → всем детям (fan-out) ИЛИ адресно (data.target), "
                "throttle → центральный троттл оркестратора; cap-детекция на обоих путях",
            ),
            "observability.tail.subscribe_all": (
                self._cmd_observability_tail_subscribe_all,
                "Брокер (Task 5.11): подписать адрес на хвост ВСЕХ процессов одним вызовом; "
                "намерение переживает рестарт, switch и появление нового процесса. "
                "Записи идут напрямую подписчику — PM брокер, не транзит",
            ),
            "observability.tail.unsubscribe_all": (
                self._cmd_observability_tail_unsubscribe_all,
                "Брокер: снять намерение подписчика и разослать снятие хвоста всем процессам",
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

    def capabilities_extra(self) -> dict:
        """Системная часть «контактной книжки» (Ф1 Task 1.9) — hook BuiltinCommands.

        Вливается в карточку ``introspect.capabilities`` PM (см.
        ``BuiltinCommands._cmd_introspect_capabilities``): PM не пере-регистрирует
        ключ и не опрашивает детей из своего хендлера (это дедлок — их ответы идут
        через тот же message_processor). Только КОНТРАКТ, без runtime-значений:

          - ``processes``: {имя: {"class": dotted-path}} из конфигов управляемых
            процессов — список адресатов для fan-out driver.capabilities();
          - ``channels``: [{"name", "kind"}] — каналы router'а PM (SocketChannel
            backend_ctl, SHM-каналы и т.п.).
        """
        processes = {
            name: {"class": str((cfg or {}).get("class") or "")} for name, cfg in sorted(self._process_configs.items())
        }
        channels = []
        if self.router_manager is not None and hasattr(self.router_manager, "get_all_channels"):
            try:
                channels = sorted(
                    (
                        {"name": str(ch.name), "kind": type(ch).__name__}
                        for ch in self.router_manager.get_all_channels()
                    ),
                    key=lambda c: c["name"],
                )
            except Exception:  # noqa: BLE001 — каналы не критичны для карточки
                channels = []
        return {"processes": processes, "channels": channels}

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
                self._mark_instance_started(process_name)
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

    def _cmd_supervision_status(self, data=None, **kwargs) -> dict:
        """Supervision-снимок (D.1b): epoch топологии + per-process incarnation,
        restart_count, last_exit, status, pid, started_at, manual_restarts.
        Опц. фильтр ``data["process"]``.

        Наружу отдаём routing-fence-истину PM (``_incarnations``/``_routing_epoch``)
        + monitor-срез (restart/exit/status) + ОС-истину инстанса одним ответом.

        Ф2 Task 2.1 — маркер «до/после рестарта»:
          - ``pid`` (истина ОС, читается из реестра в момент запроса) и
            ``instance_restarts`` (счётчик выполненных ``restart_process`` —
            и ручных, и авто-рестартов supervision) видят замену инстанса
            ВСЕГДА, включая дефолтный reuse-очередей;
          - ``incarnation`` растёт только когда сменилась identity очередей
            (reuse=off) — это fence-семантика, а не «был ли рестарт»;
          - ``restart_count`` — краш-рестарты в окне истории монитора; ручной
            рестарт в него не попадает (пересечение с instance_restarts —
            только по авто-рестартам).
        """
        self._ensure_routing_state()
        with self._routing_lock:
            epoch = self._routing_epoch
            incarnations = dict(self._incarnations)
        mon = getattr(self, "_process_monitor", None)
        snap = mon.get_supervision_snapshot() if mon is not None else {}
        instance_restarts = getattr(self, "_instance_restarts", None) or {}
        started_at = getattr(self, "_instance_started_at", None) or {}
        registry = getattr(self, "_process_registry", None)
        target = data.get("process") if isinstance(data, dict) else None
        processes: dict = {}
        for name in sorted(set(snap) | set(incarnations) | set(instance_restarts) | set(started_at)):
            if target and name != target:
                continue
            s = snap.get(name, {})
            proc = registry.get_process_by_name(name) if registry is not None else None
            if proc is None and name == getattr(self, "name", None):
                # PM не состоит в собственном реестре (он оркестратор, не ребёнок) —
                # без этого он вечно отдавал бы про СЕБЯ pid=null/alive=null, хотя
                # знает свой pid точно. Найдено на live-прогоне Ф2 Task 2.1.
                pid_val: int | None = os.getpid()
                alive_val: bool | None = True
            else:
                pid_val = getattr(proc, "pid", None)
                alive_val = bool(proc.is_alive()) if proc is not None else None
            processes[name] = {
                "incarnation": incarnations.get(name, 0),
                "restart_count": s.get("restart_count", 0),
                "last_exit": s.get("last_exit"),
                "status": s.get("status"),
                "pid": pid_val,
                "alive": alive_val,
                "started_at": started_at.get(name),
                "instance_restarts": instance_restarts.get(name, 0),
            }
        return {"success": True, "epoch": epoch, "processes": processes}

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
        # R6-G: debounce судится ДО ретаргета. Прежде отклонённый по cooldown
        # запрос успевал переставить адрес и откатить его обратно — то есть
        # дёргал watcher парой stop/start за замену, которой не было. Проверка
        # одна на два вызова (здесь и внутри `apply_topology`): второго
        # механизма коалесинга не появляется, а решает по-прежнему владелец
        # побочных эффектов — просто теперь мы не платим за его отказ.
        debounced = self._topology_debounce_reject()
        if debounced is not None:
            return debounced
        # Task 5.12: L2-watcher обязан переехать на спутник НОВОГО рецепта. Иначе
        # правка нового файла молча не применяется, а правка старого — применяется,
        # и оба симптома читаются как «hot-reload сломался».
        #
        # R6 (живой switch, 2026-07-29): ретаргет идёт ДО сборки. Адрес рецепта
        # ассемблер читает на КАЖДОЙ сборке, и пересозданные процессы уносили
        # адрес покинутого рецепта — живьём новорождённые получали `r6_a.yaml`
        # при активном `r6_b.yaml`. Откат при неудаче явный: адрес обязан
        # описывать ту топологию, которая на самом деле крутится.
        previous = self._observability_recipe_address()
        self._retarget_recipe_address(str(args.get("recipe_path") or ""))
        try:
            # Слой рецепта раздаёт сам `apply_topology` — ОДНИМ конвертом вместе
            # со сбросом сессии (R6-E). Адрес он берёт из конфига, куда его
            # только что положил ретаргет: два аргумента одного факта разошлись
            # бы ровно там, где `apply_topology` зовут в обход команды.
            result = self.apply_topology(td)
        except BaseException:
            # Ревью R6, находка 3: часть `apply_topology` живёт ВНЕ её внутреннего
            # try, и вылетевшее оттуда исключение проносило адрес мимо ветки
            # отката — новый рецепт при живой старой топологии. Адрес обязан
            # описывать то, что на самом деле крутится.
            self._retarget_recipe_address(previous)
            raise
        if not result.get("success"):
            self._retarget_recipe_address(previous)
        return result

    def _topology_debounce_reject(self) -> dict | None:
        """Отказ debounce (in-flight guard + cooldown) или ``None``, если можно идти.

        Единственная реализация коалесинга; зовут её двое — команда (до ретаргета,
        R6-G) и сам ``apply_topology`` (он владелец побочных эффектов и обязан
        держать инвариант даже при прямом вызове). Проверка идемпотентна и ничего
        не меняет, поэтому двойной вызов безопасен: гонка между ними всё равно
        разрешается второй проверкой, а адрес откатывает ветка неуспеха.
        """
        if getattr(self, "_replace_in_progress", False):
            self._log_warning("apply_topology: замена уже выполняется — запрос пропущен (debounce)")
            return {
                "success": False,
                "debounced": True,
                "error": "замена уже выполняется",
                "rolled_back": False,
            }
        cooldown = float(self.get_config("replace_debounce_s") or 0.0)
        if cooldown > 0.0 and (time.monotonic() - getattr(self, "_last_replace_ts", 0.0)) < cooldown:
            self._log_info("apply_topology: запрос в пределах cooldown — пропущен (debounce)")
            return {
                "success": False,
                "debounced": True,
                "error": "debounce cooldown",
                "rolled_back": False,
            }
        return None

    def _observability_recipe_address(self) -> str:
        """Действующий адрес рецепта (слой L2) — для отката и для конверта switch'а.

        Чтение адреса не имеет права уронить УСПЕШНО применённую топологию: этот
        вызов живёт на success-пути ``apply_topology``, и вылетевшее отсюда
        исключение откатывало бы живой switch из-за неудавшейся наблюдаемости.
        Пустая строка — честное «источник неизвестен», но молчать о ней нельзя.
        """
        from ...process_module.configs.observability_layers import RECIPE_PATH_CONFIG_KEY

        get_config = getattr(self, "get_config", None)
        if not callable(get_config):
            return ""
        try:
            return str(get_config(RECIPE_PATH_CONFIG_KEY, "") or "")
        except Exception as exc:  # noqa: BLE001 — см. докстринг
            self._log_error(f"[observability] адрес рецепта не прочитан из конфига: {exc}")
            return ""

    def _retarget_recipe_address(self, recipe_path: str) -> str:
        """Перевести адрес рецепта (и watcher за ним) — возвращает РЕЗОЛВНУТЫЙ путь.

        Раздача слоя НЕ обусловлена наличием ретаргета: watcher — про файлы
        оркестратора, слой — про конфиг каждого процесса. Свяжи мы их, и
        потребитель framework без ``app_module`` (у него метода нет) молча
        остался бы на секции покинутого рецепта.

        Task 5.11: без хука ``app_module`` адрес всё равно записывается в конфиг.
        Он не собственность watcher'а — его читают ещё ассемблер на каждой сборке
        и ``observability.persist``; оставь мы запись только внутри хука, PM без
        app_module называл бы источником слоя покинутый рецепт, а раздача уезжала
        бы по старому адресу.
        """
        retarget = getattr(self, "retarget_observability_recipe_watcher", None)
        if not callable(retarget):
            resolved = str(recipe_path or "")
            update_config = getattr(self, "update_config", None)
            if callable(update_config):
                from ...process_module.configs.observability_layers import RECIPE_PATH_CONFIG_KEY

                try:
                    update_config(RECIPE_PATH_CONFIG_KEY, resolved)
                except Exception as exc:  # noqa: BLE001 — адрес не должен ронять switch
                    self._log_error(f"[observability] адрес рецепта не записан в конфиг: {exc}")
            return resolved
        try:
            return str(retarget(str(recipe_path or "")) or "")
        except Exception as exc:  # noqa: BLE001 — ретаргет не должен ронять switch
            self._log_error(f"[observability] ретаргет L2-watcher после switch не удался: {exc}")
            return str(recipe_path or "")

    def _recipe_layer_payload(self, topology_dict: dict | None) -> dict:
        """Ключи слоя L2 нового рецепта для конверта switch'а (адрес + сырая секция).

        Рассылается СЫРАЯ секция ``observability`` рецепта, а долька процесса
        резолвится у получателя тем же ``resolve_recipe_section``, что и на boot.
        Иначе switch и старт трактовали бы один файл по-разному — а это ровно тот
        класс расхождения, который 5.12 закрывала как «boot ≡ reload».

        Свою дольку оркестратор берёт из ЭТОГО ЖЕ конверта — в
        ``_reset_observability_sessions``, тем же ``resolve_recipe_section`` и по
        собственному имени (Task 5.13). Прежняя редакция исключала себя, и это
        было верно ровно до тех пор, пока boot тоже ничего ему не давал:
        исключение держало switch и boot в согласии — оба молчали. Теперь оба
        выдают, и согласие сохранено с другой стороны.

        **Спутник домерживается ЗДЕСЬ (Task 5.13, шаг 6).** До этого он попадал в
        слой только через пересборку proc_dict'ов (``_build_proc_dicts`` прототипа
        мержит его в ``topology["observability"]``), а конверт вёз сырую секцию
        рецепта. Расхождение было ненаблюдаемым, потому что пересоздаваемый
        ребёнок получал спутник вторым путём — но два адресата второго пути не
        имеют:

        * **protected-процессы** не перезапускаются, и для них конверт —
          единственный источник: сохранённая ``observability.persist`` настройка
          после switch у них молча откатывалась;
        * **сам оркестратор**, начиная с шага 5.

        Мерж идёт общим швом ``merge_companion_over`` — тем же, что на boot и в
        пересборке, и в том же порядке (спутник ПОВЕРХ рецепта: его писал пульт,
        он новее). До ревью 5.13 это были три копии правила, уже разошедшиеся
        обработкой битого файла; теперь различие политики отказа — параметр шва,
        а не расхождение реализаций.
        """
        from ...process_module.configs.observability_companion import merge_companion_over

        section = topology_dict.get("observability") if isinstance(topology_dict, dict) else None
        recipe_path = self._observability_recipe_address()
        # Битый спутник не имеет права ронять switch — в отличие от boot.
        section = merge_companion_over(section, recipe_path, on_error=self._log_error)
        return {
            # Пустая секция едет как `{}`, а не пропускается: «новый рецепт про
            # наблюдаемость молчит» обязано СНЯТЬ прежний слой, иначе покинутый
            # рецепт продолжал бы действовать вечно.
            "observability_recipe": section,
            "observability_recipe_path": recipe_path,
        }

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
    # Wire re-issue при рестарте/switch (Ф3.5) — first-class wire-статусы
    #
    # КОНТЕКСТ A vs B (см. plans/.../f3.5-wire-status.md §Контекст):
    #   A. generic data-path (живой поток камеры) — самовосстанавливается через
    #      routing-epoch Ф3.1 (mw пересоздаётся, shm_actual_name едет в каждом msg).
    #   B. wire.* абстракция (PM-управляемые «провода», заводится ТОЛЬКО GUI
    #      connect_wire → wire.setup) — статический FrameShmMiddleware в дочернем
    #      `_wire_middlewares`. Новый инстанс после рестарта рождается с ПУСТЫМ
    #      `_wire_middlewares` → провод B висит на мёртвом инстансе. Это и есть баг.
    #
    # SHM-регион owner-scoped и переживает рестарт (restart_process зовёт
    # register_process(reuse_queues), а НЕ unregister_process — SHM не освобождается),
    # поэтому re-issue = переслать wire.configure ТОЛЬКО в перезапущенный инстанс
    # (пересоздать его middleware); партнёр не трогаем — он читает per-message
    # shm_actual_name и остаётся валиден. Переаллокация SHM не требуется.
    # -------------------------------------------------------------------------

    def _wire_reissue_enabled(self) -> bool:
        """Гейт wire re-issue: конфиг ``wire_reissue_enabled`` (дефолт True).

        Аварийный откат к старому поведению (провода не переигрываются,
        broken_wires снова оседает на 0 при живой топологии): выставить
        ``wire_reissue_enabled: false`` в конфиге PM.
        """
        cfg = self.get_config("wire_reissue_enabled") if hasattr(self, "get_config") else None
        return True if cfg is None else bool(cfg)

    def _mark_wires_broken_for(self, process_name: str) -> None:
        """Пометить задетые провода ``status="broken"`` (honest-статус до re-issue).

        Вызывается при рестарте/switch ПЕРЕД пересозданием инстанса: провод,
        чей source или target — ``process_name``, в этот момент реально мёртв
        (у нового инстанса ещё нет middleware). Монитор публикует
        ``broken_wires ≠ 0`` в это окно (acceptance Ф3.5). После успешного
        re-issue статус вернётся в ``"active"``.
        """
        wires = getattr(self, "_active_wires", None)
        if not isinstance(wires, dict) or not wires:
            return
        for info in wires.values():
            if not isinstance(info, dict):
                continue
            if process_name in (info.get("source_process"), info.get("target_process")):
                info["status"] = "broken"

    def _reissue_wires_for(self, process_name: str) -> int:
        """Переиграть ``wire.configure`` для проводов, задевающих ``process_name``.

        Перебирает ``_active_wires``; для каждого провода, где ``process_name`` —
        source или target, шлёт ``wire.configure`` в перезапущенный инстанс с
        ролью (``sender`` для source, ``receiver`` для target) и сохранённым
        ``shm_config`` (как в ``_cmd_wire_setup``). Успех → провод снова
        ``"active"``.

        Guard'ы (безопасно на mock-PM и без проводов):
          - ``_active_wires`` пуст/не dict → no-op (return 0);
          - сбой ``send_message`` (communication mock/None) → провод остаётся
            broken, ошибка логируется, перебор продолжается.

        Returns:
            Число успешно переигранных проводов.
        """
        wires = getattr(self, "_active_wires", None)
        if not isinstance(wires, dict) or not wires:
            return 0
        reissued = 0
        for wire_key, info in list(wires.items()):
            if not isinstance(info, dict):
                continue
            src = info.get("source_process", "")
            tgt = info.get("target_process", "")
            if process_name not in (src, tgt):
                continue
            role = "sender" if process_name == src else "receiver"
            shm_cfg = info.get("shm_config") or {}
            configure_cmd = {
                "type": "system",
                "command": "wire.configure",
                "sender": self.name,
                "data": {
                    "wire_key": wire_key,
                    "shm_name": shm_cfg.get("shm_name", wire_key),
                    "shm_owner": shm_cfg.get("owner_process", src),
                    "buffer_slots": shm_cfg.get("buffer_slots", 4),
                    "role": role,
                },
            }
            # Ревью Fable, находка 2: отправка шла НЕМЕДЛЕННО, сразу после барьера
            # 0.5с, которого реальный инстанс не пробегает — конверт попадал в окно
            # «message-loop крутится, команды не зарегистрированы» и выбрасывался.
            # Статус при этом ставился `active` по факту доставки-в-очередь, то есть
            # провод объявлялся живым по несостоявшемуся применению.
            outcome = {"ok": False}

            def _do(k=wire_key, i=info, r=role, cmd=configure_cmd, out=outcome):
                out["ok"] = self._send_wire_configure(process_name, k, i, r, cmd)

            deferred = self._run_when_child_ready(
                process_name,
                _do,
                label="wire-reissue",
                deadline_s=self._late_delivery_deadline() or 15.0,
            )
            # Счётчик считает ПЕРЕИГРАННЫЕ, а не запланированные. Отложенный провод
            # сюда не попадает: его исход на этот момент неизвестен, а «раздал» и
            # «применилось» — разные утверждения. Отложенный остаётся `broken` до
            # фактической отправки — статус честен в каждый момент времени.
            if not deferred and outcome["ok"]:
                reissued += 1
        return reissued

    def _send_wire_configure(
        self, process_name: str, wire_key: str, info: dict, role: str, configure_cmd: dict
    ) -> bool:
        """Отправить wire.configure и пометить провод активным по факту отправки."""
        try:
            self.send_message(process_name, configure_cmd)
            info["status"] = "active"
            self._log_info(f"wire re-issue: '{wire_key}' переигран в '{process_name}' (role={role})")
            return True
        except Exception as exc:  # noqa: BLE001 — провод остаётся broken, lifecycle не роняем
            self._log_error(f"wire re-issue '{wire_key}' в '{process_name}' не удался: {exc}")
            return False

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

    def is_known_process(self, name: str) -> bool:
        """Существует ли процесс ``name`` в текущей топологии (сид гейта state).

        Источник правды — тот же, что у lifecycle: применённый конфиг
        (``_process_configs``) ИЛИ живой объект в реестре. Второе слагаемое не
        избыточно: ``process.create`` (AD-8, Router-endpoint) поднимает процесс
        динамически, без предварительной записи в ``_process_configs`` — гейт по
        одному лишь конфигу отклонял бы его законную телеметрию.

        Сам ProcessManager известен всегда: он публикует собственный узел
        ``processes.ProcessManager.*``, но в ``_process_configs`` себя не пишет.
        """
        if not name or name == self.name:
            return True
        if name in self._process_configs:
            return True
        registry = getattr(self, "_process_registry", None)
        getter = getattr(registry, "get_process_by_name", None) if registry is not None else None
        if not callable(getter):
            return True  # fail-open: без реестра гейт не судья
        try:
            return getter(name) is not None
        except Exception:  # noqa: BLE001 — сбой реестра не должен глушить запись
            return True

    def live_process_config(self, name: str) -> dict | None:
        """Живой (применённый) конфиг процесса из ``_process_configs`` или ``None``.

        B-2 (RS-3): сид ``protected_config_provider`` планировщика — источник
        «что реально работает» для сравнения с новым blueprint (расхождение
        конфига protected-процесса → предупреждение, а не тихий успех).
        """
        cfg = self._process_configs.get(name)
        return copy.deepcopy(cfg) if isinstance(cfg, dict) else None

    def _collect_protected_conflicts(self) -> list[str]:
        """Имена protected-процессов, чей конфиг в новом рецепте разошёлся с живым.

        Планировщик (``FullReplacePlanner``, инъекция прототипа) фиксирует
        расхождения в ``last_protected_conflicts`` при генерации команд. PM читает
        их через опциональный атрибут (framework не импортирует прототип). Пусто,
        если планировщик не подключён или расхождений нет.
        """
        planner = getattr(self, "_full_replace_planner", None)
        conflicts = getattr(planner, "last_protected_conflicts", None) if planner is not None else None
        return list(conflicts) if conflicts else []

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
           Сюда же (Ф2 Task 2.1) — supervision-хвосты PM: ``_instance_restarts``
           и ``_instance_started_at``. Без этого снятый switch'ем процесс вечно
           висел бы в ``supervision.status`` (снимок итерируется и по ним), а
           новый одноимённый рождался бы с чужим счётчиком замен — ровно тот
           ложный маркер, против которого задача и делалась.
           ``_incarnations`` НЕ чистится осознанно: это fence-плоскость, её
           монотонность защищает соседей от стейл-ссылок на снятое имя.

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

        for tail in ("_instance_restarts", "_instance_started_at"):
            store = getattr(self, tail, None)
            if isinstance(store, dict):
                store.pop(name, None)

        monitor = getattr(self, "_process_monitor", None)
        forget_fn = getattr(monitor, "forget_process", None)
        if callable(forget_fn):
            try:
                forget_fn(name)
            except Exception as exc:
                self._log_warning(f"cleanup_process_resources: monitor.forget '{name}' не удался: {exc}")

        # LP-4/Ж-2 (RS-2): снять поддерево процесса из StateStore. Без этого
        # снятый switch'ем процесс висит в дереве как ``running/health ok`` с
        # растущим uptime (монитор перестал публиковать через forget, но старые
        # листья остаются) — наблюдаемость врёт, state ≠ ОС-реальность. Единая
        # точка очистки (симметрия register/unregister): реестр+SHM+монитор+state.
        self._delete_process_state(name)

        # Task 5.11: снятый с топологии процесс мог быть ПОДПИСЧИКОМ (GUI —
        # обычный процесс системы). Намерение пережившего его брокера заставляло
        # бы каждую новую инкарнацию форвардить записи в очередь мертвеца.
        # Это единственный сигнал о смерти подписчика, который у оркестратора
        # есть по факту, а не по догадке.
        broker = getattr(self, "_observability_broker", None)
        if broker is not None:
            broker.forget_subscriber(name)

    def _state_op(self, handler_name: str, payload: dict, ctx: str) -> None:
        """Единый локальный путь мутации StateStore из PM (без IPC).

        Идёт напрямую через StateStoreManager ProcessManager (как
        ``ProcessMonitor._publish_state``). Идемпотентно и НЕ бросает: телеметрия/
        state-операции не критичны для lifecycle. Тихо no-op, если StateStore
        недоступен. Обёртки ниже (delete/identity/alert) — тонкие вызовы этого метода.

        Args:
            handler_name: имя метода StateStoreManager ("handle_state_set" / "..._delete").
            payload: содержимое ключа "data" IPC-конверта команды.
            ctx: метка вызова для debug-лога при сбое.
        """
        ssm = getattr(self, "_state_store_manager", None)
        if ssm is None:
            return
        handler = getattr(ssm, handler_name, None)
        if handler is None:
            return
        try:
            handler({"data": payload})
        except Exception as exc:  # nosec B110 — state-операция не критична для lifecycle
            self._log_debug(f"_state_op[{ctx}] не удался: {exc}")

    def _delete_process_state(self, name: str) -> None:
        """Удалить поддерево ``processes.<name>`` из StateStore (RS-2/Ж-2/LP-4).

        Без этого снятый switch'ем процесс висит в дереве как ``running/health ok``
        (монитор перестал публиковать через forget, но старые листья остаются) —
        наблюдаемость врёт. Единая точка очистки: реестр+SHM+монитор+state.
        """
        self._state_op(
            "handle_state_delete",
            {"path": f"processes.{name}", "source": "ProcessManager"},
            f"delete_state:{name}",
        )

    def _mark_instance_started(self, name: str) -> None:
        """Отметка старта ИНСТАНСА процесса + шов «поднялась свежая инкарнация».

        Ф2 Task 2.1: вызывается на всех путях старта (boot, start_process,
        restart, автостарт, пересоздание топологией). Вместе с pid из ОС даёт
        ответ на вопрос «это тот же инстанс или новый?» даже когда incarnation не
        менялась (reuse-очередей).

        Task 5.11: **и по той же причине здесь висит переподписка на
        наблюдаемость.** Свежая инкарнация стартует с пустым набором форвардеров,
        то есть хвост подписчика на ней молча пропадает. Пять путей старта уже
        сходятся в этой точке — заводить шестое место «не забыть переподписать»
        значило бы построить ровно ту неполноту, которой болели оба потребителя
        (GUI-триггер ``recovered`` не покрывал ручной рестарт). Раздача адресная
        и fire-and-forget.

        **Правка после живого прогона 2026-07-29.** Здесь стояло утверждение, что
        команда «будет прочитана, когда инстанс раскрутит цикл сообщений — ждать
        нечего и некого». Живьём она читалась раньше, чем инстанс регистрировал
        команды, и молча терялась. Раздача ушла за readiness-гейт
        (:meth:`_replay_observability_when_ready`); сам шов остаётся единственной
        точкой всех путей старта.

        Защитный getattr — unit-тесты строят PM с no-op ``__init__``
        (та же философия, что ``_ensure_routing_state``).
        """
        started = getattr(self, "_instance_started_at", None)
        if started is None:
            started = {}
            self._instance_started_at = started
        started[name] = time.time()
        self._replay_observability_when_ready(name)

    # -------------------------------------------------------------------------
    # Readiness-гейт: «команда не раньше, чем инкарнация сможет её принять»
    #
    # Task 5.11 завела его для раздачи подписок, резидуал 5.11-R4 показал живьём
    # ту же гонку на routing.refresh / config.reload / telemetry.reconfigure.
    # Механизм здесь ОДИН на всех потребителей: копия на каждую команду — ровно
    # тот способ, которым дефект уже воскресал на соседней развилке.
    # -------------------------------------------------------------------------

    def _child_ready_event(self, name: str):
        """Event готовности ребёнка, либо ``None`` — сигнала нет.

        ``None`` означает «спросить не у кого» (mock-реестр, старый bundle,
        процесс не создавался), а НЕ «не готов»: потребители гейта в этом случае
        действуют немедленно — прежнее поведение хуже, чем с сигналом, но лучше,
        чем не действовать вовсе.
        """
        get_ready_event = getattr(self._process_registry, "get_ready_event", None)
        if not callable(get_ready_event):
            return None
        try:
            return get_ready_event(name)
        except Exception as exc:  # noqa: BLE001 — отсутствие сигнала не повод падать
            self._log_error(f"[ready-gate] ready_event '{name}' не прочитан: {exc}")
            return None

    def _run_when_child_ready(
        self,
        name: str,
        action,
        *,
        label: str,
        deadline_s: float,
        still_relevant=None,
    ) -> bool:
        """Выполнить действие над ребёнком тогда, когда он умеет его принять.

        Готов (или сигнала нет) → действие прямо здесь, синхронно. Не готов →
        daemon-поток ждёт ``ready_event`` и выполняет после. Ждать синхронно
        нельзя: гейт зовут из ``message_processor``, а событие живёт ВНЕ
        message-loop (``mp.Event``) — тот же аргумент, которым обоснованы
        барьеры Ф3.2.

        Args:
            still_relevant: опциональная проверка «действие ещё имеет смысл».
                Зовётся перед выполнением и во время ожидания. ``False`` → действие
                снимается. Нужна там, где событие может стать НЕДОСТИЖИМЫМ: switch
                пересоздаёт ребёнка вместе с его ``ready_event``, и ожидающий поток
                остаётся на мёртвом объекте — дотягивает дедлайн и доставляет
                конверт ПОЗЖЕ свежего (ревью Fable, находка 1).

        Returns:
            ``True`` — действие отложено до готовности; ``False`` — выполнено сразу
            (или снято как неактуальное).
        """
        if still_relevant is not None and not still_relevant():
            return False
        event = self._child_ready_event(name)
        if event is None or event.is_set():
            action()
            return False
        threading.Thread(
            target=self._run_child_action_after_ready,
            args=(name, action, label, event, deadline_s, still_relevant),
            name=f"ready-gate-{label}-{name}",
            daemon=True,
        ).start()
        return True

    #: Шаг опроса ожидания готовности. Ждём НЕ одним ``event.wait(deadline)``, а
    #: срезами: между срезами проверяется актуальность. Без этого поток, чьё
    #: событие умерло вместе с прежней инкарнацией, висит весь дедлайн и в конце
    #: доставляет прошлое в настоящее.
    _READY_GATE_POLL_S = 0.25

    def _run_child_action_after_ready(
        self,
        name: str,
        action,
        label: str,
        event,
        deadline_s: float,
        still_relevant=None,
    ) -> None:
        """Дождаться готовности инкарнации и выполнить действие (daemon-поток).

        По истечении дедлайна действуем ВСЁ РАВНО и громко: «процесс не
        объявился» — не повод молча пропустить команду, но и не повод сделать
        вид, что всё прошло штатно.

        Действие, потерявшее актуальность (``still_relevant`` → ``False``),
        снимается — но НЕ молча: снятая команда и потерянная команда снаружи
        выглядят одинаково, а различать их приходится именно в разборе.
        """
        try:
            deadline = time.monotonic() + deadline_s
            ready = False
            while True:
                if still_relevant is not None and not still_relevant():
                    self._log_info(
                        f"[ready-gate:{label}] '{name}': досылка снята — конверт устарел "
                        "(рассылка того же типа ушла позже)"
                    )
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if event.wait(min(self._READY_GATE_POLL_S, remaining)):
                    ready = True
                    break
            # Перепроверка ПОСЛЕ ожидания обязательна: конверт мог устареть ровно
            # в тот момент, когда инкарнация объявилась (свежая рассылка той же
            # команды приходит именно тогда). Без неё поток, дождавшийся события,
            # доставлял прошлое — поймано собственным тестом поколений.
            if still_relevant is not None and not still_relevant():
                self._log_info(f"[ready-gate:{label}] '{name}': досылка снята (рассылка того же типа ушла позже)")
                return
            if not ready:
                self._log_warning(
                    f"[ready-gate:{label}] '{name}' не объявил готовность за {deadline_s}s — "
                    "действую вслепую (команда может не застать обработчик)"
                )
            action()
        except Exception as exc:  # noqa: BLE001 — поток обслуживания не роняет систему
            self._log_error(f"[ready-gate:{label}] отложенное действие для '{name}' упало: {exc}")

    def _replay_observability_when_ready(self, name: str) -> None:
        """Раздать намерения свежей инкарнации — но не раньше, чем она сможет их принять.

        **Живой прогон 2026-07-29 (switch + ручной рестарт) — дефект, которого не
        видел ни один из 6000+ зелёных тестов.** Раздача со шва приезжала ребёнку,
        у которого message-loop уже крутится (шаг 7 ``initialize``), а команды ещё
        не зарегистрированы (они регистрируются в ``run()``). Ребёнок писал
        ``No handler for key 'observability.tail.subscribe'`` и ронял команду —
        хвост подписчика пропадал НАВСЕГДА и молча: раздача fire-and-forget, ответа
        никто не ждёт, повтора нет. В тестах дефект невидим по построению — у
        фейкового ребёнка хендлер есть всегда.

        Прежний докстринг шва утверждал обратное («будет прочитана, когда тот
        раскрутит цикл сообщений — ждать здесь нечего и некого»). Сообщение
        действительно читается — просто раньше, чем появляется тот, кто его поймёт.

        Ждать синхронно нельзя: шов зовут из message_processor. Ожидание живёт в
        общем примитиве :meth:`_run_when_child_ready` — том же, которым резидуал
        5.11-R4 развёл рассылки switch'а. Своей копии ожидания здесь больше нет.
        """
        broker = getattr(self, "_observability_broker", None)
        if broker is None or not broker.subscriber_names():
            # Намерений нет — ни потока, ни раздачи: платить за них на КАЖДОМ
            # старте процесса не за что.
            return
        timeout = self.get_config("observability_replay_ready_timeout_s")
        self._run_when_child_ready(
            name,
            lambda: self._replay_observability_subscriptions("instance.started", target=name),
            label="observability",
            deadline_s=30.0 if timeout is None else float(timeout),
        )

    def _publish_process_identity(self, name: str) -> None:
        """Опубликовать ОС-идентичность процесса в StateStore: pid + актуальный config.

        RS-2 (честный state): у КАЖДОГО живого процесса в дереве — реальный ``pid``
        (сопоставление state↔ОС) и ``config`` из НОВОГО рецепта. Публикуется после
        успешного ``start`` (switch, boot, restart).
        """
        proc = self._process_registry.get_process_by_name(name)
        pid = proc.pid if proc is not None else None
        config = self._process_configs.get(name)
        self._state_op(
            "handle_state_set",
            {"path": f"processes.{name}.pid", "value": pid, "source": "ProcessManager"},
            f"identity_pid:{name}",
        )
        if config is not None:
            self._state_op(
                "handle_state_set",
                {"path": f"processes.{name}.config", "value": copy.deepcopy(config), "source": "ProcessManager"},
                f"identity_config:{name}",
            )

    def _publish_unstoppable_alert(self, names: list[str]) -> None:
        """Опубликовать alert о неостановимых процессах в StateStore (B-3, RS-3).

        Процесс, переживший полную эскалацию (graceful→terminate→kill), исключается
        из cleanup/пересоздания (защита от дублей), НО не молча. Громкость для оператора
        даёт ``_log_error`` (→ logger_manager → store-tap → Наблюдаемость); этот
        state-ключ ``system.switch.unstoppable`` — queryable-поверхность для backend_ctl
        и retry-триггер (имя остаётся в реестре → следующий switch повторит остановку).
        Пустой список → снять alert (очистка после успешного switch).
        """
        self._last_unstoppable = sorted(names)
        self._state_op(
            "handle_state_set",
            {"path": "system.switch.unstoppable", "value": sorted(names), "source": "ProcessManager"},
            f"unstoppable_alert:{names}",
        )

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
                from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
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
            # B-3 (RS-3): alert в state/hub — GUI видит зависшие имена, retry на след. switch.
            self._publish_unstoppable_alert(sorted(unstoppable))

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
    # ROUTING-EPOCH (Ф3.1) — гибрид данные-refresh (switch) + стабильные очереди
    # -------------------------------------------------------------------------

    def _ensure_routing_state(self) -> None:
        """Ленивая инициализация routing-состояния (Ф3.1).

        Продовый ``__init__`` всегда ставит ``_routing_lock``/``_routing_epoch``/
        ``_incarnations``. Но unit-тесты строят PM, патча ``__init__`` в no-op
        (см. conftest.make_pm) — тогда атрибутов нет. Этот guard делает routing-
        методы безопасными в таких PM (та же философия, что communication/mock=None).
        """
        if not hasattr(self, "_routing_lock"):
            self._routing_lock = threading.Lock()
            self._routing_epoch = getattr(self, "_routing_epoch", 0)
            self._incarnations = getattr(self, "_incarnations", {})

    def _routing_meta_snapshot(self) -> dict[str, Any]:
        """Снимок {epoch, incarnations} для bundle нового ребёнка (Ф3.1).

        Вызывается ProcessRegistry на спавне — новый ребёнок рождается с
        актуальными epoch/incarnation'ами соседей.
        """
        self._ensure_routing_state()
        with self._routing_lock:
            return {"epoch": self._routing_epoch, "incarnations": dict(self._incarnations)}

    def _mirror_routing_to_psr(self, name: str, *, epoch: int | None = None, incarnation: int | None = None) -> None:
        """Best-effort зеркалирование epoch/incarnation в metadata PM-PSR.

        Диагностика/консистентность: PM хранит истину в ``_incarnations``/
        ``_routing_epoch``, но дублирует её в свою PSR-запись. Всё за guard'ами —
        в unit-тестах shared_resources/get_process_data бывают mock/None.
        """
        sr = getattr(self, "shared_resources", None)
        if sr is None:
            return
        try:
            pd = sr.get_process_data(name)
            meta = getattr(pd, "metadata", None) if pd is not None else None
            if not isinstance(meta, dict):
                return
            if epoch is not None:
                meta["routing_epoch"] = epoch
            if incarnation is not None:
                meta["routing_incarnation"] = incarnation
        except Exception:  # noqa: BLE001 — зеркало не критично
            pass

    def _bump_routing_epoch(self) -> int:
        """Инкремент epoch рассылок под локом (+ зеркало в PM-PSR)."""
        self._ensure_routing_state()
        with self._routing_lock:
            self._routing_epoch += 1
            epoch = self._routing_epoch
        self._mirror_routing_to_psr(self.name, epoch=epoch)
        return epoch

    def _bump_incarnation(self, name: str) -> int:
        """Инкремент incarnation процесса под локом (+ зеркало в PM-PSR).

        Каждое пере-провижинивание/пересоздание очередей процесса поднимает его
        incarnation: выжившие соседи по расхождению incarnation сбрасывают
        стейл-ссылку на его очереди.
        """
        self._ensure_routing_state()
        with self._routing_lock:
            self._incarnations[name] = self._incarnations.get(name, 0) + 1
            inc = self._incarnations[name]
        self._mirror_routing_to_psr(name, incarnation=inc)
        return inc

    def _routing_refresh_enabled(self) -> bool:
        """Гейт рассылки refresh: конфиг routing_refresh_enabled (дефолт True) +
        env FW_ROUTING_REFRESH != "0" (аварийный откат к поведению main)."""
        cfg = self.get_config("routing_refresh_enabled") if hasattr(self, "get_config") else None
        if cfg is False:
            return False
        if not is_enabled("FW_ROUTING_REFRESH"):
            return False
        return True

    def _broadcast_routing_refresh(self, reason: str) -> bool:
        """Разослать routing.refresh всем детям (декларативная сверка снимка, Ф3.1).

        Payload — ПОЛНЫЙ снимок (не дельта): имена из PSR + их incarnation +
        текущий epoch. Идемпотентно у ребёнка (guard epoch<=last_seen);
        потерянная рассылка самовосстанавливается следующей. Отправка — существующим
        путём ``communication.broadcast(exclude_self=True)`` (system-очереди детей).

        Все обращения за guard'ами: в unit-тестах communication/shared_resources
        бывают mock/None → тихий no-op (поведение switch-тестов не меняется).
        """
        if not self._routing_refresh_enabled():
            return False
        comm = getattr(self, "communication", None)
        sr = getattr(self, "shared_resources", None)
        if comm is None or sr is None:
            return False
        try:
            names = list(sr.get_process_names())
        except Exception:  # noqa: BLE001
            return False
        self._ensure_routing_state()
        with self._routing_lock:
            epoch = self._routing_epoch
            processes = {n: {"incarnation": self._incarnations.get(n, 0)} for n in names}
        data = {
            "epoch": epoch,
            "hub": self.name,
            "reason": reason,
            "processes": processes,
            "ts": time.time(),
        }
        try:
            # Общий примитив рассылки (тот же путь comm.broadcast использует fan-out
            # телеметрии, PC 3.3) — не дублируем сборку конверта.
            self._broadcast_command("routing.refresh", data)
            self._log_info(f"routing.refresh разослан (reason={reason}, epoch={epoch}, процессов={len(processes)})")
            return True
        except Exception as exc:  # noqa: BLE001 — рассылка не должна ронять lifecycle
            self._log_error(f"_broadcast_routing_refresh({reason}) упал: {exc}")
            return False

    def _replay_telemetry_runtime_delta(self, reason: str, *, target: str | None = None) -> int:
        """Доиграть сохранённую runtime telemetry publish-дельту детям (Task 3.2).

        Runtime-правка publisher-gate (``telemetry.broadcast`` fan-out) живёт только в
        процессах-детях; при hot-swap/respawn пересозданный ребёнок стартует с BOOT-конфига
        и потерял бы правку. PM хранит последнюю fan-out publish-дельту (``_telemetry_runtime_delta``)
        и доигрывает её. ``publish=None``-broadcast очистил персист → доигрывать нечего.

        Args:
            reason: причина доигрывания (для лога).
            target: имя конкретного процесса → адресно ОДНОМУ ребёнку (``_send_child_command``,
                напр. single-process ``restart_process`` — краш-рестарт частый, broadcast всем
                избыточен). ``None`` → fan-out ВСЕМ живым детям (``_broadcast_command``, напр.
                ``apply_topology`` пересоздал набор). Оба пути идемпотентны (replace/merge
                повторно на уже настроенном ребёнке даёт то же состояние).

        Returns:
            Охват доставки (0 — нет дельты / нет коммуникации / ошибка).
        """
        delta = getattr(self, "_telemetry_runtime_delta", None)
        if not delta:
            return 0
        payload: dict[str, Any] = {"publish": delta["publish"]}
        if delta.get("mode", "replace") != "replace":
            payload["telemetry_mode"] = delta["mode"]
        try:
            if target is not None:
                # Ревью Fable, находка 2: адресный путь шёл МИМО гейта готовности —
                # ровно для того процесса, которого только что перезапустили, то есть
                # для сценария из Why задачи R4. Компенсирующей рассылки за ним нет:
                # потеря тихая и постоянная (ребёнок остаётся на boot-конфиге).
                deferred = self._run_when_child_ready(
                    target,
                    lambda t=target, p=payload: self._send_child_command(t, "telemetry.reconfigure", p),
                    label="telemetry-replay",
                    deadline_s=self._late_delivery_deadline() or 15.0,
                )
                # Охват отложенной отправки неизвестен на этот момент — честнее
                # вернуть 0, чем выдать намерение за доставку.
                reached = 0 if deferred else 1
            else:
                reached = self._broadcast_command("telemetry.reconfigure", payload)
            self._log_info(f"telemetry runtime-дельта доиграна ({reason}, target={target!r}): reached={reached}")
            return int(reached)
        except Exception as exc:  # noqa: BLE001 — доигрывание не должно ронять lifecycle
            self._log_error(f"_replay_telemetry_runtime_delta({reason}) упал: {exc}")
            return 0

    def _reset_observability_sessions(self, reason: str, *, recipe: dict | None = None) -> dict:
        """Обнулить слой сессии наблюдаемости (L3) у себя и у всех живых детей.

        Switch рецепта — это новый конвейер, а L3 отвечает на вопрос «что я кручу
        руками ПРЯМО СЕЙЧАС». Пережившая switch ручка отвечала бы на него про
        прошлый конвейер. Хуже того, пережила бы она НЕ у всех: protected-процессы
        не перезапускаются и сохранили бы L3, пересозданные стартуют чистыми — и
        ``introspect.observability`` соседей начал бы врать по-разному.

        **Что здесь честно, а что нет.** Свои ключи PM называет поимённо — он их
        знает. Ключи детей он НЕ собирает: ``_broadcast_command`` — fire-and-forget,
        а собирать N ответов внутри ``topology.apply`` значит ждать в потоке, где
        уже ловили дедлоки. Поэтому в ответе — охват рассылки, а не выдуманный
        список: проверяемое утверждение «после switch у всех пусто» доказывается
        опросом ``introspect.observability``, не эхом этой команды.
        """
        own: list = []
        own_recipe: dict | None = None
        try:
            from ...process_module.configs.observability_layers import (
                LAYER_RECIPE,
                process_observability_layers,
                resolve_recipe_section,
            )
            from ...process_module.managers.observability_reload import (
                apply_observability_layers,
                telemetry_targets,
            )

            # Task 5.9: `reason` в origin, а не «switch» литералом — сброс L3
            # инициируют разные события (switch рецепта, пересборка топологии), и
            # в разборе инцидента вопрос ровно этот: чем именно унесло ручки.
            layers = process_observability_layers(self)
            origin = f"switch:{reason}"
            own = list(layers.session_clear(origin=origin))
            # Task 5.13: свой слой L2 — из ТОГО ЖЕ конверта и ТЕМ ЖЕ резолвером,
            # что у детей (`resolve_recipe_section` по собственному имени). До
            # 5.13 оркестратор себе дольку не выдавал — сознательно, чтобы не
            # развести switch и boot, потому что boot её тоже не выдавал. Теперь
            # выдают оба, и исключение снято с ОБОИХ концов провода сразу.
            #
            # Место выбрано на ОБЩЕМ пути, а не внутри app_module-хука ретаргета:
            # PM без этого хука идёт другой развилкой (`_retarget_recipe_address`),
            # и правка там оставила бы такую сборку без слоя. Один код на обе
            # развилки вместо двух похожих.
            if recipe is not None:
                own_recipe = resolve_recipe_section(recipe.get("observability_recipe"), self.name)
                layers.replace_layer(
                    LAYER_RECIPE,
                    own_recipe,
                    source=str(recipe.get("observability_recipe_path") or ""),
                    origin=origin,
                )
            # R6 (живой switch, 2026-07-29): снять ключ со слоя — половина дела.
            # Без пересборки менеджеры остаются на СНЯТОМ значении, а readback
            # честно отвечает «сессия пуста» — то есть провенанс и действующий
            # конфиг расходятся, и расходятся молча. Живьём: PM после switch
            # держал DEBUG при пустом L3, тогда как ребёнок (у него пересборку
            # делает `config.reload`) вернулся на INFO. Асимметрия ровно та, от
            # которой эта функция и должна была защищать.
            # Пересборка нужна, если изменился ЛЮБОЙ слой: снятая ручка сессии
            # или новый слой рецепта. Условие «только own» оставило бы switch без
            # ручек молча неприменённым — рецепт сменился, менеджеры прежние.
            if own or recipe is not None:
                apply_observability_layers(
                    layers,
                    logger=getattr(self, "logger_manager", None),
                    error=getattr(self, "error_manager", None),
                    stats=getattr(self, "stats_manager", None),
                    log_info=None,  # своё сообщение об охвате ниже
                    **telemetry_targets(self),
                    origin=origin,
                )
            # Advisory A2 ревью 5.9: у детей та же смена подписана `switch:broadcast`
            # (см. `_ORIGIN_SWITCH`) — оба написания начинаются с `switch:`, и
            # grep по одному находит другое. Разными они остаются намеренно:
            # оркестратор чистит СВОЙ слой, ребёнок — по рассылке, и в разборе
            # «у кого не сбросилось» это первый различающий признак.
        except Exception as exc:  # noqa: BLE001 — сброс не имеет права ронять switch
            self._log_error(f"_reset_observability_sessions({reason}): свой L3 не сброшен: {exc}")

        # R6-E: сброс L3 и новый слой L2 едут ОДНИМ конвертом. Двумя рассылками
        # каждый ребёнок делал две полные пересборки на один switch, а между ними
        # существовало окно, где сессия уже пуста, а слой рецепта ещё прежний —
        # состояние, которого не описывает ни один слой. Обработчик ребёнка умеет
        # оба ключа сразу и делает ОДНУ пересборку, порядок «снизу вверх» (слой
        # рецепта въезжает до сброса сессии) держит он же.
        payload: dict = {"observability_session_clear": True}
        if recipe:
            payload.update(recipe)
        reached = 0
        try:
            reached = self._broadcast_command("config.reload", payload)
        except Exception as exc:  # noqa: BLE001
            self._log_error(f"_reset_observability_sessions({reason}): рассылка не удалась: {exc}")

        if own or reached or own_recipe is not None:
            self._log_info(
                f"[observability] слой сессии сброшен ({reason}): свои ключи={own or '—'}, "
                f"свой слой рецепта={sorted(own_recipe) if own_recipe is not None else 'не менялся'}, "
                f"рассылка детям reached={reached}, слой рецепта={'в том же конверте' if recipe else 'не менялся'}"
            )
        result = {"orchestrator": own, "broadcast_reached": int(reached)}
        # Task 5.13: свой слой называется отдельно от детского. «Раздал всем» и
        # «применил себе» — разные утверждения, и до 5.13 второе было ложным при
        # истинном первом; слить их в одно поле значило бы снова сделать этот
        # разрыв ненаблюдаемым.
        if own_recipe is not None:
            result["orchestrator_recipe_keys"] = sorted(own_recipe)
        # Что именно уехало детям — в ответе: «раздал» и «раздал ЭТО» — разные
        # утверждения, а проверяется потом второе. Читаем ИЗ КОНВЕРТА, а не из
        # аргумента (находка 3 ревью 5.11): по аргументу ответ называл слой даже
        # тогда, когда тот не попал в рассылку, — то есть отвечал за намерение,
        # выдавая это за доставку.
        if "observability_recipe" in payload:
            result["recipe_path"] = payload.get("observability_recipe_path", "")
            result["recipe_keys"] = sorted(payload.get("observability_recipe") or {})
        return result

    def _broadcast_command(self, command: str, data: dict, *, queue_type: str = "system") -> int:
        """Единый примитив рассылки command-билета всем детям (Ф3.1 / PC 3.3).

        Строит command-конверт и отправляет существующим путём
        ``ProcessCommunication.broadcast(exclude_self=True)`` (system-очереди детей) —
        ТЕМ ЖЕ, которым едет routing.refresh: после hot-swap рассылка идёт по СВЕЖИМ
        очередям PM (он держатель актуального PSR), поэтому долетает и до процессов,
        пересозданных заменой рецепта.

        Исключения НЕ глотает (пробрасывает вызывающему) — так routing.refresh
        сохраняет своё поведение error-пути (лог «упал» + return False), а fan-out
        телеметрии решает по-своему. ``communication`` недоступен (минимальный/тестовый
        PM) → 0 (тихий no-op).

        **Резидуал 5.11-R4 — досылка не-готовым.** Ребёнок читает system-очередь с
        шага 7 ``initialize()``, а команды регистрирует в ``run()``: попавшее в это
        окно сообщение читается и выбрасывается (``No handler for key ...``), а
        отправитель fire-and-forget об этом не узнаёт никогда. Живой лог switch'а
        показал так и ``routing.refresh``, и ``config.reload``. Поэтому рассылка
        идёт как прежде — всем и сразу, — а тем, кто на этот момент готовности не
        объявил, тот же конверт досылается адресно за readiness-гейтом. Досылка
        живёт ЗДЕСЬ, а не в трёх вызывающих: список «не забыть» из трёх пунктов —
        ровно та форма, которой дефект уже воскресал на соседней развилке.

        Все команды этого пути идемпотентны (``routing.refresh`` — guard по epoch,
        ``config.reload`` — пересборка слоёв, ``telemetry.reconfigure`` —
        replace/merge, ``observability.tail.*`` — идемпотентны по подписчику),
        поэтому ребёнок, успевший стать готовым в зазоре, безопасно переживает
        двойную доставку.

        Returns:
            Число успешных доставок (охват) от ``comm.broadcast`` — доставок В
            ОЧЕРЕДЬ на момент рассылки. Досланные позже здесь НЕ учитываются:
            «раздал» и «применилось» — разные утверждения, и складывать их в одно
            число значило бы отвечать за второе, измерив первое.
        """
        comm = getattr(self, "communication", None)
        if comm is None:
            return 0
        msg = {
            "type": "command",
            "command": command,
            "sender": self.name,
            "queue_type": queue_type,
            "data": data,
        }
        reached = int(comm.broadcast(msg, exclude_self=True))
        self._redeliver_to_unready_children(command, data, queue_type=queue_type)
        return reached

    def _next_broadcast_generation(self, command: str) -> int:
        """Начать новое поколение рассылки команды и вернуть его номер.

        Поколение — на КОМАНДУ, не общее: ``config.reload`` и ``routing.refresh``
        живут своими жизнями, и свежий refresh не должен отменять досылку ещё
        актуального reload'а.
        """
        with self._broadcast_generations_lock:
            nxt = self._broadcast_generations.get(command, 0) + 1
            self._broadcast_generations[command] = nxt
            return nxt

    def _broadcast_generation(self, command: str) -> int:
        """Текущее (последнее) поколение рассылки команды."""
        with self._broadcast_generations_lock:
            return self._broadcast_generations.get(command, 0)

    @property
    def _broadcast_generations(self) -> dict:
        """Ленивый реестр поколений (та же философия, что ``_ensure_routing_state``:
        unit-тесты строят PM с no-op ``__init__``)."""
        gens = self.__dict__.get("_broadcast_generations_map")
        if gens is None:
            gens = {}
            self.__dict__["_broadcast_generations_map"] = gens
        return gens

    @property
    def _broadcast_generations_lock(self) -> threading.Lock:
        lock = self.__dict__.get("_broadcast_generations_lock_obj")
        if lock is None:
            lock = threading.Lock()
            self.__dict__["_broadcast_generations_lock_obj"] = lock
        return lock

    def _late_delivery_deadline(self) -> float:
        """Сколько ждать готовности ребёнка перед досылкой (``child_command_ready_timeout_s``).

        Отдельный ключ от ``observability_replay_ready_timeout_s`` намеренно:
        механизм ожидания один (:meth:`_run_when_child_ready`), а политика разная.
        Раздача подписок может ждать долго — подписчик всё равно молчит, пока не
        дождётся. Досылка lifecycle-команды ждать столько же не должна: рассылка
        привязана к событию (switch, рестарт), и через минуту она уже про прошлое.
        ``0`` → досылка выключена (аварийный откат к поведению до R4).
        """
        raw = self.get_config("child_command_ready_timeout_s")
        return 15.0 if raw is None else float(raw)

    def _log_redelivery(self, name: str, command: str, data: dict, *, queue_type: str) -> bool:
        """Отправить досылку и сказать вслух, чем она кончилась.

        Механизм, о котором нельзя спросить, через час неотличим от сломанного:
        «запланировал» и «доставил» — разные утверждения, а без второго в логе
        остаётся только намерение. Пара строк ЗАПЛАНИРОВАНА/ДОСТАВЛЕНА — то, по
        чему живой прогон отличает работающую досылку от заведённого потока.
        """
        delivered = self._send_child_command(name, command, data, queue_type=queue_type)
        if delivered:
            self._log_info(f"[ready-gate] '{command}' → '{name}': досылка доставлена (инкарнация готова)")
        else:
            self._log_error(f"[ready-gate] '{command}' → '{name}': досылка НЕ доставлена — команда потеряна")
        return delivered

    def _redeliver_to_unready_children(self, command: str, data: dict, *, queue_type: str) -> list[str]:
        """Досылать конверт тем детям, кто на момент рассылки ещё не готов её принять.

        Отбор — по ``ready_event``: событие есть и НЕ взведено. Нет события
        (mock-реестр, не-ProcessModule) → спрашивать не у кого, досылка не
        заводится: гадать «наверное, не готов» значило бы слать вторую копию
        всем и всегда.

        Returns:
            Имена, которым досылка запланирована (для лога и тестов).
        """
        deadline = self._late_delivery_deadline()
        if deadline <= 0:
            return []
        registry = getattr(self, "_process_registry", None)
        if registry is None:
            return []
        # Поколение рассылки ЭТОЙ команды. Досылка обязана нести содержимое своего
        # конверта — но только пока он последний: конверт switch'а A→B, доставленный
        # после конверта B→C, пересобирает у ребёнка слой ПОКИНУТОГО рецепта.
        # Идемпотентность тут не спасает: дубль безвреден, стейл-после-свежего нет
        # (ревью Fable, находка 1 — воспроизведено двумя switch подряд).
        generation = self._next_broadcast_generation(command)
        late: list[str] = []
        snapshot: dict | None = None
        for proc in list(getattr(registry, "os_processes", None) or []):
            name = getattr(proc, "name", None)
            if not name:
                continue
            event = self._child_ready_event(name)
            if event is None or event.is_set():
                continue
            if snapshot is None:
                # Досылка уходит секундами позже, а вызывающий волен переиспользовать
                # свой payload (так делает fan-out телеметрии). Уезжает СНИМОК того,
                # что реально ушло в рассылке, а не то, во что он превратился потом.
                snapshot = copy.deepcopy(data)
            late.append(name)
            self._run_when_child_ready(
                name,
                lambda n=name, d=snapshot: self._log_redelivery(n, command, d, queue_type=queue_type),
                label=f"redeliver:{command}",
                deadline_s=deadline,
                still_relevant=lambda g=generation: self._broadcast_generation(command) == g,
            )
        if late:
            self._log_info(
                f"[ready-gate] '{command}': досылка запланирована не-готовым {sorted(late)} "
                f"(дедлайн {deadline}s) — рассылка их обработчика не застала бы"
            )
        return late

    def _send_child_command(self, target: str, command: str, data: dict, *, queue_type: str = "system") -> bool:
        """Адресная отправка command-билета ОДНОМУ ребёнку (аналог :meth:`_broadcast_command`).

        Тот же конверт, что broadcast, но через ``comm.send_to_process(target, msg)`` —
        свежий PSR PM (долетает и до пересозданных hot-swap'ом процессов). Fire-and-forget:
        возвращает факт ДОСТАВКИ в очередь (bool), НЕ подтверждение применения — синхронный
        сбор ответа ребёнка в хендлере PM заблокировал бы message_processor (тот же дедлок,
        что описан в ``driver.capabilities``). ``communication`` недоступен / без
        ``send_to_process`` (минимальный/тестовый PM) → ``False`` (тихий no-op).

        Returns:
            ``True`` — билет доставлен в очередь адресата, иначе ``False``.
        """
        comm = getattr(self, "communication", None)
        if comm is None or not hasattr(comm, "send_to_process"):
            return False
        msg = {
            "type": "command",
            "command": command,
            "sender": self.name,
            "queue_type": queue_type,
            "data": data,
        }
        return bool(comm.send_to_process(target, msg))

    # -------------------------------------------------------------------------
    # Брокер подписки на наблюдаемость (Task 5.11)
    # -------------------------------------------------------------------------

    def _observability_broker_obj(self):
        """Ленивый брокер подписки (та же философия, что ``_ensure_routing_state``).

        Строится на уже существующих примитивах рассылки: ``_broadcast_command``
        (fan-out всем детям тем же путём, что routing.refresh — по СВЕЖИМ
        очередям PM, значит долетает и до пересозданных switch'ем) и
        ``_send_child_command`` (адресно одному). Свой хвост оркестратор ставит
        тем же ``subscribe_observability_tail``, что и любой процесс.
        """
        broker = getattr(self, "_observability_broker", None)
        if broker is None:
            from .observability_broker import ObservabilitySubscriptionBroker

            broker = ObservabilitySubscriptionBroker(
                broadcast=lambda command, data: self._broadcast_command(command, data),
                send_to=lambda target, command, data: self._send_child_command(target, command, data),
                subscribe_self=getattr(self, "subscribe_observability_tail", None),
                unsubscribe_self=getattr(self, "unsubscribe_observability_tail", None),
                log_info=self._log_info,
                log_error=self._log_error,
            )
            self._observability_broker = broker
        return broker

    def _forget_observability_session(self, session_id: str) -> None:
        """Снять намерения подписчика закрытой сессии (5.11-R1, сигнал от SocketChannel).

        Зовётся из read-потока канала. Ничего блокирующего здесь делать нельзя и не
        нужно: снятие — это правка словаря брокера под его же локом.
        """
        broker = getattr(self, "_observability_broker", None)
        if broker is None:
            return  # брокера не заводили — снимать нечего
        try:
            broker.forget_session(session_id)
        except Exception as exc:  # noqa: BLE001 — сигнал не имеет права ронять канал
            self._log_error(f"[observability] снятие намерений сессии '{session_id}' упало: {exc}")

    def _cmd_observability_tail_subscribe_all(self, data=None, **kwargs) -> dict:
        """Подписать адрес на хвост ВСЕХ процессов одним вызовом (Task 5.11).

        До брокера потребитель сам опрашивал топологию, сам крутил цикл подписок
        и сам ловил рестарты — каждый по-своему и каждый неполно (GUI не видел
        ручного рестарта, драйвер получил дедлок автоподписки из reader-потока).
        Здесь намерение записывается один раз, а разворачивает его тот, у кого
        есть сигнал «поднялась свежая инкарнация», — оркестратор.

        Параметры (data): ``subscriber`` (адрес получателя пушей, обяз.).
        """
        args = _merge_cmd_args(data, kwargs)
        return self._observability_broker_obj().subscribe_all(str(args.get("subscriber") or ""))

    def _cmd_observability_tail_unsubscribe_all(self, data=None, **kwargs) -> dict:
        """Снять намерение подписчика и разослать снятие хвоста всем процессам.

        ``subscriber`` обязателен: пустой адрес у процесса означает «снять всех»,
        и та же вольность здесь снесла бы хвост соседнего потребителя.
        """
        args = _merge_cmd_args(data, kwargs)
        return self._observability_broker_obj().unsubscribe_all(str(args.get("subscriber") or ""))

    def observability_introspect_extra(self) -> dict:
        """Хук ``introspect.observability``: секция брокера (Task 5.11).

        Оркестраторская часть readback'а — единственное место, где видно,
        КТО подписан на всё и доехала ли последняя раздача. Без неё «хвоста нет»
        неотличимо от «намерение снято».
        """
        return {"broker": self._observability_broker_obj().snapshot()}

    def _replay_observability_subscriptions(self, reason: str, *, target: str | None = None) -> dict:
        """Доиграть намерения подписки (шов инкарнации / смена топологии).

        Fire-and-forget по построению: PM не ждёт ответа ребёнка ни здесь, ни в
        хендлере команды. Именно это, а не договорённость «не звать из такого-то
        потока», делает дедлок-путь автоподписки невоспроизводимым.
        """
        broker = getattr(self, "_observability_broker", None)
        if broker is None:
            # Ни одного намерения не записано — строить брокер ради пустой
            # раздачи значит платить на КАЖДОМ старте процесса.
            return {"subscribers": [], "reached": 0}
        try:
            return broker.replay(target=target, reason=reason)
        except Exception as exc:  # noqa: BLE001 — раздача не имеет права ронять старт
            self._log_error(f"_replay_observability_subscriptions({reason}) упал: {exc}")
            return {"subscribers": [], "reached": 0, "error": str(exc)}

    def _refresh_after_topology(self, reason: str, executed: list | None) -> int | None:
        """Если топология что-то исполнила (executed непуст) — bump epoch + broadcast.

        Успех И rollback пересоздают очереди → в обоих случаях выжившие соседи
        обязаны сверить снимок. Возвращает новый epoch (или None, если нечего слать).
        """
        if not executed:
            return None
        epoch = self._bump_routing_epoch()
        self._broadcast_routing_refresh(reason)
        return epoch

    def _drain_process_queues(self, name: str) -> None:
        """Дренаж мусора прошлой жизни из очередей процесса (get_nowait до Empty).

        Осознанно НЕ ``clear_queue`` (тот спит ~0.2с/очередь на macOS). Перед
        рестартом с reuse_queues=True переиспользуемые очереди могут держать
        недочитанные билеты убитого процесса — сливаем их, чтобы новый инстанс
        стартовал с чистыми очередями. Best-effort, за guard'ами.
        """
        sr = getattr(self, "shared_resources", None)
        if sr is None:
            return
        try:
            pd = sr.get_process_data(name)
            queues = getattr(pd, "queues", None) if pd is not None else None
            if queues is None:
                return
            for q in list(queues.values()):
                if q is None:
                    continue
                for _ in range(10_000):
                    try:
                        q.get_nowait()
                    except Exception:  # noqa: BLE001 — Empty (и прочее) → стоп дренажа
                        break
        except Exception:  # noqa: BLE001 — дренаж не критичен
            pass

    def _process_queue_ids(self, name: str) -> dict[str, int]:
        """id() очередей процесса из PSR — для сверки identity до/после рестарта."""
        sr = getattr(self, "shared_resources", None)
        if sr is None:
            return {}
        try:
            pd = sr.get_process_data(name)
            queues = getattr(pd, "queues", None) if pd is not None else None
            if queues is None:
                return {}
            return {qt: id(q) for qt, q in queues.items()}
        except Exception:  # noqa: BLE001
            return {}

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

    def _live_child_names(self) -> list[str]:
        """Имена живых процессов-детей из PSR (для охвата fan-out), кроме себя.

        Тот же источник, что снимок routing.refresh (``get_process_names``) — после
        hot-swap отражает СВЕЖИЙ набор процессов. Best-effort: нет shared_resources /
        сбой → пустой список (охват = 0, видно в результате).
        """
        sr = getattr(self, "shared_resources", None)
        if sr is None:
            return []
        try:
            return sorted(n for n in sr.get_process_names() if n != self.name)
        except Exception:  # noqa: BLE001 — охват не критичен для применения
            return []

    def _cmd_telemetry_broadcast(self, data=None, **kwargs) -> dict:
        """Fan-out ИЛИ адресная telemetry-переконфигурация через PM + центральный троттл (PC 3.3 / Task 1.4).

        Закрывает пробел адресного ``telemetry.reconfigure`` (PC 3.1): рантайм-правка
        publisher-gate детей ОДНИМ вызовом (не по одному). Task 1.1: опциональный
        ``data["telemetry_mode"]`` (``"replace"`` по умолчанию | ``"merge"``) — общий
        режим применения обеих плоскостей; ``merge`` прокидывается детям и в central-throttle
        как дельта (точечная правка не стирает соседние правила/метрики). Контракт ``data``
        (обе под-секции опциональны, но нужна хотя бы одна — проверяем НАЛИЧИЕ ключа, т.к.
        ``publish=None`` валиден):

          - ``publish`` → ``telemetry.reconfigure {publish}`` детям. Адресация задаётся
            ``data["target"]`` (Task 1.4):

              * ``None`` / ``""`` / ``"all"`` / ``"*"`` → **fan-out ВСЕМ живым детям** через
                ``comm.broadcast(exclude_self=True)`` (:meth:`_broadcast_command` — тот же
                надёжный путь, что routing.refresh: свежие очереди PM после hot-swap);
              * имя процесса → **адресно ОДНОМУ ребёнку** через
                :meth:`_send_child_command` (``comm.send_to_process``). Транзит через PM —
                а не driver→child напрямую — чтобы PM (единственный держатель central-троттла)
                мог детектить ``capped_by_throttle`` на per-process пути (ADR-PM-017 Task 1.4).

            ``publish=None`` → выключить gate. **Fire-and-forget:** сообщается ОХВАТ
            ДОСТАВКИ (``reached`` / ``target_count``, «no silent caps»), НЕ per-child
            подтверждение применения (синхронный сбор ответа ребёнка дедлочил бы
            message_processor — см. :meth:`_send_child_command`).
          - ``throttle`` → применяется к ЦЕНТРАЛЬНОМУ ``ThrottleMiddleware`` самого
            оркестратора (держатель StateStoreManager) через единый
            ``apply_telemetry_reconfigure``; детям НЕ рассылается (у них нет
            StateStoreManager). ``target`` throttle НЕ касается — троттл оркестратор-глобален.
            Нет state-plane → ``applied=False`` (видно «нет приёмника»).

        Returns:
            Агрегированный dict (Dict at Boundary): ``publish``-охват (+ ``capped_by_throttle``
            при срезе) и/или ``throttle``-применение — по каждой ЗАПРОШЕННОЙ под-секции.
        """
        from ...process_module.managers.telemetry_reload import (
            VALID_MODES,
            apply_telemetry_reconfigure,
            detect_throttle_caps,
            resolve_store_throttle,
        )

        args = _merge_cmd_args(data, kwargs)
        has_publish = "publish" in args
        has_throttle = "throttle" in args
        if not has_publish and not has_throttle:
            return {"success": False, "reason": "нужна хотя бы одна под-секция: publish и/или throttle"}

        # Task 1.1: режим применения (replace|merge) — общий для обеих плоскостей.
        # Прокидывается детям в publish-broadcast и в central-throttle apply. На проводе
        # присутствует ТОЛЬКО при merge (replace = дефолт → бит-в-бит прежний конверт).
        # Task 1.2 (замечание ревьюера): валидируем mode ЗДЕСЬ, ДО fan-out — broadcast
        # fire-and-forget (ошибку детей никто не соберёт), поэтому битый mode не должен
        # уйти детям и молча «похорониться». Явная ошибка вместо тихого no-op.
        mode = str(args.get("telemetry_mode", "replace"))
        if mode not in VALID_MODES:
            return {
                "success": False,
                "process": self.name,
                "mode": mode,
                "reason": f"неизвестный telemetry mode={mode!r} (ожидается {VALID_MODES}); секция НЕ применена",
            }

        result: dict[str, Any] = {"success": True, "process": self.name}

        # Task 1.4: адресация publish. Пусто/all/* → fan-out всем; имя процесса → адресно
        # одному ребёнку транзитом через PM (throttle-плоскость от target не зависит —
        # троттл оркестратор-глобален, см. блок has_throttle ниже).
        target = args.get("target")
        addressed = target not in (None, "", "all", "*")

        if has_publish:
            publish_payload: dict[str, Any] = {"publish": args["publish"]}
            if mode != "replace":
                publish_payload["telemetry_mode"] = mode
            if addressed:
                # Адресно ОДНОМУ ребёнку (Task 1.4): fire-and-forget, охват = 0/1.
                try:
                    delivered = self._send_child_command(target, "telemetry.reconfigure", publish_payload)
                except Exception as exc:  # noqa: BLE001 — отправка не роняет применение throttle
                    self._log_error(f"telemetry.broadcast: publish адресно target={target!r} упал: {exc}")
                    delivered = False
                targets = [target]
                reached = 1 if delivered else 0
            else:
                targets = self._live_child_names()
                try:
                    reached = self._broadcast_command("telemetry.reconfigure", publish_payload)
                except Exception as exc:  # noqa: BLE001 — рассылка не роняет применение throttle
                    self._log_error(f"telemetry.broadcast: publish fan-out упал: {exc}")
                    reached = 0
            result["publish"] = {
                "requested": True,
                "target_count": len(targets),
                "reached": int(reached),
                "targets": targets,
                # Полный охват = доставили всем адресатам (иначе сигнал наверх).
                "complete": int(reached) >= len(targets),
                # Ф4 Task 4.2 (plans/truth-holes-closure.md): ЧЕСТНОЕ имя того, что
                # измеряет reached. Путь fire-and-forget (сбор ответов детей дедлочил бы
                # message_processor), поэтому reached = «сообщение положено в очередь
                # адресата», а НЕ «gate перестроен». Читатель, принимавший reached за
                # применение, ошибался в пользу системы — теперь семантика объявлена
                # в самом ответе. Проверка применения — readback introspect.telemetry
                # (Task 4.1) / driver telemetry_set(verify=True).
                "semantics": "delivered",
            }
            self._log_info(f"telemetry.broadcast: publish → target={target!r} reached={reached}/{len(targets)}")
            # Task 3.2: персист эффективной fan-out publish-дельты — доиграть пересозданным
            # детям после hot-swap/respawn (иначе новый ребёнок взял бы boot-конфиг, потеряв
            # рантайм-правку publisher-gate). Адресные (target=процесс) НЕ персистятся — они
            # per-child, а не системный runtime. publish=None (выключить gate) → сброс персиста.
            #
            # ПОСЛЕДОВАТЕЛЬНЫЕ merge-дельты АККУМУЛИРУЮТСЯ (deep_merge): telemetry_set работает
            # в merge — частый операторский сценарий из нескольких точечных правок. Хранить лишь
            # последнюю — потерять предыдущие при respawn (расхождение с выжившими детьми, которые
            # аккумулировали всё). replace семантически обнуляет прошлое → перезапись целиком.
            # ИЗВЕСТНЫЙ GAP: смешанные merge→replace→merge-цепочки полной эффективной-от-boot
            # модели не дают (replace сбрасывает накопленное) — приемлемо для рантайм-правок.
            if not addressed:
                if args["publish"] is None:
                    self._telemetry_runtime_delta = None
                else:
                    prev = getattr(self, "_telemetry_runtime_delta", None)
                    if (
                        mode == "merge"
                        and isinstance(prev, dict)
                        and prev.get("mode") == "merge"
                        and isinstance(prev.get("publish"), dict)
                        and isinstance(args["publish"], dict)
                    ):
                        from ...data_schema_module import deep_merge

                        self._telemetry_runtime_delta = {
                            "publish": deep_merge(prev["publish"], args["publish"]),
                            "mode": "merge",
                        }
                    else:
                        self._telemetry_runtime_delta = {"publish": args["publish"], "mode": mode}

        if has_throttle:
            try:
                applied = apply_telemetry_reconfigure(
                    {"throttle": args["throttle"]},
                    mode=mode,  # Task 1.1: merge → per-правило update/remove, replace → set_rules
                    heartbeat=None,  # publisher-gate детей идёт broadcast'ом (publish), не здесь
                    store_throttle=resolve_store_throttle(self),
                    log_info=getattr(self, "_log_info", None),
                )
                result["throttle"] = {"requested": True, "applied": bool(applied.get("throttle"))}
            except Exception as exc:  # noqa: BLE001 — ошибка throttle не должна терять уже совершённый publish-fan-out
                self._log_error(f"telemetry.broadcast: применение throttle упало: {exc}")
                result["throttle"] = {"requested": True, "applied": False, "error": str(exc)}

        if has_publish:
            # ADR-PM-017 (Task 1.3): «no silent caps». Если поднятие частоты метрики через
            # publisher уходит НИЖЕ действующего central-правила той же метрики — троттл
            # молча срезал бы его. Не режем тихо и не ослабляем страховку авто-магически:
            # возвращаем ЯВНЫЙ отчёт, чтобы инициатор увидел потолок и осознанно ослабил
            # central-правило (telemetry_set plane=throttle). Дефолт-троттл теперь мягче
            # публикатора (manager_setup), поэтому в дефолтном сценарии caps пуст и частота
            # реально растёт; флаг всплывает лишь при операторском строгом правиле.
            #
            # Ревью-фикс (#3): детектор зовётся ПОСЛЕ применения throttle-под-секции (блок
            # выше), а не до — иначе комбинированная команда {publish: raise, throttle: relax}
            # ловила бы ложноположительный cap по PRE-relax central-правилу (детектор читает
            # store_throttle.rules ЖИВЬЁМ — тот же объект, что мутирует _apply_throttle).
            caps = detect_throttle_caps(args["publish"], resolve_store_throttle(self))
            if caps:
                result["publish"]["capped_by_throttle"] = caps
                self._log_info(f"telemetry.broadcast: publish частично ограничен central-троттлом: {caps}")

        return result

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
        """Двухфазно: очереди для всех, затем create + start волнами по depends_on.

        Провал create → конфиг и provisioned-ресурсы (очереди/PSR) процесса
        откатываются: «призрак» (конфиг без Process-объекта) не должен
        попадать в ``_topology_current_names``/stop-фазу, а его очереди —
        в routing_map остальных детей.

        Ф5 3.9: если ``FW_DEPENDS_ON_BOOT_ORDER`` включён и хоть один процесс задал
        ``depends_on``, старт идёт волнами топосорта — перед каждой волной ждём
        self-reported ready её апстримов (``_wait_processes_ready``). Без depends_on
        (или флаг off / цикл) — одна плоская волна = прежнее поведение.
        """
        valid = [(n, c) for n, c in processes_config.items() if isinstance(c, dict) and c.get("class")]
        if not valid:
            return

        for name, proc_config in valid:
            self._process_configs[name] = copy.deepcopy(proc_config)
            if self.shared_resources:
                self.shared_resources.register_process(name, proc_config)

        ordered_names = [n for n, _ in valid]
        config_by_name = {n: c for n, c in valid}
        waves = self._plan_boot_waves(ordered_names, config_by_name)

        started: set[str] = set()
        timeout_s = self._boot_ready_timeout()
        for wave_index, wave in enumerate(waves):
            if wave_index > 0 and timeout_s > 0:
                # Гейт: дождаться ready апстримов этой волны, реально стартовавших.
                upstreams = sorted(
                    {d for name in wave for d in (config_by_name[name].get("depends_on") or []) if d in started}
                )
                if upstreams:
                    ready = self._wait_processes_ready(upstreams, timeout_s, "boot-deps")
                    # Не глотать сигнал: подтверждённо не-ready апстрим → зависимые
                    # волны стартуют ВСЁ РАВНО (boot не блокируем), но это должно быть
                    # видно на уровне гейта, а не тонуть в generic-warning примитива.
                    not_ready = sorted(n for n, ok in ready.items() if not ok)
                    if not_ready:
                        self._log_warning(
                            f"boot-deps: волна {wave_index} ({wave}) стартует при не-ready "
                            f"апстримах {not_ready} — зависимые могут не получить данные апстрима"
                        )
            for name in wave:
                if self._boot_create_and_start(config_by_name[name], name):
                    started.add(name)

    def _boot_create_and_start(self, proc_config: dict[str, Any], name: str) -> bool:
        """Создать+стартовать один процесс на boot. ``True`` если реально стартован.

        Провал create → откат конфига и ресурсов (не «призрак»), ``False``.
        """
        priority = proc_config.get("priority", "normal")
        if self._process_registry.create_and_register(name, proc_config["class"], proc_config, priority):
            self._priority.register_priority(name, priority)
            process = self._process_registry.get_process_by_name(name)
            if process:
                process.start()
                self._mark_instance_started(name)
                self._priority.apply_priority(process)
                return True
            return False
        self._log_error(f"boot: создание '{name}' не удалось — конфиг и ресурсы откатываются (не призрак)")
        self._cleanup_process_resources(name)
        self._process_configs.pop(name, None)
        return False

    def _boot_ready_timeout(self) -> float:
        """Таймаут ожидания ready на boot (``boot_ready_timeout_s``, дефолт 5.0с; 0 → без ожидания)."""
        raw = self.get_config("boot_ready_timeout_s")
        return 5.0 if raw is None else float(raw)

    def _plan_boot_waves(self, ordered_names: list[str], config_by_name: dict[str, dict[str, Any]]) -> list[list[str]]:
        """Волны старта по ``depends_on`` (Ф5 3.9).

        Флаг ``FW_DEPENDS_ON_BOOT_ORDER`` off / нет зависимостей / цикл в графе →
        одна плоская волна (исходный порядок, прежнее поведение). Рёбра на
        несуществующий процесс или сам-на-себя — отброшены с WARNING (boot не рушим).
        """
        if not is_enabled("FW_DEPENDS_ON_BOOT_ORDER"):
            return [ordered_names]
        valid_set = set(ordered_names)
        deps_map: dict[str, list[str]] = {}
        any_deps = False
        for name in ordered_names:
            deps: list[str] = []
            for d in config_by_name[name].get("depends_on") or []:
                if d == name:
                    self._log_warning(f"boot: '{name}' depends_on сам на себя — ребро отброшено")
                elif d not in valid_set:
                    self._log_warning(f"boot: '{name}' depends_on '{d}' — нет такого процесса, ребро отброшено")
                elif d not in deps:
                    deps.append(d)
            if deps:
                any_deps = True
            deps_map[name] = deps
        if not any_deps:
            return [ordered_names]
        waves, had_cycle = self._compute_boot_waves(ordered_names, deps_map)
        if had_cycle:
            self._log_error("boot: цикл в depends_on — плоский старт (порядок не гарантирован)")
            return [ordered_names]
        self._log_info(f"boot: depends_on-порядок, волн {len(waves)} (размеры {[len(w) for w in waves]})")
        return waves

    @staticmethod
    def _compute_boot_waves(ordered_names: list[str], deps_map: dict[str, list[str]]) -> tuple[list[list[str]], bool]:
        """Топосорт (Kahn) на волны. Внутри волны — исходный порядок ``ordered_names``.

        ``deps_map`` — уже отфильтрован (рёбра только на валидные процессы, без self).
        Возвращает ``(waves, had_cycle)``: при цикле ``([], True)`` — вызывающий
        делает плоский фолбэк.
        """
        remaining = {n: set(deps_map.get(n, ())) for n in ordered_names}
        waves: list[list[str]] = []
        placed: set[str] = set()
        while remaining:
            wave = [n for n in ordered_names if n in remaining and not (remaining[n] - placed)]
            if not wave:
                return [], True  # ни один узел не разрешим → цикл
            waves.append(wave)
            for n in wave:
                del remaining[n]
            placed.update(wave)
        return waves, False

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
        # Ж-4 (RS-3): shutdown ОБЯЗАН подтвердить смерть ВСЕХ детей. stop_all теперь
        # возвращает карту {name: stopped} (confirmed-death путь). Выживших — громко.
        stop_results = self._process_registry.stop_all(timeout=shutdown_timeout)
        if isinstance(stop_results, dict):
            survivors = sorted(n for n, ok in stop_results.items() if not ok)
            if survivors:
                self._log_error(
                    f"shutdown: дети ВЫЖИЛИ после остановки: {survivors} — смерть не подтверждена "
                    f"(ручное вмешательство/утечка процессов)"
                )
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
            self._mark_instance_started(process_name)
            self._priority.apply_priority(process)
            return True
        # Ф2 Task 2.1: отметку старта получают ТОЛЬКО реально стартовавшие.
        # start_all пропускает живых — если бы мы метили всех подряд, у живого
        # процесса started_at «омолаживался» бы без замены инстанса (pid тот же),
        # т.е. маркер врал бы ровно в ту сторону, против которой задача.
        was_dead = {p.name for p in self._process_registry.os_processes if not p.is_alive()}
        self._process_registry.start_all()
        for process in self._process_registry.os_processes:
            self._priority.apply_priority(process)
        # RS-2: boot-путь — опубликовать pid+config всех стартованных процессов.
        for process in self._process_registry.os_processes:
            if process.name in was_dead:
                self._mark_instance_started(process.name)
            self._publish_process_identity(process.name)
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
        """Перезапустить процесс: stop → снять с реестра → (reuse-очереди) → create → start.

        Ф3.1 (routing-epoch, дорога B): очереди процесса ПЕРЕИСПОЛЬЗУЮТСЯ
        (``reuse_queues=True``, конфиг-откат ``restart_reuse_queues: false``) —
        identity сохраняется, стейл-ссылки выживших соседей остаются валидными,
        hot-path не деградирует. Мусор прошлой жизни дренируется. Если identity
        всё же сменилась (reuse выключен) — соседям поднимается incarnation.
        В конце — bump epoch + broadcast refresh (декларативная сверка снимка).
        """
        config = self._process_configs.get(process_name)
        if not config:
            self._log_error(f"No saved config for '{process_name}'")
            return False
        if not self.stop_process(process_name):
            return False
        self._process_registry.remove_process(process_name)

        # Ф3.5: старый инстанс мёртв → задетые wire-провода реально оборваны.
        # Помечаем broken ДО пересоздания — монитор публикует broken_wires ≠ 0
        # в это окно (honest-статус, acceptance). Re-issue ниже вернёт «active».
        if self._wire_reissue_enabled():
            self._mark_wires_broken_for(process_name)

        reuse_cfg = self.get_config("restart_reuse_queues")
        reuse_queues = True if reuse_cfg is None else bool(reuse_cfg)  # дефолт True
        ids_before = self._process_queue_ids(process_name)
        if self.shared_resources:
            self.shared_resources.register_process(process_name, config, reuse_queues=reuse_queues)
            # Дренаж переиспользованных очередей: новый инстанс стартует чистым.
            self._drain_process_queues(process_name)
        ids_after = self._process_queue_ids(process_name)

        # Identity очередей сменилась → соседи должны сбросить стейл-ссылки. Bump
        # ДО create_and_register (как в _topology_provision): create_and_register
        # захватывает routing_meta-снимок (_routing_meta_snapshot) в bundle нового
        # инстанса. Если бампить ПОСЛЕ create, инстанс рождается со СТЕЙЛ incarnation
        # и штампует её в исходящие → PM/соседи дропают его легитимные сообщения как
        # stale (fence false-positive, ADR-PMM-014). Порядок обязан совпадать с seed.
        if ids_before != ids_after:
            self._bump_incarnation(process_name)

        priority = config.get("priority", "normal")
        process = self._process_registry.create_and_register(process_name, config["class"], config, priority)
        if not process:
            self._log_error(f"Failed to recreate process '{process_name}'")
            return False
        process.start()
        self._mark_instance_started(process_name)
        # Ф2 Task 2.1: инкремент БЕЗУСЛОВНЫЙ — в отличие от _bump_incarnation выше,
        # который срабатывает только при смене identity очередей (reuse=off).
        # Именно этот счётчик + новый pid делают reuse-рестарт видимым в supervision.
        # Считает ЛЮБУЮ замену инстанса через restart_process, включая авто-рестарт
        # монитора (он приходит той же командой process.restart) — см. __init__.
        restarts = getattr(self, "_instance_restarts", None)
        if restarts is None:
            restarts = {}
            self._instance_restarts = restarts
        restarts[process_name] = restarts.get(process_name, 0) + 1
        self._priority.register_priority(process_name, priority)
        self._priority.apply_priority(process)
        # Ф3.2: дождаться self-reported ready пересозданного инстанса (тот же
        # барьер на один процесс). Свежий ready_event создан create_and_register;
        # старый (у прежнего инстанса) не мешает — это другой объект.
        raw_timeout = self.get_config("start_ready_timeout_s")
        restart_timeout = 0.5 if raw_timeout is None else float(raw_timeout)
        if restart_timeout > 0:
            self._wait_processes_ready([process_name], restart_timeout, "restart")
        # Ф3.5: инстанс готов принимать команды (после _wait_processes_ready) —
        # переигрываем wire.configure в него (путь B: GUI-провода). Ортогонально
        # epoch/ready Ф3.1/Ф3.2 — не трогает их инварианты. Путь A (generic
        # data-path) самовосстанавливается через refresh ниже.
        if self._wire_reissue_enabled():
            self._reissue_wires_for(process_name)
        # Обновить epoch и разослать refresh (при reuse incarnation не менялась →
        # выжившие соседи оставят валидную переиспользованную очередь).
        self._bump_routing_epoch()
        self._broadcast_routing_refresh("process.restart")
        # RS-2: пересозданный инстанс имеет НОВЫЙ pid — обновить identity в state,
        # иначе в дереве навсегда остаётся pid мёртвого инстанса (нарушение инварианта).
        self._publish_process_identity(process_name)
        # Task 3.2: single-process respawn — доиграть runtime telemetry-дельту АДРЕСНО
        # пересозданному ребёнку (иначе он взял бы boot-конфиг, потеряв рантайм-правку
        # publisher-gate; тот же silent-loss, что закрыт для apply_topology).
        self._replay_telemetry_runtime_delta("process.restart", target=process_name)
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
        # --- Debounce: in-flight guard + cooldown (одна реализация, R6-G) ---
        debounced = self._topology_debounce_reject()
        if debounced is not None:
            return debounced

        # --- Проверка конфигурации ---
        if self._topology_manager is None:
            return {"success": False, "error": "TopologyManager not initialized"}
        if self._topology_manager._commands_fn is None:
            return {"success": False, "error": "topology not configured (no commands_fn)"}

        self._replace_in_progress = True
        # B-3 (RS-3): собираем неостановимые имена этого apply — поднимем в ответ
        # (согласованность с cleanup_failures/protected_conflicts). Обновляется в
        # _publish_unstoppable_alert (rollback/stop_all-fail) и чистится на успехе.
        self._last_unstoppable = []
        try:
            # Snapshot (non-protected) для rollback
            snapshot = self._snapshot_processes()

            # Ф3.5: switch сносит/пересоздаёт non-protected процессы → их
            # wire-провода на время замены оборваны. Помечаем broken ДО apply
            # (honest broken_wires в окне switch); success-ветка ниже переиграет
            # wire.configure в пересозданные инстансы и вернёт «active».
            if self._wire_reissue_enabled():
                for _sname in snapshot:
                    self._mark_wires_broken_for(_sname)

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
                            "apply_topology: провал до исполнения команд — топология не тронута, откат не требуется"
                        )
                    resp = {
                        "success": False,
                        "rolled_back": True,
                        **{k: v for k, v in result.items() if k != "success"},
                    }
                    # B-3: неостановимые имена этого rollback — в ответ (согласовано
                    # с cleanup_failures/protected_conflicts; retry на след. switch).
                    if self._last_unstoppable:
                        resp["unstoppable"] = list(self._last_unstoppable)
                    # Ф3.1: rollback тоже пересоздаёт очереди — разослать refresh.
                    epoch = self._refresh_after_topology("rollback", executed)
                    if epoch is not None:
                        resp["routing_epoch"] = epoch
                    return resp

                # Успех: readiness-барьер (Task 2.2) + ответ, совместимый с GUI
                ready = self._wait_started_ready(result.get("results") or [])
                # Ф3.5: пересозданные switch-ем процессы готовы → переиграть их
                # wire-провода (путь B). Провода, чьи endpoint'ы switch НЕ вернул,
                # остаются broken — это честный статус (монитор их учтёт).
                if self._wire_reissue_enabled():
                    for _rname in ready:
                        self._reissue_wires_for(_rname)
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
                # B-4 (RS-2): cleanup-хвост доисполнился, но часть старых ресурсов не
                # освободилась — громко (не тихий WARNING) наверх и в ObservabilityHub
                # (self._log_error → logger_manager → store-tap → вкладка Наблюдаемость).
                cleanup_failures = result.get("cleanup_failures") or []
                if cleanup_failures:
                    failed_names = sorted(r.get("process_name", "?") for r in cleanup_failures if isinstance(r, dict))
                    self._log_error(
                        f"apply_topology: cleanup не подтверждён для {failed_names} — "
                        f"топология применена, но их ресурсы/state могли остаться (ghost-риск)"
                    )
                # B-2 (RS-3): расхождение конфига protected-процесса между живым и
                # новым blueprint — switch НЕ «тихо успешен»: конфликты в ответе + громко.
                conflicts = self._collect_protected_conflicts()
                if conflicts:
                    response["protected_conflicts"] = conflicts
                    self._log_error(
                        f"apply_topology: protected-процессы с изменённым конфигом в новом рецепте "
                        f"{sorted(conflicts)} — protected не перезапускается, изменения НЕ применены "
                        f"(switch не тихо успешен)"
                    )
                # B-3 (RS-3): успешный switch без зависших — снять stale unstoppable-alert.
                self._publish_unstoppable_alert([])
                # Ф3.1: switch пересоздал очереди — bump epoch + broadcast refresh.
                epoch = self._refresh_after_topology("topology.apply", result.get("results") or [])
                if epoch is not None:
                    response["routing_epoch"] = epoch
                # Task 3.2: доиграть сохранённую runtime telemetry-дельту пересозданным
                # детям — runtime-состояние publisher-gate ≡ до свитча (не boot-дефолт).
                self._replay_telemetry_runtime_delta("topology.apply")
                # Task 5.12: наблюдаемость — НАОБОРОТ. Телеметрия доигрывается (её
                # runtime-дельта переживает switch намеренно), а слой сессии
                # наблюдаемости обнуляется: switch = новый конвейер = новая сессия.
                # Асимметрия осознанная — у телеметрии PM хранит дельту централизованно
                # и может её честно восстановить всем, а L3 живёт у каждого процесса
                # свой; «восстановить частично» дало бы лоскутное состояние.
                # R6-E: сброс сессии и слой нового рецепта — один конверт, одна
                # пересборка у ребёнка. Адрес берётся из конфига (его положил
                # ретаргет ДО сборки), а не приезжает вторым аргументом: при
                # прямом вызове `apply_topology` второй аргумент разошёлся бы с
                # тем, что реально записано в процессе.
                response["observability_session_reset"] = self._reset_observability_sessions(
                    "topology.apply",
                    recipe=self._recipe_layer_payload(blueprint),
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
                # Ф3.1: rollback пере-провижинил snapshot (новые incarnation) —
                # разослать refresh, чтобы выжившие сверили снимок.
                self._bump_routing_epoch()
                self._broadcast_routing_refresh("rollback")
                exc_resp = {
                    "success": False,
                    "rolled_back": True,
                    "error": str(exc),
                }
                if self._last_unstoppable:
                    exc_resp["unstoppable"] = list(self._last_unstoppable)
                return exc_resp

            finally:
                self._resume_monitor(monitor_was_running)

        finally:
            self._replace_in_progress = False
            self._last_replace_ts = time.monotonic()

    def _wait_processes_ready(self, names: list[str], timeout_s: float, reason: str) -> dict[str, bool]:
        """Ф3.2: ждать self-reported ready указанных процессов (event + death-watch).

        Общий примитив барьеров switch и boot. Цикл poll 0.05с до дедлайна:

        - ready_event ребёнка выставлен → ``True`` **немедленно** (ранний выход,
          здоровый процесс больше НЕ ждёт весь settle-window — acceptance Ф3.2);
        - процесс ПОДТВЕРЖДЁННО умер (нет в реестре / ``not is_alive``) → ``False``;
        - иначе процесс остаётся в ``pending`` до дедлайна.

        На дедлайне живые-без-event → ``True`` с WARNING «фолбэк по liveness»
        (прежнее death-watch поведение; так же ведёт себя mock без ready_event —
        существующие тесты зелёные без правок ожиданий).

        Строгую готовность здесь ждать НЕЛЬЗЯ через IPC: и heartbeat, и
        ``topology.apply`` обрабатываются ОДНИМ message_processor-потоком —
        ожидание заблокировало бы само себя. ready_event живёт ВНЕ message-loop
        (mp.Event, inheritance при spawn) → дедлок исключён.

        Args:
            names: имена процессов, чью готовность ждать.
            timeout_s: дедлайн ожидания (секунды).
            reason: метка контекста для логов («switch» / «boot» / «restart»).

        Returns:
            ``{name: bool}`` — ``True`` готов (по event или liveness-фолбэку),
            ``False`` подтверждённо мёртв.
        """
        # Guard: mock-реестр может не иметь get_ready_event → чистый death-watch.
        get_ready_event = getattr(self._process_registry, "get_ready_event", None)

        ready: dict[str, bool] = {}
        pending = set(names)
        deadline = time.monotonic() + timeout_s
        while pending and time.monotonic() < deadline:
            for name in list(pending):
                event = get_ready_event(name) if get_ready_event is not None else None
                if event is not None and event.is_set():
                    ready[name] = True
                    pending.discard(name)
                    self._log_info(f"{reason}: '{name}' ready via event")
                    continue
                proc = self._process_registry.get_process_by_name(name)
                if proc is None or not proc.is_alive():
                    ready[name] = False
                    pending.discard(name)
                    self._log_warning(f"{reason}: '{name}' умер до готовности → not-ready")
            if pending:
                time.sleep(0.05)
        for name in pending:
            ready[name] = True  # пережил окно — считаем работающим
            self._log_warning(f"{reason}: '{name}' ready via liveness-fallback (event не получен за {timeout_s}s)")
        return ready

    def _wait_boot_ready(self) -> None:
        """Ф3.2: boot-барьер — дождаться ready всех стартованных на boot детей.

        Вызывается в ``initialize()`` PM (initialize-поток, НЕ message_processor)
        ПЕРЕД ``_system_ready_event.set()``. Ждёт до ``boot_ready_timeout_s``
        (дефолт 5.0с; 0 → барьер выключен). По таймауту система стартует ВСЁ
        РАВНО (boot не блокировать навсегда) — не-ready логируются WARNING'ом.
        Медленный ребёнок (ML-веса) не ломает boot: liveness-фолбэк → ready.
        """
        timeout_s = self._boot_ready_timeout()
        if timeout_s <= 0:
            return
        names = [p.name for p in self._process_registry.os_processes]
        if not names:
            return
        ready = self._wait_processes_ready(names, timeout_s, "boot")
        not_ready = sorted(n for n, ok in ready.items() if not ok)
        if not_ready:
            self._log_warning(
                f"boot: процессы не сообщили ready за {timeout_s}s: {not_ready} — система стартует всё равно"
            )

    def _wait_started_ready(self, applied_results: list[dict]) -> dict[str, bool]:
        """Readiness-барьер после start-фазы switch: ready_event + death-watch.

        Ф3.2: ребёнок сам сигналит готовность (``ready_event`` после успешного
        ``initialize()``) — здоровый switch закрывается по факту, НЕ по таймеру.
        Ребёнок, упавший в ``initialize()``, выходит с exitcode 0 → death-watch
        ловит его как ``False`` (типовой случай: камера ещё занята предыдущим
        владельцем). Окно ``start_ready_timeout_s`` (дефолт 0.5с; 0 → выключен)
        остаётся фолбэком: медленный ребёнок, не успевший поставить event, но
        живой на дедлайне, считается работающим (WARNING).

        Строгую готовность (первый heartbeat) через IPC здесь ждать НЕЛЬЗЯ:
        heartbeat и ``topology.apply`` — один message_processor-поток; ready_event
        живёт вне message-loop (см. ``_wait_processes_ready``).

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
        # НЕ «or 0.5»: явный 0 в конфиге = барьер выключен, or съел бы его
        raw_timeout = self.get_config("start_ready_timeout_s")
        timeout_s = 0.5 if raw_timeout is None else float(raw_timeout)
        if timeout_s <= 0:
            return {}
        return self._wait_processes_ready(started, timeout_s, "switch")

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
            # B-3 (RS-3): alert в state/hub — зависшие имена видны, retry на след. switch.
            self._publish_unstoppable_alert(failed)
            return False
        return True

    def _topology_cleanup(self, name: str) -> bool:
        """Сид cleanup: снять с реестра + освободить SHM + удалить конфиг.

        Единственная мутация: удаление процесса из реестра, освобождение
        его SHM-ресурсов и удаление записи из ``_process_configs``.

        Порядок обязателен: конфиг снимается ПЕРВЫМ, и только потом идёт
        cleanup (внутри которого — ``_delete_process_state``). Иначе между
        удалением поддерева и снятием конфига остаётся окно, в котором процесс
        ещё «известен» гейту топологии, и поздний ``state.set`` от умирающего
        инстанса воскрешает узел — ровно та гонка, ради которой гейт заведён.
        """
        self._process_configs.pop(name, None)
        self._cleanup_process_resources(name)
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
            # Ф3.1: провижининг создаёт свежие очереди → новая incarnation
            # (выжившие соседи по расхождению сбросят стейл-ссылку на них).
            self._bump_incarnation(name)

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
        RS-2: после успешного старта публикует ОС-идентичность (pid + config
        нового рецепта) в StateStore — state сходится с ОС-реальностью.
        """
        started = self.start_process(name)
        if started:
            self._publish_process_identity(name)
        return started
