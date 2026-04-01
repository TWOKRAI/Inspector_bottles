# multiprocess_prototype/frontend/widgets/hikvision_widget/
"""
Виджет Hikvision: устройство, Open/Close, Grabbing, параметры.

Использует BaseWidget (Model + View + Presenter), пассивный View.
"""
from .callbacks import HikvisionWidgetCallbacks, build_hikvision_callbacks
from .widget import HikvisionWidget

__all__ = [
    "HikvisionWidget",
    "HikvisionWidgetCallbacks",
    "build_hikvision_callbacks",
]
