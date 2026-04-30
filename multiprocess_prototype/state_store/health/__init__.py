"""state_store.health — watchdog-мониторинг процессов по state-обновлениям."""

from multiprocess_prototype.state_store.health.monitor import HealthMonitor, WatchedProcess

__all__ = ["HealthMonitor", "WatchedProcess"]
