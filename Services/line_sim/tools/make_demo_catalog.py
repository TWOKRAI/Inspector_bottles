"""Нарисовать демо-каталог дисков-букв для стенда, пока нет реальных эталонов.

Реальные эталоны режет `Services.dataset_gen.tools.cut_real_disks` из фотографий;
до этого стенду нужен хоть какой-то каталог в той же форме (`<класс>/sprite.png`,
RGBA), иначе движок сцены откатывается к пустому фону.

    python -m Services.line_sim.tools.make_demo_catalog --out data/line_sim/demo_catalog

**`--size-px` — ПИКСЕЛИ эталона, не миллиметры (фикс ревью Task 3.4, P4).**
Формула: `size_px = diameter_mm * px_per_mm` — эталон катaлога это, что рисует
`SceneCompositor` 1:1 (без масштабирования слоя), поэтому диаметр диска на экране
равен `size_px` пикселей, а не `size_px` миллиметров ленты. Дефолт `66` — под стенд
`apps/line_sim/pipeline.yaml` (`disk_radius_mm: 55.0` рецепта прототипа => диаметр
110 мм, `px_per_mm: 0.6` => `110 * 0.6 = 66` px). Смена `px_per_mm` в конфиге стенда
требует пересчитать `--size-px` по той же формуле и перегенерировать каталог.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from Services.dataset_gen.core.catalog import imwrite_unicode

# Латиница: cv2.putText кириллицу не рисует (нужен freetype/PIL — для демо избыточно).
_LETTERS = {"A": (40, 40, 170), "K": (20, 110, 40), "P": (150, 30, 30), "X": (90, 40, 140)}


def make_disc(letter: str, color_rgb: tuple[int, int, int], size_px: int) -> np.ndarray:
    """RGBA-диск с буквой по центру, фон прозрачный."""
    sprite = np.zeros((size_px, size_px, 4), dtype=np.uint8)
    radius = size_px // 2 - 2
    cv2.circle(sprite, (size_px // 2, size_px // 2), radius, (215, 210, 195, 255), -1)
    scale = size_px / 50.0
    (tw, th), _ = cv2.getTextSize(letter, cv2.FONT_HERSHEY_DUPLEX, scale, max(1, int(scale * 2.5)))
    org = ((size_px - tw) // 2, (size_px + th) // 2)
    cv2.putText(sprite, letter, org, cv2.FONT_HERSHEY_DUPLEX, scale, (*color_rgb, 255), max(1, int(scale * 2.5)))
    return sprite


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="каталог классов (создаётся)")
    parser.add_argument(
        "--size-px",
        type=int,
        default=66,
        help="диаметр диска в ПИКСЕЛЯХ эталона (size_px = diameter_mm * px_per_mm — см. докстринг модуля)",
    )
    args = parser.parse_args()

    out = Path(args.out)
    for letter, color in _LETTERS.items():
        class_dir = out / letter
        class_dir.mkdir(parents=True, exist_ok=True)
        sprite = make_disc(letter, color, args.size_px)
        imwrite_unicode(class_dir / "sprite.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))
    print(f"каталог: {out} — {len(_LETTERS)} классов, диск {args.size_px} px")


if __name__ == "__main__":
    main()
