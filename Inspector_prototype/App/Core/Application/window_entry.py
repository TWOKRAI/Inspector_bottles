
# ═════════════════════════════════════════════════════════════════════
# Window Entry — описание окна в реестре
# ═════════════════════════════════════════════════════════════════════

from dataclasses import dataclass, field
from PyQt5.QtWidgets import QWidget
from typing import Optional, Callable



@dataclass
class WindowEntry:
    """
    Конфигурация окна в реестре.
    
    Поля:
        factory: Функция создания окна. Получает зависимости, возвращает QWidget.
        singleton: Создавать один раз или каждый раз при show?
        needs_fullscreen: Участвует в глобальном set_fullscreen?
        needs_cursor: Участвует в глобальном toggle_cursor?
        needs_access_level: Участвует в глобальном admin_function?
        auto_close: Автозакрытие через N секунд (0 = отключено)
    """
    factory: Callable[..., QWidget]
    singleton: bool = True
    needs_fullscreen: bool = True
    needs_cursor: bool = True
    needs_access_level: bool = True
    auto_close: int = 0  # секунды, 0 = не закрывать автоматически
    
    # Runtime state (не для конфигурации)
    instance: Optional[QWidget] = field(default=None, repr=False)
    created: bool = field(default=False, repr=False)

