# multiprocess_prototype/frontend/commands/message_manager_adapter.py
"""
MessageManagerAdapter — обёртка MessageAdapter для CommandAdapter.

Предоставляет create_command_message для CommandAdapter.execute_via_message.
"""

from typing import Any, Dict, List, Optional


class MessageManagerAdapter:
    """
    Адаптер MessageAdapter -> message_manager для CommandAdapter.

    CommandAdapter ожидает process.message_manager.create_command_message().
    MessageAdapter создаёт Message через command().
    """

    def __init__(self, msg_adapter: Any):
        """
        Args:
            msg_adapter: MessageAdapter (sender уже установлен).
        """
        self._msg = msg_adapter

    def create_command_message(
        self,
        command: str,
        args: Dict[str, Any],
        targets: List[str],
        need_ack: bool = False,
    ) -> Any:
        """
        Создать command-сообщение (Message с to_dict).

        Returns:
            Message — объект с методом to_dict().
        """
        return self._msg.command(
            targets=targets,
            command=command,
            args=args,
            need_ack=need_ack,
        )
