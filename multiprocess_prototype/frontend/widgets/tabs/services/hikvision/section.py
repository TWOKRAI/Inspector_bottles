# -*- coding: utf-8 -*-
"""_HikvisionSection — секция «Hikvision Camera» во вкладке Services.

Строит HikvisionSettingsWidget + presenter + controller (проводка вынесена в
HikvisionWidgetController, переиспользуется инспектором ноды Pipeline).
Изображение — в дисплее активного рецепта.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec

from .controller import HikvisionWidgetController, build_hikvision_controls


class _HikvisionSection:
    """Секция «Hikvision Camera» (SectionProtocol)."""

    def __init__(self, services: Any, runtime: Any) -> None:
        self._services = services
        self._runtime = runtime
        self._widget: QWidget | None = None
        self._controller: HikvisionWidgetController | None = None
        self._runner: Any = None

    @property
    def key(self) -> str:
        return "__hikvision__"

    @property
    def title(self) -> str:
        return "Hikvision Camera"

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

        # RequestRunner парентим к виджету — живёт вместе с секцией, шлёт сигнал в main-thread.
        self._widget = QWidget()  # временный placeholder, заменяется ниже
        self._runner = RequestRunner()
        widget, controller = build_hikvision_controls(
            services=self._services,
            runtime=self._runtime,
            request_runner=self._runner,
        )
        self._runner.setParent(widget)
        self._widget = widget
        self._controller = controller


def build_hikvision_section(
    services: Any,
    runtime: Any,
    *,
    parent_key: str | None = None,
    title: str = "Hikvision Camera",
) -> SectionSpec:
    """SectionSpec для секции «Hikvision Camera» (lazy). parent_key — для группировки."""
    section = _HikvisionSection(services, runtime)
    return SectionSpec(
        key="__hikvision__",
        title=title,
        factory=lambda _ctx_arg: section,
        parent_key=parent_key,
    )
