"""Генератор эталонов для пресета ru_letters_disk: 33 русские заглавные буквы,
чёрные, одним шрифтом, на белом диске; вне диска — прозрачно (RGBA).

Запуск из корня репозитория:
    python -m Services.dataset_gen.tools.make_ru_letter_sprites \
        --out data/dataset_gen/ru_letters/sprites [--size 256] [--font path.ttf]

Создаёт подкаталог на букву (имя подкаталога = имя класса) с base.png внутри —
ровно та структура, которую ждёт CatalogConfig.classes_dir.
Запись через PIL: cv2.imwrite не умеет кириллические пути на Windows.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

RU_UPPERCASE = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"  # 33 буквы

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def find_default_font() -> str:
    """Найти системный TTF с кириллицей; FileNotFoundError если нет ни одного."""
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise FileNotFoundError("Не найден системный шрифт с кириллицей — укажите --font путь/к/шрифту.ttf")


def render_letter_sprite(
    letter: str,
    size: int = 256,
    font_path: str | None = None,
    disk_margin_frac: float = 0.03,
    letter_frac: float = 0.60,
) -> np.ndarray:
    """Отрисовать эталон: чёрная буква на белом диске, фон прозрачный.

    Pre:
      - len(letter) == 1; 0 < letter_frac < 1
    Post:
      - RGBA uint8 size×size; углы (вне диска) полностью прозрачны
    """
    if len(letter) != 1:
        raise ValueError(f"Ожидалась одна буква, получено {letter!r}")
    font_path = font_path or find_default_font()

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = size * disk_margin_frac
    draw.ellipse((margin, margin, size - margin, size - margin), fill=(255, 255, 255, 255))

    # подбор кегля: высота буквы ≈ letter_frac от диаметра (двухшаговая оценка)
    target_h = size * letter_frac
    probe = ImageFont.truetype(font_path, 100)
    bbox = probe.getbbox(letter)
    probe_h = max(1, bbox[3] - bbox[1])
    font = ImageFont.truetype(font_path, max(8, int(round(100 * target_h / probe_h))))

    # Центрируем по ФАКТИЧЕСКОМУ bbox чернил, не по метрикам шрифта: anchor="mm"
    # ставит глиф по линиям ascender/descender и смещает букву от центра диска —
    # это ломает 180°-симметрию спрайта (буква при повороте «переезжает»).
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((size / 2.0, size / 2.0), letter, fill=(0, 0, 0, 255), font=font, anchor="mm")
    ink_bbox = layer.getbbox()
    if ink_bbox is None:
        raise ValueError(f"Глиф {letter!r} не отрисовался шрифтом {font_path}")
    glyph = layer.crop(ink_bbox)
    paste_x = int(round((size - glyph.width) / 2.0))
    paste_y = int(round((size - glyph.height) / 2.0))
    img.paste(glyph, (paste_x, paste_y), glyph)
    return np.array(img)


def generate_sprites(
    out_dir: str | Path,
    letters: str = RU_UPPERCASE,
    size: int = 256,
    font_path: str | None = None,
) -> list[Path]:
    """Сгенерировать каталог классов: подкаталог на букву с base.png.

    Post:
      - создано len(letters) подкаталогов, в каждом base.png (RGBA)
    """
    out = Path(out_dir)
    created: list[Path] = []
    for letter in letters:
        sprite = render_letter_sprite(letter, size=size, font_path=font_path)
        class_dir = out / letter
        class_dir.mkdir(parents=True, exist_ok=True)
        path = class_dir / "base.png"
        Image.fromarray(sprite).save(path)  # PIL: unicode-пути ок на Windows
        created.append(path)
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="каталог классов (classes_dir пресета)")
    parser.add_argument("--size", type=int, default=256, help="сторона эталона, px")
    parser.add_argument("--font", default=None, help="путь к TTF (дефолт: системный Arial Bold)")
    parser.add_argument("--letters", default=RU_UPPERCASE, help="набор символов-классов")
    args = parser.parse_args()

    created = generate_sprites(args.out, args.letters, args.size, args.font)
    print(f"Создано {len(created)} эталонов в {args.out}")


if __name__ == "__main__":
    main()
