# pipeline_tab — вкладка Pipeline Builder (Phase 9).
# NodeGraphQtAdapter (Task 9.7), InspectorBaseNode + NodePreviewBridge (Task 9.8),
# LibraryPalette + LibraryDropTarget (Task 9.9),
# InspectorPanel + ParamsForm + ProcessIdCombo + DisplayTargetCombo (Task 9.10),
# PipelineTableView + PipelineViewSwitch (Task 9.11),
# PipelineTabWidget (Task 9.13) — единая вкладка, заменяет graph_editor.
# Перенесённые из graph_editor: model, linearity_check, auto_layout,
# _layout_constants, context_menu.

from .canvas.auto_layout import auto_layout
from .canvas.linearity_check import get_linearity_warning, is_linear
from .canvas.model import GraphEditorModel
from .library.library_palette import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    MIME_TYPE,
    UNCATEGORIZED_LABEL,
    LibraryDropTarget,
    LibraryPalette,
    install_palette_drop_target,
)
from .bridges.display_target_combo import DisplayTargetCombo
from .bridges.process_id_combo import ProcessIdCombo
from .inspector.inspector_panel import InspectorPanel
from .inspector.params_form import ParamsForm
from .views.table_view import PipelineTableView
from .views.view_switch import PipelineViewSwitch

__all__ = [
    "auto_layout",
    "get_linearity_warning",
    "is_linear",
    "GraphEditorModel",
    "MIME_TYPE",
    "CATEGORY_ORDER",
    "CATEGORY_LABELS",
    "UNCATEGORIZED_LABEL",
    "LibraryPalette",
    "LibraryDropTarget",
    "install_palette_drop_target",
    "DisplayTargetCombo",
    "InspectorPanel",
    "ParamsForm",
    "ProcessIdCombo",
    "PipelineTableView",
    "PipelineViewSwitch",
]
