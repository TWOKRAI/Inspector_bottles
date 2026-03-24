"""
Публичные контракты console_module.

IPlatformConsole — платформо-зависимая абстракция терминала.
IConsoleManager  — менеджер терминальных окон.

Правило: внешние модули импортируют только из interfaces.py.
"""
from abc import ABC, abstractmethod
from typing import Callable, List, Optional

from ..base_manager.interfaces import IBaseManager


# =============================================================================
# IPlatformConsole
# =============================================================================

class IPlatformConsole(ABC):
    """Платформо-зависимая абстракция терминала.

    Реализации: WindowsConsole, UnixConsole.
    Выбор — через фабрику create_platform_console() в platforms/__init__.py.
    """

    @abstractmethod
    def create(self, title: str) -> bool:
        """Создать/инициализировать терминал."""

    @abstractmethod
    def write(self, text: str) -> bool:
        """Записать текст в терминал."""

    @abstractmethod
    def show(self) -> bool:
        """Показать терминал."""

    @abstractmethod
    def hide(self) -> bool:
        """Скрыть терминал."""

    @abstractmethod
    def is_visible(self) -> bool:
        """Видим ли терминал."""

    @abstractmethod
    def close(self) -> None:
        """Закрыть и освободить ресурсы."""

    @abstractmethod
    def supports_multiple_windows(self) -> bool:
        """Поддерживает ли платформа множественные окна."""

    @abstractmethod
    def read_input(self) -> Optional[str]:
        """Блокирующее чтение строки ввода. None — при EOF/ошибке."""


# =============================================================================
# IConsoleManager
# =============================================================================

class IConsoleManager(IBaseManager, ABC):
    """Менеджер терминальных окон процесса.

    ConsoleManager управляет терминалами:
    - Основной терминал: показать/скрыть, направить вывод, читать ввод
    - Дополнительные терминалы: create_console / close_console
    - God Mode: интерактивный ввод → CommandManager → RouterManager

    ConsoleManager НЕ логирует (это LoggerManager),
    НЕ парсит команды (это CommandManager),
    НЕ маршрутизирует (это RouterManager).
    Он предоставляет «экран» — терминальное I/O.
    """

    @abstractmethod
    def show(self) -> bool:
        """Показать основной терминал."""

    @abstractmethod
    def hide(self) -> bool:
        """Скрыть основной терминал."""

    @abstractmethod
    def is_visible(self) -> bool:
        """True если основной терминал видим."""

    @abstractmethod
    def write(
        self,
        text: str,
        level: str = "INFO",
        console_name: Optional[str] = None,
    ) -> bool:
        """Вывести текст.

        Args:
            text:         Текст для вывода.
            level:        Уровень («INFO», «ERROR», «STDOUT» и т.д.).
            console_name: Имя дополнительного терминала; None → основной.
        """

    @abstractmethod
    def create_console(self, name: str, title: str = "") -> bool:
        """Создать дополнительный терминал с указанным именем."""

    @abstractmethod
    def close_console(self, name: str) -> bool:
        """Закрыть дополнительный терминал."""

    @abstractmethod
    def list_consoles(self) -> List[str]:
        """Список имён дополнительных терминалов."""

    @abstractmethod
    def enable_input(self, callback: Callable[[str], None]) -> bool:
        """Запустить чтение ввода. callback вызывается при вводе строки."""

    @abstractmethod
    def disable_input(self) -> bool:
        """Остановить чтение ввода."""

    @abstractmethod
    def setup_redirect(self, enabled: bool = True) -> bool:
        """Перенаправить / восстановить stdout/stderr."""
