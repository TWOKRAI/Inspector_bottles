"""Frame generator for simulator camera backend."""

import numpy as np


class FrameGenerator:
    """Generates test frames with moving patterns."""

    def __init__(self, width: int, height: int, image_path: str = None):
        self._width = width
        self._height = height
        self._frame_count = 0
        self._static_image = None
        if image_path:
            try:
                import cv2
                img = cv2.imread(image_path)
                if img is not None:
                    self._static_image = cv2.resize(img, (width, height))
            except ImportError:
                pass

    def generate_frame(self) -> np.ndarray:
        self._frame_count += 1
        if self._static_image is not None:
            return self._static_image.copy()
        frame = np.zeros((self._height, self._width, 3), dtype=np.uint8)
        # Moving red rectangle
        x = (self._frame_count * 3) % max(1, self._width - 100)
        y = (self._frame_count * 2) % max(1, self._height - 100)
        frame[y:y+100, x:x+100] = [0, 0, 200]
        return frame

    def close(self):
        pass
