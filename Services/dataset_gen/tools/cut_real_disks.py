"""Каталог эталонов из РЕАЛЬНЫХ фото: вырез диска кругом → RGBA-спрайты.

Вход — папка с подпапкой на букву; в подпапке реальные снимки буквы под
разными углами (0/90/180/270°), угол берётся из имени файла:
    <input>/А/0.jpg  90.jpg  180.jpg  270.jpg
    <input>/Б/letter_000.png  letter_090.png ...

Каждый снимок: детекция диска (HoughCircles) → вырез в RGBA → приведение к
вертикали (поворот на -угол) → ресайз до --size. Результат — каталог в
точности того формата, что ждёт CatalogConfig.classes_dir (как у
make_ru_letter_sprites), несколько эталонов-вариантов на класс:
    <out>/А/000.png  090.png  180.png  270.png  meta.yaml

Дальше — штатный движок dataset_gen (пресет real_letters_disk.yaml):
поворот на любой угол 0..359°, композиция на фон, аугментации, экспорт
sin/cos + симметрия. Обучение — Services/ml_train (MobileNetV3 Large).

Запуск из корня репозитория:
    python -m Services.dataset_gen.tools.cut_real_disks \
        --input data/real_photos --out data/dataset_gen/ru_letters_real/sprites
    ... [--size 256] [--debug]   # debug дампит наложение детекции круга
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from Services.dataset_gen.core.catalog import imread_unicode
from Services.dataset_gen.core.metadata import ClassMeta, write_meta
from Services.dataset_gen.core.realcut import cut_disk_rgba, detect_disk, rotate_upright

BASE_ANGLES = (0, 90, 180, 270)
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


_ANGLE_TOLERANCE = 30  # град: если угол из имени дальше — предупредить (вероятно опечатка)


def _circ_dist(a: int, b: int) -> int:
    """Кратчайшая дистанция углов на окружности (град)."""
    return min((a - b) % 360, (b - a) % 360)


def _parse_angle(stem: str) -> int:
    """Угол из имени файла (целое; весь stem-число приоритетнее последней группы).

    Поддерживает `0.jpg`, `090.png`, `C_180.png`. Имена с угла НЕ в конце
    (например `IMG_0090_v2`) парсятся ненадёжно — называйте файл углом.
    """
    if stem.isdigit():
        return int(stem) % 360
    nums = re.findall(r"\d+", stem)
    if not nums:
        raise ValueError(f"В имени '{stem}' нет угла (ожидалось число вроде 0/90/180/270)")
    return int(nums[-1]) % 360


def _sprite_from_photo(path: Path, size: int, debug_dir: Path | None) -> tuple[int, np.ndarray]:
    """Фото → (base_angle, RGBA-эталон size×size, приведённый к вертикали).

    base = ближайший из BASE_ANGLES; при отклонении > _ANGLE_TOLERANCE — warn
    (вероятна опечатка в имени или съёмка не под каноничным углом).
    """
    raw = _parse_angle(path.stem)
    base = min(BASE_ANGLES, key=lambda b: _circ_dist(raw, b))
    if _circ_dist(raw, base) > _ANGLE_TOLERANCE:
        print(
            f"  [warn] {path.name}: угол {raw}° далёк от базового {base}° "
            f"(дист {_circ_dist(raw, base)}°) — проверьте имя/съёмку"
        )
    bgr = imread_unicode(path, cv2.IMREAD_COLOR)
    circle = detect_disk(bgr)
    if debug_dir is not None:
        overlay = bgr.copy()
        cv2.circle(overlay, (circle[0], circle[1]), circle[2], (0, 0, 255), 3)
        debug_dir.mkdir(parents=True, exist_ok=True)
        cv2.imencode(".png", overlay)[1].tofile(str(debug_dir / f"detect_{path.stem}.png"))

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    rgba = rotate_upright(cut_disk_rgba(rgb, circle), base)
    rgba = cv2.resize(rgba, (size, size), interpolation=cv2.INTER_AREA)
    return base, rgba


def build_catalog(input_root: Path, out_root: Path, size: int, debug: bool) -> list[Path]:
    """Собрать каталог классов из реальных фото. Возвращает список папок-классов.

    Несколько фото на один базовый угол сохраняются под РАЗНЫМИ именами
    (`000.png`, `000_01.png`, …) — без затирания; счётчик считает записанные файлы.
    """
    letter_dirs = sorted(d for d in input_root.iterdir() if d.is_dir() and not d.name.startswith((".", "_")))
    if not letter_dirs:
        raise SystemExit(f"Во входе нет подпапок-классов: {input_root}")

    created: list[Path] = []
    for letter_dir in letter_dirs:
        letter = letter_dir.name
        photos = sorted(p for p in letter_dir.iterdir() if p.suffix.lower() in _IMAGE_SUFFIXES)
        if not photos:
            print(f"[skip] '{letter}': нет фото")
            continue
        class_dir = out_root / letter
        class_dir.mkdir(parents=True, exist_ok=True)
        dbg = (out_root / "_debug" / letter) if debug else None

        per_base: dict[int, int] = {}
        written: list[str] = []
        for photo in photos:
            base, rgba = _sprite_from_photo(photo, size, dbg)
            idx = per_base.get(base, 0)
            per_base[base] = idx + 1
            name = f"{base:03d}.png" if idx == 0 else f"{base:03d}_{idx:02d}.png"
            Image.fromarray(rgba, mode="RGBA").save(class_dir / name)  # PIL: unicode-safe
            written.append(name)
        write_meta(class_dir, ClassMeta(display_name=f"Буква {letter}", tags=["letter", "real"]))
        created.append(class_dir)
        print(f"[ok] '{letter}': {len(written)} эталонов (базовые углы {sorted(per_base)}) -> {class_dir}")
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", required=True, help="папка с реальными фото (подпапка на букву)")
    parser.add_argument("--out", required=True, help="каталог эталонов (classes_dir пресета)")
    parser.add_argument("--size", type=int, default=256, help="сторона эталона, px (по умолчанию 256)")
    parser.add_argument("--debug", action="store_true", help="дамп наложения детекции круга")
    args = parser.parse_args()

    input_root = Path(args.input)
    if not input_root.is_dir():
        raise SystemExit(f"Папка входа не найдена: {input_root}")
    created = build_catalog(input_root, Path(args.out), args.size, args.debug)
    print(f"\nСоздано {len(created)} классов в {args.out}")
    print("Дальше: пресет classes_dir -> этот каталог, затем обучение:")
    print("  python -m Services.ml_train train Services/ml_train/presets/ru_letters_real.yaml")


if __name__ == "__main__":
    main()
