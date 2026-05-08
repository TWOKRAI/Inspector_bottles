"""BuiltinCommands — встроенные команды ProcessModule через IProcessServices.

- worker.pause_all / worker.resume_all — управление воркерами
- wire.configure / wire.deconfigure — runtime-настройка SHM-каналов
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..plugins.interfaces import IProcessServices


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
        self._register_wire_commands()

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
            f"wire.configure: middleware подключён — wire_key={wire_key}, "
            f"role={role}, shm={shm_owner}/{shm_name}",
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
