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
        # Ж-5 (RS-3): «Failed to set priority» повторяется ×N на КАЖДЫЙ switch
        # (на macOS/без прав установка приоритета не проходит для каждого процесса).
        # Дедуп по ПРИЧИНЕ (нормализованный priority_name), НЕ глобальный bool:
        # первый отказ для КАЖДОГО уровня приоритета — WARNING, повторы того же
        # уровня — debug. Новая причина (другой priority_name, напр. 'realtime')
        # снова видна, а не давится навсегда после первого же отказа.
        self._priority_warn_reasons: set[str] = set()

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
            # Ж-5: дедуп по причине (priority_name) — первый отказ ЭТОГО уровня громко,
            # повторы того же уровня тихо (debug). Новый уровень снова виден.
            if self.logger:
                reason = str(priority_name)
                if reason not in self._priority_warn_reasons:
                    self._priority_warn_reasons.add(reason)
                    self.logger._log_warning(
                        f"Failed to set priority '{priority_name}' for {process.name} "
                        f"(нет прав/не поддерживается на этой платформе; дальнейшие отказы "
                        f"уровня '{priority_name}' подавлены до debug)"
                    )
                else:
                    _dbg = getattr(self.logger, "_log_debug", None)
                    if callable(_dbg):
                        _dbg(f"Failed to set priority '{priority_name}' for {process.name} (подавлено)")

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
