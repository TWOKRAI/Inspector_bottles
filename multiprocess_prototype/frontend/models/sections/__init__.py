"""Section Views для SystemTopologyEditor.

Каждый SectionView — тонкий адаптер: хранение делегирует в SystemTopologyEditor,
мутации уведомляют подписчиков секции. API совместим с существующими моделями
(ProcessEditorModel, TopologyEditorModel) для минимальных изменений в UI.
"""

from .displays_section import DisplaysSectionView
from .pipeline_section import PipelineSectionView
from .processes_section import ProcessesSectionView
from .sources_section import SourcesSectionView

__all__ = [
    "DisplaysSectionView",
    "PipelineSectionView",
    "ProcessesSectionView",
    "SourcesSectionView",
]
