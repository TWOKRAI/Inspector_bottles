"""RED-приёмка Task 1.1b, блок C — инструмент `tools.make_font_letters`.

Независимый тест (blind): пишется ДО реализации, по спеке `plans/line-sim-layer-editor/phase-1-engine.md`
(раздел Task 1.1b, критерии C1-C2). НЕ читает `Services/line_sim/tools/*.py`.

Инструмент запускается subprocess'ом (модуль ещё не существует -> ModuleNotFoundError
сегодня, это и есть ожидаемый RED). Шрифты — из matplotlib data dir (DejaVuSans,
DejaVuSans-Bold, cmr10 — без кириллицы).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import cv2
import matplotlib
import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imread_unicode

WORKTREE_ROOT = Path(__file__).resolve().parents[3]
FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
DEJAVU_SANS = FONT_DIR / "DejaVuSans.ttf"
DEJAVU_SANS_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"
CMR10 = FONT_DIR / "cmr10.ttf"


@pytest.fixture(autouse=True)
def _fonts_exist() -> None:
    """GREEN-контроль: шрифты фикстуры реально есть на диске (matplotlib data dir)."""
    for f in (DEJAVU_SANS, DEJAVU_SANS_BOLD, CMR10):
        assert f.is_file(), f"шрифт не найден: {f} (проверь установку matplotlib)"


def _run_tool(args: list[str]) -> subprocess.CompletedProcess:
    # Ребёнок пишет UTF-8, родитель читает UTF-8: иначе при PYTHONIOENCODING=utf-8 в окружении
    # кириллица в stderr декодируется локалью (cp1251) и «А» из сообщения не находится.
    env = {**__import__("os").environ, "PYTHONPATH": str(WORKTREE_ROOT), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", "Services.line_sim.tools.make_font_letters", *args],
        cwd=str(WORKTREE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def _alpha_bbox(rgba: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(rgba[:, :, 3] > 0)
    assert len(ys) > 0, "нет непрозрачных пикселей вовсе"
    return int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())


def test_font_tool_writes_centered_black_letters_per_font(tmp_path: Path) -> None:
    """C1: инструмент с двумя шрифтами и двумя буквами -> 4 файла RGBA 100x100, чёрные непрозрачные
    пиксели, высота альфа-bbox 60±2, центр bbox в 50±2; два шрифта дают разные картинки."""
    out_dir = tmp_path / "letters_out"
    result = _run_tool(
        [
            "--letters",
            "АК",
            "--font",
            str(DEJAVU_SANS),
            "--font",
            str(DEJAVU_SANS_BOLD),
            "--size-px",
            "100",
            "--letter-frac",
            "0.6",
            "--out",
            str(out_dir),
        ]
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    expected_files = [
        out_dir / "А" / "DejaVuSans.png",
        out_dir / "А" / "DejaVuSans-Bold.png",
        out_dir / "К" / "DejaVuSans.png",
        out_dir / "К" / "DejaVuSans-Bold.png",
    ]
    for f in expected_files:
        assert f.is_file(), f"файл не создан: {f}"

    images: dict[Path, np.ndarray] = {}
    for f in expected_files:
        # cv2.imread на Windows не открывает путь с кириллицей (папка буквы «А») — читаем как продукт пишет.
        bgra = imread_unicode(f, cv2.IMREAD_UNCHANGED)
        assert bgra.shape == (100, 100, 4), f"{f}: shape={bgra.shape}, ожидали (100,100,4)"
        rgba = cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA)
        images[f] = rgba

        opaque = rgba[:, :, 3] > 0
        assert opaque.any(), f"{f}: нет непрозрачных пикселей"
        opaque_rgb = rgba[opaque][:, 0:3]
        assert (opaque_rgb.max(axis=1) < 60).all(), f"{f}: непрозрачные пиксели не чёрные"

        y0, y1, x0, x1 = _alpha_bbox(rgba)
        bbox_h = y1 - y0 + 1
        assert abs(bbox_h - 60) <= 2, f"{f}: высота альфа-bbox {bbox_h}, ожидали 60±2"
        cy = (y0 + y1) / 2.0
        cx = (x0 + x1) / 2.0
        assert abs(cy - 50) <= 2, f"{f}: центр bbox по Y {cy}, ожидали 50±2"
        assert abs(cx - 50) <= 2, f"{f}: центр bbox по X {cx}, ожидали 50±2"

    assert not np.array_equal(
        images[out_dir / "А" / "DejaVuSans.png"], images[out_dir / "А" / "DejaVuSans-Bold.png"]
    ), "обычный и жирный шрифт дали одинаковую картинку буквы А"


def test_font_tool_rejects_font_without_glyph(tmp_path: Path) -> None:
    """C2: шрифт без кириллицы (cmr10.ttf) -> ненулевой код выхода, в тексте ошибки имя шрифта и буква."""
    out_dir = tmp_path / "letters_out_bad"
    result = _run_tool(
        [
            "--letters",
            "А",
            "--font",
            str(CMR10),
            "--size-px",
            "100",
            "--letter-frac",
            "0.6",
            "--out",
            str(out_dir),
        ]
    )
    assert result.returncode != 0, "ожидали ошибку - у cmr10 нет глифа кириллической А"
    combined_output = result.stdout + result.stderr
    assert "cmr10" in combined_output, f"в выводе нет имени шрифта cmr10: {combined_output!r}"
    assert "А" in combined_output, f"в выводе нет буквы 'А': {combined_output!r}"
