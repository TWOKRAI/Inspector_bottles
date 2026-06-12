"""Фотометрические аугментации полным кадром — ПОСЛЕ композиции.

КРИТИЧНО: размытие, motion blur, шум, яркость/контраст, цветовая температура,
JPEG-артефакты применяются единым проходом на весь скомпозиченный кадр.
Если применять их к объекту до вклейки — модель выучит шов вклейки, а не объект.

Порядок прохода (от «сцены» к «сенсору» и кодеку):
сцена: блик → тень → окклюзия; оптика: расфокус → смаз движения;
сенсор: яркость/контраст → температура → сдвиг каналов → шум;
кодек: JPEG — последним.

Каждая операция — отдельная детерминированная функция с явными параметрами
(тестируемость); apply_photometric сэмплирует параметры из конфига.
"""

from __future__ import annotations

import cv2
import numpy as np

from Services.dataset_gen.core.config import AugmentConfig


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


def apply_photometric(frame_rgb_u8: np.ndarray, cfg: AugmentConfig, rng: np.random.Generator) -> np.ndarray:
    """Полный фотометрический проход по скомпозиченному кадру.

    Pre:
      - frame_rgb_u8: HxWx3 uint8 (после композиции объекта на фон)
    Post:
      - выход той же формы, uint8; при всех выключенных аугментациях — копия входа
    """
    x = frame_rgb_u8.astype(np.float32)
    h, w = x.shape[:2]

    g = cfg.glare
    if g.enabled and rng.random() < g.prob:
        radius = _uniform(rng, g.radius_frac) * min(h, w)
        center = (float(rng.uniform(0, w)), float(rng.uniform(0, h)))
        x = apply_glare(x, center, radius, _uniform(rng, g.intensity))

    sh = cfg.shadow
    if sh.enabled and rng.random() < sh.prob:
        x = apply_shadow(
            x,
            angle_deg=float(rng.uniform(0.0, 360.0)),
            offset=float(rng.uniform(0.2, 0.8)),
            strength=_uniform(rng, sh.strength),
            softness=_uniform(rng, sh.softness_frac),
        )

    oc = cfg.occlusion
    if oc.enabled and rng.random() < oc.prob:
        for _ in range(int(rng.integers(oc.count[0], oc.count[1] + 1))):
            side = _uniform(rng, oc.size_frac) * min(h, w)
            rw, rh = int(side * rng.uniform(0.6, 1.6)), int(side * rng.uniform(0.6, 1.6))
            rect = (int(rng.uniform(0, w - 1)), int(rng.uniform(0, h - 1)), max(1, rw), max(1, rh))
            color = tuple(float(c) for c in rng.uniform(0, 255, size=3))
            x = apply_occlusion(x, rect, color)

    b = cfg.gaussian_blur
    if b.enabled and rng.random() < b.prob:
        sigma = _uniform(rng, b.sigma)
        x = cv2.GaussianBlur(x, (0, 0), sigmaX=sigma, sigmaY=sigma)

    m = cfg.motion_blur
    if m.enabled and rng.random() < m.prob:
        length = int(rng.integers(m.length[0], m.length[1] + 1))
        x = apply_motion_blur(x, length, float(rng.uniform(0.0, 180.0)))

    bc = cfg.brightness_contrast
    if bc.enabled and rng.random() < bc.prob:
        x = apply_brightness_contrast(x, _uniform(rng, bc.brightness), _uniform(rng, bc.contrast))

    t = cfg.color_temperature
    if t.enabled and rng.random() < t.prob:
        x = apply_color_temperature(x, _uniform(rng, t.shift))

    cs = cfg.channel_shift
    if cs.enabled and rng.random() < cs.prob:
        shifts = tuple(float(s) for s in rng.uniform(-cs.max_shift, cs.max_shift, size=3))
        x = apply_channel_shift(x, shifts)

    n = cfg.noise
    if n.enabled and rng.random() < n.prob:
        std = _uniform(rng, n.std)
        x = x + rng.normal(0.0, std, size=x.shape).astype(np.float32)

    out = np.clip(x, 0, 255).astype(np.uint8)

    j = cfg.jpeg
    if j.enabled and rng.random() < j.prob:
        quality = int(rng.integers(j.quality[0], j.quality[1] + 1))
        out = apply_jpeg(out, quality)

    return out
