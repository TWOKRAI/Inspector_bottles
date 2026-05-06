"""BlobDetectorPlugin -- детекция цветных контуров по HSV-маске.

Processing-плагин: process(items) → items с cv2.findContours.
"""
from __future__ import annotations

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
    for_each,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin


@register_plugin("blob_detector", category="processing", description="Детекция цветных контуров по HSV-маске")
class BlobDetectorPlugin(ProcessModulePlugin):
    """HSV-маска → findContours → фильтрация по area → detections."""

    name = "blob_detector"
    category = "processing"

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Кадр (опционально с контурами)"),
        Port(name="detections", dtype="list[dict]", shape="N", description="Список детекций (bbox, center, area)"),
        Port(name="mask", dtype="image/gray", shape="(H, W)", description="Бинарная маска"),
    ]

    commands = {
        "set_color_range": "set_color_range",
        "set_area_range": "set_area_range",
        "toggle_draw_contours": "toggle_draw_contours",
    }

    def configure(self, ctx: PluginContext) -> None:
        """Настройка параметров: HSV-пороги, фильтрация площади, отрисовка."""
        cfg = ctx.config
        self._ctx = ctx

        # HSV-пороги как numpy arrays для быстрой передачи в cv2.inRange
        self._lower = np.array([
            cfg.get("h_min", 0),
            cfg.get("s_min", 50),
            cfg.get("v_min", 50),
        ], dtype=np.uint8)
        self._upper = np.array([
            cfg.get("h_max", 180),
            cfg.get("s_max", 255),
            cfg.get("v_max", 255),
        ], dtype=np.uint8)

        # Фильтрация по площади контура
        self._min_area = cfg.get("min_area", 100)
        self._max_area = cfg.get("max_area", 0)  # 0 = без ограничения

        # Параметры отрисовки контуров
        self._draw_contours = cfg.get("draw_contours", False)
        self._contour_color = cfg.get("contour_color_bgr", [0, 255, 0])
        self._contour_thickness = cfg.get("contour_thickness", 2)

        ctx.log_info(
            f"BlobDetectorPlugin: HSV [{self._lower}]-[{self._upper}], "
            f"area=[{self._min_area}, {self._max_area}], draw={self._draw_contours}"
        )

    def start(self, ctx: PluginContext) -> None:
        """No-op -- обработка через process()."""

    # --- Обработка ---

    @for_each
    def process(self, item: dict) -> dict | None:
        """BGR → HSV-маска → findContours → фильтрация → detections."""
        frame = item.get("frame")
        if frame is None:
            return None

        # Применяем HSV-маску
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self._lower, self._upper)

        # Находим контуры на бинарной маске
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Фильтрация по площади и формирование списка детекций
        detections = []
        filtered_contours = []
        for c in contours:
            area = int(cv2.contourArea(c))
            if area < self._min_area:
                continue
            if self._max_area > 0 and area > self._max_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            detections.append({
                "bbox": [x, y, x + w, y + h],
                "center": [x + w // 2, y + h // 2],
                "area": area,
            })
            filtered_contours.append(c)

        # Опционально рисуем контуры на кадре
        if self._draw_contours and filtered_contours:
            cv2.drawContours(
                frame,
                filtered_contours,
                -1,
                tuple(self._contour_color),
                self._contour_thickness,
            )

        return {**item, "detections": detections, "contours": filtered_contours, "mask": mask}

    # --- Команды ---

    def set_color_range(self, data: dict) -> dict:
        """Обновить HSV-диапазон в runtime."""
        if "h_min" in data:
            self._lower[0] = max(0, min(180, int(data["h_min"])))
        if "h_max" in data:
            self._upper[0] = max(0, min(180, int(data["h_max"])))
        if "s_min" in data:
            self._lower[1] = max(0, min(255, int(data["s_min"])))
        if "s_max" in data:
            self._upper[1] = max(0, min(255, int(data["s_max"])))
        if "v_min" in data:
            self._lower[2] = max(0, min(255, int(data["v_min"])))
        if "v_max" in data:
            self._upper[2] = max(0, min(255, int(data["v_max"])))
        return {"status": "ok", "lower": self._lower.tolist(), "upper": self._upper.tolist()}

    def set_area_range(self, data: dict) -> dict:
        """Обновить min/max площадь в runtime."""
        if "min_area" in data:
            self._min_area = max(1, int(data["min_area"]))
        if "max_area" in data:
            self._max_area = max(0, int(data["max_area"]))
        return {"status": "ok", "min_area": self._min_area, "max_area": self._max_area}

    def toggle_draw_contours(self, data: dict) -> dict:
        """Переключить отрисовку контуров."""
        self._draw_contours = not self._draw_contours
        return {"status": "ok", "draw_contours": self._draw_contours}
