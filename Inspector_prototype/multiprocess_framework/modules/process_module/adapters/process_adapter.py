# -*- coding: utf-8 -*-
"""
ProcessAdapter — адаптер ProcessModule для использования в process_manager_module.

Роль в архитектуре:
    process_manager_module  →  ProcessAdapter  →  ProcessModule (IProcessModule)

Предоставляет:
  - get_status() — текущий статус процесса (ProcessStatus enum)
  - get_stats()  — агрегированная статистика (Dict at Boundary)
  - send_command() — отправка команды процессу
  - is_running()  — проверка активности процесса
"""

from typing import Any, Dict, Optional

from ...base_manager.adapters.base_adapter import BaseAdapter
from ..types import ProcessStatus


class ProcessAdapter(BaseAdapter):
    """
    Адаптер ProcessModule для интеграции в process_manager_module.

    Создаётся process_manager_module при запуске процесса:
        adapter = ProcessAdapter(process_module)
        process_module.attach_adapter(adapter, name="manager")

    Все данные возвращаются как dict (Dict at Boundary).
    """

    def __init__(self, process_module, process: Optional[Any] = None) -> None:
        super().__init__(process_module, process, "ProcessAdapter")

    # ---- BaseAdapter lifecycle ----

    def setup(self) -> bool:
        if not self.manager:
            self._log("error", "ProcessModule not set")
            return False
        self._initialized = True
        self._log("info", "ProcessAdapter initialized")
        return True

    # ---- Статус ----

    def get_status(self) -> str:
        """Текущий статус процесса (строка из ProcessStatus)."""
        if not self.manager:
            return ProcessStatus.ERROR.value
        try:
            if hasattr(self.manager, "shared_resources") and self.manager.shared_resources:
                state = self.manager.shared_resources.get_process_state(self.manager.name)
                if state and "status" in state:
                    return state["status"]
            if self.manager.stop_process:
                return ProcessStatus.STOPPED.value
            return ProcessStatus.RUNNING.value
        except Exception:
            return ProcessStatus.ERROR.value

    def is_running(self) -> bool:
        """Проверка — процесс активен."""
        return self.get_status() in (
            ProcessStatus.RUNNING.value,
            ProcessStatus.READY.value,
        )

    # ---- Команды ----

    def send_command(self, command: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """Отправить команду процессу через command_adapter."""
        if not self.manager:
            return False
        try:
            adapter = getattr(self.manager, "command_adapter", None)
            if adapter and hasattr(adapter, "execute"):
                adapter.execute(command, data or {})
                return True
            if hasattr(self.manager, "execute_command"):
                self.manager.execute_command(command, data)
                return True
        except Exception as e:
            self._log("error", f"send_command failed: {e}")
        return False

    def stop(self) -> bool:
        """Остановить процесс."""
        if not self.manager:
            return False
        try:
            self.manager.stop()
            return True
        except Exception as e:
            self._log("error", f"stop failed: {e}")
            return False

    # ---- Статистика ----

    def get_stats(self) -> Dict[str, Any]:
        """Агрегированная статистика процесса (Dict at Boundary)."""
        stats = super().get_stats()
        if self.manager and hasattr(self.manager, "get_stats"):
            try:
                stats["process"] = self.manager.get_stats()
            except Exception:
                pass
        stats["status"] = self.get_status()
        return stats
