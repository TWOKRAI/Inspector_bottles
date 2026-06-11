# -*- coding: utf-8 -*-
"""_VfdSection — секция «ПЧ (частотный преобразователь)» во вкладке Services.

Строит VfdControlWidget + presenter + controller + DeviceComboController.
Паттерн hikvision/section.py: lazy-build, RequestRunner, bindings.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec

from .controller import VfdWidgetController, build_vfd_controls


class _VfdSection:
    """Секция «ПЧ» (SectionProtocol)."""

    def __init__(self, services: Any, runtime: Any) -> None:
        self._services = services
        self._runtime = runtime
        self._widget: QWidget | None = None
        self._controller: VfdWidgetController | None = None
        self._combo_ctrl: Any = None
        self._runner: Any = None

    @property
    def key(self) -> str:
        return "__vfd__"

    @property
    def title(self) -> str:
        return "ПЧ (частотный преобразователь)"

    def widget(self) -> QWidget:
        if self._widget is None:
            self._build()
        return self._widget  # type: ignore[return-value]

    def action_buttons(self) -> list[QWidget]:
        return []

    def on_activated(self) -> None:
        # Обновить комбо при активации секции (fallback если нет push)
        if self._combo_ctrl is not None:
            self._combo_ctrl.refresh()

    def on_deactivated(self) -> None: ...

    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner
        from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.combo import (
            DeviceComboController,
        )
        from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.presenter import (
            DevicesPresenter,
        )

        self._runner = RequestRunner()
        bindings = getattr(self._runtime, "bindings", None)

        widget, controller, _presenter = build_vfd_controls(
            runtime=self._runtime,
            request_runner=self._runner,
            bindings=bindings,
        )
        self._runner.setParent(widget)

        # DeviceComboController (kind=vfd)
        devices_presenter = DevicesPresenter(
            command_sender=getattr(self._runtime, "command_sender", None),
            request_runner=self._runner,
        )
        self._combo_ctrl = DeviceComboController(
            kind="vfd",
            presenter=devices_presenter,
            bindings=bindings,
            on_device_changed=controller.set_device,
        )
        widget.add_combo_widget(self._combo_ctrl.widget())

        self._widget = widget
        self._controller = controller


def build_vfd_section(
    services: Any,
    runtime: Any,
    *,
    parent_key: str | None = None,
    title: str = "ПЧ (частотный преобразователь)",
) -> SectionSpec:
    """SectionSpec для секции «ПЧ» (lazy)."""
    section = _VfdSection(services, runtime)
    return SectionSpec(
        key="__vfd__",
        title=title,
        factory=lambda _ctx_arg: section,
        parent_key=parent_key,
    )
