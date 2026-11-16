"""Проверка набора кадров дисков «день №1: камера» (чисел PASS/FAIL, без железа).

Схема имён (зафиксирована в docs/handoffs/2026-11-15_day1-camera-checklist.md, разд. 4):
    <каталог>/<БУКВА>/a<УГОЛ:03d>_<индекс:06d>.<png|jpg|...>
Буква — имя подкаталога (одна кириллическая буква), угол — в градусах, в имени файла.
Так пишет ``Plugins/io/frame_saver`` при ``subfolder_by_date: false``, ``output_dir`` =
``<каталог>/<БУКВА>`` и ``filename_prefix`` = ``a<УГОЛ:03d>``.

Что считает: файлов на (буква, угол); у каждого кадра — резкость (дисперсия Лапласа серого
кадра) и средняя яркость по каналам. Кадр «плохой», если резкость ниже порога, или яркость
ниже/выше порогов, или файл не читается. Все пороги по умолчанию — ПРЕДЛОЖЕНИЯ лиду, не числа из
репозитория (в репозитории порога резкости нет), они печатаются в отчёте и меняются флагами.

Запуск:  .venv/bin/python -I scripts/day1_capture_check.py <каталог> [флаги]
Код выхода: 0 — PASS, 1 — FAIL, 2 — ошибка вызова (нет каталога, нет кадров).
Слои: только stdlib + opencv + numpy; ничего из multiprocess_prototype.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
NAME_RE = re.compile(r"^a(\d{3})_(\d+)$")

# Предложения лиду на утверждение (не из репозитория):
DEFAULT_LETTERS = "ПЕРМИ"  # различные буквы слова «ПЕРЕМИРИЕ»
DEFAULT_ANGLES = "0,45,90,135,180,225,270,315"
DEFAULT_MIN_PER_CELL = 6
DEFAULT_MIN_SHARPNESS = 100.0
DEFAULT_MIN_BRIGHT = 60.0
DEFAULT_MAX_BRIGHT = 230.0
DEFAULT_MAX_BAD_FRAC = 0.10


@dataclass(frozen=True)
class FrameStat:
    path: Path
    letter: str
    angle: int
    sharpness: float
    brightness: float
    width: int
    height: int


def measure(path: Path) -> tuple[float, float, int, int] | None:
    """(резкость, яркость, ширина, высота) или None, если файл не читается.

    imdecode(fromfile), а не imread: на Windows imread не открывает путь с кириллицей (имя буквы).
    """
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except (OSError, cv2.error):
        return None
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return sharp, float(img.mean()), int(img.shape[1]), int(img.shape[0])


def scan(root: Path) -> tuple[list[FrameStat], list[str], list[str]]:
    """(кадры с мерами, файлы с неверным именем, нечитаемые файлы). Имя буквы — NFC."""
    stats: list[FrameStat] = []
    bad_names: list[str] = []
    unreadable: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        rel = p.relative_to(root)
        letter = unicodedata.normalize("NFC", rel.parts[0]) if len(rel.parts) == 2 else ""
        m = NAME_RE.match(p.stem)
        if len(rel.parts) != 2 or len(letter) != 1 or m is None:
            bad_names.append(str(rel))
            continue
        res = measure(p)
        if res is None:
            unreadable.append(str(rel))
            continue
        stats.append(FrameStat(p, letter, int(m.group(1)), *res))
    return stats, bad_names, unreadable


def is_good(s: FrameStat, min_sharp: float, min_bright: float, max_bright: float) -> bool:
    return s.sharpness >= min_sharp and min_bright <= s.brightness <= max_bright


def run(args: argparse.Namespace, out=sys.stdout) -> int:
    root = Path(args.root)
    if not root.is_dir():
        print(f"ОШИБКА: нет каталога {root}", file=sys.stderr)
        return 2
    stats, bad_names, unreadable = scan(root)
    if not stats and not bad_names and not unreadable:
        print(f"ОШИБКА: в {root} нет изображений", file=sys.stderr)
        return 2

    letters = [unicodedata.normalize("NFC", c) for c in args.letters]
    angles = [int(a) for a in args.angles.split(",") if a.strip()]
    good: dict[tuple[str, int], int] = defaultdict(int)
    total: dict[tuple[str, int], int] = defaultdict(int)
    for s in stats:
        total[(s.letter, s.angle)] += 1
        if is_good(s, args.min_sharpness, args.min_bright, args.max_bright):
            good[(s.letter, s.angle)] += 1

    n_all = len(stats) + len(unreadable)
    n_bad = (len(stats) - sum(good.values())) + len(unreadable)
    bad_frac = n_bad / n_all if n_all else 1.0
    sizes = sorted({(s.width, s.height) for s in stats})

    print(
        f"каталог={root}  кадров читаемых={len(stats)}  нечитаемых={len(unreadable)}  "
        f"неверных имён={len(bad_names)}  размеры={sizes}",
        file=out,
    )
    print(
        f"пороги (предложения): min_per_cell={args.min_per_cell} min_sharpness={args.min_sharpness} "
        f"яркость=[{args.min_bright}, {args.max_bright}] max_bad_frac={args.max_bad_frac}",
        file=out,
    )
    print("буква  " + " ".join(f"{a:>7}" for a in angles) + "   (годных/всего)", file=out)
    missing_cells: list[tuple[str, int]] = []
    for letter in letters:
        row = []
        for a in angles:
            g, t = good[(letter, a)], total[(letter, a)]
            row.append(f"{g:>3}/{t:<3} ")
            if g < args.min_per_cell:
                missing_cells.append((letter, a))
        print(f"  {letter}    " + " ".join(row), file=out)
    extra = sorted({(s.letter, s.angle) for s in stats} - {(ltr, a) for ltr in letters for a in angles})
    if extra:
        print(f"вне сетки (не считаются): {extra}", file=out)
    for name in bad_names[:20]:
        print(f"BAD_NAME {name}", file=out)
    for name in unreadable[:20]:
        print(f"UNREADABLE {name}", file=out)
    if stats:
        print(
            f"резкость: min={min(s.sharpness for s in stats):.1f} "
            f"медиана={float(np.median([s.sharpness for s in stats])):.1f}; "
            f"яркость: min={min(s.brightness for s in stats):.1f} "
            f"медиана={float(np.median([s.brightness for s in stats])):.1f} "
            f"max={max(s.brightness for s in stats):.1f}",
            file=out,
        )

    checks = {
        f"ячеек (буква, угол) с годных < {args.min_per_cell}: {len(missing_cells)}": not missing_cells,
        f"доля плохих кадров {bad_frac:.3f} <= {args.max_bad_frac}": bad_frac <= args.max_bad_frac,
        f"неверных имён: {len(bad_names)}": not bad_names,
        f"размеров кадра: {len(sizes)} (должен быть 1)": len(sizes) <= 1,
    }
    ok = True
    for text, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}  {text}", file=out)
        ok = ok and passed
    print("ИТОГ: PASS" if ok else "ИТОГ: FAIL", file=out)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Проверка набора кадров дисков (день №1: камера)")
    p.add_argument("root", help="каталог набора: <root>/<БУКВА>/a<УГОЛ>_<индекс>.png")
    p.add_argument("--letters", default=DEFAULT_LETTERS, help="ожидаемые буквы одной строкой")
    p.add_argument("--angles", default=DEFAULT_ANGLES, help="ожидаемые углы через запятую, градусы")
    p.add_argument("--min-per-cell", type=int, default=DEFAULT_MIN_PER_CELL)
    p.add_argument("--min-sharpness", type=float, default=DEFAULT_MIN_SHARPNESS)
    p.add_argument("--min-bright", type=float, default=DEFAULT_MIN_BRIGHT)
    p.add_argument("--max-bright", type=float, default=DEFAULT_MAX_BRIGHT)
    p.add_argument("--max-bad-frac", type=float, default=DEFAULT_MAX_BAD_FRAC)
    return p


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
