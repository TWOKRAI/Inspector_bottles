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
        ]
        for name, handler, desc in specs:
            cm.register_command(name, handler, metadata={"description": desc}, tags=["system"])
        self._services._log_debug(
            "Встроенные команды introspect.* зарегистрированы",
            module="lifecycle",
        )

    def _cmd_introspect_handlers(self, data=None, **kwargs) -> dict:
        """Приёмники процесса: ключи router message_dispatcher + команды CommandManager.

        ``router_handlers`` — это реальные ключи, по которым процесс принимает
        IPC-сообщения (включая register_update, если плагин его зарегистрировал).
        Отсутствие ожидаемого ключа = диагноз (находка Этапа 2).
        """
        svc = self._services
        router_handlers: list = []
        router = svc.router_manager
        md = getattr(router, "message_dispatcher", None) if router else None
        if md is not None:
            try:
                router_handlers = [h.get("key") for h in md.get_all_handlers()]
            except Exception as exc:  # noqa: BLE001
                return {"success": False, "reason": f"message_dispatcher: {exc}"}

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
