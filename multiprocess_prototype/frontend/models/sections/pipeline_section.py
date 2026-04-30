"""PipelineSectionView — управление секцией pipeline.

CRUD для region_key → pipeline config dict.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Dict, List, TYPE_CHECKING

from multiprocess_prototype.registers.system_topology.schemas import SECTION_PIPELINE

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.models.system_topology_editor import SystemTopologyEditor

logger = logging.getLogger(__name__)


class PipelineSectionView:
    """Section View для pipeline конфигурации."""

    def __init__(self, editor: SystemTopologyEditor) -> None:
        self._editor = editor

    @property
    def pipeline(self) -> Dict[str, dict]:
        """Текущая pipeline конфигурация."""
        return self._editor._data.get("pipeline", {})

    @property
    def dirty(self) -> bool:
        return self._editor.is_dirty(SECTION_PIPELINE)

    def get_pipeline_for_region(self, region_key: str) -> dict:
        """Pipeline config для конкретного региона.

        Args:
            region_key: Ключ региона.

        Returns:
            Pipeline config dict (пустой dict если не задан).
        """
        return self.pipeline.get(region_key, {})

    def set_pipeline_for_region(self, region_key: str, config: dict) -> None:
        """Установить pipeline config для региона.

        Args:
            region_key: Ключ региона.
            config: Pipeline config dict.
        """
        self._editor.update_item("pipeline", region_key, config)

    def remove_pipeline_for_region(self, region_key: str) -> None:
        """Удалить pipeline для региона."""
        if region_key in self.pipeline:
            self._editor.remove_item("pipeline", region_key)

    def full_snapshot(self) -> dict:
        """Снимок секции для undo/redo."""
        return deepcopy(self.pipeline)

    def load_from_snapshot(self, data: dict) -> None:
        """Загрузить из snapshot."""
        self._editor._data["pipeline"] = deepcopy(data)
        self._editor._notify_section(SECTION_PIPELINE)

    def validate(self) -> List[str]:
        return self._editor.validate(SECTION_PIPELINE)


__all__ = ["PipelineSectionView"]
