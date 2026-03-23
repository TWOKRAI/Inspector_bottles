# multiprocess_prototype/frontend/widgets/camera_tab/
"""
Вкладка управления камерой: Simulator / Webcam / Hikvision.

Эталонная реализация MVP (View + Presenter + Callbacks). Использует
RegisterBindingContext, coerce_schema_config, callback_no_args.
См. frontend_module/components/tabs/TAB_STRUCTURE.md.

Экспорты:
- CameraTabWidget — виджет вкладки
- CameraTabUiConfig — конфиг подписей и пределов UI
- CameraTabCallbacks — колбэки команд в backend
"""

from .callbacks import CameraTabCallbacks
from .schemas import CameraTabUiConfig
from .widget import CameraTabWidget

__all__ = ["CameraTabCallbacks", "CameraTabUiConfig", "CameraTabWidget"]
