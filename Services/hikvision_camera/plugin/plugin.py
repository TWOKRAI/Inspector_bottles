"""HikvisionCameraPlugin -- source-плагин камеры Hikvision на ядре `camera_device`.

Ядро (`CameraDevicePlugin`) даёт сеанс, команды Р7, наблюдаемость, цвет (BGR) и дебайер. Вендор добавляет
порт MVS (`driver.make_port`), таблицу привязки `driver.BINDINGS`, register с вендорскими полями и приведение
кадра к размеру слота SHM (`resolution_*`, `resize_mode`). SHM write и IPC send выполняет SourceProducer.
"""

from __future__ import annotations

import cv2

from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin
from Services.camera_device.interface import Binding, DevicePort, RawFrame
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.hikvision_camera.core.converter import FrameConverter

from .registers import HikvisionCameraRegisters


@register_plugin(
    "hikvision",
    category="source",
    description="Промышленная камера Hikvision (MVS SDK)",
)
class HikvisionCameraPlugin(CameraDevicePlugin):
    """Source-плагин Hikvision: команды и сеанс -- от базы ядра, вендорские -- порт, привязки, ресайз кадра."""

    name = "hikvision"
    category = "source"

    # Атрибут класса: wire проверяется до открытия камеры, по `pixel_format` порт не выбирается (mono8 -> BGR).
    outputs: list[Port] = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="BGR-кадр с камеры Hikvision"),
    ]

    register_class = HikvisionCameraRegisters

    def create_port(self) -> DevicePort:
        """Порт `mvs`; драйвер импортируется лениво -- процессы без Hikvision его не тянут."""
        from Services.hikvision_camera import driver

        return driver.make_port()

    def bindings(self) -> dict[str, Binding]:
        from Services.hikvision_camera import driver

        return driver.BINDINGS

    def _build_item(self, seq: int, ts: float, mono: float, raw: RawFrame, cap_ns: int) -> dict:
        """Item ядра, приведённый к `(resolution_height, resolution_width, 3)`: mono8 -> BGR, затем ресайз."""
        item = super()._build_item(seq, ts, mono, raw, cap_ns)
        frame = item["frame"]
        try:
            if frame.ndim == 2:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            frame = FrameConverter.resize(
                frame, self._reg.resolution_width, self._reg.resolution_height, self._reg.resize_mode
            )
        except cv2.error as exc:  # `produce()` ловит только ValueError: кадр отбрасывается, а не роняет цикл
            raise ValueError(f"приведение кадра к размеру слота не удалось: {exc}") from exc
        item["frame"] = frame
        item["pixel_format"] = "bgr8"
        item["height"], item["width"] = frame.shape[:2]
        return item
