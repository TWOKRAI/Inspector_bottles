"""
Управление приоритетами процессов ОС.

Отвечает за:
- Установку приоритетов процессов
- Маппинг приоритетов на системные значения
- Использует платформо-зависимые адаптеры
"""

from multiprocessing import Process
from typing import Dict


class ProcessPriority:
    """
    Управление приоритетами процессов ОС.

    Использует платформо-зависимые адаптеры для установки приоритетов.
    """

    def __init__(self, logger=None, platform_adapter=None):
        """
        Инициализация менеджера приоритетов.

        Args:
            logger: Менеджер логирования (опционально)
            platform_adapter: Адаптер платформы (если None, определяется автоматически)
        """
        self.logger = logger
        self.process_priorities: Dict[str, str] = {}

        # Импорт платформенного адаптера
        if platform_adapter:
            self.platform = platform_adapter
        else:
            # Временно используем заглушку, потом будет импорт из старого модуля
            self.platform = None

    def set_priority(self, process: Process, priority_name: str) -> bool:
        """
        Установить приоритет запущенному процессу ОС.

        Args:
            process: Процесс ОС
            priority_name: Имя приоритета

        Returns:
            True если установка успешна
        """
        if not self.platform:
            return False

        success = self.platform.apply_priority(process, priority_name)

        if success:
            if self.logger:
                self.logger._log_info(f"Priority set: {priority_name} for {process.name}")
        else:
            if self.logger:
                self.logger._log_warning(f"Failed to set priority '{priority_name}' for {process.name}")

        return success

    def register_priority(self, process_name: str, priority: str):
        """
        Зарегистрировать приоритет для процесса.

        Args:
            process_name: Имя процесса
            priority: Приоритет процесса
        """
        self.process_priorities[process_name] = priority

    def get_priority(self, process_name: str, default: str = "normal") -> str:
        """
        Получить приоритет процесса.

        Args:
            process_name: Имя процесса
            default: Приоритет по умолчанию

        Returns:
            Приоритет процесса
        """
        return self.process_priorities.get(process_name, default)

    def apply_priority(self, process: Process, delay: float = 0.1) -> bool:
        """
        Применить зарегистрированный приоритет к процессу.

        Args:
            process: Процесс ОС
            delay: Задержка перед установкой приоритета (для инициализации процесса)

        Returns:
            True если установка успешна
        """
        import time

        time.sleep(delay)  # Даем процессу время на инициализацию

        priority = self.get_priority(process.name)
        return self.set_priority(process, priority)
