"""Фотометрические эффекты кадра: функции и упорядоченный реестр `EFFECTS` (Task 2.2).

Тела функций перенесены из `Services/dataset_gen/core/augment.py` без изменений. Новое здесь —
реестр: `EFFECTS[name](x_float32, params, rng) -> x` — один фотометрический шаг без вентиля
вероятности, значения тянет из `rng` в том же порядке, что и прежний `apply_photometric`.
Порядок вставки в `EFFECTS` — канонический порядок прохода (описан в `dataset_gen.core.augment`):
блик → тень → окклюзия → расфокус → смаз → виньетка → яркость/контраст → gamma → температура →
сдвиг каналов → шум → JPEG. Отдельной константы порядка нет.

`EffectSpec` — один шаг списка (имя, вероятность, параметры); `apply_effects` прогоняет список.
Слой `layer_render` не знает про `dataset_gen`: дефолты параметров — литералы в `EFFECT_PARAMS`,
их равенство полям `AugmentConfig` держит тест в `dataset_gen/tests`.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import cv2
import numpy as np


def apply_glare(
    frame: np.ndarray,
    center_xy: tuple[float, float],
    radius_px: float,
    intensity: float,
) -> np.ndarray:
    """Блик-пятно: радиальный градиент пересвета (квадратичное затухание).

    Pre:
      - frame: HxWx3 float32 (шкала 0–255); radius_px > 0
    Post:
      - яркость в центре пятна увеличена на ~intensity, вне пятна кадр не тронут
    """
    h, w = frame.shape[:2]
    cx, cy = center_xy
    yy, xx = np.ogrid[:h, :w]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2).astype(np.float32)
    falloff = np.clip(1.0 - dist / float(radius_px), 0.0, 1.0) ** 2
    return frame + (intensity * falloff)[:, :, None]


def make_motion_kernel(length: int, angle_deg: float) -> np.ndarray:
    """Линейное ядро смаза: отрезок длиной length под углом angle_deg, sum == 1."""
    size = max(3, int(length) | 1)  # нечётный размер, центр в середине
    kernel = np.zeros((size, size), dtype=np.float32)
    c = size // 2
    rad = np.deg2rad(angle_deg)
    dx, dy = np.cos(rad) * (length / 2.0), np.sin(rad) * (length / 2.0)
    p1 = (int(round(c - dx)), int(round(c - dy)))
    p2 = (int(round(c + dx)), int(round(c + dy)))
    cv2.line(kernel, p1, p2, 1.0, thickness=1)
    s = kernel.sum()
    if s == 0:
        kernel[c, c] = 1.0
        s = 1.0
    return kernel / s


def apply_motion_blur(frame: np.ndarray, length: int, angle_deg: float) -> np.ndarray:
    """Смаз движения линейным ядром (конвейер движется)."""
    return cv2.filter2D(frame, -1, make_motion_kernel(length, angle_deg))


def apply_brightness_contrast(frame: np.ndarray, brightness: float, contrast: float) -> np.ndarray:
    """Контраст вокруг середины шкалы + аддитивная яркость."""
    return (frame - 127.5) * contrast + 127.5 + brightness


def apply_color_temperature(frame: np.ndarray, shift: float) -> np.ndarray:
    """Баланс белого: shift>0 — теплее (R↑ B↓), shift<0 — холоднее. Кадр RGB."""
    out = frame.copy()
    out[:, :, 0] *= 1.0 + shift
    out[:, :, 2] *= 1.0 - shift
    return out


def apply_channel_shift(frame: np.ndarray, shifts: tuple[float, float, float]) -> np.ndarray:
    """Независимый аддитивный сдвиг каналов RGB (нестабильность баланса камеры)."""
    return frame + np.asarray(shifts, dtype=np.float32)[None, None, :]


def apply_shadow(
    frame: np.ndarray,
    angle_deg: float,
    offset: float,
    strength: float,
    softness: float,
) -> np.ndarray:
    """Мягкая тень: линейный градиент затемнения поперёк направления angle_deg.

    offset ∈ [0..1] — положение фронта тени вдоль направления;
    strength — затемнение в полностью затенённой зоне;
    softness ∈ (0..1] — ширина переходной зоны (доля кадра).

    Pre:
      - frame: HxWx3 float32; 0 <= strength < 1; softness > 0
    Post:
      - пиксели затемнены не более чем на strength, форма сохранена
    """
    h, w = frame.shape[:2]
    rad = np.deg2rad(angle_deg)
    yy, xx = np.ogrid[:h, :w]
    proj = (xx / max(w - 1, 1)) * np.cos(rad) + (yy / max(h - 1, 1)) * np.sin(rad)
    proj = (proj - proj.min()) / max(proj.max() - proj.min(), 1e-6)  # → [0..1]
    mask = np.clip((proj - offset) / softness, 0.0, 1.0).astype(np.float32)
    return frame * (1.0 - strength * mask)[:, :, None]


def apply_occlusion(
    frame: np.ndarray,
    rect_xywh: tuple[int, int, int, int],
    color: tuple[float, float, float],
) -> np.ndarray:
    """Окклюзия: закрасить прямоугольник (x, y, w, h) сплошным цветом.

    Выход за границы кадра обрезается; кадр не модифицируется (копия).
    """
    fh, fw = frame.shape[:2]
    x, y, w, h = rect_xywh
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(fw, x + w), min(fh, y + h)
    out = frame.copy()
    if x0 < x1 and y0 < y1:
        out[y0:y1, x0:x1] = np.asarray(color, dtype=np.float32)
    return out


def apply_gamma(frame: np.ndarray, gamma: float) -> np.ndarray:
    """Степенная тональная кривая: out = 255 * (in/255)^gamma.

    gamma<1 — высветляет тени, gamma>1 — затемняет. Имитирует нелинейность
    отклика сенсора и тонмаппинг камеры (то, что линейная яркость не даёт).

    Pre:
      - frame: HxWx3 float32 (0–255); gamma > 0
    """
    norm = np.clip(frame, 0, 255) / 255.0
    return np.power(norm, gamma, dtype=np.float32) * 255.0


def apply_vignette(frame: np.ndarray, strength: float, radius_frac: float) -> np.ndarray:
    """Виньетка: радиальное затемнение к краям (есть у любой реальной оптики).

    strength — максимум затемнения в углах; radius_frac — доля полудиагонали,
    внутри которой кадр почти не тронут.

    Pre:
      - frame: HxWx3 float32; 0 <= strength < 1; radius_frac > 0
    """
    h, w = frame.shape[:2]
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    yy, xx = np.ogrid[:h, :w]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    max_dist = np.sqrt(cx**2 + cy**2)
    norm = np.clip((dist / max_dist - radius_frac) / max(1.0 - radius_frac, 1e-6), 0.0, 1.0)
    mask = (1.0 - strength * norm**2).astype(np.float32)
    return frame * mask[:, :, None]


def apply_jpeg(frame_u8_rgb: np.ndarray, quality: int) -> np.ndarray:
    """JPEG-артефакты: пережатие с заданным качеством (вход/выход RGB uint8)."""
    bgr = cv2.cvtColor(frame_u8_rgb, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        return frame_u8_rgb
    decoded = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)


def _uniform(rng: np.random.Generator, rng_pair: tuple[float, float]) -> float:
    return float(rng.uniform(rng_pair[0], rng_pair[1]))


# --------------------------------------------------------------------------------------------------
# Реестр: один шаг = блок прежнего apply_photometric без строки `if enabled and rng.random() < prob`.
# x — float32 HxWx3 (шкала 0–255), p — параметры (Mapping), результат — float32; для U8-эффектов (JPEG) x — uint8.
# --------------------------------------------------------------------------------------------------


def _fx_glare(x: np.ndarray, p: Mapping[str, Any], rng: np.random.Generator) -> np.ndarray:
    h, w = x.shape[:2]
    radius = _uniform(rng, p["radius_frac"]) * min(h, w)
    center = (float(rng.uniform(0, w)), float(rng.uniform(0, h)))
    return apply_glare(x, center, radius, _uniform(rng, p["intensity"]))


def _fx_shadow(x: np.ndarray, p: Mapping[str, Any], rng: np.random.Generator) -> np.ndarray:
    return apply_shadow(
        x,
        angle_deg=float(rng.uniform(0.0, 360.0)),
        offset=float(rng.uniform(0.2, 0.8)),
        strength=_uniform(rng, p["strength"]),
        softness=_uniform(rng, p["softness_frac"]),
    )


def _fx_occlusion(x: np.ndarray, p: Mapping[str, Any], rng: np.random.Generator) -> np.ndarray:
    h, w = x.shape[:2]
    count = p["count"]
    for _ in range(int(rng.integers(count[0], count[1] + 1))):
        side = _uniform(rng, p["size_frac"]) * min(h, w)
        rw, rh = int(side * rng.uniform(0.6, 1.6)), int(side * rng.uniform(0.6, 1.6))
        rect = (int(rng.uniform(0, w - 1)), int(rng.uniform(0, h - 1)), max(1, rw), max(1, rh))
        color = tuple(float(c) for c in rng.uniform(0, 255, size=3))
        x = apply_occlusion(x, rect, color)
    return x


def _fx_gaussian_blur(x: np.ndarray, p: Mapping[str, Any], rng: np.random.Generator) -> np.ndarray:
    sigma = _uniform(rng, p["sigma"])
    return cv2.GaussianBlur(x, (0, 0), sigmaX=sigma, sigmaY=sigma)


def _fx_motion_blur(x: np.ndarray, p: Mapping[str, Any], rng: np.random.Generator) -> np.ndarray:
    length = int(rng.integers(p["length"][0], p["length"][1] + 1))
    return apply_motion_blur(x, length, float(rng.uniform(0.0, 180.0)))


def _fx_vignette(x: np.ndarray, p: Mapping[str, Any], rng: np.random.Generator) -> np.ndarray:
    return apply_vignette(x, _uniform(rng, p["strength"]), _uniform(rng, p["radius_frac"]))


def _fx_brightness_contrast(x: np.ndarray, p: Mapping[str, Any], rng: np.random.Generator) -> np.ndarray:
    return apply_brightness_contrast(x, _uniform(rng, p["brightness"]), _uniform(rng, p["contrast"]))


def _fx_gamma(x: np.ndarray, p: Mapping[str, Any], rng: np.random.Generator) -> np.ndarray:
    return apply_gamma(x, _uniform(rng, p["gamma"]))


def _fx_color_temperature(x: np.ndarray, p: Mapping[str, Any], rng: np.random.Generator) -> np.ndarray:
    return apply_color_temperature(x, _uniform(rng, p["shift"]))


def _fx_channel_shift(x: np.ndarray, p: Mapping[str, Any], rng: np.random.Generator) -> np.ndarray:
    shifts = tuple(float(s) for s in rng.uniform(-p["max_shift"], p["max_shift"], size=3))
    return apply_channel_shift(x, shifts)


def _fx_noise(x: np.ndarray, p: Mapping[str, Any], rng: np.random.Generator) -> np.ndarray:
    std = _uniform(rng, p["std"])
    # standard_normal(dtype=float32) — без промежуточного float64-массива; вход не меняем (запись реестра чистая)
    return x + rng.standard_normal(x.shape, dtype=np.float32) * std


def _fx_jpeg(x_u8: np.ndarray, p: Mapping[str, Any], rng: np.random.Generator) -> np.ndarray:
    quality = int(rng.integers(p["quality"][0], p["quality"][1] + 1))
    return apply_jpeg(x_u8, quality)


EffectFn = Callable[[np.ndarray, Mapping[str, Any], np.random.Generator], np.ndarray]

# Порядок вставки = канонический порядок прохода. Добавить эффект = функция + запись здесь + запись в EFFECT_PARAMS.
# Точка расширения на этапе импорта: во время работы EFFECTS/EFFECT_PARAMS не менять.
EFFECTS: dict[str, EffectFn] = {
    "glare": _fx_glare,
    "shadow": _fx_shadow,
    "occlusion": _fx_occlusion,
    "gaussian_blur": _fx_gaussian_blur,
    "motion_blur": _fx_motion_blur,
    "vignette": _fx_vignette,
    "brightness_contrast": _fx_brightness_contrast,
    "gamma": _fx_gamma,
    "color_temperature": _fx_color_temperature,
    "channel_shift": _fx_channel_shift,
    "noise": _fx_noise,
    "jpeg": _fx_jpeg,
}

# Дефолты параметров (без enabled/prob) — литералы; равенство полям AugmentConfig держит тест в dataset_gen.
EFFECT_PARAMS: dict[str, dict[str, Any]] = {
    "glare": {"intensity": (40.0, 120.0), "radius_frac": (0.15, 0.45)},
    "shadow": {"strength": (0.15, 0.45), "softness_frac": (0.2, 0.6)},
    "occlusion": {"count": (1, 2), "size_frac": (0.05, 0.18)},
    "gaussian_blur": {"sigma": (0.4, 1.8)},
    "motion_blur": {"length": (3, 9)},
    "vignette": {"strength": (0.15, 0.45), "radius_frac": (0.4, 0.7)},
    "brightness_contrast": {"brightness": (-30.0, 30.0), "contrast": (0.85, 1.15)},
    "gamma": {"gamma": (0.7, 1.4)},
    "color_temperature": {"shift": (-0.08, 0.08)},
    "channel_shift": {"max_shift": 15.0},
    "noise": {"std": (2.0, 10.0)},
    "jpeg": {"quality": (50, 90)},
}

# Эффекты, которым нужен uint8-кадр (кодек): перед ними clip → uint8, после — обратно во float32.
_U8_EFFECTS = frozenset({"jpeg"})


@dataclass(frozen=True, eq=False)
class EffectSpec:
    """Один шаг списка эффектов: имя из `EFFECTS`, вероятность применения, параметры.

    Pre: `name` в `EFFECTS`; ключи `params` ⊆ ключей `EFFECT_PARAMS[name]`; `0 <= prob <= 1` — иначе `ValueError`.
    Post: `params` — `MappingProxyType` (read-only только верхний уровень: вложенные списки изменяемы), недостающие
    ключи добавлены из `EFFECT_PARAMS`, глубокая копия (правка словаря вызывающего на spec не влияет).
    `eq=False` — сравнение по идентичности.
    """

    name: str
    prob: float = 1.0
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.name not in EFFECTS:
            raise ValueError(f"EffectSpec.name: неизвестный эффект {self.name!r}; известные: {', '.join(EFFECTS)}")
        defaults = EFFECT_PARAMS[self.name]
        unknown = [k for k in self.params if k not in defaults]
        if unknown:
            raise ValueError(
                f"EffectSpec({self.name!r}).params: неизвестные ключи {unknown!r}; допустимые: {', '.join(defaults)}"
            )
        if not 0.0 <= self.prob <= 1.0:
            raise ValueError(f"EffectSpec.prob: ожидалось 0..1, получено {self.prob!r}")
        merged = copy.deepcopy({**defaults, **self.params})
        object.__setattr__(self, "params", MappingProxyType(merged))


def apply_effects(frame_u8: np.ndarray, specs: Sequence[EffectSpec], rng: np.random.Generator) -> np.ndarray:
    """Применяет список эффектов к uint8-кадру HxWx3 RGB по порядку списка.

    Pre: `frame_u8` — HxWx3 uint8 (иной dtype — `ValueError`, проверка до любого розыгрыша); `specs` — `EffectSpec`
    в порядке применения.
    Post: uint8 той же формы; вход не меняется; пустой список — копия входа без единого розыгрыша `rng`.
    Вентиль `rng.random() < prob` тянется ВСЕГДА (и при prob 0.0/1.0) — поток rng не зависит от значения prob.
    """
    if frame_u8.dtype != np.uint8:
        raise ValueError(f"apply_effects: ожидался кадр dtype=uint8, получено dtype={frame_u8.dtype}")
    if not specs:
        return frame_u8.copy()
    x = frame_u8.astype(np.float32)
    for spec in specs:
        if rng.random() < spec.prob:
            fn = EFFECTS[spec.name]
            if spec.name in _U8_EFFECTS:
                x = fn(np.clip(x, 0, 255).astype(np.uint8), spec.params, rng).astype(np.float32)
            else:
                x = fn(x, spec.params, rng)
    return np.clip(x, 0, 255).astype(np.uint8)
