"""persistence — Protocol-интерфейсы для Action-persistence.

Конкретные реализации (зависящие от sql) живут в Services/sql/action_log/.
См. docs/refactors/2026-05_arch_cleanup.md (Task 4.1).
"""

from .interfaces import IActionLogRepository, IActionLogWriter

__all__ = [
    "IActionLogRepository",
    "IActionLogWriter",
]
