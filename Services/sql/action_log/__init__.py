"""Services.sql.action_log -- персистентность Action-лога через sql.

Перенесено из multiprocess_framework/modules/actions_module/persistence/
по плану docs/refactors/2026-05_arch_cleanup.md (Task 4.1) — реализации,
зависящие от sql, выехали в Services вместе с самим sql-модулем.

В framework (actions_module/persistence/interfaces.py) остался только
Protocol IActionLogWriter — composition root приложения подключает конкретные
реализации отсюда.
"""

from .log_writer import ActionLogWriter
from .recovery import ActionLogRecovery
from .repository import ActionLogRepository
from .rotation import ActionLogRotation
from .schema_ext import ActionLogRow, from_action_log_row, to_action_log_row

__all__ = [
    "ActionLogWriter",
    "ActionLogRecovery",
    "ActionLogRepository",
    "ActionLogRotation",
    "ActionLogRow",
    "from_action_log_row",
    "to_action_log_row",
]
