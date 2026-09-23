"""Собрать каталог классов-букв для боевого рецепта из готовых кириллических эталонов.

В отличие от `make_demo_catalog.py` (латиница, генерируется `cv2.putText`), здесь
источник — уже нарисованные спрайты (`manual_sprites/<буква>/*.png`, RGBA), инструмент
только ресайзит их до единого диаметра и раскладывает в форму каталога `line_sim`
(`<буква>/<файл>.png`), которую читает `Services.dataset_gen.core.catalog.SpriteCatalog`.

    python -m Services.line_sim.tools.make_letter_catalog \
        --src manual_sprites --letters АКРХ --diameter-px 300 \
        --out data/line_sim/letter_catalog

**`--diameter-px` — диаметр диска НА ЭКРАНЕ, в пикселях кадра сима (контракт лида
5.3b, §4.1).** `diameter_px ≈ disc_mm * px_per_mm` — но, в отличие от
`make_demo_catalog.py`, дефолт здесь не выводится из диаметра диска в мм, а фиксирован
окном детектора `circle_detector` боевого рецепта: минимальный/максимальный радиус
90..230 px, середина окна ≈ 150 px радиуса → `DEFAULT_DIAMETER_PX = 300`. Путь такой,
что радиус эталона (`DEFAULT_DIAMETER_PX / 2`) заведомо внутри окна детектора — сторож
дрейфа `apps/line_sim/tests/test_fit_letter_robot.py::test_disc_diameter_inside_circle_detector_window`.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

from Services.dataset_gen.core.catalog import imread_unicode, imwrite_unicode

#: Радиус диска на экране лежит в окне circle_detector [90, 230] px (боевой рецепт
#: hikvision_letter_robot.yaml) — середина окна ≈ 150 px радиуса, см. докстринг модуля.
DEFAULT_DIAMETER_PX = 300

_META_FILENAME = "meta.yaml"


def _resize_keep_alpha(sprite: np.ndarray, diameter_px: int, *, src_path: Path) -> np.ndarray:
    """Ресайз RGBA-эталона до `(diameter_px, diameter_px)` с сохранением альфы.

    Pre: `sprite` — RGBA (`ndim == 3`, `shape[2] == 4`), иначе `SystemExit` называет
    файл (§4.2.4 контракта — эталон без альфы не годится движку сцены).
    Post: `cv2.INTER_CUBIC` при увеличении, `cv2.INTER_AREA` при уменьшении — тот же
    выбор интерполяции, что даёт корректные значения альфы (не только 0/255).
    """
    if sprite.ndim != 3 or sprite.shape[2] != 4:
        raise SystemExit(f"make_letter_catalog: эталон без альфа-канала (нужен RGBA): {src_path}")
    if sprite.shape[0] != sprite.shape[1]:
        # Неквадратный эталон при ресайзе в квадрат сплющился бы в эллипс (ревью 5.3b п.5).
        raise SystemExit(f"make_letter_catalog: эталон не квадратный {sprite.shape[1]}x{sprite.shape[0]}: {src_path}")
    size = sprite.shape[0]
    interp = cv2.INTER_AREA if diameter_px < size else cv2.INTER_CUBIC
    return cv2.resize(sprite, (diameter_px, diameter_px), interpolation=interp)


def build_catalog(src: Path, letters: str, diameter_px: int, out: Path) -> None:
    """Собрать каталог: для каждой буквы из `letters` — все `*.png` папки `src/<буква>`,
    ресайз до `diameter_px`, запись в `out/<буква>/<то же имя файла>`; `meta.yaml`
    копируется, если есть. Нет папки буквы источника -> `SystemExit`, называющий букву
    (§4.2.4 контракта)."""
    # Сборка поверх каталога с другими буквами молча смешала бы наборы: движок сцены
    # берёт классы из ВСЕХ папок каталога (ревью 5.3b п.5).
    if out.is_dir():
        foreign = sorted(p.name for p in out.iterdir() if p.is_dir() and p.name not in letters)
        if foreign:
            raise SystemExit(f"make_letter_catalog: в {out} уже есть буквы не из --letters: {', '.join(foreign)}")
    for letter in letters:
        letter_src = src / letter
        if not letter_src.is_dir():
            raise SystemExit(f"make_letter_catalog: нет папки буквы {letter!r} в источнике: {letter_src}")
        letter_out = out / letter
        letter_out.mkdir(parents=True, exist_ok=True)
        png_paths = sorted(letter_src.glob("*.png"))
        for png_path in png_paths:
            try:
                sprite = imread_unicode(png_path, cv2.IMREAD_UNCHANGED)
            except (ValueError, cv2.error) as exc:
                raise SystemExit(f"make_letter_catalog: не читается эталон {png_path}: {exc}") from exc
            resized = _resize_keep_alpha(sprite, diameter_px, src_path=png_path)
            imwrite_unicode(letter_out / png_path.name, resized)
        meta_src = letter_src / _META_FILENAME
        if meta_src.is_file():
            shutil.copyfile(meta_src, letter_out / _META_FILENAME)
        print(f"буква {letter}: {len(png_paths)} эталонов -> {letter_out}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", required=True, help="папка с эталонами: <src>/<буква>/*.png")
    parser.add_argument("--letters", default="АКРХ", help="буквы каталога, по одному символу (дефолт АКРХ)")
    parser.add_argument(
        "--diameter-px",
        type=int,
        default=DEFAULT_DIAMETER_PX,
        help=f"диаметр диска в ПИКСЕЛЯХ кадра сима (дефолт {DEFAULT_DIAMETER_PX} — см. докстринг модуля)",
    )
    parser.add_argument("--out", required=True, help="каталог классов (создаётся)")
    args = parser.parse_args()

    build_catalog(Path(args.src), args.letters, args.diameter_px, Path(args.out))
    print(f"каталог: {args.out} — {len(args.letters)} букв, диск {args.diameter_px} px")


if __name__ == "__main__":
    main()
