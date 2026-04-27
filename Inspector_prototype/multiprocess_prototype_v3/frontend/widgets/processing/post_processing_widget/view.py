# multiprocess_prototype_v3/frontend/widgets/post_processing_widget/view.py
"""Протокол вида для PostProcessingPresenter."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Tuple, runtime_checkable

from .schemas import PostProcessingTabUiConfig


@runtime_checkable
class PostProcessingPanelViewProtocol(Protocol):
    @property
    def ui(self) -> PostProcessingTabUiConfig:
        ...

    def show_warning(self, title: str, text: str) -> None:
        ...

    def show_information(self, title: str, text: str) -> None:
        ...

    def refresh_table(self) -> None:
        ...

    def get_tree_selection(self) -> Tuple[Optional[str], Optional[str]]:
        """(camera_id, region_name) — region_name None при выборе только камеры."""

    def select_region(self, camera_id: str, region_name: str) -> None:
        ...

    def apply_form_from_region(self, region: Optional[Dict[str, Any]]) -> None:
        ...

    def read_form_region(self) -> Dict[str, Any]:
        ...

    def block_form_signals(self, block: bool) -> None:
        ...

    def confirm_delete(self, text: str) -> bool:
        """Подтверждение удаления региона."""
        ...
