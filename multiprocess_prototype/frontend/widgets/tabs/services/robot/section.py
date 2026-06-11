# -*- coding: utf-8 -*-
"""_RobotSection — секция «Робот Delta» во вкладке Services.

Строит RobotControlWidget + presenter + controller (паттерн hikvision/).
Управление роботом/ПЧ — round-trip командами плагинам robot_io / vfd_control /
robot_draw активного рецепта (co-location в одном процессе-ноде).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec

from .controller import RobotWidgetController, build_robot_controls


class _RobotSection:
    """Секция «Робот Delta» (SectionProtocol)."""

    def __init__(self, services: Any, runtime: Any) -> None:
        self._services = services
        self._runtime = runtime
        self._widget: QWidget | None = None
        self._controller: RobotWidgetController | None = None
        self._runner: Any = None

    @property
    def key(self) -> str:
        return "__robot__"

    @property
    def title(self) -> str:
        return "Робот Delta"

    def widget(self) -> QWidget:
        if self._widget is None:
            self._build()
        return self._widget  # type: ignore[return-value]

    def action_buttons(self) -> list[QWidget]:
        return []

    def on_activated(self) -> None:
        if self._controller is not None:
            self._controller.refresh_status()

    def on_deactivated(self) -> None: ...

    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner

        # RequestRunner парентим к виджету — живёт вместе с секцией.
        self._runner = RequestRunner()
        widget, controller = build_robot_controls(
            services=self._services,
            runtime=self._runtime,
            request_runner=self._runner,
        )
        self._runner.setParent(widget)
        self._widget = widget
        self._controller = controller


def build_robot_section(
    services: Any,
    runtime: Any,
    *,
    parent_key: str | None = None,
    title: str = "Робот Delta",
) -> SectionSpec:
    """SectionSpec для секции «Робот Delta» (lazy)."""
    section = _RobotSection(services, runtime)
    return SectionSpec(
        key="__robot__",
        title=title,
        factory=lambda _ctx_arg: section,
        parent_key=parent_key,
    )
