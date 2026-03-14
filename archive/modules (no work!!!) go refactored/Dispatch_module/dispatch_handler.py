"""
Модуль диспетчеризации сообщений (устаревший файл).

⚠️ ВНИМАНИЕ: Этот файл оставлен для обратной совместимости.
Используйте импорт из основного модуля:
    from ..Dispatch_module import Dispatcher, DispatchStrategy, ...

Все классы реэкспортируются из новых модулей.
"""
import warnings

# Реэкспорт всех классов для обратной совместимости
from .types import DispatchStrategy, HandlerInfo, Scenario
from .base import BaseDispatcher
from .dispatcher import Dispatcher

# Для обратной совместимости
AdvancedDispatcher = Dispatcher

# Предупреждение при импорте из устаревшего файла
warnings.warn(
    "Импорт из dispatch_handler.py устарел. "
    "Используйте: from ..Dispatch_module import ...",
    DeprecationWarning,
    stacklevel=2
)

__all__ = [
    "DispatchStrategy",
    "HandlerInfo",
    "Scenario",
    "BaseDispatcher",
    "Dispatcher",
    "AdvancedDispatcher",
]
