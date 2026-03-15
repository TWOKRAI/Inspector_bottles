"""
Генератор тестовых кадров для имитации камеры.

Используется при use_simulator=True вместо cv2.VideoCapture.
Режимы:
  - image_path задан: загружает изображение и возвращает его как numpy (BGR),
    ресайз под resolution. Имитирует камеру без реального устройства.
  - image_path не задан: генерирует синтетические кадры с цветным пятном.
"""

from pathlib import Path
from typing import Optional, Union

import numpy as np


def _default_test_image_path() -> Path:
    """Путь к test_image.png относительно multiprocess_prototype."""
    return Path(__file__).resolve().parent.parent / "tests" / "test_image.png"


class FrameGenerator:
    """Имитация камеры: загрузка из файла или генерация синтетических кадров."""

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        image_path: Optional[Union[str, Path]] = None,
    ):
        self.width = width
        self.height = height
        self._frame_count = 0

        # Режим имитации: из файла или синтетика
        # image_path=None → default test_image.png; "" → только синтетика
        path = None if image_path == "" else (image_path or _default_test_image_path())
        self._cached_frame: Optional[np.ndarray] = None
        self._image_path = Path(path) if path else None

        if self._image_path and self._image_path.exists():
            try:
                self._cached_frame = self._load_and_resize(str(self._image_path))
            except (ImportError, FileNotFoundError, OSError) as e:
                import warnings
                warnings.warn(
                    f"Cannot load simulator image {self._image_path}: {e}. "
                    "Falling back to synthetic frames. Install opencv-python or Pillow."
                )
                self._cached_frame = None
        else:
            self._cached_frame = None
            if self._image_path:
                import warnings
                warnings.warn(
                    f"Simulator image not found: {self._image_path}, "
                    "falling back to synthetic frames"
                )

    def _load_and_resize(self, path: str) -> np.ndarray:
        """Загружает изображение и приводит к (height, width, 3) BGR uint8.
        Использует cv2 при наличии, иначе PIL (RGB→BGR через [:, :, ::-1]).
        """
        try:
            import cv2
            img = cv2.imread(path)
            if img is None:
                raise FileNotFoundError(f"Cannot load image: {path}")
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            elif img.shape[2] == 4:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            if (img.shape[0], img.shape[1]) != (self.height, self.width):
                img = cv2.resize(
                    img, (self.width, self.height), interpolation=cv2.INTER_LINEAR
                )
            return img.astype(np.uint8)
        except ImportError:
            pass

        # Fallback: PIL (кросс-платформенно, без opencv)
        from PIL import Image
        pil_img = Image.open(path)
        if pil_img.mode == "RGBA":
            pil_img = pil_img.convert("RGB")
        elif pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")
        img = np.array(pil_img)
        if (img.shape[0], img.shape[1]) != (self.height, self.width):
            pil_resized = pil_img.resize(
                (self.width, self.height), Image.Resampling.LANCZOS
            )
            img = np.array(pil_resized)
        # PIL RGB → BGR для совместимости с cv2-пайплайном
        return img[:, :, ::-1].astype(np.uint8)

    def generate_frame(self) -> np.ndarray:
        """Возвращает кадр: из файла (если загружен) или синтетический."""
        self._frame_count += 1
        if self._cached_frame is not None:
            return self._cached_frame.copy()

        # Fallback: синтетический кадр
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (30, 30, 30)
        cx = int(self.width / 2 + 150 * np.sin(self._frame_count * 0.05))
        cy = int(self.height / 2 + 100 * np.cos(self._frame_count * 0.03))
        radius = 30
        y, x = np.ogrid[-cy : self.height - cy, -cx : self.width - cx]
        mask = x**2 + y**2 <= radius**2
        frame[mask] = (0, 0, 255)
        return frame

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def uses_image_file(self) -> bool:
        """True, если кадры берутся из файла (имитация камеры без устройства)."""
        return self._cached_frame is not None
