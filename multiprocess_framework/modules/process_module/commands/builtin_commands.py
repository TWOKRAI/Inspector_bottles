"""BuiltinCommands — встроенные команды ProcessModule через IProcessServices.

- worker.pause_all / worker.resume_all — управление воркерами
- wire.configure / wire.deconfigure — runtime-настройка SHM-каналов
"""

from __future__ import annotations

import os
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
        self._register_routing_commands()
        self._register_message_guards()

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
            (
                "introspect.plugins",
                self._cmd_introspect_plugins,
                "Каталог плагинов процесса: зарегистрированные + failed_imports (модули, упавшие на discover)",
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
        """Имя процесса, PID, статус, воркеры (имена + сериализуемые статусы).

        ``pid`` — реальный OS-pid процесса (``os.getpid()`` исполняется ВНУТРИ
        целевого процесса). Честная наблюдаемость для debug-plane и fault-injection
        (Ф3.7): harness читает pid → ``os.kill(pid, SIGKILL)`` для проверки
        авто-рестарта. Аддитивно — прежние поля не тронуты.
        """
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
            "pid": os.getpid(),
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

        # Ф4.2 шаг 6: реестр контрактов → params_schema команды (форма параметров).
        registry = getattr(svc, "contract_registry", None)

        commands: list = []
        cm = svc.command_manager
        if cm is not None:
            try:
                from .command_contracts import params_schema_of

                for h in cm.get_commands():
                    meta = h.get("metadata") or {}
                    name = h.get("key")
                    entry = {
                        "name": name,
                        "description": str(meta.get("description") or ""),
                        "tags": sorted(h.get("tags") or []),
                    }
                    contract = registry.get(name) if (registry is not None and name) else None
                    if contract is not None:
                        entry["params_schema"] = params_schema_of(contract.schema)
                    commands.append(entry)
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

    def _cmd_introspect_plugins(self, data=None, **kwargs) -> dict:
        """Каталог плагинов ЭТОГО процесса + failed_imports (Ф2.3) + манифест (Ф4.4).

        Отвечает на «куда делся мой плагин»: модуль с опечаткой падает на
        import при discover() и раньше молча исчезал из каталога; теперь он
        в ``failed_imports`` (module_path -> "ExcType: сообщение"). Каталог —
        глобальный singleton per-process (discover выполняется в каждом
        процессе отдельно), поэтому ответ честный для процесса-адресата.

        ``manifest`` (Ф4 Task 4.4) — аддитивное поле рядом с уже существующим
        ``plugins`` (name -> category, НЕ трогаем — обратная совместимость):
        runtime-зеркало статического манифеста плагина (version/api_version/
        category/requires — см. ``ProcessModulePlugin``/``plugins/manifest.py``).
        """
        svc = self._services
        from ..plugins.registry import PluginRegistry

        entries = PluginRegistry.list()
        plugins = {entry.name: entry.category for entry in entries}
        manifest = {
            entry.name: {
                "category": entry.category,
                "version": entry.version,
                "api_version": entry.api_version,
                "requires": list(entry.requires),
            }
            for entry in entries
        }
        failed = PluginRegistry.failed_imports()
        return {
            "success": True,
            "process": svc.name,
            "plugins": dict(sorted(plugins.items())),
            "manifest": dict(sorted(manifest.items())),
            "count": len(plugins),
            "failed_imports": dict(sorted(failed.items())),
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
        result = {"success": True, "process": svc.name, "router_stats": router_stats}
        # Ф3.1: аддитивно epoch и число применённых refresh из своей PSR-записи
        # (наблюдаемость routing-epoch; driver-обёртка читает только router_stats).
        try:
            sr = getattr(svc, "shared_resources", None)
            psr = getattr(sr, "process_state_registry", None) if sr is not None else None
            pd = psr.get_process_data(svc.name) if psr is not None else None
            meta = getattr(pd, "metadata", None) if pd is not None else None
            if isinstance(meta, dict):
                result["routing_epoch"] = int(meta.get("routing_epoch", 0) or 0)
                result["routing_refresh_applied"] = int(meta.get("routing_refresh_applied", 0) or 0)
        except Exception:  # noqa: BLE001 — наблюдаемость не критична
            pass
        return result

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
            (
                "observability.tail.subscribe",
                self._cmd_observability_tail_subscribe,
                "Подписать GUI-адрес на live-хвост наблюдаемости (log/stats/error → observability.record)",
            ),
            (
                "observability.tail.unsubscribe",
                self._cmd_observability_tail_unsubscribe,
                "Снять подписку на live-хвост наблюдаемости процесса",
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

    def _cmd_observability_tail_subscribe(self, data=None, **kwargs) -> dict:
        """Подписать GUI-адрес на live-хвост наблюдаемости процесса (Ф5.20b).

        Делегирует в ProcessModule.subscribe_observability_tail: ставит форвардер
        (drain log/stats) + error-tap'ы (write-through) → адресный push
        ``command="observability.record"`` на подписчика. Живой хвост вкладок
        Логи/Ошибки/Статистика (Ф5.19). Идемпотентно по подписчику.

        Параметры (data): ``subscriber`` (адрес GUI-процесса, обяз.).
        """
        args = self._merge_args(data, kwargs)
        svc = self._services
        subscriber = str(args.get("subscriber") or "").strip()
        if not subscriber:
            return {"success": False, "reason": "subscriber (адрес получателя) обязателен"}
        if not hasattr(svc, "subscribe_observability_tail"):
            return {"success": False, "reason": "процесс не поддерживает observability-tail"}
        return svc.subscribe_observability_tail(subscriber)

    def _cmd_observability_tail_unsubscribe(self, data=None, **kwargs) -> dict:
        """Снять подписку на live-хвост наблюдаемости (форвардер + error-tap'ы)."""
        svc = self._services
        if not hasattr(svc, "unsubscribe_observability_tail"):
            return {"success": False, "reason": "процесс не поддерживает observability-tail"}
        return svc.unsubscribe_observability_tail()

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

        mw = FrameShmMiddleware(
            memory_manager=mm,
            owner=shm_owner,
            slot=shm_name,
            # M2b: без log_error громкий pickle-fallback (G.3d) на wire-пути был мёртв.
            log_error=lambda m: self._services._log_error(m, module="wire"),
        )

        # Подключить middleware к router
        if role == "sender":
            self._services.router_manager.add_send_middleware(mw.on_send)
            # Ф7 G.6 (F5): счётчик границ агрегируется в RouterManager.get_stats()
            # (introspect.router_stats) — только на send-стороне, receiver границу
            # не пересекает повторно (см. класс-докстринг FrameShmMiddleware).
            self._services.router_manager.register_frame_middleware(mw)
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
        router = self._services.router_manager

        if router:
            if role == "sender":
                router.remove_send_middleware(mw.on_send)
                # H5b: снять из агрегации счётчиков (иначе утечка объектов + задвоение).
                unreg = getattr(router, "unregister_frame_middleware", None)
                if callable(unreg):
                    unreg(mw)
            else:
                router.remove_receive_middleware(mw.on_receive)

        # H5b: sender-middleware владеет SHM-блоками — освободить (иначе каждый цикл
        # configure/deconfigure копит сегменты на POSIX).
        if role == "sender":
            release_mem = getattr(mw, "release_owned_memory", None)
            if callable(release_mem):
                try:
                    release_mem()
                except Exception:  # noqa: BLE001 — teardown не критичен
                    pass

        # Ф7 G.3: закрыть кэш SHM-handles читателя (если включён) — на switch старые
        # сегменты освобождаются, новые имена owner+incarnation откроются заново.
        close_cache = getattr(mw, "close_handle_cache", None)
        if callable(close_cache):
            try:
                close_cache()
            except Exception:  # noqa: BLE001 — teardown не критичен
                pass

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

    # ========================================================================
    # ROUTING-EPOCH (Ф3.1: probe для воспроизведения дыры + refresh-handler)
    # ========================================================================

    def _register_routing_commands(self) -> None:
        """Зарегистрировать routing.probe (диагностика) + routing.refresh (Ф3.1).

        ``routing.probe`` — детерминированный способ проверить peer→peer доставку
        после switch/restart: процесс-отправитель шлёт ``inner``-билет соседу тем
        же путём, что и обычный трафик (``send_to_process`` → RouterManager →
        _deliver_by_targets по стейл/свежей очереди). Нельзя использовать
        ``router.relay`` — он ставит ``_relayed=True`` и отключает hub-fallback,
        маскируя дыру. Результат доставки НЕ наблюдается по ack (``put_nowait`` в
        осиротевшую очередь возвращает успех) — только по downstream-эффекту у
        соседа (например health-дельта в state-дереве).

        ``routing.refresh`` — приём авторитетного снимка epoch+incarnation от хаба
        (PM). Выживший ребёнок сбрасывает локальные стейл-очереди соседей, которых
        PM пересоздал → последующий send падает в hub-relay (Ф1.7) → PM со свежим
        PSR доставит. Идемпотентно (guard epoch<=last_seen).
        """
        cm = self._services.command_manager
        if not cm:
            return
        cm.register_command(
            "routing.probe",
            self._cmd_routing_probe,
            metadata={"description": "Диагностика: отправить inner-билет соседу (peer→peer доставка после switch)"},
            tags=["system"],
        )
        cm.register_command(
            "routing.refresh",
            self._cmd_routing_refresh,
            metadata={
                "description": "Сверка снимка routing-epoch: сброс стейл-очередей соседей (Ф3.1)",
                "manages_own_reply": True,  # broadcast fire-and-forget: инициатору ничего не едет
            },
            tags=["system"],
        )
        self._services._log_debug(
            "Встроенные команды routing.probe/refresh зарегистрированы",
            module="lifecycle",
        )

    def _cmd_routing_refresh(self, data=None, **kwargs) -> dict:
        """Применить авторитетный снимок routing-epoch от хаба (Ф3.1).

        Контракт ``data``: ``epoch`` (int), ``hub`` (имя хаба), ``reason``,
        ``processes`` ({имя: {"incarnation": N}}), ``ts``. Все ветки идемпотентны:

          - ``epoch <= last_seen`` → ignored (повтор/устаревшая рассылка);
          - имя отсутствует в снимке → сбросить его локальные очереди;
          - incarnation ≠ локальной → сбросить очереди + запомнить новую;
          - свою запись и ``hub`` не трогаем (их очереди всегда валидны);
          - в конце: last_seen = epoch + счётчик ``routing_refresh_applied`` в
            своей PSR-записи.

        Ошибки не роняют message-loop: логируются и возвращают success=False.
        """
        args = self._merge_args(data, kwargs)
        svc = self._services
        sr = getattr(svc, "shared_resources", None)
        psr = getattr(sr, "process_state_registry", None) if sr is not None else None
        if psr is None:
            return {"success": False, "reason": "routing.refresh: PSR недоступен"}

        self_name = getattr(svc, "name", None)
        hub = str(args.get("hub") or "")
        try:
            epoch = int(args.get("epoch", 0) or 0)
        except (TypeError, ValueError):
            epoch = 0
        snapshot = args.get("processes")
        snapshot = snapshot if isinstance(snapshot, dict) else {}

        try:
            self_pd = psr.get_process_data(self_name)
            self_meta = getattr(self_pd, "metadata", None) if self_pd is not None else None
            last_seen = int(self_meta.get("routing_epoch", -1) or -1) if isinstance(self_meta, dict) else -1
            # Guard: устаревшая/повторная рассылка — no-op (самовосстановление
            # обеспечивает следующий полный снимок).
            if epoch <= last_seen:
                return {"success": True, "ignored": True, "epoch": epoch, "last_seen": last_seen}

            reset: list[str] = []
            for name in list(psr.get_process_names()):
                if name == self_name or name == hub:
                    continue
                pd = psr.get_process_data(name)
                meta = getattr(pd, "metadata", None) if pd is not None else None
                meta = meta if isinstance(meta, dict) else {}
                if name not in snapshot:
                    # Имя исчезло из авторитетного снимка → его очереди мертвы.
                    if psr.drop_process_queues(name):
                        reset.append(name)
                    continue
                local_inc = int(meta.get("routing_incarnation", 0) or 0)
                new_inc = int((snapshot.get(name) or {}).get("incarnation", 0) or 0)
                if new_inc != local_inc:
                    if psr.drop_process_queues(name):
                        reset.append(name)
                    meta["routing_incarnation"] = new_inc

            # Зафиксировать epoch (last_seen) + счётчик применений.
            if isinstance(self_meta, dict):
                self_meta["routing_epoch"] = epoch
                self_meta["routing_refresh_applied"] = int(self_meta.get("routing_refresh_applied", 0) or 0) + 1
            return {"success": True, "epoch": epoch, "reset": sorted(reset), "reset_count": len(reset)}
        except Exception as exc:  # noqa: BLE001 — не ронять message-loop
            log_error = getattr(svc, "_log_error", None)
            if callable(log_error):
                log_error(f"routing.refresh handler упал: {exc}", module="lifecycle")
            err_mgr = getattr(svc, "error_manager", None)
            if err_mgr is not None and hasattr(err_mgr, "track_error"):
                try:
                    err_mgr.track_error(exc, {"phase": "routing.refresh"})
                except Exception:  # noqa: BLE001
                    pass
            return {"success": False, "reason": str(exc)}

    def _cmd_routing_probe(self, data=None, **kwargs) -> dict:
        """Отправить ``inner``-билет процессу ``target`` (peer→peer probe, Ф3.1).

        data: ``target`` (имя процесса-соседа), ``inner`` (полный билет-команда,
        доставляемый соседу «как есть»). Идёт через ``send_to_process`` —
        нормальный peer-путь, тот же, что теряется на стейл-очереди после switch.
        """
        args = self._merge_args(data, kwargs)
        target = str(args.get("target") or "").strip()
        inner = args.get("inner")
        if not target or not isinstance(inner, dict):
            return {"success": False, "reason": "routing.probe: нужны target и inner (dict)"}
        try:
            ok = self._services.send_to_process(target, inner)
        except Exception as exc:  # noqa: BLE001 — вернуть видимую ошибку инициатору
            return {"success": False, "reason": f"routing.probe: send_to_process упал: {exc}", "target": target}
        return {"success": bool(ok), "target": target}

    # ========================================================================
    # MESSAGE GUARDS (Ф4.2: реестр контрактов warn/strict + fencing-token)
    # ========================================================================

    def _routing_meta_of(self, name) -> Any:
        """metadata PSR-записи процесса ``name`` (или ``None``). Тот же путь, что у
        ``_cmd_routing_refresh``: ``routing_epoch``/``routing_incarnation`` в metadata."""
        svc = self._services
        sr = getattr(svc, "shared_resources", None)
        psr = getattr(sr, "process_state_registry", None) if sr is not None else None
        if psr is None or not name:
            return None
        try:
            pd = psr.get_process_data(name)
            meta = getattr(pd, "metadata", None) if pd is not None else None
            return meta if isinstance(meta, dict) else None
        except Exception:  # noqa: BLE001 — PSR-сбой не должен ронять проводку/приём
            return None

    def _get_own_fence(self) -> tuple:
        """(own_incarnation | None, own_epoch | None) для штампа отправителя.

        Свой incarnation проставлен при spawn (bundle_builder), epoch растёт с каждым
        применённым ``routing.refresh`` — оба в своей PSR-записи.
        """
        meta = self._routing_meta_of(getattr(self._services, "name", None))
        if meta is None:
            return (None, None)
        inc = meta.get("routing_incarnation")
        epoch = meta.get("routing_epoch")
        return (
            int(inc) if isinstance(inc, int) else None,
            int(epoch) if isinstance(epoch, int) else None,
        )

    def _get_expected_incarnation(self, sender):
        """Известный получателю текущий incarnation отправителя (или ``None``).

        Читает ``PSR[sender].routing_incarnation`` — обновляется ``routing.refresh``
        при смене incarnation соседа. ``None`` (неизвестный процесс) → fail-open.
        """
        meta = self._routing_meta_of(sender)
        if meta is None:
            return None
        inc = meta.get("routing_incarnation")
        return int(inc) if isinstance(inc, int) else None

    def _register_message_guards(self) -> None:
        """Проводка receive/send-middleware процесса (Ф4.2): контракты + fencing.

        Оба живут в одном receive-pipeline (``_recv_mw.apply`` первым шагом
        ``receive()``), плюс fence добавляет send-mw для штампа. Порядок приёма:
        **fence-filter ПЕРВЫМ** (дроп стейл до валидации контракта), затем
        contract-check. Флаги:

          - ``FW_FENCE`` (дефолт **ON**; ``FW_FENCE=0`` → откат) — штамп+фильтр.
          - ``FW_CONTRACTS_STRICT`` (дефолт warn) — нарушение контракта дропает.

        Реестр контрактов создаётся пустым (ноль оверхеда) и вешается на процесс
        (``services.contract_registry``) — наполняется при регистрации обработчиков
        и отдаётся `introspect.capabilities` v1. Идемпотентно: если router уже нет
        (bare/тест без транспорта) — тихий no-op.
        """
        svc = self._services
        router = getattr(svc, "router_manager", None)
        if router is None:
            return

        # --- Реестр контрактов (пуст; наполнение — позже, декларативно) ---
        registry = getattr(svc, "contract_registry", None)
        if registry is None:
            from ...message_module import MessageContractRegistry

            registry = MessageContractRegistry()
            try:
                svc.contract_registry = registry
            except Exception:  # noqa: BLE001 — не все services допускают set-атрибут
                pass

        # Ф4.2 шаг 6: декларативное наполнение реестра контрактами параметров
        # built-in команд → introspect.capabilities отдаёт params_schema. Идемпотентно
        # (override=True): повторная проводка не падает на дубле.
        from .command_contracts import BUILTIN_COMMAND_CONTRACTS

        for _cmd, _schema in BUILTIN_COMMAND_CONTRACTS.items():
            try:
                # params_in_data=True: параметры команды едут в message["data"] —
                # warn-mw сверяет их, а не плоский конверт (H5, иначе инертна).
                registry.register(_cmd, _schema, params_in_data=True, override=True)
            except Exception:  # noqa: BLE001 — кривой контракт не должен ронять проводку
                pass

        inc_stat = getattr(router, "_inc_stat", None)

        # --- Fencing-token (FW_FENCE, дефолт ON) ---
        fence_on = os.environ.get("FW_FENCE", "1").strip().lower() not in ("0", "false", "no", "off", "")
        if fence_on:
            from ...message_module import (
                make_fence_filter_middleware,
                make_fence_stamp_middleware,
            )

            sender_name = getattr(svc, "name", None) or "process"

            def _on_fence_drop(message, _inc=inc_stat, _svc=svc):
                if callable(_inc):
                    _inc("fence_dropped")
                log_warning = getattr(_svc, "_log_warning", None)
                if callable(log_warning):
                    fence = message.get("_fence") or {}
                    log_warning(
                        f"fence: отброшено от устаревшего инстанса {fence.get('sender')!r} "
                        f"inc={fence.get('inc')} (command={message.get('command')!r})",
                        module="lifecycle",
                    )

            router.add_send_middleware(make_fence_stamp_middleware(sender_name, self._get_own_fence))
            # fence-filter добавляем ПЕРВЫМ на receive (до contract-check).
            router.add_receive_middleware(
                make_fence_filter_middleware(self._get_expected_incarnation, on_drop=_on_fence_drop)
            )

        # --- Контракт-мидлвар (warn по умолчанию; strict за флагом) ---
        from ...message_module import make_contract_check_middleware

        strict = os.environ.get("FW_CONTRACTS_STRICT", "").strip().lower() in ("1", "true", "yes", "on")

        def _on_violation(check, _inc=inc_stat, _svc=svc, _strict=strict):
            if callable(_inc):
                _inc("contract_violations")
            log_warning = getattr(_svc, "_log_warning", None)
            if callable(log_warning):
                verb = "ДРОП (strict)" if _strict else "WARNING"
                log_warning(
                    f"contract {verb}: '{check.key}' — {check.diff_summary()}",
                    module="lifecycle",
                )

        router.add_receive_middleware(
            make_contract_check_middleware(registry, strict=strict, on_violation=_on_violation)
        )

        self._services._log_debug(
            f"Message guards зарегистрированы (fence={'on' if fence_on else 'off'}, "
            f"contracts={'strict' if strict else 'warn'})",
            module="lifecycle",
        )
