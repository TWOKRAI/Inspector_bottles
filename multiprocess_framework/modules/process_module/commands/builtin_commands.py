"""BuiltinCommands — встроенные команды ProcessModule через IProcessServices.

- worker.pause_all / worker.resume_all — управление воркерами
- wire.configure / wire.deconfigure — runtime-настройка SHM-каналов
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class BuiltinCommands:
    """Встроенные команды ProcessModule через IProcessServices.

    - worker.pause_all / worker.resume_all
    - wire.configure / wire.deconfigure
    """

    def __init__(self, services: Any) -> None:
        """
        Args:
            services: объект удовлетворяющий IProcessServices
        """
        self._services = services
        # Трекинг wire middleware (wire_key → (middleware_instance, role))
        self._wire_middlewares: dict[str, tuple] = {}

    def register(self) -> None:
        """Зарегистрировать все встроенные команды."""
        self._register_worker_commands()
        self._register_worker_crud_commands()
        self._register_wire_commands()
        self._register_introspect_commands()
        self._register_observability_commands()
        self._register_health_commands()
        self._register_relay_commands()

    # ========================================================================
    # КОМАНДЫ УПРАВЛЕНИЯ ВОРКЕРАМИ
    # ========================================================================

    def _register_worker_commands(self) -> None:
        """Зарегистрировать worker.pause_all / worker.resume_all."""
        cm = self._services.command_manager
        if not cm:
            _log = getattr(self._services, "_log_debug", None) or getattr(
                self._services, "log_info", lambda m, **kw: None
            )
            _log(
                "command_manager недоступен — встроенные команды воркеров не зарегистрированы",
                module="lifecycle",
            )
            return

        services = self._services

        def pause_all_handler(data=None, **kwargs) -> dict:
            """Поставить все прикладные воркеры на паузу."""
            if not services.worker_manager:
                return {"success": False, "reason": "worker_manager недоступен"}
            services.worker_manager.pause_all_workers(exclude_system=True)
            # Обновляем статус — он попадёт в следующий heartbeat
            services._current_process_status = "paused"
            services._log_info(f"Процесс '{services.name}' переведён в паузу", module="lifecycle")
            return {"success": True, "status": "paused"}

        def resume_all_handler(data=None, **kwargs) -> dict:
            """Возобновить все прикладные воркеры."""
            if not services.worker_manager:
                return {"success": False, "reason": "worker_manager недоступен"}
            services.worker_manager.resume_all_workers(exclude_system=True)
            # Возвращаем статус "running"
            services._current_process_status = "running"
            services._log_info(f"Процесс '{services.name}' возобновлён", module="lifecycle")
            return {"success": True, "status": "running"}

        cm.register_command(
            "worker.pause_all",
            pause_all_handler,
            metadata={"description": "Поставить все прикладные воркеры процесса на паузу"},
            tags=["system"],
        )
        cm.register_command(
            "worker.resume_all",
            resume_all_handler,
            metadata={"description": "Возобновить все прикладные воркеры процесса"},
            tags=["system"],
        )
        services._log_debug(
            "Встроенные команды worker.pause_all/resume_all зарегистрированы",
            module="lifecycle",
        )

    # ========================================================================
    # WORKER CRUD — создание/удаление/настройка отдельных воркеров (IPC из GUI)
    # ========================================================================

    def _register_worker_crud_commands(self) -> None:
        """Зарегистрировать worker.create / remove / update / restart / stop.

        Команды адресуются конкретному процессу-владельцу (target=process_name) и
        приходят через message_processor → CommandManager. Защищённые воркеры
        (message_processor, SYSTEM) нельзя remove/stop/restart/update.
        """
        cm = self._services.command_manager
        if not cm:
            return

        specs = [
            ("worker.create", self._cmd_worker_create, "Создать воркер в процессе"),
            ("worker.remove", self._cmd_worker_remove, "Удалить воркер из процесса"),
            ("worker.update", self._cmd_worker_update, "Перенастроить воркер (приоритет/интервал)"),
            ("worker.restart", self._cmd_worker_restart, "Перезапустить воркер"),
            ("worker.start", self._cmd_worker_start, "Запустить остановленный воркер"),
            ("worker.stop", self._cmd_worker_stop, "Остановить воркер (без удаления)"),
        ]
        for name, handler, desc in specs:
            cm.register_command(name, handler, metadata={"description": desc}, tags=["system"])
        self._services._log_debug(
            "Встроенные команды worker.create/remove/update/restart/start/stop зарегистрированы",
            module="lifecycle",
        )

    @staticmethod
    def _merge_args(data, kwargs) -> dict:
        """Слить data-dict и kwargs (паттерн handlers data=None/**kwargs)."""
        args: dict = {}
        if isinstance(data, dict):
            args.update(data)
        args.update(kwargs)
        return args

    def _resolve_worker_target(self, worker_class: str | None, worker_cfg: dict):
        """Создать инстанс воркера и вернуть его target callable (instance.run).

        worker_class=None → generic IdleWorker. Иначе — импорт по dotted-path.
        Возвращает (target, error_reason). target=None при ошибке.
        """
        try:
            if not worker_class:
                from ..generic.idle_worker import IdleWorker

                instance = IdleWorker(process=self._services, config=worker_cfg)
            else:
                import importlib

                module_path, class_name = worker_class.rsplit(".", 1)
                module = importlib.import_module(module_path)
                cls = getattr(module, class_name)
                instance = cls(process=self._services, config=worker_cfg)
            target = getattr(instance, "run", instance)
            return target, None
        except Exception as exc:  # noqa: BLE001 — возвращаем причину наверх
            return None, str(exc)

    def _build_thread_config(self, args: dict):
        """Собрать ThreadConfig из args (priority/execution_mode/worker_type)."""
        from multiprocess_framework.modules.worker_module.core.thread_config import ThreadConfig

        return ThreadConfig.from_dict(
            {
                "priority": str(args.get("priority", "NORMAL")),
                "execution_mode": str(args.get("execution_mode", "loop")),
                "worker_type": str(args.get("worker_type", "application")),
                "restart_on_failure": bool(args.get("restart_on_failure", False)),
                "max_restarts": int(args.get("max_restarts", 3)),
            }
        )

    @staticmethod
    def _build_worker_cfg(args: dict) -> dict:
        """Собрать payload-config воркера (target_interval_ms/execution_mode + extra)."""
        worker_cfg = dict(args.get("config") or {})
        if args.get("target_interval_ms") is not None:
            worker_cfg["target_interval_ms"] = args.get("target_interval_ms")
        worker_cfg.setdefault("execution_mode", str(args.get("execution_mode", "loop")))
        return worker_cfg

    def _cmd_worker_create(self, data=None, **kwargs) -> dict:
        """Создать и запустить воркер. data: worker_name, priority?, execution_mode?,
        target_interval_ms?, worker_class?, config?."""
        args = self._merge_args(data, kwargs)
        wm = self._services.worker_manager
        if not wm:
            return {"success": False, "reason": "worker_manager недоступен"}

        name = str(args.get("worker_name", "")).strip()
        if not name:
            return {"success": False, "reason": "worker_name обязателен"}
        if wm.has_worker(name):
            return {"success": False, "reason": f"воркер '{name}' уже существует"}

        worker_cfg = self._build_worker_cfg(args)
        target, err = self._resolve_worker_target(args.get("worker_class"), worker_cfg)
        if target is None:
            return {"success": False, "reason": f"не удалось создать воркер: {err}"}

        thread_config = self._build_thread_config(args)
        ok = wm.create_worker(name, target, thread_config, auto_start=True)
        if ok:
            self._services._log_info(
                f"worker.create: воркер '{name}' создан и запущен (priority={args.get('priority', 'NORMAL')})",
                module="lifecycle",
            )
        return {"success": bool(ok), "worker_name": name}

    def _cmd_worker_remove(self, data=None, **kwargs) -> dict:
        """Удалить воркер (stop + unregister). Защищённые — запрещены."""
        args = self._merge_args(data, kwargs)
        wm = self._services.worker_manager
        if not wm:
            return {"success": False, "reason": "worker_manager недоступен"}

        name = str(args.get("worker_name", "")).strip()
        if not name:
            return {"success": False, "reason": "worker_name обязателен"}
        if wm.is_worker_protected(name):
            return {"success": False, "reason": "protected", "worker_name": name}

        ok = wm.remove_worker(name)
        return {"success": bool(ok), "worker_name": name}

    def _cmd_worker_stop(self, data=None, **kwargs) -> dict:
        """Остановить воркер (поток), оставив в реестре. Защищённые — запрещены."""
        args = self._merge_args(data, kwargs)
        wm = self._services.worker_manager
        if not wm:
            return {"success": False, "reason": "worker_manager недоступен"}

        name = str(args.get("worker_name", "")).strip()
        if not name:
            return {"success": False, "reason": "worker_name обязателен"}
        if wm.is_worker_protected(name):
            return {"success": False, "reason": "protected", "worker_name": name}

        ok = wm.stop_worker(name)
        return {"success": bool(ok), "worker_name": name}

    def _cmd_worker_start(self, data=None, **kwargs) -> dict:
        """Запустить остановленный воркер (поток), не пересоздавая его.

        Старт безопасен — protected-проверка не нужна (в отличие от stop/remove).
        """
        args = self._merge_args(data, kwargs)
        wm = self._services.worker_manager
        if not wm:
            return {"success": False, "reason": "worker_manager недоступен"}

        name = str(args.get("worker_name", "")).strip()
        if not name:
            return {"success": False, "reason": "worker_name обязателен"}

        ok = wm.start_worker(name)
        return {"success": bool(ok), "worker_name": name}

    def _cmd_worker_restart(self, data=None, **kwargs) -> dict:
        """Перезапустить воркер. Защищённые — запрещены."""
        args = self._merge_args(data, kwargs)
        wm = self._services.worker_manager
        if not wm:
            return {"success": False, "reason": "worker_manager недоступен"}

        name = str(args.get("worker_name", "")).strip()
        if not name:
            return {"success": False, "reason": "worker_name обязателен"}
        if wm.is_worker_protected(name):
            return {"success": False, "reason": "protected", "worker_name": name}

        ok = wm.restart_worker(name)
        return {"success": bool(ok), "worker_name": name}

    def _cmd_worker_update(self, data=None, **kwargs) -> dict:
        """Перенастроить воркер: remove + create с новыми параметрами.

        Защищённый воркер пересоздавать нельзя (теряется IPC-lifeline) → запрет.
        """
        args = self._merge_args(data, kwargs)
        wm = self._services.worker_manager
        if not wm:
            return {"success": False, "reason": "worker_manager недоступен"}

        name = str(args.get("worker_name", "")).strip()
        if not name:
            return {"success": False, "reason": "worker_name обязателен"}
        if wm.is_worker_protected(name):
            return {"success": False, "reason": "protected", "worker_name": name}
        if not wm.has_worker(name):
            return {"success": False, "reason": f"воркер '{name}' не найден"}

        worker_cfg = self._build_worker_cfg(args)
        target, err = self._resolve_worker_target(args.get("worker_class"), worker_cfg)
        if target is None:
            return {"success": False, "reason": f"не удалось пересоздать воркер: {err}"}

        wm.remove_worker(name)
        thread_config = self._build_thread_config(args)
        ok = wm.create_worker(name, target, thread_config, auto_start=True)
        if ok:
            self._services._log_info(
                f"worker.update: воркер '{name}' перенастроен (priority={args.get('priority', 'NORMAL')})",
                module="lifecycle",
            )
        return {"success": bool(ok), "worker_name": name}

    # ========================================================================
    # INTROSPECT COMMANDS — «что у меня есть» (P1, backend-control-mcp)
    # ========================================================================

    def _register_introspect_commands(self) -> None:
        """Зарегистрировать introspect.handlers / registers / status.

        Generic-инструмент диагностики процесса: отвечает «какие приёмники,
        регистры и воркеры у меня есть». Ловит баги вида «нет приёмника
        register_update» (ключа нет в handlers) мгновенно, без драйва GUI.
        Возвращают dict (Dict at Boundary); ответ инициатору едет через
        request-response (P0.5: reply_to_request на generic command-пути).
        """
        cm = self._services.command_manager
        if not cm:
            return

        specs = [
            (
                "introspect.handlers",
                self._cmd_introspect_handlers,
                "Router message-handlers + команды CommandManager процесса",
            ),
            (
                "introspect.registers",
                self._cmd_introspect_registers,
                "Регистры процесса (имена + поля) из RegistersManager",
            ),
            ("introspect.status", self._cmd_introspect_status, "Имя процесса, статус, воркеры (имена + статусы)"),
            (
                "introspect.router_stats",
                self._cmd_introspect_router_stats,
                "Счётчики router'а: sent_ok/received/dropped/errors (дошло ли сообщение)",
            ),
            (
                "introspect.queues",
                self._cmd_introspect_queues,
                "Глубины очередей процесса (backpressure)",
            ),
            (
                "introspect.capabilities",
                self._cmd_introspect_capabilities,
                "Карточка процесса для «контактной книжки»: команды+descriptions, регистры (поля), router-handlers",
            ),
        ]
        for name, handler, desc in specs:
            cm.register_command(name, handler, metadata={"description": desc}, tags=["system"])
        self._services._log_debug(
            "Встроенные команды introspect.* зарегистрированы",
            module="lifecycle",
        )

    def _cmd_introspect_handlers(self, data=None, **kwargs) -> dict:
        """Приёмники процесса: ключи router event_dispatcher + команды CommandManager.

        P4.4.1 (B2): команды (type=="command", вкл. register_update/process.command/
        state.*) приходят через kind-router → CommandManager → поле ``commands``.
        ``router_handlers`` (event_dispatcher) держит НЕ-командные ключи: события
        (state.changed), heartbeat и т.п. Отсутствие ожидаемого ключа в нужном поле
        = диагноз (находка Этапа 2).
        """
        svc = self._services
        router_handlers: list = []
        router = svc.router_manager
        md = getattr(router, "event_dispatcher", None) if router else None
        if md is not None:
            try:
                router_handlers = [h.get("key") for h in md.get_all_handlers()]
            except Exception as exc:  # noqa: BLE001
                return {"success": False, "reason": f"event_dispatcher: {exc}"}

        commands: list = []
        cm = svc.command_manager
        if cm is not None:
            try:
                commands = [c.get("key") for c in cm.get_commands()]
            except Exception as exc:  # noqa: BLE001
                return {"success": False, "reason": f"command_manager: {exc}"}

        return {
            "success": True,
            "process": svc.name,
            "router_handlers": sorted({k for k in router_handlers if k}),
            "commands": sorted({k for k in commands if k}),
        }

    def _cmd_introspect_registers(self, data=None, **kwargs) -> dict:
        """Регистры процесса (имена + поля) из RegistersManager оркестратора.

        Пусто, если у процесса нет плагинов с register_schema — это само по себе
        диагностично (нет регистров → некуда применять register_update, Этап 2).
        """
        svc = self._services
        orchestrator = getattr(svc, "_orchestrator", None)
        rm = getattr(orchestrator, "registers_manager", None) if orchestrator else None
        if rm is None:
            return {
                "success": True,
                "process": svc.name,
                "registers": {},
                "note": "нет RegistersManager (плагины без register_schema)",
            }
        try:
            registers = rm.model_dump_all()
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "reason": f"model_dump_all: {exc}"}
        return {"success": True, "process": svc.name, "registers": registers}

    def _cmd_introspect_status(self, data=None, **kwargs) -> dict:
        """Имя процесса, статус, воркеры (имена + сериализуемые статусы)."""
        svc = self._services
        workers: dict = {}
        wm = svc.worker_manager
        if wm is not None:
            try:
                workers = wm.get_all_workers_status()
            except Exception as exc:  # noqa: BLE001
                return {"success": False, "reason": f"worker_manager: {exc}"}
        return {
            "success": True,
            "process": svc.name,
            "status": getattr(svc, "_current_process_status", "unknown"),
            "workers": workers,
        }

    def _cmd_introspect_capabilities(self, data=None, **kwargs) -> dict:
        """Карточка процесса для «контактной книжки» (Ф1 Task 1.9, capability manifest v0).

        Свод КОНТРАКТА процесса (не runtime-значений — они в introspect.status/registers):
          - ``commands``: [{name, description, tags}] из CommandManager (metadata.description
            существующих регистраций — новый реестр НЕ вводится);
          - ``registers``: {имя_регистра: [имена_полей]} — только структура, без значений
            (детерминизм дампа: значения волатильны, контракт — нет);
          - ``router_handlers``: НЕ-командные ключи event_dispatcher (события, heartbeat).

        Расширение хоста: если у services есть callable ``capabilities_extra`` —
        его dict вливается в карточку (PM добавляет топологию процессов и каналы).
        Так PM не пере-регистрирует ключ (ExactMatch запрещает дубликаты), а v0
        обходится без блокирующего fan-out внутри PM-хендлера (ответы детей едут
        через тот же message_processor → блокировка была бы дедлоком; свод по
        живым детям собирает driver.capabilities()).
        """
        svc = self._services

        commands: list = []
        cm = svc.command_manager
        if cm is not None:
            try:
                for h in cm.get_commands():
                    meta = h.get("metadata") or {}
                    commands.append(
                        {
                            "name": h.get("key"),
                            "description": str(meta.get("description") or ""),
                            "tags": sorted(h.get("tags") or []),
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                return {"success": False, "reason": f"command_manager: {exc}"}
        commands = sorted((c for c in commands if c["name"]), key=lambda c: c["name"])

        router_handlers: list = []
        router = svc.router_manager
        md = getattr(router, "event_dispatcher", None) if router else None
        if md is not None:
            try:
                router_handlers = sorted({h.get("key") for h in md.get_all_handlers() if h.get("key")})
            except Exception as exc:  # noqa: BLE001
                return {"success": False, "reason": f"event_dispatcher: {exc}"}

        registers: dict = {}
        orchestrator = getattr(svc, "_orchestrator", None)
        rm = getattr(orchestrator, "registers_manager", None) if orchestrator else None
        if rm is not None:
            try:
                dump = rm.model_dump_all()
            except Exception as exc:  # noqa: BLE001
                return {"success": False, "reason": f"model_dump_all: {exc}"}
            for reg_name, fields in (dump or {}).items():
                registers[reg_name] = sorted(fields) if isinstance(fields, dict) else []

        card = {
            "success": True,
            "process": svc.name,
            "commands": commands,
            "router_handlers": router_handlers,
            "registers": registers,
        }

        extra_fn = getattr(svc, "capabilities_extra", None)
        if callable(extra_fn):
            try:
                extra = extra_fn()
            except Exception as exc:  # noqa: BLE001
                return {"success": False, "reason": f"capabilities_extra: {exc}"}
            if isinstance(extra, dict):
                card.update(extra)
        return card

    def _cmd_introspect_router_stats(self, data=None, **kwargs) -> dict:
        """Счётчики router'а процесса: отвечает «дошло/ушло/дропнулось ли сообщение».

        Ключевая диагностика на таймауте: sent_ok/received/errors/middleware_dropped
        показывают, добралось ли отправленное и не съела ли его middleware.
        """
        svc = self._services
        router = svc.router_manager
        if router is None or not hasattr(router, "get_stats"):
            return {"success": True, "process": svc.name, "router_stats": {}, "note": "нет router_manager"}
        try:
            stats = router.get_stats()
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "reason": f"get_stats: {exc}"}
        # get_stats() возвращает {"router": {...счётчики...}, ...}; берём router-секцию
        router_stats = stats.get("router", stats) if isinstance(stats, dict) else {}
        return {"success": True, "process": svc.name, "router_stats": router_stats}

    def _cmd_introspect_queues(self, data=None, **kwargs) -> dict:
        """Глубины собственных очередей процесса (backpressure-диагностика).

        Растущая system/data-очередь = процесс не успевает разгребать вход —
        частая причина «команда/кадр будто не доходит».
        """
        svc = self._services
        sizes: dict = {}
        queues = getattr(svc, "queues", None)
        if isinstance(queues, dict):
            for qtype, queue in queues.items():
                try:
                    sizes[qtype] = queue.qsize()
                except (NotImplementedError, OSError, AttributeError):
                    sizes[qtype] = None  # qsize недоступен (macOS) — диагностично само по себе
        return {"success": True, "process": svc.name, "queue_sizes": sizes}

    # ========================================================================
    # OBSERVABILITY CONTROL PLANE — config.reload / logger.sink.* (Ф1 Task 1.4)
    # Реализация ADR-CRM-006 п.3 поверх ГОТОВЫХ reconfigure/sink-реестра.
    # ========================================================================

    def _register_observability_commands(self) -> None:
        """Зарегистрировать config.reload / logger.sink.enable / logger.sink.disable.

        IPC-двойник hot-reload watcher'а (тот живёт в оркестраторе, эти команды
        адресуются ЛЮБОМУ процессу). Оба пути идут через один
        ``apply_observability_reconfigure`` → ``reconfigure`` — не конфликтуют.
        """
        cm = self._services.command_manager
        if not cm:
            return

        specs = [
            (
                "config.reload",
                self._cmd_config_reload,
                "Перечитать/применить секцию observability (уровень логов, sink'и) на лету",
            ),
            (
                "logger.sink.enable",
                self._cmd_logger_sink_enable,
                "Включить sink логгера по имени (register_channel)",
            ),
            (
                "logger.sink.disable",
                self._cmd_logger_sink_disable,
                "Выключить sink логгера по имени (unregister_channel)",
            ),
            (
                "log.tail.subscribe",
                self._cmd_log_tail_subscribe,
                "Подписать адрес на LogRecord'ы процесса с level ≥ порога (router-push)",
            ),
            (
                "log.tail.unsubscribe",
                self._cmd_log_tail_unsubscribe,
                "Снять подписку на tail логов процесса",
            ),
        ]
        for name, handler, desc in specs:
            cm.register_command(name, handler, metadata={"description": desc}, tags=["system"])
        self._services._log_debug(
            "Встроенные команды config.reload / logger.sink.* / log.tail.* зарегистрированы",
            module="lifecycle",
        )

    def _cmd_config_reload(self, data=None, **kwargs) -> dict:
        """Перечитать observability-секцию и применить через reconfigure (Ф1 Task 1.4).

        Источник секции (по приоритету):
          1. ``data["observability"]`` — inline-override (dict), например
             ``{"log_level": "DEBUG"}`` — сменить уровень логгера на лету через driver;
          2. файл конфига по ``data["path"]`` или ``get_config("observability_config_path")``
             (тот же путь, что читает hot-reload watcher).

        Применение делегируется в ``apply_observability_reconfigure`` — ЕДИНЫЙ путь с
        watcher'ом (идемпотентный full-rebuild ``reconfigure``, конфликта нет).
        """
        args = self._merge_args(data, kwargs)
        svc = self._services

        section = args.get("observability")
        source = "inline"
        if not isinstance(section, dict):
            path = args.get("path") or (
                svc.get_config("observability_config_path") if hasattr(svc, "get_config") else None
            )
            if not path:
                return {"success": False, "reason": "нет секции observability и пути к конфигу"}
            try:
                from ...data_schema_module.serialization.converter import DataConverter

                loaded = DataConverter.load_from_file(path)
            except Exception as exc:  # noqa: BLE001 — вернуть причину инициатору
                return {"success": False, "reason": f"не удалось прочитать конфиг {path}: {exc}"}
            section = (loaded.get("observability", {}) if isinstance(loaded, dict) else {}) or {}
            source = str(path)

        from ..managers.observability_reload import apply_observability_reconfigure

        try:
            expanded = apply_observability_reconfigure(
                section,
                logger=getattr(svc, "logger_manager", None),
                error=getattr(svc, "error_manager", None),
                stats=getattr(svc, "stats_manager", None),
                log_info=getattr(svc, "_log_info", None),
            )
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "reason": f"reconfigure failed: {exc}"}

        return {
            "success": True,
            "process": svc.name,
            "source": source,
            "applied": {"log_level": expanded["logger"].get("default_level")},
        }

    def _cmd_logger_sink_enable(self, data=None, **kwargs) -> dict:
        """Включить sink логгера по имени (ADR-CRM-006 п.3: register_channel)."""
        return self._toggle_logger_sink(data, kwargs, enabled=True)

    def _cmd_logger_sink_disable(self, data=None, **kwargs) -> dict:
        """Выключить sink логгера по имени (ADR-CRM-006 п.3: unregister_channel)."""
        return self._toggle_logger_sink(data, kwargs, enabled=False)

    def _toggle_logger_sink(self, data, kwargs, *, enabled: bool) -> dict:
        """Общий обработчик logger.sink.enable|disable — делегирует в set_sink_enabled."""
        args = self._merge_args(data, kwargs)
        svc = self._services
        name = str(args.get("sink") or args.get("name") or "").strip()
        if not name:
            return {"success": False, "reason": "sink (имя канала) обязателен"}
        logger = getattr(svc, "logger_manager", None)
        if logger is None or not hasattr(logger, "set_sink_enabled"):
            return {"success": False, "reason": "logger_manager недоступен"}
        ok = logger.set_sink_enabled(name, enabled)
        return {"success": bool(ok), "sink": name, "enabled": enabled, "process": svc.name}

    def _cmd_log_tail_subscribe(self, data=None, **kwargs) -> dict:
        """Подписать адрес на LogRecord'ы процесса с level ≥ порога (Ф1 Task 1.5).

        Ставит RouterPushChannel как tap на logger (и, если есть, error) процесса:
        каждая запись ≥ ``level`` пушится ``targets=[subscriber]`` + ``queue_type=system``
        → мост 1.1b → внешний driver (events()). Идемпотентно по имени tap'а.

        Параметры (data): ``subscriber`` (адрес получателя, обяз.), ``level`` (по
        умолчанию "ERROR"), ``command`` (поле command пуша, по умолчанию "log.record").
        """
        args = self._merge_args(data, kwargs)
        svc = self._services
        subscriber = str(args.get("subscriber") or "").strip()
        if not subscriber:
            return {"success": False, "reason": "subscriber (адрес получателя) обязателен"}
        level = str(args.get("level") or "ERROR").upper()
        command = str(args.get("command") or "log.record")

        router = getattr(svc, "router_manager", None)
        if router is None:
            return {"success": False, "reason": "router_manager недоступен"}
        logger = getattr(svc, "logger_manager", None)
        if logger is None or not hasattr(logger, "add_log_tap"):
            return {"success": False, "reason": "logger_manager недоступен"}

        from multiprocess_framework.modules.logger_module import RouterPushChannel

        tap_name = self._log_tap_name(subscriber)
        # Отдельные push-каналы на logger и error (у каждого свой реестр tap'ов).
        installed = []
        for mgr in self._log_tail_managers():
            channel = RouterPushChannel(
                tap_name,
                router=router,
                subscriber=subscriber,
                sender=svc.name,
                command=command,
            )
            mgr.add_log_tap(channel, min_level=level, name=tap_name)
            installed.append(getattr(mgr, "manager_name", mgr.__class__.__name__))

        if not installed:
            return {"success": False, "reason": "нет менеджеров логов с поддержкой tap"}
        return {
            "success": True,
            "process": svc.name,
            "subscriber": subscriber,
            "level": level,
            "tap": tap_name,
            "managers": installed,
        }

    def _cmd_log_tail_unsubscribe(self, data=None, **kwargs) -> dict:
        """Снять подписку на tail логов (по subscriber или явному tap-имени)."""
        args = self._merge_args(data, kwargs)
        svc = self._services
        subscriber = str(args.get("subscriber") or "").strip()
        tap_name = str(args.get("tap") or "").strip() or (self._log_tap_name(subscriber) if subscriber else "")
        if not tap_name:
            return {"success": False, "reason": "subscriber или tap обязателен"}
        removed = False
        for mgr in self._log_tail_managers():
            removed = mgr.remove_log_tap(tap_name) or removed
        return {"success": bool(removed), "process": svc.name, "tap": tap_name}

    @staticmethod
    def _log_tap_name(subscriber: str) -> str:
        """Детерминированное имя tap'а по подписчику (идемпотентность подписки)."""
        return f"log_tail::{subscriber}"

    def _log_tail_managers(self) -> list:
        """Менеджеры логов процесса, поддерживающие tap (logger + error, если есть)."""
        svc = self._services
        managers = []
        for attr in ("logger_manager", "error_manager"):
            mgr = getattr(svc, attr, None)
            if mgr is not None and hasattr(mgr, "add_log_tap"):
                managers.append(mgr)
        return managers

    # ========================================================================
    # HEALTH — наблюдаемость отказов (Ф2 Task 2.1)
    # ========================================================================

    def _register_health_commands(self) -> None:
        """Зарегистрировать health.report / health.status.

        ``health.report`` — диагностический впрыск health-события в процесс: даёт
        детерминированный способ проверить канал наблюдаемости (report_error →
        heartbeat → state-дерево → driver), не дожидаясь реального отказа железа.
        ``health.status`` — прочитать текущий снапшот здоровья процесса.
        """
        cm = self._services.command_manager
        if not cm:
            return
        specs = [
            (
                "health.report",
                self._cmd_health_report,
                "Диагностика: впрыснуть health-событие (report_error) — проверка канала наблюдаемости",
            ),
            (
                "health.status",
                self._cmd_health_status,
                "Текущий снапшот здоровья процесса (status/errors/last_error)",
            ),
        ]
        for name, handler, desc in specs:
            cm.register_command(name, handler, metadata={"description": desc}, tags=["system", "health"])
        self._services._log_debug(
            "Встроенные команды health.report/status зарегистрированы",
            module="lifecycle",
        )

    def _cmd_health_report(self, data=None, **kwargs) -> dict:
        """Впрыснуть синтетическую ошибку в HealthState процесса (диагностика).

        data: ``context`` (сайт-тег, по умолч. "diagnostics"), ``message`` (текст),
        ``status`` (опц.: перевести процесс в degraded/failed после впрыска).
        """
        args = self._merge_args(data, kwargs)
        context = str(args.get("context") or "diagnostics")
        message = str(args.get("message") or "synthetic health event")

        from ..health import HealthSelfTestError, get_or_create_health_state

        state = get_or_create_health_state(self._services)
        state.report_error(HealthSelfTestError(message), context=context)

        status = args.get("status")
        if status:
            try:
                state.set_status(str(status), reason=f"health.report: {message}")
            except ValueError:
                return {
                    "success": False,
                    "process": self._services.name,
                    "reason": f"неизвестный status '{status}' (ok|degraded|failed)",
                }

        return {"success": True, "process": self._services.name, "errors": state.error_count}

    def _cmd_health_status(self, data=None, **kwargs) -> dict:
        """Вернуть снапшот здоровья процесса (status/errors/last_error/...)."""
        from ..health import get_or_create_health_state

        state = get_or_create_health_state(self._services)
        return {"success": True, "process": self._services.name, "health": state.snapshot()}

    # ========================================================================
    # WIRE COMMANDS — runtime-настройка SHM-каналов
    # ========================================================================

    def _register_wire_commands(self) -> None:
        """Зарегистрировать wire.configure / wire.deconfigure."""
        cm = self._services.command_manager
        if not cm:
            return

        cm.register_command(
            "wire.configure",
            self._cmd_wire_configure,
            metadata={"description": "Настроить wire middleware (SHM sender/receiver)"},
            tags=["system"],
        )
        cm.register_command(
            "wire.deconfigure",
            self._cmd_wire_deconfigure,
            metadata={"description": "Удалить wire middleware"},
            tags=["system"],
        )
        self._services._log_debug(
            "Встроенные команды wire.configure/deconfigure зарегистрированы",
            module="lifecycle",
        )

    def _cmd_wire_configure(self, data=None, **kwargs) -> dict:
        """Настроить wire middleware: создать FrameShmMiddleware и подключить к router.

        Параметры в data:
            wire_key: уникальный ключ wire
            role: "sender" или "receiver"
            shm_name: имя SHM-слота
            shm_owner: имя процесса-владельца SHM
            buffer_slots: кол-во буферных слотов (информативно)
        """
        if isinstance(data, dict):
            kwargs.update(data)

        wire_key = kwargs.get("wire_key", "")
        role = kwargs.get("role", "")
        shm_name = kwargs.get("shm_name", "")
        shm_owner = kwargs.get("shm_owner", "")

        if not wire_key or not role:
            return {"success": False, "reason": "wire_key и role обязательны"}
        if role not in ("sender", "receiver"):
            return {"success": False, "reason": f"неизвестная role: {role}"}
        if not self._services.router_manager:
            return {"success": False, "reason": "router_manager недоступен"}

        # Получить memory_manager
        mm = self._services.memory_manager
        if mm is None and self._services.shared_resources:
            mm = getattr(self._services.shared_resources, "memory_manager", None)

        from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
            FrameShmMiddleware,
        )

        mw = FrameShmMiddleware(memory_manager=mm, owner=shm_owner, slot=shm_name)

        # Подключить middleware к router
        if role == "sender":
            self._services.router_manager.add_send_middleware(mw.on_send)
        else:
            self._services.router_manager.add_receive_middleware(mw.on_receive)

        # Сохранить для последующего удаления
        self._wire_middlewares[wire_key] = (mw, role)

        self._services._log_info(
            f"wire.configure: middleware подключён — wire_key={wire_key}, role={role}, shm={shm_owner}/{shm_name}",
            module="wire",
        )
        return {"success": True, "wire_key": wire_key, "role": role}

    def _cmd_wire_deconfigure(self, data=None, **kwargs) -> dict:
        """Удалить wire middleware из router.

        Параметры в data:
            wire_key: ключ wire для удаления
        """
        if isinstance(data, dict):
            kwargs.update(data)

        wire_key = kwargs.get("wire_key", "")
        if not wire_key:
            return {"success": False, "reason": "wire_key обязателен"}

        entry = self._wire_middlewares.pop(wire_key, None)
        if entry is None:
            self._services._log_warning(
                f"wire.deconfigure: wire_key '{wire_key}' не найден в _wire_middlewares",
                module="wire",
            )
            return {
                "success": True,
                "wire_key": wire_key,
                "note": "уже удалён или не существовал",
            }

        mw, role = entry

        if self._services.router_manager:
            if role == "sender":
                self._services.router_manager.remove_send_middleware(mw.on_send)
            else:
                self._services.router_manager.remove_receive_middleware(mw.on_receive)

        self._services._log_info(
            f"wire.deconfigure: middleware удалён — wire_key={wire_key}, role={role}",
            module="wire",
        )
        return {"success": True, "wire_key": wire_key}

    # ========================================================================
    # RELAY (Ф1 Task 1.7: хаб-релей недоставляемых push'ей к внешним подписчикам)
    # ========================================================================

    def _register_relay_commands(self) -> None:
        """Зарегистрировать router.relay — приём билета от RouterManager._relay_via_hub.

        Дочерний процесс не может доставить push внешнему подписчику (канал
        'backend_ctl' живёт только в router'е хаба) и однократно пересылает билет
        сюда. Обработчик просто отправляет билет СВОИМ router'ом — дальше работает
        мост 1.1b (_deliver_by_targets → канал). Команда generic и есть у всех
        процессов, но реально relay адресуется хабу (ProcessManager).
        """
        cm = self._services.command_manager
        if not cm:
            return
        cm.register_command(
            "router.relay",
            self._cmd_router_relay,
            metadata={
                "description": "Переслать недоставляемый push-билет своим router'ом (хаб-релей к внешним подписчикам)",
                "manages_own_reply": True,  # fire-and-forget: инициатору ничего не едет
            },
            tags=["system"],
        )

    def _cmd_router_relay(self, data=None, **kwargs) -> dict:
        """Отправить чужой билет своим router'ом (fire-and-forget, без reply).

        Билет уже помечен ``_relayed=True`` отправителем (страховкой ставим и здесь):
        если и наш router доставить не сможет — билет дропнется, второго relay не будет.
        """
        ticket = (data or {}).get("ticket")
        if not isinstance(ticket, dict) or not ticket.get("targets"):
            return {"success": False, "reason": "router.relay: нет ticket/targets"}
        router = self._services.router_manager
        if router is None:
            return {"success": False, "reason": "router.relay: router недоступен"}
        ticket.setdefault("_relayed", True)
        send_async = getattr(router, "send_async", None)
        if callable(send_async):
            send_async(ticket, priority="normal")
        else:  # тестовые/минимальные router'ы без async-очереди
            router.send(ticket)
        return {"success": True, "relayed": True}
