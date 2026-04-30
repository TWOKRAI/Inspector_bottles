"""
Лёгкий командный менеджер без ObservableMixin.

Используется когда нужен минимальный менеджер команд без зависимости от
BaseManager/ObservableMixin. Для production-кода используйте CommandManager.
"""
from typing import Dict, Any, Callable, Optional, List


class BaseCommandManager:
    """
    Лёгкий конкретный командный менеджер — EXACT_MATCH only, без ObservableMixin.

    Предназначен для юнит-тестов и простых случаев, где зависимость от
    BaseManager избыточна. Для полной функциональности (мульти-стратегии,
    логирование, статистика) используйте CommandManager.
    """

    def __init__(self, process_name: str):
        self.process_name = process_name
        self._commands: Dict[str, Callable] = {}

    def register_command(
        self,
        command_name: str,
        handler: Callable,
        **kwargs
    ) -> bool:
        if command_name in self._commands:
            return False
        self._commands[command_name] = handler
        return True

    def overwrite_command(self, command_name: str, handler: Callable, **kwargs) -> bool:
        self._commands[command_name] = handler
        return True

    def handle_command(self, message: Dict) -> Any:
        command_name = message.get("command")
        if command_name not in self._commands:
            return {"status": "error", "reason": f"Command '{command_name}' not found"}
        try:
            handler = self._commands[command_name]
            data = message.get("data", {})
            return handler(data)
        except Exception as e:
            return {"status": "error", "reason": f"Command failed: {str(e)}"}

    def get_commands(self) -> List[Dict]:
        return [{"key": name} for name in self._commands]

    def get_command_info(self, command_name: str) -> Optional[Dict]:
        if command_name not in self._commands:
            return None
        return {"key": command_name}
