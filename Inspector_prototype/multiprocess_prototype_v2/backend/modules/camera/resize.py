"""Ресайз кадра под размер SHM."""

import numpy as np


def resize_frame_for_shm(
    frame: np.ndarray, target_h: int, target_w: int
) -> np.ndarray:
    if frame.shape[0] == target_h and frame.shape[1] == target_w:
        return frame
    try:
        import cv2

        return cv2.resize(
            frame,
            (target_w, target_h),
            interpolation=cv2.INTER_LINEAR,
        )
    except ImportError:
        return frame
