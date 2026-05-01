"""health — watchdog-мониторинг процессов по state-обновлениям."""
from .monitor import HealthMonitor, WatchedProcess

__all__ = ["HealthMonitor", "WatchedProcess"]
