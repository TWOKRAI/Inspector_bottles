"""RenderOverlayPlugin -- наложение маски и bounding boxes на кадр.

Processing-плагин: process(items) → items с alpha blending маски.

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

from .registers import RenderOverlayRegisters


@register_plugin(
    "render_overlay",
    category="processing",
    description="Наложение маски и bounding boxes на кадр",
)
class RenderOverlayPlugin(ProcessModulePlugin):
    """Alpha blending маски + отрисовка bounding boxes."""

    name = "render_overlay"
    category = "processing"

    inputs = [
        Port(
            name="frame",
            dtype="image/bgr",
            shape="(H, W, 3)",
            description="Исходный BGR-кадр",
        ),
        Port(
            name="mask",
            dtype="image/gray",
            shape="(H, W)",
            description="Бинарная маска (опционально)",
        ),
        Port(
            name="detections",
            dtype="list[dict]",
            shape="N",
            description="Список детекций (опционально)",
        ),
    ]
    outputs = [
        Port(
            name="rendered_frame",
            dtype="image/bgr",
            shape="(H, W, 3)",
            description="Кадр с наложением",
        ),
    ]

    commands = {
        "set_alpha": "set_alpha",
        "set_color": "set_color",
        "toggle_detections": "toggle_detections",
    }

    register_class = RenderOverlayRegisters

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: register managed (GUI) или локальный (defaults)."""
        self._ctx = ctx
        self._reg = self._init_register(ctx)

        ctx.log_info(
            f"RenderOverlayPlugin: alpha={self._reg.mask_alpha}, "
            f"color_bgr=[{self._reg.mask_color_b},{self._reg.mask_color_g},{self._reg.mask_color_r}], "
            f"draw_detections={self._reg.draw_detections}"
        )

    # --- Обработка ---

    @for_each
    def process(self, item: dict) -> dict | None:
        """Наложить маску и bounding boxes на кадр.

        Шаги:
          1. Получить frame из item — без кадра пропускаем item.
          2. Сделать копию кадра (оригинал не трогаем).
          3. Если есть mask — alpha blending цветного overlay.
          4. Если draw_detections — нарисовать bounding boxes.
          5. Записать rendered_frame в item.
        """
        frame = item.get("frame")
        if frame is None:
            return None

        # Параметры всегда из register
        alpha = max(0.0, min(1.0, float(self._reg.mask_alpha)))
        mask_color = np.array(
            [self._reg.mask_color_b, self._reg.mask_color_g, self._reg.mask_color_r],
            dtype=np.uint8,
        )

        # Работаем с копией — оригинальный кадр остаётся нетронутым
        result = frame.copy()

        # --- Наложение маски (alpha blending) ---
        mask = item.get("mask")
        if mask is not None:
            # Маска может прийти как (H, W) или (H, W, 1) — нормализуем до 2D
            if mask.ndim == 3:
                mask = mask[:, :, 0]

            # Создаём цветной overlay (заливка цветом маски по всему кадру)
            color_overlay = np.zeros_like(result)
            color_overlay[:] = mask_color

            # Blending только там, где маска ненулевая
            mask_bool = mask > 0
            if mask_bool.any():
                result[mask_bool] = cv2.addWeighted(
                    result[mask_bool],
                    1.0 - alpha,
                    color_overlay[mask_bool],
                    alpha,
                    0,
                )

        # --- Отрисовка bounding boxes ---
        if self._reg.draw_detections:
            detections = item.get("detections", [])
            for det in detections:
                bbox = det.get("bbox")
                if bbox and len(bbox) == 4:
                    x1, y1, x2, y2 = bbox
                    # Цвет как tuple int — cv2 не принимает numpy uint8
                    color_tuple = tuple(int(c) for c in mask_color)
                    cv2.rectangle(
                        result,
                        (x1, y1),
                        (x2, y2),
                        color_tuple,
                        self._reg.line_thickness,
                    )
                    # Подпись area если присутствует в detection
                    area = det.get("area")
                    if area is not None:
                        label = f"area={area}"
                        cv2.putText(
                            result,
                            label,
                            (x1, y1 - 5),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            self._reg.label_font_scale,
                            color_tuple,
                            1,
                        )

        return {**item, "rendered_frame": result}

    # --- Команды ---

    def set_alpha(self, data: dict) -> dict:
        """Установить прозрачность маски (0.0-1.0)."""
        alpha = data.get("alpha", self._reg.mask_alpha)
        self._reg.mask_alpha = max(0.0, min(1.0, float(alpha)))
        self._ctx.log_info(f"RenderOverlayPlugin: alpha обновлён → {self._reg.mask_alpha}")
        return {"status": "ok", "alpha": self._reg.mask_alpha}

    def set_color(self, data: dict) -> dict:
        """Установить цвет маски BGR (ключи b, g, r)."""
        if "b" in data:
            self._reg.mask_color_b = max(0, min(255, int(data["b"])))
        if "g" in data:
            self._reg.mask_color_g = max(0, min(255, int(data["g"])))
        if "r" in data:
            self._reg.mask_color_r = max(0, min(255, int(data["r"])))
        self._ctx.log_info(
            f"RenderOverlayPlugin: цвет обновлён → "
            f"[{self._reg.mask_color_b},{self._reg.mask_color_g},{self._reg.mask_color_r}]"
        )
        return {
            "status": "ok",
            "color_bgr": [self._reg.mask_color_b, self._reg.mask_color_g, self._reg.mask_color_r],
        }

    def toggle_detections(self, data: dict) -> dict:
        """Переключить отрисовку bounding boxes (вкл/выкл)."""
        self._reg.draw_detections = not self._reg.draw_detections
        self._ctx.log_info(
            f"RenderOverlayPlugin: draw_detections → {self._reg.draw_detections}"
        )
        return {"status": "ok", "draw_detections": self._reg.draw_detections}
