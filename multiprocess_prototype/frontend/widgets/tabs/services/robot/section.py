# -*- coding: utf-8 -*-
"""_RobotSection — секция «Робот Delta» во вкладке Services.

Фаза C device-tree-recipe: master-detail вместо комбо. Слева — список
устройств kind=robot из активного рецепта (DeviceListPanel), справа —
страница выбранного устройства (телеметрия/CVT/рисование) с шапкой
conn + кнопки Подключить/Отключить/Изменить/Удалить. Комбо устранён.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec

from .controller import RobotWidgetController, build_robot_controls


class _NullRecipeStore:
    """Заглушка RecipeStore, когда services.recipes недоступен (нет рецептов)."""

    def get_active(self) -> str | None:
        return None

    def read_raw(self, _slug: str) -> dict | None:
        return None

    def save_raw(self, _slug: str, _data: dict) -> None:  # pragma: no cover
        pass


class _RobotSection:
    """Секция «Робот Delta» (SectionProtocol) — master-detail устройств."""

    def __init__(self, services: Any, runtime: Any) -> None:
        self._services = services
        self._runtime = runtime
        self._widget: QWidget | None = None
        self._master: Any = None
        self._crud: Any = None
        self._recipe_store: Any = None
        self._devices_presenter: Any = None
        self._bindings: Any = None

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
        if self._master is not None:
            self._master.refresh()

    def on_deactivated(self) -> None: ...

    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner
        from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.crud_actions import (
            DeviceCrudActions,
        )
        from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.master_detail import (
            DeviceMasterDetail,
        )
        from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.presenter import (
            DevicesPresenter,
        )
        from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.recipe_devices import (
            RecipeDevicesStore,
        )

        self._bindings = getattr(self._runtime, "bindings", None)
        recipes = getattr(self._services, "recipes", None)
        self._recipe_store = RecipeDevicesStore(recipes if recipes is not None else _NullRecipeStore())

        # Презентер CRUD/connect (общий runner для дискретных команд секции)
        self._devices_presenter = DevicesPresenter(
            command_sender=getattr(self._runtime, "command_sender", None),
            request_runner=RequestRunner(),
        )

        self._master = DeviceMasterDetail(
            kind="robot",
            recipe_store=self._recipe_store,
            bindings=self._bindings,
            device_page_factory=self._make_device_page,
            add_page_factory=None,  # Фаза D
        )
        self._crud = DeviceCrudActions(
            kind="robot",
            presenter=self._devices_presenter,
            recipe_store=self._recipe_store,
            refresh_cb=self._master.refresh,
            parent_widget=self._master,
        )
        self._widget = self._master

    def _make_device_page(self, device_id: str) -> QWidget:
        from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner
        from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.master_detail import (
            DeviceDetailPage,
        )

        runner = RequestRunner()
        widget, controller, _presenter = build_robot_controls(
            runtime=self._runtime,
            request_runner=runner,
            bindings=self._bindings,
        )
        runner.setParent(widget)
        if isinstance(controller, RobotWidgetController):
            controller.set_device(device_id)

        entry = self._recipe_store.get(device_id) or {}
        name = entry.get("name") or device_id
        return DeviceDetailPage(
            device_id=device_id,
            name=name,
            inner_widget=widget,
            devices_presenter=self._devices_presenter,
            on_edit=self._crud.on_edit_clicked,
            on_remove=self._crud.on_remove_clicked,
            bindings=self._bindings,
        )


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
