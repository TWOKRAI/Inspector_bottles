# -*- coding: utf-8 -*-
"""_VfdSection — секция «ПЧ (частотный преобразователь)» во вкладке Services.

Фаза C device-tree-recipe: master-detail вместо комбо. Слева — список
устройств kind=vfd из активного рецепта (DeviceListPanel), справа —
страница выбранного устройства (пуск/частота/статус) с шапкой conn +
кнопки Подключить/Отключить/Изменить/Удалить. Комбо устранён.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import SectionSpec

from .controller import VfdWidgetController, build_vfd_controls


class _NullRecipeStore:
    """Заглушка RecipeStore, когда services.recipes недоступен (нет рецептов)."""

    def get_active(self) -> str | None:
        return None

    def read_raw(self, _slug: str) -> dict | None:
        return None

    def save_raw(self, _slug: str, _data: dict) -> None:  # pragma: no cover
        pass


class _VfdSection:
    """Секция «ПЧ» (SectionProtocol) — master-detail устройств."""

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

        self._devices_presenter = DevicesPresenter(
            command_sender=getattr(self._runtime, "command_sender", None),
            request_runner=RequestRunner(),
        )

        self._master = DeviceMasterDetail(
            kind="vfd",
            recipe_store=self._recipe_store,
            bindings=self._bindings,
            device_page_factory=self._make_device_page,
            add_page_factory=self._make_add_page,  # Фаза D: встроенная страница
        )
        self._crud = DeviceCrudActions(
            kind="vfd",
            presenter=self._devices_presenter,
            recipe_store=self._recipe_store,
            refresh_cb=self._master.refresh,
            parent_widget=self._master,
        )
        self._widget = self._master

    def _make_add_page(self, on_committed, on_cancel) -> QWidget:
        from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.add_page import (
            AddDevicePage,
        )

        return AddDevicePage(
            kind="vfd",
            presenter=self._devices_presenter,
            recipe_store=self._recipe_store,
            on_committed=on_committed,
            on_cancel=on_cancel,
            bindings=self._bindings,
        )

    def _make_device_page(self, device_id: str) -> QWidget:
        from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner
        from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.master_detail import (
            DeviceDetailPage,
        )

        runner = RequestRunner()
        widget, controller, _presenter = build_vfd_controls(
            runtime=self._runtime,
            request_runner=runner,
            bindings=self._bindings,
        )
        runner.setParent(widget)
        if isinstance(controller, VfdWidgetController):
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
            # bug-hunt A-5: отвязать controller (stale-таймер + bind_fanout),
            # когда страница устройства снимается со стека (удалено из рецепта).
            on_cleanup=controller.unbind,
        )


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
