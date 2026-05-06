"""RenderOverlayPlugin -- наложение маски и bounding boxes на кадр.

Processing-плагин: process(items) → items с alpha blending маски.
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

    def configure(self, ctx: PluginContext) -> None:
        """Инициализация параметров из конфига."""
        cfg = ctx.config
        self._ctx = ctx

        # Прозрачность маски с зажимом в [0.0, 1.0]
        alpha_raw = cfg.get("mask_alpha", 0.5)
        self._alpha = max(0.0, min(1.0, float(alpha_raw)))

        # Цвет маски в формате BGR (numpy array для in-place обновления через set_color)
        self._mask_color = np.array(
            [
                cfg.get("mask_color_b", 0),
                cfg.get("mask_color_g", 255),
                cfg.get("mask_color_r", 0),
            ],
            dtype=np.uint8,
        )

        # Параметры отрисовки detections
        self._draw_detections = bool(cfg.get("draw_detections", True))
        self._line_thickness = int(cfg.get("line_thickness", 2))
        self._label_font_scale = float(cfg.get("label_font_scale", 0.5))

        ctx.log_info(
            f"RenderOverlayPlugin: alpha={self._alpha}, "
            f"color_bgr={self._mask_color.tolist()}, "
            f"draw_detections={self._draw_detections}"
        )

    def start(self, ctx: PluginContext) -> None:
        """No-op — обработка ведётся через process()."""

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
            color_overlay[:] = self._mask_color

            # Blending только там, где маска ненулевая
            mask_bool = mask > 0
            if mask_bool.any():
                result[mask_bool] = cv2.addWeighted(
                    result[mask_bool],
                    1.0 - self._alpha,
                    color_overlay[mask_bool],
                    self._alpha,
                    0,
                )

        # --- Отрисовка bounding boxes ---
        if self._draw_detections:
            detections = item.get("detections", [])
            for det in detections:
                bbox = det.get("bbox")
                if bbox and len(bbox) == 4:
                    x1, y1, x2, y2 = bbox
                    # Цвет как tuple int — cv2 не принимает numpy uint8
                    color_tuple = tuple(int(c) for c in self._mask_color)
                    cv2.rectangle(
                        result,
                        (x1, y1),
                        (x2, y2),
                        color_tuple,
                        self._line_thickness,
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
                            self._label_font_scale,
                            color_tuple,
                            1,
                        )

        return {**item, "rendered_frame": result}

    # --- Команды ---

    def set_alpha(self, data: dict) -> dict:
        """Установить прозрачность маски (0.0-1.0)."""
        alpha = data.get("alpha", self._alpha)
        self._alpha = max(0.0, min(1.0, float(alpha)))
        self._ctx.log_info(f"RenderOverlayPlugin: alpha обновлён → {self._alpha}")
        return {"status": "ok", "alpha": self._alpha}

    def set_color(self, data: dict) -> dict:
        """Установить цвет маски BGR (ключи b, g, r)."""
        if "b" in data:
            self._mask_color[0] = max(0, min(255, int(data["b"])))
        if "g" in data:
            self._mask_color[1] = max(0, min(255, int(data["g"])))
        if "r" in data:
            self._mask_color[2] = max(0, min(255, int(data["r"])))
        self._ctx.log_info(
            f"RenderOverlayPlugin: цвет обновлён → {self._mask_color.tolist()}"
        )
        return {"status": "ok", "color_bgr": self._mask_color.tolist()}

    def toggle_detections(self, data: dict) -> dict:
        """Переключить отрисовку bounding boxes (вкл/выкл)."""
        self._draw_detections = not self._draw_detections
        self._ctx.log_info(
            f"RenderOverlayPlugin: draw_detections → {self._draw_detections}"
        )
        return {"status": "ok", "draw_detections": self._draw_detections}
