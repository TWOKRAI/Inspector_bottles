# -*- coding: utf-8 -*-
"""DeviceEditorDialog — модальный диалог создания/редактирования устройства.

Тонкая обёртка над :class:`DeviceFormWidget` (общая форма) + кнопки OK/Cancel.
Результат — entry dict для device_upsert (``get_entry()``).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout, QWidget

from .device_form import DeviceFormWidget


class DeviceEditorDialog(QDialog):
    """Диалог создания/редактирования записи реестра устройств.

    Args:
        kind: вид устройства (фиксирован для вкладки).
        protocols: список имён протоколов для данного kind.
        robot_devices: список robot-устройств из реестра (для bridge-транспорта).
        existing: если dict — режим редактирования (id заблокирован).
        parent: родительский виджет.
    """

    def __init__(
        self,
        *,
        kind: str,
        protocols: list[str] | None = None,
        robot_devices: list[dict] | None = None,
        existing: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Изменить устройство" if existing is not None else "Добавить устройство")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        self._form = DeviceFormWidget(
            kind=kind,
            protocols=protocols,
            robot_devices=robot_devices,
            existing=existing,
        )
        layout.addWidget(self._form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_entry(self) -> dict[str, Any]:
        """Собрать entry dict для device_upsert."""
        return self._form.get_entry()
