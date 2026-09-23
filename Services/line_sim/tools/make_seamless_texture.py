# -*- coding: utf-8 -*-
"""Превратить произвольную фотографию (ленты, стола, чего угодно) в бесшовный
прокручиваемый тайл фона для `SceneCompositor` (Task 3.6).

Два пути. (1) Периодический: период вдоль X ищется автокорреляцией профиля столбцов
(среднее по строкам и каналам); кадр обрезается по целому числу периодов — это точный
шов, работает на модульной ленте со звеньями. Принимается, только если шов (разница
последнего и первого столбца) не хуже внутренней разницы между соседними столбцами —
иначе выбор периода дал бы более грубый скачок на стыке, чем внутри тайла. (2) Зеркало:
`[image | image[:, ::-1]]` — стыкует буквально одинаковые столбцы, шов = 0 всегда;
кросс-фейда нет (на зеркальной склейке он ничего не чинит, только размывает). Выбранный
путь, найденный период и остаточная разница кромок печатаются числами, а не решаются
молча.

    python -m Services.line_sim.tools.make_seamless_texture photo.jpg --out tile.png \
        --scene-px-per-mm 0.6 --pitch-mm 55.0
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import cv2
import numpy as np

from Services.dataset_gen.core.catalog import imread_unicode, imwrite_unicode

#: Минимальный лаг автокорреляции — короче реального периода звена ленты не бывает,
#: и совсем маленькие лаги совпадают с локальным шумом соседних пикселей.
_MIN_LAG = 4

#: Порог нормированной автокорреляции для признания локального максимума периодом.
_AC_THRESHOLD = 0.5


@dataclass(frozen=True)
class SeamlessResult:
    """Результат `make_seamless_tile` — тайл + диагностика выбора шва.

    `period_px` заполнен только при `method == "period"`. `note` — причина отката на
    зеркало (пусто, если период не искался вовсе или тайл получен зеркалом без отказа
    от найденного периода — печатается инструментом при непустом значении).
    """

    tile: np.ndarray
    method: str
    period_px: int | None
    seam_diff: float
    inner_diff: float
    note: str = ""


def find_period(image: np.ndarray) -> int | None:
    """Период вдоль X по автокорреляции профиля яркости столбцов.

    Pre: `image` — `(H, W, C)`, любой числовой dtype.
    Post: первый локальный максимум нормированной автокорреляции
    (`ac[k-1] < ac[k] >= ac[k+1]`) с `ac[k] / ac[0] >= 0.5` для `k` в `[4, W // 2]`;
    плоский профиль (нулевая дисперсия) или отсутствие такого максимума — `None`.
    """
    width = image.shape[1]
    profile = image.astype(float).mean(axis=(0, 2))
    profile = profile - profile.mean()
    if not np.any(profile):
        return None

    def ac(lag: int) -> float | None:
        if lag < 0 or lag >= width:
            return None
        denom = width - lag
        return float(np.sum(profile[: width - lag] * profile[lag:]) / denom)

    ac0 = ac(0)
    if not ac0:
        return None

    max_lag = width // 2
    for k in range(_MIN_LAG, max_lag + 1):
        prev, cur, nxt = ac(k - 1), ac(k), ac(k + 1)
        if prev is None or cur is None or nxt is None:
            continue
        if prev < cur >= nxt and (cur / ac0) >= _AC_THRESHOLD:
            return k
    return None


def _step(a: np.ndarray, b: np.ndarray) -> float:
    """Мера шага между двумя столбцами тайла: средний модуль разницы по строкам и каналам."""
    return float(np.mean(np.abs(a.astype(float) - b.astype(float))))


def _seam_and_inner(tile: np.ndarray) -> tuple[float, float]:
    """`(inner_diff, seam_diff)` готового тайла — максимум внутренних шагов и шаг шва."""
    tw = tile.shape[1]
    inner_diff = max(_step(tile[:, u], tile[:, u + 1]) for u in range(tw - 1))
    seam_diff = _step(tile[:, tw - 1], tile[:, 0])
    return inner_diff, seam_diff


def make_seamless_tile(image: np.ndarray) -> SeamlessResult:
    """Собрать бесшовный тайл: период — если он есть и его шов не хуже внутреннего,
    иначе зеркало."""
    period = find_period(image)
    note = ""
    if period is not None:
        width = image.shape[1]
        crop_w = (width // period) * period
        if crop_w >= period:
            candidate = image[:, :crop_w].copy()
            inner_diff, seam_diff = _seam_and_inner(candidate)
            if seam_diff <= inner_diff:
                return SeamlessResult(candidate, "period", period, seam_diff, inner_diff)
            note = (
                f"период найден (period_px={period}), но шов ({seam_diff:.2f}) хуже "
                f"внутренней разницы тайла ({inner_diff:.2f}) — откат на зеркальную склейку"
            )
        else:
            note = f"период найден (period_px={period}), но фото короче одного периода — откат на зеркало"
    else:
        note = "период не найден автокорреляцией — зеркальная склейка"

    mirror = np.concatenate([image, image[:, ::-1]], axis=1)
    inner_diff, seam_diff = _seam_and_inner(mirror)
    return SeamlessResult(mirror, "mirror", None, seam_diff, inner_diff, note=note)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Превратить фото в бесшовный тайл фона сцены (period/mirror, см. докстринг модуля)."
    )
    parser.add_argument("input", help="путь к исходной фотографии")
    parser.add_argument("--out", required=True, help="путь для сохранения тайла (PNG)")
    parser.add_argument(
        "--scene-px-per-mm",
        type=float,
        default=None,
        dest="scene_px_per_mm",
        help="масштаб сцены (px/мм) — приводит фото к масштабу сцены вместе с --photo-width-mm/--pitch-mm",
    )
    scale_group = parser.add_mutually_exclusive_group()
    scale_group.add_argument(
        "--photo-width-mm",
        type=float,
        default=None,
        dest="photo_width_mm",
        help="сколько мм ленты вдоль хода помещается по всей ширине фото",
    )
    scale_group.add_argument(
        "--pitch-mm",
        type=float,
        default=None,
        dest="pitch_mm",
        help="шаг звена ленты в мм — период ищется на исходнике, коэффициент = S*M/P0",
    )
    args = parser.parse_args(argv)

    has_reference = args.photo_width_mm is not None or args.pitch_mm is not None
    if args.scene_px_per_mm is not None and not has_reference:
        parser.error("--scene-px-per-mm требует --photo-width-mm или --pitch-mm")
    if has_reference and args.scene_px_per_mm is None:
        parser.error("--photo-width-mm/--pitch-mm требует --scene-px-per-mm")

    image = imread_unicode(args.input, cv2.IMREAD_COLOR)
    height, width = image.shape[:2]

    scale = 1.0
    if args.scene_px_per_mm is not None:
        s = args.scene_px_per_mm
        if args.photo_width_mm is not None:
            scale = s * args.photo_width_mm / width
        else:
            period0 = find_period(image)
            if period0 is None:
                print(
                    "период не найден на исходном фото — масштаб по --pitch-mm невозможен, "
                    "используйте --photo-width-mm",
                    file=sys.stderr,
                )
                return 1
            scale = s * args.pitch_mm / period0
    else:
        print("масштаб не задан — тайл в пикселях фото", file=sys.stderr)

    # Масштаб — ДО поиска шва: ресайз готового тайла снова рвёт шов.
    if scale != 1.0:
        new_w, new_h = round(width * scale), round(height * scale)
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        image = cv2.resize(image, (new_w, new_h), interpolation=interp)

    result = make_seamless_tile(image)
    imwrite_unicode(args.out, result.tile)

    tile_h, tile_w = result.tile.shape[:2]
    period_token = "none" if result.period_px is None else str(result.period_px)
    reason = f" note={result.note}" if result.note else ""
    print(
        f"method={result.method} period_px={period_token} seam_diff={result.seam_diff:.4f} "
        f"inner_diff={result.inner_diff:.4f} scale={scale:.4f} size={tile_w}x{tile_h}{reason}"
    )
    print(f"background_texture: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
