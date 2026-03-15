"""
Mixin-классы для shared_resources_module.

ManagerStatsMixin — единый паттерн get_stats для memory, queues, events.
"""

from .stats_mixin import ManagerStatsMixin

__all__ = ["ManagerStatsMixin"]
