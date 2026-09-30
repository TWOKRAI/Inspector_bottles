"""BlobDetectorPlugin -- детекция цветных контуров по HSV-маске.

Processing-плагин: process(items) → items с cv2.findContours.

V3_MY_PURE: plugin самодостаточен — создаёт локальный register
если RegistersManager недоступен. Все параметры ВСЕГДА через self._reg.
"""

from __future__ import annotations

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    for_each,
)
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins import register_plugin

from .registers import BlobDetectorRegisters


@register_plugin("blob_detector", category="processing", description="Детекция цветных контуров по HSV-маске")
class BlobDetectorPlugin(ProcessModulePlugin):
    """HSV-маска → findContours → фильтрация по area → detections."""

    name = "blob_detector"
    category = "processing"

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
        Port(
            name="mask",
            dtype="image/gray",
            shape="(H, W)",
            optional=True,
            description="Маска от предыдущего плагина (color_mask); без неё детектор порогует цвет сам",
        ),
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

    register_class = BlobDetectorRegisters

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: register managed (GUI) или локальный (defaults)."""
        self._ctx = ctx
        self._reg = self._init_register(ctx)

        ctx.log_info(
            f"BlobDetectorPlugin: HSV [{self._reg.h_min},{self._reg.s_min},{self._reg.v_min}]-"
            f"[{self._reg.h_max},{self._reg.s_max},{self._reg.v_max}], "
            f"area=[{self._reg.min_area}, {self._reg.max_area}], draw={self._reg.draw_contours}"
        )

    # --- Обработка ---

    @for_each
    def process(self, item: dict) -> dict | None:
        """Маска (готовая из item["mask"] или своя HSV) → findContours → фильтрация → detections.

        Рисование контуров идёт на КОПИИ кадра: входной массив не меняется.
        """
        frame = item.get("frame")
        if frame is None:
            return None

        # Готовая маска от предыдущего плагина — только если она точно годится:
        # 2D uint8 того же размера, что кадр. Иначе порогуем цвет сами (старый путь).
        upstream = item.get("mask")
        if (
            isinstance(upstream, np.ndarray)
            and upstream.ndim == 2
            and upstream.dtype == np.uint8
            and upstream.shape == frame.shape[:2]
        ):
            mask = upstream
        else:
            # HSV-пороги из register
            lower = np.array([self._reg.h_min, self._reg.s_min, self._reg.v_min], dtype=np.uint8)
            upper = np.array([self._reg.h_max, self._reg.s_max, self._reg.v_max], dtype=np.uint8)
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, lower, upper)

        # Находим контуры на бинарной маске
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Фильтрация по площади и формирование списка детекций
        detections = []
        filtered_contours = []
        for c in contours:
            area = int(cv2.contourArea(c))
            if area < self._reg.min_area:
                continue
            if self._reg.max_area > 0 and area > self._reg.max_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            detections.append(
                {
                    "bbox": [x, y, x + w, y + h],
                    "center": [x + w // 2, y + h // 2],
                    "area": area,
                }
            )
            filtered_contours.append(c)

        # Опционально рисуем контуры — на копии, входной кадр не трогаем
        if self._reg.draw_contours and filtered_contours:
            frame = frame.copy()
            cv2.drawContours(
                frame,
                filtered_contours,
                -1,
                tuple(self._reg.contour_color_bgr),
                self._reg.contour_thickness,
            )

        return {**item, "frame": frame, "detections": detections, "contours": filtered_contours, "mask": mask}

    # --- Команды ---

    def set_color_range(self, data: dict) -> dict:
        """Обновить HSV-диапазон в runtime."""
        for field in type(self._reg).model_fields:
            if field in data:
                setattr(self._reg, field, data[field])
        return {
            "status": "ok",
            "lower": [self._reg.h_min, self._reg.s_min, self._reg.v_min],
            "upper": [self._reg.h_max, self._reg.s_max, self._reg.v_max],
        }

    def set_area_range(self, data: dict) -> dict:
        """Обновить min/max площадь в runtime."""
        for field in type(self._reg).model_fields:
            if field in data:
                setattr(self._reg, field, data[field])
        return {"status": "ok", "min_area": self._reg.min_area, "max_area": self._reg.max_area}

    def toggle_draw_contours(self, data: dict) -> dict:
        """Переключить отрисовку контуров."""
        self._reg.draw_contours = not self._reg.draw_contours
        return {"status": "ok", "draw_contours": self._reg.draw_contours}
