from dataclasses import dataclass, asdict, field
import uuid
import time
import json
from typing import Dict, List, Any, Optional, Union, Set

from message_type import BaseMessage, CommandMessage, LogMessage, SystemMessage

class MessageValidationError(ValueError):
    """Кастомное исключение для ошибок валидации сообщений."""
    pass

class MessageManager:
    """
    Менеджер для создания стандартизированных сообщений.
    Не знает о маршрутизации, только создает сообщения.
    """

    def __init__(self, process_name: str):
        """
        Инициализирует MessageManager с именем процесса.

        Args:
            process_name (str): Имя процесса, создающего сообщения.
        """
        self.process_name = process_name

    def create_command_message(self, command: str, args: Dict, targets: List[str], need_ack: bool = False) -> CommandMessage:
        """
        Создает командное сообщение.

        Args:
            command (str): Команда для выполнения.
            args (Dict): Аргументы команды.
            targets (List[str]): Список целей для сообщения.
            need_ack (bool): Нужно ли подтверждение.

        Returns:
            CommandMessage: Объект командного сообщения.

        Raises:
            MessageValidationError: Если обязательные поля не заполнены.
        """
        try:
            message = CommandMessage(
                id=f"cmd_{uuid.uuid4().hex[:8]}",
                type="command",
                sender=self.process_name,
                targets=targets,
                command=command,
                args=args,
                need_ack=need_ack
            )
            message.validate()
            return message
        except ValueError as e:
            raise MessageValidationError(f"Failed to create command message: {e}")

    def create_log_message(self, level: str, message: str, module: str = "main") -> LogMessage:
        """
        Создает лог-сообщение.

        Args:
            level (str): Уровень лога.
            message (str): Текст сообщения.
            module (str): Модуль, из которого поступило сообщение.

        Returns:
            LogMessage: Объект лог-сообщения.

        Raises:
            MessageValidationError: Если обязательные поля не заполнены.
        """
        try:
            message = LogMessage(
                id=f"log_{int(time.time()*1000)}",
                type="log",
                sender=self.process_name,
                targets=["logger"],
                level=level,
                message=message,
                module=module
            )
            message.validate()
            return message
        except ValueError as e:
            raise MessageValidationError(f"Failed to create log message: {e}")

    def create_system_message(self, msg_type: str, data: Any, targets: List[str]) -> SystemMessage:
        """
        Создает системное сообщение.

        Args:
            msg_type (str): Тип системного сообщения.
            data (Any): Данные сообщения.
            targets (List[str]): Список целей для сообщения.

        Returns:
            SystemMessage: Объект системного сообщения.

        Raises:
            MessageValidationError: Если обязательные поля не заполнены.
        """
        try:
            message = SystemMessage(
                id=f"{msg_type}_{uuid.uuid4().hex[:8]}",
                type=msg_type,
                sender=self.process_name,
                targets=targets,
                data=data
            )
            message.validate()
            return message
        except ValueError as e:
            raise MessageValidationError(f"Failed to create system message: {e}")


# Примеры использования
if __name__ == "__main__":
    # Инициализация менеджера сообщений
    manager = MessageManager("test_process")

    try:
        command_msg = manager.create_command_message(
            command="",
            args={"param": "value"},
            targets=["target1", "target2"]
        )
    except MessageValidationError as e:
        print(f"Error creating command message: {e}")
    else:
        print("Command Message as dict:", command_msg.to_dict())

    # Пример 1: Создание командного сообщения
    command_msg = manager.create_command_message(
        command="test_command",
        args={"param": "value"},
        targets=["target1", "target2"]
    )
    print("Command Message as dict:", command_msg.to_dict())
    print("Command Message as JSON:", command_msg.to_json())
    print("Command Message as YAML:", command_msg.to_yaml())
    print("Command Message as text:", command_msg.to_text())

    # Пример 2: Создание лог-сообщения
    log_msg = manager.create_log_message(
        level="info",
        message="Test message"
    )
    print("\nLog Message as dict:", log_msg.to_dict())
    print("Log Message as JSON:", log_msg.to_json())
    print("Log Message as YAML:", log_msg.to_yaml())
    print("Log Message as text:", log_msg.to_text())

    # Пример 3: Создание системного сообщения
    system_msg = manager.create_system_message(
        msg_type="system",
        data={"key": "value"},
        targets=["target1", "target2"]
    )
    print("\nSystem Message as dict:", system_msg.to_dict())
    print("System Message as JSON:", system_msg.to_json())
    print("System Message as YAML:", system_msg.to_yaml())
    print("System Message as text:", system_msg.to_text())

    # Пример 4: Исключение полей при конвертации
    print("\nCommand Message as dict (excluding 'args'):", command_msg.to_dict(exclude_fields={"args"}))
    print("Command Message as dict (including only 'id' and 'type'):", command_msg.to_dict(include_fields={"id", "type"}))

    # Пример 5: Валидация сообщений
    try:
        invalid_msg = manager.create_command_message(
            command="",
            args={"param": "value"},
            targets=["target1", "target2"]
        )
    except ValueError as e:
        print(f"\nValidation error: {e}")
