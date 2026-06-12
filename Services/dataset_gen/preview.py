"""QC-утилита: сетка случайных сгенерированных кадров с подписями.

Для визуальной проверки реалистичности и отсутствия видимых швов вклейки.
Подписи (класс + угол) рисуются через PIL — cv2.putText не умеет кириллицу.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from Services.dataset_gen.interfaces import SampleGenerator

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _caption(label) -> str:
    text = f"{label.class_name}  θ={label.angle_deg:.1f}°"
    if label.symmetry == "180":
        text += " [180°]"
    elif label.symmetry == "full":
        text += " [full: угол игнор.]"
    return text


def save_preview_grid(
    generator: SampleGenerator,
    path: str | Path,
    n: int = 16,
    cols: int = 4,
    rng: np.random.Generator | None = None,
    caption_height: int = 22,
) -> Path:
    """Сохранить сетку из n случайных кадров с подписями «класс + угол».

    Pre:
      - n ≥ 1, cols ≥ 1
    Post:
      - файл создан; размер сетки = cols × ceil(n/cols) тайлов
    """
    if n < 1 or cols < 1:
        raise ValueError(f"Ожидалось n>=1 и cols>=1, получено n={n}, cols={cols}")
    samples = [generator.generate_sample(rng=rng) for _ in range(n)]
    tile_h, tile_w = samples[0][0].shape[:2]
    rows = math.ceil(n / cols)
    cell_h = tile_h + caption_height

    grid = Image.new("RGB", (cols * tile_w, rows * cell_h), color=(24, 24, 24))
    draw = ImageDraw.Draw(grid)
    font = _load_font(max(10, caption_height - 8))

    for i, (frame, label) in enumerate(samples):
        r, c = divmod(i, cols)
        x0, y0 = c * tile_w, r * cell_h
        grid.paste(Image.fromarray(frame), (x0, y0))
        draw.text((x0 + 4, y0 + tile_h + 3), _caption(label), fill=(230, 230, 230), font=font)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    grid.save(out)
    return out
