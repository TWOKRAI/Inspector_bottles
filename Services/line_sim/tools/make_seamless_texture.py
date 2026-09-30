# -*- coding: utf-8 -*-
"""Превратить произвольную фотографию (ленты, стола, чего угодно) в бесшовный
прокручиваемый тайл фона для `SceneCompositor` (Task 3.6).

Два пути. (1) Периодический: период вдоль X ищется нормированной корреляцией горизонтального
градиента (Sobel по X, 2D — все строки сразу): в цепи повторяется рисунок звена, а не яркость
столбца; побеждает наименьший лаг среди локальных максимумов, не слабее 0.9 от лучшего (так P
выигрывает у 2P). Ширина тайла — там, где рисунок лучше всего повторяет своё
начало (не целое число найденных периодов: в пикселях сцены период звена нецелый).
Принимается, только если шов (разница последнего и первого столбца) не хуже внутренней
разницы между соседними столбцами —
иначе выбор периода дал бы более грубый скачок на стыке, чем внутри тайла.
Резерв (только с `--force-period`): `_best_crop` ищет старт в [0, 8] и ширину >= W/2
по 1D-профилю яркости; на реальном фото цепи ни один такой кроп не проходит шов
(лучший — на +3.82 хуже при start=6, c=320), и до зеркала пробуются кропы ширины
k * период (k от W // период вниз до 1) с наилучшим по столбцам стартом.
Резерв опт-ин, потому что автоматически он ошибается: на виньетированной синусоиде
(H6 из 3_6, дрейф средней яркости >= 20 %) он выбирает кроп с проходящим швом, но
видимым скачком огибающей яркости; у реальной цепи при неровном свете дрейф средней
яркости тайла против соседнего периода 16-22 % (мера: |mean(тайл) − mean(соседний
период)| / mean(фото)) — на уровне H6, автоматически их не различить. Без флага — как раньше.
(2) Зеркало:
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

#: Минимальный лаг корреляции — короче реального периода звена ленты не бывает,
#: и совсем маленькие лаги совпадают с локальным шумом соседних пикселей.
_MIN_LAG = 4

#: Минимум NCC градиента для признания максимума периодом. Замер: реальное фото 0.463 (лаг 205),
#: следующий локальный максимум 0.019 — порог 0.2 отсекает шум и оставляет запас вдвое до периода.
_NCC_MIN = 0.2

#: Доля от лучшего NCC, с которой меньший лаг вытесняет лучший (P против 2P: гармоника даёт ~то же).
#: Замер: чистый P=100/W=400,500 и P=64/W=512 -> P; ложные 120 и 160 синтетики -> периоды, не P/4, P/3.
_HARMONIC_FRAC = 0.9

#: Насколько далеко от левого края может начинаться тайл: край ресайза (INTER_LINEAR повторяет
#: крайний пиксель) и край объектива не повторяют рисунок. Замер: пила ×7.5 — первые 4 столбца
#: профиля нули; тайл от края давал шов 135 против 32 внутри, с отступа 8 — шов 1.93. Отступ
#: подбирается вместе с шириной (0.._EDGE_MARGIN): на коротком фото обязательный отступ съедал
#: нужную ширину (ревью, H15).
# ponytail: фиксированный отступ; подбирать по фото — когда реальный снимок покажет, что мало.
_EDGE_MARGIN = 8


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
    """Период вдоль X по нормированной корреляции горизонтального градиента (2D).

    Pre: `image` — `(H, W, C)` BGR или `(H, W)` / `(H, W, 1)`, любой числовой dtype.
    Post: `int` лаг `k` из `[_MIN_LAG, W // 2]` — наименьший локальный максимум NCC
    (`c[k-1] < c[k] >= c[k+1]`) с `c[k] >= _HARMONIC_FRAC * лучший`, при условии лучший
    `>= _NCC_MIN`; иначе (плоское/безградиентное изображение, слишком узкое, нет максимума
    или он слабее порога) — `None`.

    Отвергнуто (замер на `fixtures/belt_photo_full.png`):
    - автокорреляция 1D-профиля столбцов — ложный лаг 42 в 4 раза сильнее 204;
    - 2D-разность сдвига по яркости — минимумы 89 (17.22) и 204 (17.14) неразличимы.
    """
    width = image.shape[1]
    if width // 2 < _MIN_LAG:
        return None
    # cvtColor не берёт float64/int32/int64, но берёт float32 — приводим до конвертации.
    gray = image.astype(np.float32)
    if gray.ndim == 3 and gray.shape[2] != 1:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    gray = np.ascontiguousarray(gray.reshape(image.shape[0], width))
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)

    max_lag = width // 2
    ncc = np.zeros(max_lag + 2)  # индексы лагов 0..max_lag + 1; нужны соседи k-1 и k+1
    # ponytail: O(W·H·W/2) — 0.84 с на 598x484, ~23 с на 2000x1500; FFT-корреляция, если станет мешать
    for k in range(_MIN_LAG - 1, max_lag + 2):
        a = gx[:, : width - k].ravel().astype(np.float64)
        b = gx[:, k:].ravel().astype(np.float64)
        a -= a.mean()
        b -= b.mean()
        denom = np.sqrt(np.dot(a, a) * np.dot(b, b))
        ncc[k] = float(np.dot(a, b) / denom) if denom > 0 else 0.0

    peaks = [k for k in range(_MIN_LAG, max_lag + 1) if ncc[k - 1] < ncc[k] >= ncc[k + 1]]
    if not peaks:
        return None
    best = max(ncc[k] for k in peaks)
    if best < _NCC_MIN:
        return None
    return int(next(k for k in peaks if ncc[k] >= _HARMONIC_FRAC * best))


def _step(a: np.ndarray, b: np.ndarray) -> float:
    """Мера шага между двумя столбцами тайла: средний модуль разницы по строкам и каналам."""
    return float(np.mean(np.abs(a.astype(float) - b.astype(float))))


def _seam_and_inner(tile: np.ndarray) -> tuple[float, float]:
    """`(inner_diff, seam_diff)` готового тайла — максимум внутренних шагов и шаг шва."""
    tw = tile.shape[1]
    inner_diff = max(_step(tile[:, u], tile[:, u + 1]) for u in range(tw - 1))
    seam_diff = _step(tile[:, tw - 1], tile[:, 0])
    return inner_diff, seam_diff


def _best_crop(image: np.ndarray, period: int) -> tuple[int, int]:
    """`(start, c)`: тайл — столбцы `start..start+c`. Отступ от края `start` из `[0, _EDGE_MARGIN]`,
    ширина `c` из `[W/2, W - period - start]`: столбцы `start+c..start+c+period` должны лучше
    всего повторять `start..start+period` (по профилю яркости столбцов). Ширина выбирается по
    среднему совпадению над всеми допустимыми стартами, старт — лучший для этой ширины.

    Период звена в пикселях сцены почти никогда не целый (25.4 мм × 0.6 px/мм = 15.24 px), а
    `find_period` отдаёт целое: обрезка «целым числом найденных периодов» копит сдвиг фазы на
    шве (10 × 0.24 = 2.4 px). Лучшее самосовпадение выбирает то число звеньев, где их длина
    ближе всего к целому пикселю. Не уже половины фото — чтобы фактура повторялась реже.
    """
    width = image.shape[1]
    profile = image.mean(axis=(0, 2), dtype=np.float64)
    lo = max(period, (width + 1) // 2)
    # find_period отдаёт period <= W // 2, поэтому width - period >= lo: start = 0 допустим всегда.
    by_width: dict[int, list[tuple[float, int]]] = {}
    for start in range(min(_EDGE_MARGIN, width - period - lo) + 1):
        head = profile[start : start + period]
        for c in range(lo, width - period - start + 1):
            diff = float(np.mean(np.abs(profile[start + c : start + c + period] - head)))
            by_width.setdefault(c, []).append((diff, start))
    # Ширина — по среднему над стартами: шум окна гасится, а искажённый край прибавляет всем
    # ширинам одно и то же. Старт — лучший для выбранной ширины (уводит от искажённого края).
    best_c = min(by_width, key=lambda c: sum(d for d, _ in by_width[c]) / len(by_width[c]))
    return min(by_width[best_c])[1], best_c


def _period_multiple_crop(image: np.ndarray, period: int) -> SeamlessResult | None:
    """Резерв: тайл шириной `k * period`, k от `W // period` вниз до 1; первый с швом не хуже внутреннего.

    Старт `s` из `[0, W - c)` — минимум средней абсолютной разницы столбцов `s` и `s + c`
    (та же мера, что `_step`: все строки и каналы). Ни один k не подошёл — `None`.
    """
    width = image.shape[1]
    height = image.shape[0]
    for k in range(width // period, 0, -1):
        crop_w = k * period
        if crop_w >= width:
            continue
        diff = np.abs(image[:, : width - crop_w].astype(np.float64) - image[:, crop_w:].astype(np.float64))
        start = int(np.argmin(diff.reshape(height, width - crop_w, -1).mean(axis=(0, 2))))
        tile = image[:, start : start + crop_w].copy()
        inner_diff, seam_diff = _seam_and_inner(tile)
        if seam_diff <= inner_diff:
            note = f"резерв: {k} период(а), старт {start}"
            return SeamlessResult(tile, "period", period, seam_diff, inner_diff, note=note)
    return None


def make_seamless_tile(image: np.ndarray, *, force_period: bool = False) -> SeamlessResult:
    """Собрать бесшовный тайл: период — если он есть и его шов не хуже внутреннего, иначе зеркало.

    `force_period=True` добавляет между ними резервную обрезку по кратному периоду
    (`_period_multiple_crop`). Резерв нужен, потому что `_best_crop` ищет старт в [0, 8] и
    ширину >= W/2 по 1D-профилю; на реальном фото цепи ни один его кроп не проходит шов
    (лучший +3.82 при start=6, c=320), хотя период найден верно. Критерий шва в резерве тот же.
    Опт-ин, а не автомат: на виньетированной синусоиде (H6 из 3_6) дрейф средней яркости
    >= 20 %, а на реальной цепи при неровном свете 16-22 % (мера: |mean(тайл) − mean(соседний
    период)| / mean(фото); другой мерой 14-21 %, вывод тот же) — автоматически не различить, и
    автомат выдал бы на H6 «period» с видимым скачком огибающей. Без флага (по умолчанию)
    поведение прежнее: `_best_crop`, затем зеркало.
    """
    period = find_period(image)
    note = ""
    if period is not None:
        start, crop_w = _best_crop(image, period)
        candidate = image[:, start : start + crop_w].copy()
        inner_diff, seam_diff = _seam_and_inner(candidate)
        if seam_diff <= inner_diff:
            return SeamlessResult(candidate, "period", period, seam_diff, inner_diff)
        tried = ""
        if force_period:
            fallback = _period_multiple_crop(image, period)
            if fallback is not None:
                return fallback
            tried = "; резерв k·P тоже не прошёл шов"
        note = (
            f"период найден ({period} px), но шов ({seam_diff:.2f}) хуже "
            f"внутренней разницы тайла ({inner_diff:.2f}){tried} — откат на зеркальную склейку"
        )
    else:
        note = "период не найден (NCC градиента ниже порога или нет максимума) — зеркальная склейка"

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
    parser.add_argument(
        "--force-period",
        action="store_true",
        dest="force_period",
        help=(
            "фото заведомо периодическое (цепь): при провале обычной обрезки резать по k периодам "
            "с лучшим швом; яркость по кадру должна быть ровной — виньетирование даст видимый "
            "скачок огибающей"
        ),
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
    source = ""
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
            # period_px после масштаба равен S·M по построению и гармонику не покажет: ошибку
            # «нашёлся двойной/половинный шаг звена» видно только по числу звеньев на фото.
            source = f" source_period_px={period0} links_in_photo={width / period0:.2f}"
    else:
        print("масштаб не задан — тайл в пикселях фото", file=sys.stderr)

    # Масштаб — ДО поиска шва: ресайз готового тайла снова рвёт шов.
    if scale != 1.0:
        new_w, new_h = round(width * scale), round(height * scale)
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        image = cv2.resize(image, (new_w, new_h), interpolation=interp)

    result = make_seamless_tile(image, force_period=args.force_period)
    imwrite_unicode(args.out, result.tile)

    tile_h, tile_w = result.tile.shape[:2]
    period_token = "none" if result.period_px is None else str(result.period_px)
    reason = f" note={result.note}" if result.note else ""
    print(
        f"method={result.method} period_px={period_token} seam_diff={result.seam_diff:.4f} "
        f"inner_diff={result.inner_diff:.4f} scale={scale:.4f} size={tile_w}x{tile_h}{source}{reason}"
    )
    print(f"background_texture: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
