"""Тесты регистрации камеры Hikvision в реестре устройств.

HikvisionRegistrationHelper: list_devices плагина hikvision → диалог → device_upsert.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from multiprocess_prototype.frontend.widgets.tabs.services.hikvision.controller import (
    HikvisionRegistrationHelper,
)


class TestHikvisionRegistrationHelper:
    """Тесты HikvisionRegistrationHelper — presenter-обвязка."""

    def _make_helper(self) -> tuple[HikvisionRegistrationHelper, MagicMock, MagicMock]:
        """Создать helper с фейковыми presenter'ами: реестра (upsert) и камеры (list_devices плагина)."""
        presenter = MagicMock()
        hik_presenter = MagicMock()
        helper = HikvisionRegistrationHelper(
            devices_presenter=presenter,
            hikvision_presenter=hik_presenter,
        )
        return helper, presenter, hik_presenter

    def test_register_camera_asks_plugin_list_devices(self) -> None:
        """register_camera перечисляет приборы у плагина hikvision (list_devices), а не в хабе."""
        helper, presenter, hik_presenter = self._make_helper()
        helper.register_camera()
        hik_presenter.list_devices.assert_called_once_with(helper._on_enum_result)
        presenter._request.assert_not_called()

    def test_on_enum_result_empty_devices(self, qapp) -> None:
        """_on_enum_result с пустым списком → информационный диалог."""
        helper, presenter, _hik = self._make_helper()
        with patch("PySide6.QtWidgets.QMessageBox") as mock_msgbox:
            helper._on_enum_result([], "")
            mock_msgbox.information.assert_called_once()

    def test_on_enum_result_with_devices_upserts(self, qapp) -> None:
        """_on_enum_result с камерами + выбор в диалоге → device_upsert."""
        helper, presenter, _hik = self._make_helper()
        devices = [
            {"kind": "serial", "value": "SN123", "name": "DS-2CD"},
        ]
        with patch("PySide6.QtWidgets.QInputDialog") as mock_dialog:
            mock_dialog.getItem.return_value = (
                "DS-2CD / serial: SN123",
                True,
            )
            helper._on_enum_result(devices, "")

        presenter.device_upsert.assert_called_once()
        call_args = presenter.device_upsert.call_args[0][0]
        assert call_args["kind"] == "hikvision"
        assert call_args["params"]["serial"] == "SN123"
        assert call_args["id"] == "hik_SN123"

    def test_on_enum_result_cancel_dialog(self, qapp) -> None:
        """_on_enum_result + отмена диалога → НЕ вызывает upsert."""
        helper, presenter, _hik = self._make_helper()
        devices = [
            {"kind": "serial", "value": "SN123", "name": "DS-2CD"},
        ]
        with patch("PySide6.QtWidgets.QInputDialog") as mock_dialog:
            mock_dialog.getItem.return_value = ("", False)
            helper._on_enum_result(devices, "")

        presenter.device_upsert.assert_not_called()

    def test_register_camera_no_presenter(self) -> None:
        """register_camera без presenter → noop."""
        helper = HikvisionRegistrationHelper(
            devices_presenter=None,
            hikvision_presenter=MagicMock(),
        )
        # Не должно упасть
        helper.register_camera()
