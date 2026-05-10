# multiprocess_prototype/frontend/widgets/cropped_regions_widget/tree_adapter.py
"""Дерево камера → регионы: сборка данных для StructuredTwoLevelTreeWidget."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from multiprocess_framework.modules.frontend_module.widgets.tables.structured_two_level_tree import StructuredTwoLevelTreeWidget

from multiprocess_prototype.registers.payloads.crop_regions import (
    regions_to_table_rows,
)


class CroppedRegionsTreeAdapter:
    """Заполнение дерева ROI и чтение строки листа."""

    def __init__(self, tree: StructuredTwoLevelTreeWidget) -> None:
        self._tree = tree

    def refresh(
        self,
        crop_regions_by_camera: Mapping[str, Mapping[str, List[int]]],
        ordered_camera_ids: List[str],
    ) -> None:
        groups: List[tuple[str, List[Dict[str, Any]]]] = []
        for cam in ordered_camera_ids:
            regions = crop_regions_by_camera.get(cam) or {}
            rows = regions_to_table_rows(regions)
            groups.append((cam, rows))
        self._tree.set_data(groups)

    def read_leaf_row(self, camera_id: str, region_name: str) -> Optional[Dict[str, Any]]:
        return self._tree.leaf_row_values(camera_id, region_name)
