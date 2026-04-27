"""Processing widgets — обработка изображений (пайплайн, post-processing, ROI).

Реэкспорт Qt-классов — **ленивый** (через `__getattr__`), чтобы pure-Python тесты
могли импортировать `widgets.processing` без поднятия PySide6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — только для type-checkers
    from .cropped_regions_widget import (
        CroppedRegionsPanelWidget,
        CroppedRegionsPresenter,
        CroppedRegionsTabUiConfig,
    )
    from .post_processing_widget import (
        PostProcessingPanelWidget,
        PostProcessingTabUiConfig,
    )
    from .processing_panel_widget import (
        ProcessingPanelModel,
        ProcessingPanelPresenter,
        ProcessingPanelWidget,
        ProcessingTabUiConfig,
    )


_LAZY_ATTRS: dict[str, str] = {
    "CroppedRegionsPanelWidget": "cropped_regions_widget",
    "CroppedRegionsPresenter": "cropped_regions_widget",
    "CroppedRegionsTabUiConfig": "cropped_regions_widget",
    "PostProcessingPanelWidget": "post_processing_widget",
    "PostProcessingTabUiConfig": "post_processing_widget",
    "ProcessingPanelModel": "processing_panel_widget",
    "ProcessingPanelPresenter": "processing_panel_widget",
    "ProcessingPanelWidget": "processing_panel_widget",
    "ProcessingTabUiConfig": "processing_panel_widget",
}


def __getattr__(name: str) -> Any:
    submod_name = _LAZY_ATTRS.get(name)
    if submod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    mod = import_module(f".{submod_name}", package=__name__)
    return getattr(mod, name)


__all__ = sorted(_LAZY_ATTRS.keys())
