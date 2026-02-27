# -*- coding: utf-8 -*-
"""
СТАРЫЙ DataManager - DEPRECATED.
Используйте App.Core.Managers.DataManager вместо этого.

Этот файл оставлен для обратной совместимости.
Все новые разработки должны использовать App.Core.Managers.DataManager.
"""
import warnings

# Импортируем новый DataManager
from App.Core.Managers import DataManager as NewDataManager

# Предупреждение при использовании старого импорта
warnings.warn(
    "App.Components.data_manager.DataManager устарел. "
    "Используйте App.Core.Managers.DataManager вместо этого.",
    DeprecationWarning,
    stacklevel=2
)

# Экспортируем новый DataManager под старым именем для обратной совместимости
DataManager = NewDataManager
