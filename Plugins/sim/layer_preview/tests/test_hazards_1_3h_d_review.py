# -*- coding: utf-8 -*-
"""Hazard-тесты по ревью Task 1.3h-d, итерация 1 (F1-F3 ревьюера, воспроизведены).

F1: RGBA WebP / TIFF под именем `x.png` -> `ok`: `cv2.imdecode` определяет формат по содержимому, и сетевые
    байты доходят до КАЖДОГО декодера OpenCV. Контракт п.8 — «не PNG» -> `invalid`: сигнатура проверяется
    до любого диска и декодера.
F2: отказ создания временного файла (ACL deny на Windows) -> `tempfile.mkstemp` повторял попытки до TMP_MAX
    (2^31), поток команды `layers` не возвращался. Теперь одна попытка `O_EXCL` -> `io_error`.
F3: PNG-бомба: 6 МиБ режут сжатые байты, не пиксели (8192x8192 нулей = 0,25 МиБ -> +514 МиБ при декоде).
    Потолок пикселей читается из IHDR без декодирования.
Тест зависания — daemon-поток с дедлайном: зависание хуже падения, оно прячет регресс за таймаутом.
"""

from __future__ import annotations

import base64
import io
import os
import struct
import threading
from pathlib import Path

import cv2
import numpy as np
import pytest

from Plugins.sim.layer_preview.tests.test_acceptance_1_3h_d_sprite_put import (
    _make_world,
    _new_preview,
    _put,
    _rgba_png,
    _snapshot,
)

_PLUGIN = "Plugins.sim.layer_preview.plugin"


@pytest.fixture
def world(tmp_path: Path):
    preset_path, sprites_dir = _make_world(tmp_path)
    return _new_preview(preset_path, sprites_dir=str(sprites_dir)), sprites_dir


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _rgba_encoded(ext: str, w: int = 8, h: int = 8) -> bytes:
    arr = np.full((h, w, 4), 128, dtype=np.uint8)
    arr[:, :, 3] = 255
    ok, buf = cv2.imencode(ext, arr)
    if not ok:
        pytest.skip(f"cv2.imencode({ext!r}) с RGBA не поддержан этой сборкой OpenCV")
    return buf.tobytes()


def _assert_invalid_and_untouched(plugin, sprites_dir: Path, data: bytes) -> None:
    before = _snapshot(sprites_dir)
    res = _put(plugin, "x.png", _b64(data))
    assert res.get("status") == "error" and res.get("code") == "invalid", res
    assert _snapshot(sprites_dir) == before, "каталог побайтно прежний"


def test_f1_rgba_webp_named_png_is_invalid(world) -> None:
    plugin, sprites_dir = world
    # cv2.imencode(".webp") у этой сборки отбрасывает альфу (3 канала) — RGBA WebP делает PIL.
    image_module = pytest.importorskip("PIL.Image", reason="RGBA WebP без PIL не собрать")
    buf = io.BytesIO()
    image_module.new("RGBA", (8, 8), (1, 2, 3, 128)).save(buf, "WEBP", lossless=True)
    data = buf.getvalue()
    assert data[:4] == b"RIFF", "контроль: это WebP, не PNG"
    assert cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED).shape[2] == 4, "контроль: RGBA"
    _assert_invalid_and_untouched(plugin, sprites_dir, data)


def test_f1_rgba_tiff_named_png_is_invalid(world) -> None:
    plugin, sprites_dir = world
    data = _rgba_encoded(".tiff")
    assert data[:4] in (b"II*\x00", b"MM\x00*"), "контроль: это TIFF, не PNG"
    _assert_invalid_and_untouched(plugin, sprites_dir, data)


def test_f1_png_truncated_before_ihdr_is_invalid(world) -> None:
    plugin, sprites_dir = world
    _assert_invalid_and_untouched(plugin, sprites_dir, _rgba_png()[:20])


def test_f3_png_over_pixel_cap_is_invalid_before_decoding(world) -> None:
    plugin, sprites_dir = world
    data = _rgba_encoded(".png", 4097, 4096)  # нули/константа сжимаются в малые байты — дёшево
    w, h = struct.unpack(">II", data[16:24])
    assert w * h == 4097 * 4096 and len(data) < 6_291_456, "контроль: под потолок байт, над потолком пикселей"
    _assert_invalid_and_untouched(plugin, sprites_dir, data)


def test_control_normal_rgba_png_is_still_ok(world) -> None:
    plugin, sprites_dir = world
    res = _put(plugin, "ok.png", _b64(_rgba_png(12, 7)))
    assert res.get("status") == "ok", res
    assert sorted(p.name for p in sprites_dir.iterdir()) == ["ok.png"]


def test_f2_create_failure_returns_io_error_without_hanging(world, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin, sprites_dir = world
    real_open = os.open
    guarded = str(sprites_dir.resolve())

    def deny_in_sprites_dir(path, *args, **kwargs):
        # `tempfile` берёт тот же объект модуля `os`: патч глобален, поэтому «чужие» пути идут к настоящему os.open.
        if str(path).startswith(guarded):
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", deny_in_sprites_dir)
    box: dict = {}
    thread = threading.Thread(
        target=lambda: box.setdefault("res", _put(plugin, "up.png", _b64(_rgba_png()))), daemon=True
    )
    thread.start()
    thread.join(timeout=10)
    finished = not thread.is_alive()
    monkeypatch.undo()  # осиротевший поток (на старом коде) со следующей попытки получит настоящий os.open
    assert finished, "команда не вернулась за 10 с: цикл повторов создания временного файла"
    res = box["res"]
    assert res.get("status") == "error" and res.get("code") == "io_error", res
    assert not [p.name for p in sprites_dir.iterdir() if p.name.endswith(".uploading")], "временных файлов нет"
