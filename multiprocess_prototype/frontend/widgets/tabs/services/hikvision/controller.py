# -*- coding: utf-8 -*-
"""HikvisionWidgetController — проводка HikvisionSettingsWidget ↔ presenter.

Переиспользуется и Services-секцией, и инспектором ноды Pipeline: связывает
сигналы виджета с командами presenter, обновляет поля/статус по результатам
list_devices/read_params. Вся UI-логика секции вынесена сюда, чтобы карточка ноды
в Pipeline дублировала те же поля без копипаста.
"""

from __future__ import annotations

from typing import Any

from .presenter import NO_LIVE_HINT, HikvisionSettingsPresenter
from .widget import HikvisionSettingsWidget


class HikvisionWidgetController:
    """Связывает виджет настроек Hikvision с presenter (команды + результаты)."""

    def __init__(self, widget: HikvisionSettingsWidget, presenter: HikvisionSettingsPresenter) -> None:
        self._widget = widget
        self._presenter = presenter
        self._connect()
        self.refresh_status()

    def _connect(self) -> None:
        w = self._widget
        w.enum_requested.connect(self._on_enum)
        w.open_requested.connect(self._on_open)
        w.close_requested.connect(self._on_close)
        w.get_params_requested.connect(self._on_get_params)
        w.apply_params_requested.connect(self._on_apply_params)

    # --- обработчики сигналов виджета ---

    def _on_enum(self) -> None:
        self._widget.set_status("Поиск устройств…")
        self._presenter.list_devices(self._on_devices)

    def _on_devices(self, devices: list[dict], error: str) -> None:
        if error:
            self._widget.set_devices([])
            self._widget.set_status(error)
            return
        self._widget.set_devices(devices)
        if devices:
            self._widget.set_status(f"Найдено устройств: {len(devices)}")
        else:
            self._widget.set_status("Устройства не найдены.")

    def _on_open(self) -> None:
        ok = self._presenter.take_device()
        self._widget.set_status("Камера открыта, захват запущен." if ok else NO_LIVE_HINT)

    def _on_close(self) -> None:
        ok = self._presenter.release_device()
        self._widget.set_status("Камера закрыта." if ok else NO_LIVE_HINT)

    def _on_get_params(self) -> None:
        self._widget.set_status("Запрос параметров…")
        self._presenter.read_params(self._on_params)

    def _on_params(self, params: dict, param_errors: dict, error: str) -> None:
        if error:
            self._widget.set_status(error)
            return
        if params:
            self._widget.set_params(
                float(params.get("frame_rate", 0.0)),
                float(params.get("exposure_time", 0.0)),
                float(params.get("gain", 0.0)),
            )
        text = "Параметры получены." if params else "Параметров нет: прибор не взят."
        if param_errors:
            text += " Ошибки узлов: " + "; ".join(f"{field}: {reason}" for field, reason in param_errors.items())
        self._widget.set_status(text)

    def _on_apply_params(self, fps: float, exposure: float, gain: float) -> None:
        ok, skipped = self._presenter.set_parameters(fps, exposure, gain)
        if not ok:
            self._widget.set_status(NO_LIVE_HINT)
            return
        text = "Параметры отправлены."
        if "frame_rate" in skipped:
            text += " fps пуст: не отправлен."
        self._widget.set_status(text)

    # --- статус ---

    def refresh_status(self) -> None:
        if self._presenter.is_live:
            self._widget.set_status("Камера активна (live-управление доступно).")
        else:
            self._widget.set_status("Камера не запущена. Активируйте рецепт с камерой Hikvision для live-управления.")


class HikvisionRegistrationHelper:
    """Обвязка регистрации камеры Hikvision в реестре устройств.

    Кнопка «Зарегистрировать» → list_devices плагина hikvision → диалог выбора →
    device_upsert {kind: hikvision, params: {serial, index}}.
    """

    def __init__(
        self,
        *,
        devices_presenter: Any,
        hikvision_presenter: Any,
        parent_widget: Any = None,
    ) -> None:
        self._devices_presenter = devices_presenter
        self._hikvision_presenter = hikvision_presenter
        self._parent = parent_widget

    def register_camera(self) -> None:
        """Запустить flow регистрации: list_devices плагина → выбор → upsert."""
        if self._devices_presenter is None or self._hikvision_presenter is None:
            return
        self._hikvision_presenter.list_devices(self._on_enum_result)

    def _on_enum_result(self, devices: list[dict], error: str) -> None:
        """Обработать ответ list_devices (``{kind, value, name}``): показать диалог выбора."""
        from PySide6.QtWidgets import QInputDialog

        if error or not devices:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(
                self._parent,
                "Hikvision",
                error or "Камеры не найдены. Убедитесь, что SDK установлен и камеры подключены.",
            )
            return

        items = [f"{d.get('name') or '?'} / {d.get('kind', '?')}: {d.get('value', '?')}" for d in devices]
        item, ok = QInputDialog.getItem(
            self._parent,
            "Зарегистрировать камеру Hikvision",
            "Выберите камеру:",
            items,
            editable=False,
        )
        if not ok or item not in items:
            return
        idx = items.index(item)
        chosen = devices[idx]
        serial = chosen.get("value", "") if chosen.get("kind") == "serial" else ""
        dev_index = idx
        dev_id = f"hik_{serial}" if serial else f"hik_{dev_index}"
        model = chosen.get("name") or "Hikvision"

        self._devices_presenter.device_upsert(
            {
                "id": dev_id,
                "name": f"{model} ({serial})",
                "kind": "hikvision",
                "params": {"serial": serial, "index": dev_index},
            }
        )


def build_hikvision_controls(
    *,
    services: Any,
    runtime: Any,
    request_runner: Any,
) -> tuple[HikvisionSettingsWidget, HikvisionWidgetController]:
    """Собрать виджет + presenter + controller с зависимостями из services/runtime.

    Возвращает (widget, controller). Виджет добавляется в любой layout;
    controller держит presenter и проводку (хранить ссылку, иначе GC).
    """
    from PySide6.QtWidgets import QPushButton, QVBoxLayout, QGroupBox

    from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.combo import (
        DeviceComboController,
    )
    from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.presenter import (
        DevicesPresenter,
    )

    widget = HikvisionSettingsWidget()
    presenter = HikvisionSettingsPresenter(
        bridge=getattr(runtime, "topology_bridge", None),
        topology=getattr(services, "topology", None),
        command_sender=getattr(runtime, "command_sender", None),
        request_runner=request_runner,
    )
    controller = HikvisionWidgetController(widget, presenter)

    # --- Блок реестра устройств (Фаза 5: hikvision в реестре) ---
    devices_presenter = DevicesPresenter(
        command_sender=getattr(runtime, "command_sender", None),
        request_runner=request_runner,
    )
    bindings = getattr(runtime, "bindings", None)

    combo_ctrl = DeviceComboController(
        kind="hikvision",
        presenter=devices_presenter,
        bindings=bindings,
        show_crud=False,
    )

    reg_helper = HikvisionRegistrationHelper(
        devices_presenter=devices_presenter,
        hikvision_presenter=presenter,
        parent_widget=widget,
    )

    btn_register = QPushButton("Зарегистрировать камеру в реестре")
    btn_register.setToolTip("Найти камеры Hikvision на шине → выбрать → добавить в реестр устройств")
    btn_register.clicked.connect(reg_helper.register_camera)

    # Вставляем секцию реестра в начало layout виджета
    reg_group = QGroupBox("Реестр устройств")
    reg_layout = QVBoxLayout(reg_group)
    reg_layout.addWidget(combo_ctrl.widget())
    reg_layout.addWidget(btn_register)

    # Вставить group в layout виджета первым
    root_layout = widget.layout()
    if root_layout is not None:
        root_layout.insertWidget(0, reg_group)

    # Сохраняем ссылки от GC
    controller._combo_ctrl = combo_ctrl  # type: ignore[attr-defined]
    controller._reg_helper = reg_helper  # type: ignore[attr-defined]
    controller._devices_presenter = devices_presenter  # type: ignore[attr-defined]

    return widget, controller
