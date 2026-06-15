"""Тесты decode_image / letterbox / exif_orientation."""

from __future__ import annotations

import cv2
import numpy as np

from Services.phone_gateway.imaging import (
    decode_image,
    exif_orientation,
    letterbox,
)


def _encode(img: np.ndarray, ext: str = ".jpg") -> bytes:
    ok, buf = cv2.imencode(ext, img)
    assert ok
    return buf.tobytes()


def test_decode_jpeg_roundtrip():
    src = np.full((40, 60, 3), (10, 20, 30), dtype=np.uint8)
    out = decode_image(_encode(src, ".jpg"))
    assert out is not None
    assert out.shape == (40, 60, 3)


def test_decode_png_roundtrip_exact():
    src = np.random.randint(0, 255, (32, 48, 3), dtype=np.uint8)
    out = decode_image(_encode(src, ".png"))
    assert out is not None
    # PNG без потерь — точное совпадение
    assert np.array_equal(out, src)


def test_decode_garbage_returns_none():
    assert decode_image(b"not an image at all") is None
    assert decode_image(b"") is None


def test_exif_orientation_plain_jpeg_is_one():
    # Кадр, закодированный cv2, не содержит EXIF-ориентации -> 1 (норма)
    src = np.zeros((10, 10, 3), dtype=np.uint8)
    assert exif_orientation(_encode(src, ".jpg")) == 1


def test_exif_orientation_non_jpeg():
    assert exif_orientation(b"\x89PNG\r\n") == 1


def test_letterbox_preserves_aspect_ratio():
    # Квадрат 100x100 в широкий холст 200x100 -> вписан в центр 100x100, поля по бокам
    src = np.full((100, 100, 3), 255, dtype=np.uint8)
    out = letterbox(src, target_w=200, target_h=100, pad_value=0)
    assert out.shape == (100, 200, 3)
    # Центр белый (само изображение)
    assert out[50, 100].tolist() == [255, 255, 255]
    # Левый край — поле (чёрное)
    assert out[50, 2].tolist() == [0, 0, 0]


def test_letterbox_exact_fit():
    src = np.full((50, 50, 3), 128, dtype=np.uint8)
    out = letterbox(src, 50, 50)
    assert out.shape == (50, 50, 3)


def test_decode_applies_exif_orientation_once():
    """Портрет с EXIF orientation=6 поворачивается РОВНО один раз (не дважды).

    Регрессия: cv2.imdecode сам крутит по EXIF — без IMREAD_IGNORE_ORIENTATION
    наш ручной поворот складывался с авто-поворотом cv2 → +90° мимо.
    """
    pytest = __import__("pytest")
    Image = pytest.importorskip("PIL.Image")
    import io

    # Портрет 200(h) x 100(w); orientation=6 = повернуть 90° CW при показе.
    arr = np.zeros((200, 100, 3), dtype=np.uint8)
    arr[:, :50] = (0, 0, 255)
    im = Image.fromarray(arr[:, :, ::-1])  # BGR->RGB для PIL
    exif = im.getexif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    im.save(buf, format="JPEG", exif=exif)

    out = decode_image(buf.getvalue())
    assert out is not None
    # После одного поворота 200x100 -> 100x200 (ландшафт). Двойной дал бы 200x100.
    assert out.shape == (100, 200, 3)
