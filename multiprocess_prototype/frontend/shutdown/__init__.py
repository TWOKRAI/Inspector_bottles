"""Закрытие GUI: крестик ждёт остановки системы (plans/2026-10-20_gui-graceful-close)."""

from .close_coordinator import CloseCoordinator, CloseState, Closable

__all__ = ["CloseCoordinator", "CloseState", "Closable"]
