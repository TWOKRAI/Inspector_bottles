"""Entity Editor — generic tree-based editor for structured configurations.

Используется как: параметрические редакторы (камеры, регионы, pipeline-узлы)
с иерархическим деревом сущностей и формой параметров.
"""
from .entity_tree_config import EntityTreeConfig, EntityLevel, ParamDef
from .entity_tree_widget import EntityTreeWidget
from .base_editor_model import BaseEditorModel
from .base_editor_tree import BaseEditorTreeView
from .base_editor_toolbar import BaseEditorToolbar
from .params_form import ParamsForm
from .schema_inspector_panel import SchemaInspectorPanel

__all__ = [
    "EntityTreeConfig", "EntityLevel", "ParamDef",
    "EntityTreeWidget",
    "BaseEditorModel",
    "BaseEditorTreeView",
    "BaseEditorToolbar",
    "ParamsForm",
    "SchemaInspectorPanel",
]
