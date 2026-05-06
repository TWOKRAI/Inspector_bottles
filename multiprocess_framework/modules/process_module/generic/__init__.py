"""GenericProcess — конфиг-драйвен процесс с plugin-архитектурой.

Публичный API:
- GenericProcess — ProcessModule, загружающий плагины из конфига
- GenericProcessConfig — ProcessLaunchConfig с plugins[]
- PluginConfig — SchemaBase-конфиг одного плагина
- SystemBlueprint — SchemaBase-чертёж системы
- ProcessConfig — SchemaBase-конфиг одного процесса
- Wire — SchemaBase-связь между портами
"""

from .blueprint import ProcessConfig, SystemBlueprint, Wire
from .generic_process import GenericProcess
from .generic_process_config import GenericProcessConfig, PluginConfig
from .inspector_manager import InspectorManager

__all__ = [
    "GenericProcess",
    "GenericProcessConfig",
    "InspectorManager",
    "PluginConfig",
    "SystemBlueprint",
    "ProcessConfig",
    "Wire",
]
