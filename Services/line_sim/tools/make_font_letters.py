# -*- coding: utf-8 -*-
"""Собрать каталог классов-букв из TTF/OTF-шрифтов (Task 1.1b, блок C).

В отличие от `make_letter_catalog.py` (источник — уже нарисованные вручную эталоны),
здесь буквы рисует сам инструмент через Pillow (`ImageFont.truetype` + `ImageDraw`):
каждая буква каждого шрифта -> отдельный RGBA-файл (чёрная непрозрачная буква на
прозрачном фоне, отцентрированная по альфа-bbox), форма каталога та же, что у
`make_letter_catalog.py` (`<буква>/<файл>.png`).

    python -m Services.line_sim.tools.make_font_letters \\
        --letters АК \\
        --font /путь/до/matplotlib/mpl-data/fonts/ttf/DejaVuSans.ttf \\
        --font /путь/до/matplotlib/mpl-data/fonts/ttf/DejaVuSans-Bold.ttf \\
        --size-px 300 --letter-frac 0.6 \\
        --out data/line_sim/letters_font \\
        --disk-out data/line_sim/letters_font_disk.png

`--size-px` — та же величина канвы (и, для `--disk-out`, диаметра диска), что
`DEFAULT_DIAMETER_PX` у `make_letter_catalog.py` (контракт лида 5.3b §4.1: окно
детектора `circle_detector`) — дефолт этого инструмента импортирован оттуда, а не
продублирован. `--letter-frac` — доля высоты буквы (альфа-bbox) от `--size-px`.

Шрифт без глифа для буквы (например `cmr10.ttf` из matplotlib — латинский
математический шрифт без кириллицы) -> `SystemExit` с именем файла шрифта и буквой
в тексте ошибки, ничего не пишется на диск для этой пары шрифт/буква.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim.tools.make_letter_catalog import DEFAULT_DIAMETER_PX

#: Кодпоинт, заведомо не занятый реальными шрифтами (private use, категория `Co`, плоскость 16;
#: ревью 1.1b: это не noncharacter — тот U+10FFFF) — эталон «глифа точно нет» для сравнения масок.
_MISSING_PROBE_CH = "\U0010fffd"

#: Во сколько раз канва пробного/финального рендера больше `size_px` — запас, чтобы
#: глиф (с учётом bearings/акцентов) не обрезался ДО измерения альфа-bbox.
_CANVAS_FACTOR = 4

_DEFAULT_LETTER_FRAC = 0.6


def _render_mask(font_path: Path, ch: str, font_size_pt: int, canvas_px: int) -> np.ndarray:
    """Один символ `ch`, отрисованный шрифтом `font_path` размера `font_size_pt` в
    центр квадратной канвы `canvas_px` x `canvas_px` -> маска "L" (0..255)."""
    try:
        font = ImageFont.truetype(str(font_path), font_size_pt)
    except OSError as exc:  # битмап-шрифт, битый файл (ревью 1.1b, NIT-6)
        raise SystemExit(f"make_font_letters: шрифт {font_path.name} не открывается как масштабируемый: {exc}") from exc
    img = Image.new("L", (canvas_px, canvas_px), 0)
    draw = ImageDraw.Draw(img)
    draw.text((canvas_px / 2, canvas_px / 2), ch, font=font, fill=255, anchor="mm")
    return np.array(img)


def _alpha_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """Bbox непрозрачных пикселей маски `(y0, y1, x0, x1)`; `None` — маска пустая."""
    ys, xs = np.nonzero(mask > 0)
    if len(ys) == 0:
        return None
    return int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())


def _check_glyph_present(
    font_path: Path, letter: str, probe_mask: np.ndarray, font_size_pt: int, canvas_px: int
) -> None:
    """Глифа нет: маска пустая ИЛИ совпадает побитово с маской заведомо отсутствующего
    кодпоинта (одинаковый fallback-глиф шрифта, например `.notdef`) -> `SystemExit`
    с именем файла шрифта и буквой в тексте (§C2 контракта)."""
    if not (probe_mask > 0).any():
        raise SystemExit(f"make_font_letters: в шрифте {font_path.name} нет глифа для буквы {letter!r} (пустая маска)")
    missing_mask = _render_mask(font_path, _MISSING_PROBE_CH, font_size_pt, canvas_px)
    if np.array_equal(probe_mask, missing_mask):
        raise SystemExit(
            f"make_font_letters: в шрифте {font_path.name} нет глифа для буквы {letter!r} "
            "(совпадает с заведомо отсутствующим кодпоинтом)"
        )


def _center_crop(source: np.ndarray, center_rc: tuple[float, float], out_size: int) -> np.ndarray:
    """Квадрат `out_size` x `out_size` из `source`, вырезанный так, чтобы точка
    `center_rc` (row, col) исходного массива оказалась в центре результата. Часть
    выреза за пределами `source` остаётся нулевой (тот же dtype, что у `source`)."""
    cy, cx = center_rc
    y0 = int(round(cy - out_size / 2))
    x0 = int(round(cx - out_size / 2))
    out = np.zeros((out_size, out_size), dtype=source.dtype)
    src_y0, src_x0 = max(y0, 0), max(x0, 0)
    src_y1, src_x1 = min(y0 + out_size, source.shape[0]), min(x0 + out_size, source.shape[1])
    dst_y0, dst_x0 = src_y0 - y0, src_x0 - x0
    dst_y1, dst_x1 = dst_y0 + (src_y1 - src_y0), dst_x0 + (src_x1 - src_x0)
    if src_y1 > src_y0 and src_x1 > src_x0:
        out[dst_y0:dst_y1, dst_x0:dst_x1] = source[src_y0:src_y1, src_x0:src_x1]
    return out


def _render_letter(font_path: Path, letter: str, size_px: int, letter_frac: float) -> np.ndarray:
    """Одна буква одного шрифта -> RGBA `size_px` x `size_px` (RGB=0 чёрный, альфа=маска).

    Pre: `font_path` содержит глиф буквы `letter` (иначе `SystemExit`, см.
    `_check_glyph_present`).
    Post: высота альфа-bbox результата == `round(letter_frac * size_px)` (с точностью
    округления шрифтового размера в пунктах), центр bbox — в центре канвы.

    Метод (докстринг DESIGN, Task 1.1b §C): пробный рендер размером шрифта `size_px` пт
    на канве с запасом (`_CANVAS_FACTOR`) -> измерить высоту альфа-bbox -> посчитать
    коэффициент масштаба к желаемой высоте -> перерендерить финальным размером шрифта ->
    вырезать квадрат `size_px` так, чтобы центр НОВОГО альфа-bbox совпал с центром канвы.
    """
    canvas_px = size_px * _CANVAS_FACTOR
    probe_mask = _render_mask(font_path, letter, size_px, canvas_px)
    _check_glyph_present(font_path, letter, probe_mask, size_px, canvas_px)

    probe_bbox = _alpha_bbox(probe_mask)
    assert probe_bbox is not None  # проверено _check_glyph_present выше
    probe_h = probe_bbox[1] - probe_bbox[0] + 1
    desired_h = round(letter_frac * size_px)
    final_font_size = max(1, round(size_px * (desired_h / probe_h)))

    final_mask = _render_mask(font_path, letter, final_font_size, canvas_px)
    final_bbox = _alpha_bbox(final_mask)
    assert final_bbox is not None, f"перерендер {font_path.name}/{letter!r} дал пустую маску при size={final_font_size}"
    fy0, fy1, fx0, fx1 = final_bbox
    width = fx1 - fx0 + 1
    if width > size_px:  # масштаб по высоте; широкая буква молча обрезалась бы по бокам (ревью 1.1b)
        raise SystemExit(
            f"make_font_letters: шрифт {font_path.name}, буква {letter!r}: ширина {width} px > size_px {size_px} "
            "— уменьшите --letter-frac"
        )
    center_rc = ((fy0 + fy1) / 2.0, (fx0 + fx1) / 2.0)
    mask = _center_crop(final_mask, center_rc, size_px)

    rgba = np.zeros((size_px, size_px, 4), dtype=np.uint8)
    rgba[:, :, 3] = mask
    return rgba


def build_font_letters(
    letters: str,
    fonts: list[Path],
    size_px: int,
    letter_frac: float,
    out: Path,
) -> list[Path]:
    """Собрать каталог `out/<буква>/<стем файла шрифта>.png` для каждой пары буква x
    шрифт. Возвращает список записанных файлов (порядок: буквы `letters`, внутри —
    порядок `fonts`)."""
    # Сначала все рендеры, потом запись: ошибка на любой паре не оставляет пустых папок
    # классов, которые каталог молча принял бы (ревью 1.1b, NIT-3).
    rendered = [
        (out / letter / f"{Path(font_path).stem}.png", _render_letter(Path(font_path), letter, size_px, letter_frac))
        for letter in letters
        for font_path in fonts
    ]
    for dest, rgba in rendered:
        dest.parent.mkdir(parents=True, exist_ok=True)
        imwrite_unicode(dest, cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    return [dest for dest, _ in rendered]


def build_disk(size_px: int) -> np.ndarray:
    """Белый непрозрачный диск диаметром `size_px` на прозрачном фоне (RGBA), с
    антиалиасингом края: рисуется в 4x масштабе и уменьшается `cv2.INTER_AREA` — углы
    канвы остаются прозрачными (эллипс не касается краёв квадрата)."""
    big = size_px * _CANVAS_FACTOR
    img = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, big - 1, big - 1), fill=255)
    alpha_big = np.array(img)
    alpha = cv2.resize(alpha_big, (size_px, size_px), interpolation=cv2.INTER_AREA)

    rgba = np.zeros((size_px, size_px, 4), dtype=np.uint8)
    rgba[:, :, 0:3] = 255
    rgba[:, :, 3] = alpha
    return rgba


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--letters", required=True, help="буквы каталога, по одному символу (например АК)")
    parser.add_argument(
        "--font", required=True, action="append", help="путь к .ttf/.otf файлу шрифта (можно повторять)"
    )
    parser.add_argument(
        "--size-px",
        type=int,
        default=DEFAULT_DIAMETER_PX,
        help=f"размер канвы буквы в px, он же диаметр --disk-out (дефолт {DEFAULT_DIAMETER_PX}, см. докстринг)",
    )
    parser.add_argument(
        "--letter-frac",
        type=float,
        default=_DEFAULT_LETTER_FRAC,
        help=f"доля высоты буквы (альфа-bbox) от --size-px (дефолт {_DEFAULT_LETTER_FRAC})",
    )
    parser.add_argument("--out", required=True, help="каталог классов-букв (создаётся)")
    parser.add_argument("--disk-out", default=None, help="путь для белого диска-подложки (опционально)")
    args = parser.parse_args(argv)

    fonts = [Path(f) for f in args.font]
    out = Path(args.out)
    written = build_font_letters(args.letters, fonts, args.size_px, args.letter_frac, out)
    print(f"буквы: {len(args.letters)}, шрифты: {len(fonts)} -> {len(written)} файлов в {out}")

    if args.disk_out:
        disk = build_disk(args.size_px)
        disk_path = Path(args.disk_out)
        disk_path.parent.mkdir(parents=True, exist_ok=True)
        imwrite_unicode(disk_path, cv2.cvtColor(disk, cv2.COLOR_RGBA2BGRA))
        print(f"диск: {disk_path} ({args.size_px}px)")


if __name__ == "__main__":
    main()
