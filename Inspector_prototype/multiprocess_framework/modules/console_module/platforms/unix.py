"""
UnixConsole — реализация IPlatformConsole для Linux / macOS.

Основной терминал: print-based (sys.stdout).
Дополнительный терминал: xterm / gnome-terminal если GUI доступен,
иначе formatted секция в stdout (headless режим).
"""
import os
import sys
import shutil
from typing import Optional

from .base import IPlatformConsole


def _has_gui() -> bool:
    """True если доступна графическая оболочка (DISPLAY или WAYLAND_DISPLAY)."""
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _find_terminal() -> Optional[str]:
    """Найти доступный эмулятор терминала."""
    for term in ("xterm", "gnome-terminal", "konsole", "xfce4-terminal"):
        if shutil.which(term):
            return term
    return None


class UnixConsole(IPlatformConsole):
    """Реализация терминала для Linux / macOS."""

    def __init__(self) -> None:
        self._visible = True
        self._created = False
        self._title = ""
        self._extra_proc = None  # Reserved for future extra window support
        self._gui_available = _has_gui()
        self._terminal_cmd = _find_terminal() if self._gui_available else None

    # ------------------------------------------------------------------
    # IPlatformConsole
    # ------------------------------------------------------------------

    def create(self, title: str) -> bool:
        self._title = title
        self._created = True
        self._visible = True
        if title:
            # ANSI escape для установки заголовка терминала (работает в большинстве эмуляторов)
            try:
                sys.stdout.write(f"\033]0;{title}\007")
                sys.stdout.flush()
            except Exception:
                pass
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
        # На Unix нет нативного API — используем флаг
        self._visible = True
        return True

    def hide(self) -> bool:
        self._visible = False
        return True

    def is_visible(self) -> bool:
        return self._visible

    def close(self) -> None:
        if self._extra_proc and self._extra_proc.poll() is None:
            try:
                self._extra_proc.terminate()
            except Exception:
                pass
        self._extra_proc = None
        self._created = False

    def supports_multiple_windows(self) -> bool:
        return self._gui_available and self._terminal_cmd is not None

    def read_input(self) -> Optional[str]:
        try:
            return input()
        except (EOFError, KeyboardInterrupt):
            return None
