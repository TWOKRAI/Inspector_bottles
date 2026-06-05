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
from .data_receiver import DataReceiver

# FrameShmMiddleware — транспорт SHM-кадров живёт в router_module (P3.1.1, ADR-COMM-003);
# здесь только back-compat ре-экспорт (в process_module транспорт не определяется).
from ...router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from .generic_process import GenericProcess
from .generic_process_config import GenericProcessConfig, PluginConfig
from .plugin_orchestrator import PluginOrchestrator
from .inspector_manager import InspectorManager
from .pipeline_executor import PipelineExecutor
from .source_producer import SourceProducer

__all__ = [
    "DataReceiver",
    "FrameShmMiddleware",
    "GenericProcess",
    "GenericProcessConfig",
    "PluginOrchestrator",
    "InspectorManager",
    "PipelineExecutor",
    "PluginConfig",
    "SourceProducer",
    "SystemBlueprint",
    "ProcessConfig",
    "Wire",
]
