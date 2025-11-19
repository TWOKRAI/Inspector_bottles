from typing import Dict, Any, Callable, Optional, List, Union, Set
from Dispatch_module.dispatch_handler import Dispatcher

class CommandManager:
    """
    Командный менеджер для обработки и управления командами.

    Этот класс предоставляет простой интерфейс для регистрации и обработки команд,
    используя универсальный диспетчер для управления обработчиками.

    Attributes:
        process_name (str): Имя процесса для идентификации
        dispatcher (Dispatcher): Внутренний диспетчер для управления обработчиками команд
    """

    def __init__(self, process_name: str):
        """
        Инициализация командного менеджера.

        Args:
            process_name (str): Имя процесса для идентификации в системе
        """
        self.process_name = process_name
        self.dispatcher = Dispatcher(f"{process_name}_commands")

    def register_command(self, command_name: str, handler: Callable, **kwargs) -> bool:
        """
        Регистрация новой команды.

        Args:
            command_name (str): Название команды (ключ для диспетчеризации)
            handler (Callable): Функция-обработчик команды
            **kwargs: Дополнительные аргументы для регистрации обработчика

        Returns:
            bool: Успешность регистрации

        Example:
            def greet_handler(data):
                return f"Hello, {data.get('name', 'World')}!"

            manager.register_command("greet", greet_handler)
        """
        return self.dispatcher.register_handler(command_name, handler, **kwargs)

    def handle_command(self, message: Dict) -> Any:
        """
        Обработка командного сообщения.

        Args:
            message (Dict): Сообщение для обработки. Ожидается поле 'command' с именем команды.

        Returns:
            Any: Результат выполнения команды или сообщение об ошибке

        Example:
            message = {
                "command": "greet",
                "data": {"name": "Alice"}
            }
            result = manager.handle_command(message)
        """
        return self.dispatcher.dispatch(message)

    def get_commands(self) -> List[Dict]:
        """
        Получение списка всех зарегистрированных команд.

        Returns:
            List[Dict]: Список словарей с информацией о каждом обработчике

        Example:
            commands = manager.get_commands()
            for cmd in commands:
                print(f"Command: {cmd['key']}")
        """
        return self.dispatcher.get_all_handlers()

# Примеры использования
if __name__ == "__main__":
    # Создание командного менеджера
    command_manager = CommandManager("my_app")

    # Пример 1: Регистрация простой команды
    def greet_handler(data):
        """Простой обработчик команды приветствия"""
        name = data.get('name', 'World')
        return f"Hello, {name}!"

    command_manager.register_command("greet", greet_handler)

    # Пример 2: Регистрация команды с метаданными
    def sum_handler(data):
        """Обработчик команды сложения чисел"""
        a = data.get('a', 0)
        b = data.get('b', 0)
        return a + b

    command_manager.register_command(
        "sum",
        sum_handler,
        metadata={"description": "Adds two numbers", "version": "1.0"}
    )

    # Пример 3: Обработка команд
    greet_message = {
        "command": "greet",
        "data": {"name": "Alice"}
    }

    sum_message = {
        "command": "sum",
        "data": {"a": 5, "b": 3}
    }

    # Выполнение команд
    greet_result = command_manager.handle_command(greet_message)
    sum_result = command_manager.handle_command(sum_message)

    print("Greet result:", greet_result)
    print("Sum result:", sum_result)

    # Пример 4: Получение списка команд
    print("\nRegistered commands:")
    commands = command_manager.get_commands()
    for cmd in commands:
        print(f"- {cmd['key']}: {cmd.get('metadata', {}).get('description', 'No description')}")

    # Пример 5: Обработка несуществующей команды
    unknown_message = {
        "command": "unknown",
        "data": {}
    }
    unknown_result = command_manager.handle_command(unknown_message)
    print("\nUnknown command result:", unknown_result)
