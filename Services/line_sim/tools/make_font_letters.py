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

Краска (Task 1.2, line-sim-belt-look) — все флаги необязательны, без них вывод байт в байт прежний:

    --ink-rgb R,G,B        цвет краски букв (RGB во ВСЕХ пикселях, альфа не трогается), по умолчанию чёрный
    --grain-sigma S        σ гауссова зерна по каждому каналу, только на буквах (альфа > 0)
    --seed N               seed зерна (один rng на запуск, порядок буква x шрифт фиксирован;
                       зерно буквы поэтому зависит от набора букв и шрифтов запуска)
    --edge-blur-px S       σ гауссова размытия альфы буквы (мягкий край)
    --disk-from-photo PATH диск --disk-out вырезается из реального фото (нужен --disk-out)

Измеренные реальные значения: цвет краски ≈ (65, 70, 82) по 20 кадрам плана (в фикстуре ядро
(59, 65, 77)), зерно σ ≈ 9, край ~2 px, диск 300 px.
Реальный диск на кадре пересвечен до 255 (в фикстуре 95-97 % пикселей), поэтому плоский белый спрайт
соответствует снимку. Зерно у фото-диска не добавляется; `--grain-sigma` относится только к буквам.

    python -m Services.line_sim.tools.make_font_letters --letters АК --font ... --out ... \\
        --ink-rgb 65,70,82 --grain-sigma 9 --edge-blur-px 1 \\
        --disk-from-photo Services/line_sim/tests/fixtures/real_disk_snapshot.png --disk-out ...

`--disk-from-photo`: фото -> порог яркости 150 -> крупнейшая компонента -> `minEnclosingCircle`;
печать внутри круга стирается `cv2.inpaint`; квадрат по кругу (центр круга — в центре выреза) ->
`--size-px`; альфа — круг диаметром `size_px - 6` (отступ 3 px), размытый σ = 1 (край ~2.5 px; хвост
не упирается в край канвы). Нет круга (площадь < 0.8·πr², r < 20 px,
нечитаемое фото) -> `SystemExit` с путём фото.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from Services.dataset_gen.core.catalog import imread_unicode, imwrite_unicode
from Services.line_sim.tools.make_letter_catalog import DEFAULT_DIAMETER_PX

#: Кодпоинт, заведомо не занятый реальными шрифтами (private use, категория `Co`, плоскость 16;
#: ревью 1.1b: это не noncharacter — тот U+10FFFF) — эталон «глифа точно нет» для сравнения масок.
_MISSING_PROBE_CH = "\U0010fffd"

#: Во сколько раз канва пробного/финального рендера больше `size_px` — запас, чтобы
#: глиф (с учётом bearings/акцентов) не обрезался ДО измерения альфа-bbox.
_CANVAS_FACTOR = 4

_DEFAULT_LETTER_FRAC = 0.6

#: Порог яркости: диск светлее (маска диска), печать темнее (маска печати) — Task 1.2.
_PHOTO_GRAY_THRESHOLD = 150
#: Диск считается найденным, если его компонента занимает не меньше этой доли круга.
_MIN_DISK_FILL = 0.8
_MIN_DISK_RADIUS_PX = 20
#: Отступ маски печати от края круга (не стирать кромку диска) и ядро её расширения.
_PRINT_MASK_MARGIN_PX = 3
_PRINT_DILATE_KERNEL = 5
#: σ размытия альфы фото-диска: край 10->90 % ~2.5 px вместо 1 px у `build_disk`.
_PHOTO_DISK_EDGE_SIGMA = 1.0
#: Отступ альфа-круга фото-диска от края канвы: хвост гаусса σ=1 (2.5σ = 2.5 px от центра пикселя
#: крайней строки) умещается, α крайних строк/столбцов <= 5.
_PHOTO_DISK_MARGIN_PX = 3


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
    width = max(fx1 - fx0 + 1, fy1 - fy0 + 1)  # и высота: --letter-frac > 1 (ревью 1.1b it.2, NIT-7)
    if width >= size_px:  # масштаб по высоте; широкая буква молча обрезалась бы по бокам (ревью 1.1b)
        raise SystemExit(
            f"make_font_letters: шрифт {font_path.name}, буква {letter!r}: ширина {width} px > size_px {size_px} "
            "— уменьшите --letter-frac"
        )
    center_rc = ((fy0 + fy1) / 2.0, (fx0 + fx1) / 2.0)
    mask = _center_crop(final_mask, center_rc, size_px)

    rgba = np.zeros((size_px, size_px, 4), dtype=np.uint8)
    rgba[:, :, 3] = mask
    return rgba


def _finish_ink(
    rgba: np.ndarray,
    ink_rgb: tuple[int, int, int] | None,
    grain_sigma: float,
    edge_blur_px: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Покрасить букву: мягкий край -> цвет краски -> зерно. Без опций возвращает `rgba` как есть.

    Порядок: альфа размывается ПЕРВОЙ, зерно применяется по итоговой маске `альфа > 0` — иначе
    расширенная размытием кромка осталась бы без зерна. Цвет краски пишется во ВСЕ пиксели (в том
    числе прозрачные, альфа не меняется): `LayeredObject._transform` масштабирует/поворачивает RGB
    без премультипликации, и чёрный RGB прозрачных соседей подмешивался бы в кромку (color bleed,
    кромка темнела до ~17 уровней). Зерно считается в float и клипуется в uint8 (без переполнения) и
    в прозрачные пиксели не попадает — там ровный цвет краски.
    """
    if ink_rgb is None and grain_sigma <= 0 and edge_blur_px <= 0:
        return rgba
    if edge_blur_px > 0:
        rgba[:, :, 3] = cv2.GaussianBlur(rgba[:, :, 3], (0, 0), sigmaX=edge_blur_px)
    ink_mask = rgba[:, :, 3] > 0
    if ink_rgb is not None:
        rgba[:, :, 0:3] = ink_rgb
    if grain_sigma > 0:
        noise = rng.normal(0.0, grain_sigma, size=rgba.shape[:2] + (3,))
        noisy = rgba[:, :, 0:3].astype(np.float64) + noise
        rgba[ink_mask, 0:3] = np.clip(np.rint(noisy[ink_mask]), 0, 255).astype(np.uint8)
    return rgba


def build_font_letters(
    letters: str,
    fonts: list[Path],
    size_px: int,
    letter_frac: float,
    out: Path,
    *,
    ink_rgb: tuple[int, int, int] | None = None,
    grain_sigma: float = 0.0,
    edge_blur_px: float = 0.0,
    seed: int = 0,
) -> list[Path]:
    """Собрать каталог `out/<буква>/<стем файла шрифта>.png` для каждой пары буква x
    шрифт. Возвращает список записанных файлов (порядок: буквы `letters`, внутри —
    порядок `fonts`). Опции краски (`ink_rgb`, `grain_sigma`, `edge_blur_px`, `seed`) — см.
    `_finish_ink`; по умолчанию вывод прежний."""
    rng = np.random.default_rng(seed)  # один на вызов: порядок буква x шрифт фиксирует зерно
    # Сначала все рендеры, потом запись: ошибка на любой паре не оставляет пустых папок
    # классов, которые каталог молча принял бы (ревью 1.1b, NIT-3).
    rendered = [
        (
            out / letter / f"{Path(font_path).stem}.png",
            _finish_ink(
                _render_letter(Path(font_path), letter, size_px, letter_frac),
                ink_rgb,
                grain_sigma,
                edge_blur_px,
                rng,
            ),
        )
        for letter in letters
        for font_path in fonts
    ]
    for dest, rgba in rendered:
        dest.parent.mkdir(parents=True, exist_ok=True)
        imwrite_unicode(dest, cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    return [dest for dest, _ in rendered]


def _disk_alpha(size_px: int) -> np.ndarray:
    """Альфа круга диаметром `size_px` (uint8, `size_px` x `size_px`): рисуется в 4x масштабе и
    уменьшается `cv2.INTER_AREA` — антиалиасинг края, углы канвы остаются прозрачными
    (эллипс не касается краёв квадрата)."""
    big = size_px * _CANVAS_FACTOR
    img = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, big - 1, big - 1), fill=255)
    alpha_big = np.array(img)
    return cv2.resize(alpha_big, (size_px, size_px), interpolation=cv2.INTER_AREA)


def build_disk(size_px: int) -> np.ndarray:
    """Белый непрозрачный диск диаметром `size_px` на прозрачном фоне (RGBA), с
    антиалиасингом края (`_disk_alpha`)."""
    rgba = np.zeros((size_px, size_px, 4), dtype=np.uint8)
    rgba[:, :, 0:3] = 255
    rgba[:, :, 3] = _disk_alpha(size_px)
    return rgba


def _find_disk_circle(gray: np.ndarray, photo_path: Path) -> tuple[float, float, float]:
    """Круг диска на фото `(cx, cy, r)`: крупнейшая светлая компонента + `minEnclosingCircle`.
    `SystemExit` с путём фото, если компонента не похожа на круг (заполнение < 0.8, r < 20 px)."""
    mask = (gray > _PHOTO_GRAY_THRESHOLD).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count < 2:
        raise SystemExit(
            f"make_font_letters: на фото {photo_path} нет светлой области диска (яркость > {_PHOTO_GRAY_THRESHOLD})"
        )
    label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    area = float(stats[label, cv2.CC_STAT_AREA])
    contours, _ = cv2.findContours((labels == label).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    (cx, cy), r = cv2.minEnclosingCircle(np.concatenate(contours))
    if r < _MIN_DISK_RADIUS_PX or area < _MIN_DISK_FILL * np.pi * r * r:
        raise SystemExit(
            f"make_font_letters: на фото {photo_path} не найден круглый диск "
            f"(r={r:.1f} px, площадь {area:.0f} при круге {np.pi * r * r:.0f})"
        )
    return float(cx), float(cy), float(r)


def build_disk_from_photo(photo_path: Path, size_px: int) -> np.ndarray:
    """Диск из реального фото (RGBA `size_px` x `size_px`): печать стёрта `cv2.inpaint`,
    зерно фото сохранено (у пересвеченного диска его нет), альфа — круг `size_px - 6`, размытый.

    Pre: на фото светлый (> 150) круглый диск радиусом >= 20 px.
    Post: `SystemExit` с путём фото, если фото не читается или круга нет.
    """
    try:
        photo = imread_unicode(photo_path, cv2.IMREAD_COLOR)
    except (ValueError, OSError, cv2.error) as exc:  # cv2.error — пустой файл (0 байт)
        raise SystemExit(f"make_font_letters: фото {photo_path} не читается: {exc}") from exc
    gray = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
    cx, cy, r = _find_disk_circle(gray, photo_path)

    yy, xx = np.mgrid[0 : gray.shape[0], 0 : gray.shape[1]]
    inside = (xx - cx) ** 2 + (yy - cy) ** 2 <= (r - _PRINT_MASK_MARGIN_PX) ** 2
    print_mask = (inside & (gray < _PHOTO_GRAY_THRESHOLD)).astype(np.uint8) * 255
    print_mask = cv2.dilate(print_mask, np.ones((_PRINT_DILATE_KERNEL, _PRINT_DILATE_KERNEL), np.uint8))
    clean = cv2.inpaint(photo, print_mask, 5, cv2.INPAINT_TELEA)

    # Квадрат [c - r, c + r]; если круг у края фото — добиваем повтором крайних пикселей.
    # Центр круга (индексы пикселей) должен попасть в центр выреза: центр side пикселей — x0 + (side - 1) / 2.
    # Чётность side подбирается (round(2r) или +1) так, чтобы целочисленный x0, y0 давал минимальный сдвиг:
    # при целом центре нужен нечётный side, при полуцелом — чётный.
    def _center_error(side_px: int) -> float:
        half = (side_px - 1) / 2
        return sum(abs(round(c - half) + half - c) for c in (cx, cy))

    side0 = int(round(2 * r))
    side = min((side0, side0 + 1), key=_center_error)
    x0, y0 = int(round(cx - (side - 1) / 2)), int(round(cy - (side - 1) / 2))
    pad = side  # с запасом: сдвиг выреза не выходит за padded-массив (круг всегда внутри фото)
    padded = cv2.copyMakeBorder(clean, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    crop = padded[y0 + pad : y0 + pad + side, x0 + pad : x0 + pad + side]
    resized = cv2.resize(crop, (size_px, size_px), interpolation=cv2.INTER_AREA)

    rgba = np.zeros((size_px, size_px, 4), dtype=np.uint8)
    rgba[:, :, 0:3] = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    # Круг с отступом от края канвы, иначе размытый хвост обрезался бы краем (ступенька на ~22 % окружности).
    alpha = np.pad(_disk_alpha(size_px - 2 * _PHOTO_DISK_MARGIN_PX), _PHOTO_DISK_MARGIN_PX)
    rgba[:, :, 3] = cv2.GaussianBlur(alpha, (0, 0), sigmaX=_PHOTO_DISK_EDGE_SIGMA)
    return rgba


def _parse_ink_rgb(text: str) -> tuple[int, int, int]:
    """`R,G,B` -> кортеж из трёх int 0..255; иначе `ArgumentTypeError` (argparse -> exit 2)."""
    try:
        parts = [int(p) for p in text.split(",")]
    except ValueError:
        parts = []
    if len(parts) != 3 or not all(0 <= v <= 255 for v in parts):
        raise argparse.ArgumentTypeError(f"ожидали R,G,B — три целых 0..255, получили {text!r}")
    return (parts[0], parts[1], parts[2])


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
    parser.add_argument("--ink-rgb", type=_parse_ink_rgb, default=None, help="цвет краски букв R,G,B (0..255)")
    parser.add_argument("--grain-sigma", type=float, default=0.0, help="σ зерна на буквах (дефолт 0 — без зерна)")
    parser.add_argument("--seed", type=int, default=0, help="seed зерна (дефолт 0)")
    parser.add_argument("--edge-blur-px", type=float, default=0.0, help="σ размытия альфы буквы (дефолт 0)")
    parser.add_argument(
        "--disk-from-photo", default=None, help="фото реального диска для --disk-out (вместо белого круга)"
    )
    args = parser.parse_args(argv)
    if args.disk_from_photo and not args.disk_out:
        parser.error("--disk-from-photo требует --disk-out")
    for flag, value in (("--grain-sigma", args.grain_sigma), ("--edge-blur-px", args.edge_blur_px)):
        if not (math.isfinite(value) and value >= 0):
            parser.error(f"{flag} должен быть конечным числом >= 0, получили {value}")

    fonts = [Path(f) for f in args.font]
    out = Path(args.out)
    # Диск строится в памяти ДО букв: нечитаемое фото не оставляет на диске ни одного файла.
    disk = None
    if args.disk_from_photo:
        disk = build_disk_from_photo(Path(args.disk_from_photo), args.size_px)
    elif args.disk_out:
        disk = build_disk(args.size_px)
    written = build_font_letters(
        args.letters,
        fonts,
        args.size_px,
        args.letter_frac,
        out,
        ink_rgb=args.ink_rgb,
        grain_sigma=args.grain_sigma,
        edge_blur_px=args.edge_blur_px,
        seed=args.seed,
    )
    print(f"буквы: {len(args.letters)}, шрифты: {len(fonts)} -> {len(written)} файлов в {out}")

    if disk is not None:
        disk_path = Path(args.disk_out)
        disk_path.parent.mkdir(parents=True, exist_ok=True)
        imwrite_unicode(disk_path, cv2.cvtColor(disk, cv2.COLOR_RGBA2BGRA))
        print(f"диск: {disk_path} ({args.size_px}px)")


if __name__ == "__main__":
    main()
