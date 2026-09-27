"""Тест лида Task 1.1b (редактор слоёв): пробел матрицы инъекций.

Инъекция I4 («пятно дефекта строится по спрайту класса, а не по нижнему слою») не убила ни
одного теста: в приёмке A5 буква лежит внутри диска, и пятно по букве тоже не меняет альфу.
Здесь проверяется то, что отличает два варианта: пятно ложится и на диск вокруг буквы.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from Services.line_sim import ObjectFactory, ScenePreset


def _write_rgba(path: Path, rgba: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))


def _square(size: int, rgb: tuple[int, int, int]) -> np.ndarray:
    img = np.zeros((size, size, 4), dtype=np.uint8)
    img[:, :, :3] = rgb
    img[:, :, 3] = 255
    return img


def test_defect_blob_covers_disk_not_only_letter(tmp_path: Path) -> None:
    """Слои `[диск 60×60 белый, class:// буква 20×20 красная]`, принудительный дефект: среди
    пикселей, изменённых пятном, есть пиксели ВНЕ квадрата буквы (на диске). Пятно по букве
    (маска 20×20) за её пределы не выходит — такой вариант этот тест роняет."""
    _write_rgba(tmp_path / "cat" / "A" / "0.png", _square(20, (255, 0, 0)))
    _write_rgba(tmp_path / "disk.png", _square(60, (255, 255, 255)))
    preset = ScenePreset.from_dict(
        {
            "base_dir": str(tmp_path),
            "catalog_dir": "cat",
            "angle_range_deg": [0, 0],
            "layers": [
                {"name": "disk", "mode": "static", "sprite_source": "disk.png"},
                {"name": "letter", "mode": "static", "sprite_source": "class://"},
            ],
        }
    )
    plain = ObjectFactory(preset).make("o1", 0.0, np.random.default_rng(3)).render()
    factory = ObjectFactory(preset)
    factory.force_defect_next()
    dirty = factory.make("o1", 0.0, np.random.default_rng(3)).render()

    assert plain.shape == (60, 60, 4)
    changed = np.any(plain[:, :, :3] != dirty[:, :, :3], axis=2)
    letter_box = np.zeros_like(changed)
    letter_box[20:40, 20:40] = True  # буква 20×20 по центру канвы 60×60
    assert changed.any()
    assert (changed & ~letter_box).any(), "пятно не вышло за букву — построено не по нижнему слою"


def test_font_tool_rejects_letter_wider_than_canvas_and_writes_nothing(tmp_path: Path) -> None:
    """Ревью 1.1b, SHOULD-1 + NIT-3: DejaVuSans «Ж» (ширина/высота ≈ 1.42) при `letter_frac=0.8` шире
    квадрата `size_px` — выход с ошибкой (шрифт, буква в тексте), и НИ ОДНОГО файла/папки в `out`
    (иначе каталог молча принял бы пустой класс). При `letter_frac=0.6` та же буква проходит."""
    import subprocess
    import sys

    import matplotlib

    font = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
    root = Path(__file__).resolve().parents[3]

    def run(frac: str, out: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "Services.line_sim.tools.make_font_letters", "--letters", "ИЖ",
             "--font", str(font), "--size-px", "100", "--letter-frac", frac, "--out", str(out)],
            capture_output=True, text=True, timeout=60, cwd=root,
            env={"PYTHONPATH": str(root), "PATH": "/usr/bin:/bin"},
        )

    bad = run("0.8", tmp_path / "bad")
    assert bad.returncode != 0
    assert "DejaVuSans" in bad.stderr + bad.stdout and "Ж" in bad.stderr + bad.stdout
    assert not (tmp_path / "bad").exists() or not any((tmp_path / "bad").iterdir())

    ok = run("0.6", tmp_path / "ok")
    assert ok.returncode == 0, ok.stderr
    assert (tmp_path / "ok" / "Ж" / "DejaVuSans.png").is_file()
