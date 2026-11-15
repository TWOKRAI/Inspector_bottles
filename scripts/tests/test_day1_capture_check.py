"""scripts/day1_capture_check.py: набор кадров дисков -> числа PASS/FAIL.

Кадры синтетические: резкая шахматка (дисперсия Лапласа порядка тысяч), размытая шахматка
(порядка единиц), тёмный кадр (яркость 28 — как тёмная сцена 0.5). Ожидаемые значения — литералы.
"""

from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np

from scripts import day1_capture_check as chk


def _checker(size: int = 128, cell: int = 8, lo: int = 40, hi: int = 200) -> np.ndarray:
    ys, xs = np.indices((size, size))
    g = np.where(((ys // cell) + (xs // cell)) % 2 == 0, hi, lo).astype(np.uint8)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


def _write(path: Path, img: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    path.write_bytes(buf.tobytes())


def _fill(root: Path, letters: str, angles: list[int], n: int, img: np.ndarray) -> None:
    for letter in letters:
        for a in angles:
            for i in range(1, n + 1):
                _write(root / letter / f"a{a:03d}_{i:06d}.png", img)


def _run(root: Path, *extra: str) -> tuple[int, str]:
    buf = io.StringIO()
    args = chk.build_parser().parse_args([str(root), "--letters", "ПЕ", "--angles", "0,90", *extra])
    return chk.run(args, out=buf), buf.getvalue()


def test_full_sharp_set_passes(tmp_path):
    _fill(tmp_path, "ПЕ", [0, 90], 6, _checker())
    rc, text = _run(tmp_path)
    assert rc == 0
    assert "ИТОГ: PASS" in text
    assert "6/6" in text


def test_missing_cell_fails(tmp_path):
    _fill(tmp_path, "ПЕ", [0], 6, _checker())  # угла 90 нет ни у одной буквы
    _fill(tmp_path, "П", [90], 6, _checker())
    rc, text = _run(tmp_path)
    assert rc == 1
    assert "ячеек (буква, угол) с годных < 6: 1" in text  # нет только Е/90
    assert "ИТОГ: FAIL" in text


def test_blurred_frames_fail_by_sharpness(tmp_path):
    blurred = cv2.GaussianBlur(_checker(), (0, 0), 6)
    _fill(tmp_path, "ПЕ", [0, 90], 6, blurred)
    rc, text = _run(tmp_path)
    assert rc == 1
    assert "FAIL  доля плохих кадров 1.000" in text


def test_dark_frames_fail_by_brightness(tmp_path):
    dark = np.full((128, 128, 3), 28, np.uint8)
    dark[::8, ::8] = 100  # не нулевой Лаплас, но средняя яркость остаётся ~28
    _fill(tmp_path, "ПЕ", [0, 90], 6, dark)
    rc, text = _run(tmp_path, "--min-sharpness", "0")
    assert rc == 1
    assert "FAIL  доля плохих кадров 1.000" in text


def test_bad_name_and_unreadable_reported(tmp_path):
    _fill(tmp_path, "ПЕ", [0, 90], 6, _checker())
    _write(tmp_path / "П" / "frame_000001.png", _checker())  # имя не по схеме
    (tmp_path / "Е" / "a000_000099.png").write_bytes(b"not an image")
    rc, text = _run(tmp_path)
    assert rc == 1
    assert "BAD_NAME П" in text
    assert "UNREADABLE Е" in text
    assert "FAIL  неверных имён: 1" in text


def test_mixed_frame_sizes_fail(tmp_path):
    _fill(tmp_path, "ПЕ", [0, 90], 6, _checker())
    _write(tmp_path / "П" / "a000_000007.png", _checker(size=64))
    rc, text = _run(tmp_path)
    assert rc == 1
    assert "FAIL  размеров кадра: 2" in text


def test_missing_directory_is_usage_error(tmp_path):
    rc, _ = _run(tmp_path / "нет_такого")
    assert rc == 2
