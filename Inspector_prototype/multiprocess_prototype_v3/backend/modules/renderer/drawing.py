"""Отрисовка детекций на кадре (numpy + опционально OpenCV)."""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None


@dataclass
class RenderOverlayState:
    draw_bboxes: bool = True
    draw_contours: bool = True


def draw_bbox_numpy(
    frame: np.ndarray, bbox: list, color: tuple = (0, 255, 0), thickness: int = 2
) -> None:
    x1, y1, x2, y2 = bbox
    h, w = frame.shape[:2]
    x1, x2 = max(0, x1), min(w, x2)
    y1, y2 = max(0, y1), min(h, y2)
    t = min(thickness, x2 - x1, y2 - y1)
    if t <= 0:
        return
    frame[y1 : y1 + t, x1:x2, :] = color
    frame[y2 - t : y2, x1:x2, :] = color
    frame[y1:y2, x1 : x1 + t, :] = color
    frame[y1:y2, x2 - t : x2, :] = color


def apply_detection_overlays(
    frame: np.ndarray,
    data: dict,
    state: RenderOverlayState,
    *,
    output_dir: str,
    save_frames: bool,
) -> np.ndarray:
    detections = data.get("detections", [])
    contours = data.get("contours", [])
    frame_id = data.get("frame_id", 0)
    if state.draw_bboxes:
        for det in detections:
            draw_bbox_numpy(frame, det.get("bbox", [0, 0, 0, 0]))
    if state.draw_contours and contours and cv2 is not None:
        cv2.drawContours(frame, contours, -1, (0, 255, 0), 2)
    if save_frames:
        os.makedirs(output_dir, exist_ok=True)
        np.save(os.path.join(output_dir, f"frame_{frame_id:06d}.npy"), frame)
    return frame
