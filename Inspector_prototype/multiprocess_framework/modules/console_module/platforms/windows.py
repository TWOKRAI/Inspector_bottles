"""
WindowsConsole — реализация IPlatformConsole для Windows.

Использует WinAPI через ctypes:
  - GetConsoleWindow / ShowWindow для show/hide основного окна
  - AllocConsole / FreeConsole для дополнительных окон (subprocess-подход)
  - WriteConsoleW для записи в основной терминал
"""
import sys
import subprocess
from typing import Optional

from .base import IPlatformConsole


class WindowsConsole(IPlatformConsole):
    """Реализация терминала для Windows."""

    def __init__(self) -> None:
        self._visible = True
        self._created = False
        self._title = ""
        self._extra_proc: Optional[subprocess.Popen] = None  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # IPlatformConsole
    # ------------------------------------------------------------------

    def create(self, title: str) -> bool:
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            # Если консоль уже есть — ничего не делаем
            hwnd = kernel32.GetConsoleWindow()
            if not hwnd:
                kernel32.AllocConsole()
            if title:
                ctypes.windll.kernel32.SetConsoleTitleW(title)  # type: ignore[attr-defined]
            self._title = title
            self._created = True
            self._visible = True
            return True
        except Exception:
            # Fallback: просто помечаем как созданный
            self._created = True
            return True

    def write(self, text: str) -> bool:
        if not self._visible:
            return True
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
            return True
        except Exception:
            return False

    def show(self) -> bool:
        try:
            import ctypes
            SW_SHOW = 5
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()  # type: ignore[attr-defined]
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, SW_SHOW)  # type: ignore[attr-defined]
            self._visible = True
            return True
        except Exception:
            self._visible = True
            return True

    def hide(self) -> bool:
        try:
            import ctypes
            SW_HIDE = 0
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()  # type: ignore[attr-defined]
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, SW_HIDE)  # type: ignore[attr-defined]
            self._visible = False
            return True
        except Exception:
            self._visible = False
            return True

    def is_visible(self) -> bool:
        return self._visible

    def close(self) -> None:
        try:
            if self._extra_proc and self._extra_proc.poll() is None:
                self._extra_proc.terminate()
                self._extra_proc = None
            import ctypes
            ctypes.windll.kernel32.FreeConsole()  # type: ignore[attr-defined]
        except Exception:
            pass
        self._created = False

    def supports_multiple_windows(self) -> bool:
        return True

    def read_input(self) -> Optional[str]:
        try:
            return input()
        except (EOFError, KeyboardInterrupt):
            return None
