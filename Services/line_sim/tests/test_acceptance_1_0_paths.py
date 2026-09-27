"""Приёмочные тесты Task 1.0 — переносимые пути `ScenePreset`.

Пресет, сохранённый на одной машине, должен открываться на другой: относительные
пути (`catalog_dir`, `layers[*].sprite_source`) в YAML должны оставаться
относительными после `to_dict()`/`to_yaml()`, а не «застывать» в абсолютный вид
машины, на которой их когда-то загрузили.

Независимый тестировщик (blind): тесты написаны по DESIGN из брифа и README
`Services/line_sim/README.md`, без чтения `core/preset.py`, `core/factory.py`,
`core/catalog_bridge.py`, `core/layered_object.py`.

Числа в докстринге каждого теста — номер критерия приёмки из брифа.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from Services.line_sim import ObjectFactory, ScenePreset

# -- фикстуры-строители ------------------------------------------------------


def _make_disk_rgba(size: int, color_rgb: tuple[int, int, int]) -> np.ndarray:
    """RGBA uint8 (size, size, 4): непрозрачный диск (alpha=255) на прозрачном фоне."""
    img = np.zeros((size, size, 4), dtype=np.uint8)
    yy, xx = np.ogrid[:size, :size]
    c = size / 2.0
    r = size / 2.0 - 1.0
    mask = (xx - c) ** 2 + (yy - c) ** 2 <= r**2
    img[..., 0][mask] = color_rgb[0]
    img[..., 1][mask] = color_rgb[1]
    img[..., 2][mask] = color_rgb[2]
    img[..., 3][mask] = 255
    return img


def _write_rgba_png(path: Path, rgba: np.ndarray) -> None:
    """Запись RGBA-массива в PNG — OpenCV пишет BGRA, поэтому конвертируем перед imwrite."""
    bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
    ok = cv2.imwrite(str(path), bgra)
    assert ok, f"cv2.imwrite не смог записать {path}"


def _build_catalog(root: Path) -> Path:
    """Строит каталог: `root/sprites/<class0|class1>/*.png` (2 класса, 40x40,
    непрозрачные диски разного цвета) + `root/cap.png` (10x10, отдельный цвет) +
    `root/p.yaml` с относительным `catalog_dir: sprites` и слоем `cap`.

    Возвращает `root`.
    """
    root.mkdir(parents=True, exist_ok=True)
    sprites_dir = root / "sprites"
    (sprites_dir / "class0").mkdir(parents=True)
    (sprites_dir / "class1").mkdir(parents=True)
    _write_rgba_png(sprites_dir / "class0" / "a.png", _make_disk_rgba(40, (255, 0, 0)))
    _write_rgba_png(sprites_dir / "class1" / "b.png", _make_disk_rgba(40, (0, 0, 255)))
    _write_rgba_png(root / "cap.png", _make_disk_rgba(10, (0, 255, 0)))
    (root / "p.yaml").write_text(
        "catalog_dir: sprites\nlayers:\n  - name: cap\n    mode: static\n    sprite_source: cap.png\n",
        encoding="utf-8",
    )
    return root


def _render(preset: ScenePreset) -> np.ndarray:
    """Рендер-оракул: один и тот же object_id/spawn_encoder/seed -> детерминированный кадр."""
    factory = ObjectFactory(preset)
    obj = factory.make("o1", 0.0, np.random.default_rng(7))
    return obj.render()


# -- критерий 1 ---------------------------------------------------------------


def test_to_dict_keeps_relative_strings(tmp_path: Path) -> None:
    """Критерий 1: YAML с `catalog_dir: sprites` и слоем `sprite_source: cap.png`
    -> `to_dict()` хранит РОВНО строки `"sprites"` и `"cap.png"` (не абсолютный путь)."""
    a = _build_catalog(tmp_path / "A")
    preset = ScenePreset.from_yaml(a / "p.yaml")

    d = preset.to_dict()

    assert d["catalog_dir"] == "sprites"
    assert d["layers"][0]["sprite_source"] == "cap.png"


# -- критерий 2 ---------------------------------------------------------------


def test_to_yaml_same_dir_has_no_absolute_path(tmp_path: Path) -> None:
    """Критерий 2: `from_yaml(A/p.yaml).to_yaml(A/q.yaml)` — текст q.yaml не содержит
    ни `str(A)`, ни `str(A.resolve())` (на macOS tmp резолвится через /private)."""
    a = _build_catalog(tmp_path / "A")
    preset = ScenePreset.from_yaml(a / "p.yaml")

    q = a / "q.yaml"
    preset.to_yaml(q)
    text = q.read_text(encoding="utf-8")

    assert str(a) not in text
    assert str(a.resolve()) not in text


# -- критерий 3 ---------------------------------------------------------------


def test_moved_folder_renders_same(tmp_path: Path) -> None:
    """Критерий 3: перенос (копия A->C, A удалён) -> рендер из C побитово равен
    рендеру, снятому из A до удаления."""
    a = _build_catalog(tmp_path / "A")
    render_before = _render(ScenePreset.from_yaml(a / "p.yaml"))

    c = tmp_path / "C"
    shutil.copytree(a, c)
    shutil.rmtree(a)

    render_after = _render(ScenePreset.from_yaml(c / "p.yaml"))

    assert np.array_equal(render_before, render_after)


# -- критерий 4 ---------------------------------------------------------------


def test_save_as_other_dir_keeps_images_and_relative_paths(tmp_path: Path) -> None:
    """Критерий 4: save-as в другую папку B (картинки остаются в A) -> рендер из B
    побитово равен рендеру из A, И пути внутри q.yaml — относительные (не абсолютные)."""
    a = _build_catalog(tmp_path / "A")
    preset = ScenePreset.from_yaml(a / "p.yaml")
    render_a = _render(preset)

    b = tmp_path / "B"
    b.mkdir()
    q = b / "q.yaml"
    preset.to_yaml(q)

    render_b = _render(ScenePreset.from_yaml(q))
    assert np.array_equal(render_a, render_b)

    data = yaml.safe_load(q.read_text(encoding="utf-8"))
    assert not Path(data["catalog_dir"]).is_absolute()
    assert not Path(data["layers"][0]["sprite_source"]).is_absolute()


# -- критерий 5 ---------------------------------------------------------------


def test_load_independent_of_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Критерий 5: `monkeypatch.chdir` в постороннюю папку перед `from_yaml`+`make`
    -> тот же рендер, что без chdir."""
    a = _build_catalog(tmp_path / "A")
    render_no_chdir = _render(ScenePreset.from_yaml(a / "p.yaml"))

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    render_chdir = _render(ScenePreset.from_yaml(a / "p.yaml"))

    assert np.array_equal(render_no_chdir, render_chdir)


# -- критерий 6 ---------------------------------------------------------------


def test_absolute_and_scheme_ids_untouched(tmp_path: Path) -> None:
    """Критерий 6: абсолютный путь, записанный в YAML, остаётся абсолютным КАК ЕСТЬ
    после `from_yaml`->`to_dict()`; `fixture://base` в layers-only пресете (без
    каталога, без фабрики) не трогается."""
    abs_sprite = tmp_path / "abs_cap.png"
    _write_rgba_png(abs_sprite, _make_disk_rgba(10, (0, 255, 0)))

    abs_yaml = tmp_path / "abs.yaml"
    abs_yaml.write_text(
        f"layers:\n  - name: cap\n    mode: static\n    sprite_source: {abs_sprite}\n",
        encoding="utf-8",
    )
    preset_abs = ScenePreset.from_yaml(abs_yaml)
    d_abs = preset_abs.to_dict()
    assert d_abs["layers"][0]["sprite_source"] == str(abs_sprite)

    scheme_yaml = tmp_path / "scheme.yaml"
    scheme_yaml.write_text(
        "layers:\n  - name: base\n    mode: static\n    sprite_source: fixture://base\n",
        encoding="utf-8",
    )
    preset_scheme = ScenePreset.from_yaml(scheme_yaml)
    d_scheme = preset_scheme.to_dict()
    assert d_scheme["layers"][0]["sprite_source"] == "fixture://base"


# -- критерий 7 ---------------------------------------------------------------


def test_from_dict_roundtrip_after_from_yaml(tmp_path: Path) -> None:
    """Критерий 7: `ScenePreset.from_dict(p.to_dict()) == p` для `p`, загруженного `from_yaml`."""
    a = _build_catalog(tmp_path / "A")
    preset = ScenePreset.from_yaml(a / "p.yaml")

    assert ScenePreset.from_dict(preset.to_dict()) == preset
