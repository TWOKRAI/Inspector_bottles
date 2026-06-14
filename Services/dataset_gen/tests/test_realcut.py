"""Тесты выреза диска из реального фото (core/realcut)."""

from __future__ import annotations

import cv2
import numpy as np

from Services.dataset_gen.core.realcut import cut_disk_rgba, detect_disk, rotate_upright


def _make_photo(size: int = 300, cx: int = 150, cy: int = 140, r: int = 90) -> np.ndarray:
    """Синтетический «снимок»: тёмный фон, белый диск, тёмная асимметричная метка."""
    img = np.full((size, size, 3), 30, dtype=np.uint8)  # тёмный фон
    cv2.circle(img, (cx, cy), r, (245, 245, 245), thickness=-1)  # белый диск
    cv2.rectangle(img, (cx - 10, cy - r // 2), (cx + 30, cy - r // 2 + 18), (20, 20, 20), -1)  # метка
    return img


def test_detect_disk_finds_center_and_radius() -> None:
    img = _make_photo(cx=150, cy=140, r=90)
    cx, cy, r = detect_disk(img)
    assert abs(cx - 150) <= 8 and abs(cy - 140) <= 8
    assert abs(r - 90) <= 12


def test_detect_disk_fallback_on_blank() -> None:
    blank = np.full((200, 240, 3), 0, dtype=np.uint8)  # нет круга → вписанный фолбэк
    cx, cy, r = detect_disk(blank)
    assert (cx, cy) == (120, 100)
    assert r == int(0.48 * 200)


def test_cut_disk_rgba_shape_and_alpha() -> None:
    img = _make_photo(r=90)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    rgba = cut_disk_rgba(rgb, (150, 140, 90), feather=0.0)
    assert rgba.shape == (180, 180, 4)
    # углы вне круга прозрачны, центр — непрозрачен
    assert rgba[0, 0, 3] == 0
    assert rgba[90, 90, 3] == 255


def test_cut_disk_handles_edge_clipping() -> None:
    """Диск у края: недостающая зона прозрачна (не чёрная непрозрачная)."""
    img = _make_photo(size=200, cx=20, cy=100, r=90)  # центр близко к левому краю
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    rgba = cut_disk_rgba(rgb, (20, 100, 90), feather=0.0)
    # левая часть спрайта выходит за кадр источника → прозрачна
    assert rgba[90, 5, 3] == 0


def test_rotate_upright_zero_is_identity() -> None:
    rgba = cut_disk_rgba(np.zeros((180, 180, 3), np.uint8), (90, 90, 90))
    assert np.array_equal(rotate_upright(rgba, 0), rgba)


def test_rotate_upright_90_is_lossless_and_square() -> None:
    img = _make_photo(r=90)
    rgba = cut_disk_rgba(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), (150, 140, 90), feather=0.0)
    rotated = rotate_upright(rgba, 90)
    assert rotated.shape == rgba.shape
    # поворот на 90° дважды по 180° возвращает исходник (без потерь интерполяции)
    assert np.array_equal(rotate_upright(rotate_upright(rgba, 180), 180), rgba)
