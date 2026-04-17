"""Tab widget factory for MainWindow."""

from __future__ import annotations

from typing import Any, Callable

from multiprocess_prototype_v3.frontend.app_context import FrontendAppContext

TabWidgetFactory = Callable[[str, dict], Any]


def create_tab_widget_factory(ctx: FrontendAppContext) -> TabWidgetFactory:
    """Build tab factory from app context. Lazy imports inside factory."""

    def factory(widget_key: str, tab_config: dict) -> Any:
        if widget_key == "camera":
            from multiprocess_prototype_v3.frontend.widgets.camera_tab import CameraTabWidget
            return CameraTabWidget(
                camera_type=ctx.camera_type,
                registers_manager=ctx.registers_manager,
                callbacks_map=ctx.camera_callbacks_map,
                command_handler=ctx.command_handler,
                ui=ctx.get_camera_tab_ui(),
                touch_keyboard=ctx.get_touch_keyboard(),
            )
        if widget_key == "processing":
            from multiprocess_prototype_v3.frontend.widgets.processing_tab import ProcessingTabWidget
            return ProcessingTabWidget(
                registers_manager=ctx.registers_manager,
                ui=ctx.get_processing_tab_ui(),
                touch_keyboard=ctx.get_touch_keyboard(),
            )
        return None

    return factory
