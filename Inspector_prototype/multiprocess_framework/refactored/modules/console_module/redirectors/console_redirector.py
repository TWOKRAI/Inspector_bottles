"""
ConsoleRedirector — перенаправитель stdout/stderr в ConsoleManager.

Рефакторинг: убрана Queue; вместо неё прямой вызов console_manager.write().
Сохраняет оригинальные sys.stdout / sys.stderr для restore().
"""
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..interfaces import IConsoleManager


class ConsoleRedirector:
    """
    File-like объект, перенаправляющий вывод в ConsoleManager.write().

    Использование:
        redirector = ConsoleRedirector(console_manager)
        sys.stdout = redirector
        sys.stderr = redirector
        ...
        redirector.restore()
    """

    def __init__(self, console_manager: "IConsoleManager") -> None:
        self._console = console_manager
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._closed = False

    # -------------------------------------------------------------------------
    # file-like interface
    # -------------------------------------------------------------------------

    def write(self, data: str) -> None:
        if self._closed or not data:
            return
        try:
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")
            self._console.write(data, level="STDOUT")
        except Exception:
            self._closed = True

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self._closed = True

    # -------------------------------------------------------------------------
    # Восстановление
    # -------------------------------------------------------------------------

    def restore(self) -> bool:
        """Восстановить оригинальные sys.stdout / sys.stderr."""
        try:
            sys.stdout = self._original_stdout
            sys.stderr = self._original_stderr
            return True
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # Поддержка проверок is_atty и прочих атрибутов
    # -------------------------------------------------------------------------

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        return getattr(self._original_stdout, "encoding", "utf-8") or "utf-8"
