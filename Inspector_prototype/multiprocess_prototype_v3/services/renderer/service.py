"""RendererService — бизнес-логика рендеринга кадров."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

if TYPE_CHECKING:
    from multiprocess_prototype_v3.services.renderer.ports import RendererOutputPort

from multiprocess_prototype_v3.services.renderer.drawing import (
    RenderOverlayState,
    apply_detection_overlays,
)


class RendererService:
    """Сервис рендеринга. Чистая логика без привязки к фреймворку."""

    def __init__(
        self,
        output: RendererOutputPort,
        output_dir: str = "./output_frames",
        save_frames: bool = False,
        draw_bboxes: bool = True,
        draw_contours: bool = True,
        show_original: bool = True,
        show_mask: bool = True,
    ) -> None:
        self._out = output
        self._output_dir = output_dir
        self._save_frames = save_frames
        self._draw_bboxes = draw_bboxes
        self._overlay_state = RenderOverlayState(draw_contours=draw_contours)
        self._show_original = show_original
        self._show_mask = show_mask

    # --- Properties для команд ---

    @property
    def draw_contours(self) -> bool:
        return self._overlay_state.draw_contours

    @draw_contours.setter
    def draw_contours(self, value: bool) -> None:
        self._overlay_state.draw_contours = bool(value)

    @property
    def draw_bboxes(self) -> bool:
        return self._draw_bboxes

    @draw_bboxes.setter
    def draw_bboxes(self, value: bool) -> None:
        self._draw_bboxes = bool(value)

    @property
    def show_original(self) -> bool:
        return self._show_original

    @show_original.setter
    def show_original(self, value: bool) -> None:
        self._show_original = bool(value)

    @property
    def show_mask(self) -> bool:
        return self._show_mask

    @show_mask.setter
    def show_mask(self, value: bool) -> None:
        self._show_mask = bool(value)

    @property
    def save_frames(self) -> bool:
        return self._save_frames

    @save_frames.setter
    def save_frames(self, value: bool) -> None:
        self._save_frames = bool(value)

    def render_frame(self, original: np.ndarray, mask: np.ndarray, data: dict) -> None:
        """Отрендерить кадр: overlay → SHM → GUI + Robot."""
        width, height = data.get("width", 640), data.get("height", 480)

        # Resize при необходимости
        if (original.shape[0] != height or original.shape[1] != width) and cv2 is not None:
            original = cv2.resize(original, (width, height), interpolation=cv2.INTER_LINEAR)

        # Применить overlay
        overlay = RenderOverlayState(
            draw_bboxes=self._draw_bboxes,
            draw_contours=self._overlay_state.draw_contours,
        )
        rendered = apply_detection_overlays(
            original,
            data,
            overlay,
            output_dir=self._output_dir,
            save_frames=self._save_frames,
        )

        # Записать в SHM и уведомить GUI через порт
        shm_data = self._out.write_rendered_to_shm(rendered, mask)
        if shm_data:
            detections = data.get("detections", [])
            notification = {
                "frame_id": data.get("frame_id", 0),
                "width": width,
                "height": height,
                "detections_count": len(detections),
                "show_original": self._show_original,
                "show_mask": self._show_mask,
                "draw_contours": self._overlay_state.draw_contours,
                **shm_data,
            }
            self._out.send_rendered_to_gui(notification)

        # Команда роботу при наличии детекций
        detections = data.get("detections", [])
        if detections:
            self._out.send_reject_to_robot(data.get("frame_id", 0), detections)

    @staticmethod
    def should_reject(detections: list[dict]) -> bool:
        """Нужна ли отбраковка."""
        return bool(detections)
