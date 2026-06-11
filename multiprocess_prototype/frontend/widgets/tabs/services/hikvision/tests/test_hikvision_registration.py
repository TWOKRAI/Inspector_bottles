"""Тесты регистрации камеры Hikvision в реестре устройств.

HikvisionRegistrationHelper: hik_enum → диалог → device_upsert.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from multiprocess_prototype.frontend.widgets.tabs.services.hikvision.controller import (
    HikvisionRegistrationHelper,
)


class TestHikvisionRegistrationHelper:
    """Тесты HikvisionRegistrationHelper — presenter-обвязка."""

    def _make_helper(self) -> tuple[HikvisionRegistrationHelper, MagicMock]:
        """Создать helper с фейковым presenter."""
        presenter = MagicMock()
        runner = MagicMock()
        helper = HikvisionRegistrationHelper(
            devices_presenter=presenter,
            request_runner=runner,
        )
        return helper, presenter

    def test_register_camera_calls_hik_enum(self) -> None:
        """register_camera вызывает _request('hik_enum', ...)."""
        helper, presenter = self._make_helper()
        helper.register_camera()
        presenter._request.assert_called_once()
        call_args = presenter._request.call_args
        assert call_args[0][0] == "hik_enum"

    def test_on_enum_result_empty_devices(self, qapp) -> None:
        """_on_enum_result с пустым списком → информационный диалог."""
        helper, presenter = self._make_helper()
        with patch("PySide6.QtWidgets.QMessageBox") as mock_msgbox:
            helper._on_enum_result({"devices": []})
            mock_msgbox.information.assert_called_once()

    def test_on_enum_result_with_devices_upserts(self, qapp) -> None:
        """_on_enum_result с камерами + выбор в диалоге → device_upsert."""
        helper, presenter = self._make_helper()
        devices = [
            {"model": "DS-2CD", "serial": "SN123", "ip": "192.168.1.10", "index": 0},
        ]
        with patch("PySide6.QtWidgets.QInputDialog") as mock_dialog:
            mock_dialog.getItem.return_value = (
                "DS-2CD / SN123 (192.168.1.10)",
                True,
            )
            helper._on_enum_result({"devices": devices})

        presenter.device_upsert.assert_called_once()
        call_args = presenter.device_upsert.call_args[0][0]
        assert call_args["kind"] == "hikvision"
        assert call_args["params"]["serial"] == "SN123"
        assert call_args["id"] == "hik_SN123"

    def test_on_enum_result_cancel_dialog(self, qapp) -> None:
        """_on_enum_result + отмена диалога → НЕ вызывает upsert."""
        helper, presenter = self._make_helper()
        devices = [
            {"model": "DS-2CD", "serial": "SN123", "ip": "192.168.1.10", "index": 0},
        ]
        with patch("PySide6.QtWidgets.QInputDialog") as mock_dialog:
            mock_dialog.getItem.return_value = ("", False)
            helper._on_enum_result({"devices": devices})

        presenter.device_upsert.assert_not_called()

    def test_register_camera_no_presenter(self) -> None:
        """register_camera без presenter → noop."""
        helper = HikvisionRegistrationHelper(
            devices_presenter=None,
            request_runner=MagicMock(),
        )
        # Не должно упасть
        helper.register_camera()
