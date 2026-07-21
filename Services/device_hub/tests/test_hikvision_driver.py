"""Тесты HikvisionDriver.is_connected: A-14 (bug-hunt 2026-07-20).

CameraState.OPENED не существует (реальные значения: CLOSED/OPEN/GRABBING) —
обращение к несуществующему атрибуту enum кидало AttributeError, который
глотался нижним ``except Exception: return False`` в is_connected. В итоге
is_connected был ВСЕГДА False, независимо от реального состояния камеры.
На этом представлении опирается арбитраж hik_release в device_hub-плагине
(broadcast без device_id вызывает driver.call("release", ...) только если
driver.is_connected): до фикса broadcast-release для hub-драйверов был
тихим no-op (released всегда []), после фикса реально закрывает открытые
камеры.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from Services.device_hub.drivers.hikvision_driver import HikvisionDriver
from Services.device_hub.registry.entry import DeviceEntry
from Services.hikvision_camera.core.camera import CameraState


def _make_entry() -> DeviceEntry:
    return DeviceEntry(
        id="cam_1",
        name="Камера",
        kind="hikvision",
        params={"serial": "SN1"},
    )


class TestHikvisionDriverIsConnected:
    """is_connected должен опираться на реальные значения CameraState."""

    def test_is_connected_true_when_state_open(self) -> None:
        driver = HikvisionDriver(_make_entry())
        driver._camera = MagicMock()
        driver._camera.state = CameraState.OPEN

        assert driver.is_connected is True

    def test_is_connected_true_when_state_grabbing(self) -> None:
        driver = HikvisionDriver(_make_entry())
        driver._camera = MagicMock()
        driver._camera.state = CameraState.GRABBING

        assert driver.is_connected is True

    def test_is_connected_false_when_state_closed(self) -> None:
        driver = HikvisionDriver(_make_entry())
        driver._camera = MagicMock()
        driver._camera.state = CameraState.CLOSED

        assert driver.is_connected is False

    def test_is_connected_false_when_no_camera(self) -> None:
        driver = HikvisionDriver(_make_entry())

        assert driver.is_connected is False
