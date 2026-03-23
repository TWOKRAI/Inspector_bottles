# multiprocess_prototype/frontend/widgets/tabs_setting/processing_tab/
"""
Вкладка обработки: BGR, min/max area, Original/Mask/Contours.

Простой виджет: RegisterBindingContext, coerce_schema_config, IRegistersManagerGui.
При отсутствии rm — заглушка. control_v2 API. См. TAB_STRUCTURE.md.

Экспорты:
- ProcessingTabWidget — виджет вкладки
- ProcessingTabUiConfig — конфиг подписей UI
"""

from .schemas import ProcessingTabUiConfig
from .widget import ProcessingTabWidget

__all__ = ["ProcessingTabUiConfig", "ProcessingTabWidget"]
