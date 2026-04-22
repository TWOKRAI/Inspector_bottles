# multiprocess_prototype/frontend/widgets/cropped_regions_widget/view.py
"""Протокол вида для CroppedRegionsPresenter."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from .schemas import CroppedRegionsTabUiConfig


@runtime_checkable
class CroppedRegionsPanelViewProtocol(Protocol):
    """Методы панели ROI, вызываемые презентером (без прямого Qt в презентере)."""

    def show_warning(self, title: str, text: str) -> None:
        ...

    def show_information(self, title: str, text: str) -> None:
        ...

    @property
    def ui(self) -> CroppedRegionsTabUiConfig:
        ...

    def set_camera_options(self, camera_ids: List[str], selected: str) -> None:
        """Устарело: дерево камер показывает все id; оставлено для совместимости (no-op)."""

    def set_region_combo_options(self, names: List[str], selected: Optional[str]) -> None:
        """Список имён регионов текущей камеры; selected — текущее выделение дерева (или None)."""

    def get_region_combo_selection(self) -> Optional[str]:
        """Текущий текст выбранного региона в ComboBox или None."""

    def refresh_table(self) -> None:
        ...

    def get_tree_selection(self) -> Tuple[Optional[str], Optional[str]]:
        """(camera_id, region_name) — region_name None, если выбрана только камера."""

    def read_leaf_row(self, camera_id: str, region_name: str) -> Optional[Dict[str, Any]]:
        """Значения колонок для листа региона."""

    def selected_region_key(self) -> Optional[str]:
        """Имя выбранного региона или None."""

    def select_region(self, camera_id: str, region_name: str) -> None:
        """Выделить регион в дереве."""

    def clear_table_selection(self) -> None:
        """Снять выделение в дереве."""

    def get_region_name_text(self) -> str:
        ...

    def set_region_name_text(self, text: str) -> None:
        ...

    def apply_controls_params(self, params: Dict[str, Any]) -> None:
        ...

    def get_controls_params(self) -> Dict[str, Any]:
        ...

    def set_rect_label_text(self, text: str) -> None:
        ...
