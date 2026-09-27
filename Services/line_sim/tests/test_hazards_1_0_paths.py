"""Тесты автора (внутренние риски механизма) Task 1.0 — переносимые пути `ScenePreset`.

Механизм: `base_dir` — реальное pydantic-поле (едет через `to_dict`/`from_dict`,
участвует в равенстве); `from_yaml` ставит его в каталог файла, ПЕРЕКРЫВАЯ любой
`base_dir` из самого YAML; `resolve_path()` резолвит лениво, только когда
`ObjectFactory` реально грузит изображение; `to_yaml()` `base_dir` не пишет, а
пересчитывает относительные строки от каталога ЦЕЛЕВОГО файла (`os.path.relpath`).

Риски этой конкретной реализации, не покрытые приёмочными тестами:
  - двойной ребейз (save-as A -> B -> C) не накапливает ошибку счёта каталогов;
  - `to_yaml()` в файл не пишет ключ `base_dir` вовсе (а не пишет его пустым/null);
  - стаяет ключ `base_dir` внутри самого YAML-файла игнорируется `from_yaml`
    (каталог файла — единственный источник истины, не то, что кто-то дописал вручную);
  - ребейз не трогает абсолютные пути и `fixture://`-id побайтово;
  - `from_dict(p.to_dict())` после `from_yaml` — не просто pydantic-равенство,
    а РАБОЧИЙ пресет (фабрика реально грузит те же картинки после chdir);
  - путь без файла-источника (`ScenePreset(catalog_dir=<abs>)`, как строит
    `Plugins/sim/scene_source/plugin.py:254`) ведёт себя как до Task 1.0.

Литералы фиксированы — ожидаемые значения не выводятся из кода под тестом.
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from Services.line_sim import ObjectFactory, ScenePreset

# -- фикстуры-строители (те же паттерны, что в test_acceptance_1_0_paths.py, но
# независимая копия — hazard-тесты автора не должны зависеть от приёмочного файла) ---


def _make_disk_rgba(size: int, color_rgb: tuple[int, int, int]) -> np.ndarray:
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
    bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
    ok = cv2.imwrite(str(path), bgra)
    assert ok, f"cv2.imwrite не смог записать {path}"


def _build_catalog(root: Path) -> Path:
    """`root/sprites/<class0|class1>/*.png` + `root/cap.png` + `root/p.yaml`
    (относительный `catalog_dir: sprites`, слой `cap`)."""
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
    factory = ObjectFactory(preset)
    obj = factory.make("o1", 0.0, np.random.default_rng(7))
    return obj.render()


# -- риск 1: цепочка A -> B -> C (два ребейза подряд) -------------------------


def test_save_as_chain_two_rebases_renders_same(tmp_path: Path) -> None:
    """save-as A -> B -> C (две записи `to_yaml`, два ребейза строк) — рендер из C
    побитово равен рендеру из A; ребейз не накапливает ошибку счёта каталогов."""
    a = _build_catalog(tmp_path / "A")
    preset_a = ScenePreset.from_yaml(a / "p.yaml")
    render_a = _render(preset_a)

    b = tmp_path / "sub" / "B"
    b.mkdir(parents=True)
    preset_a.to_yaml(b / "q.yaml")
    preset_b = ScenePreset.from_yaml(b / "q.yaml")

    c = tmp_path / "C"
    c.mkdir()
    preset_b.to_yaml(c / "r.yaml")
    preset_c = ScenePreset.from_yaml(c / "r.yaml")

    render_c = _render(preset_c)
    assert np.array_equal(render_a, render_c)

    data_c = yaml.safe_load((c / "r.yaml").read_text(encoding="utf-8"))
    assert not Path(data_c["catalog_dir"]).is_absolute()
    assert not Path(data_c["layers"][0]["sprite_source"]).is_absolute()


# -- риск 2: base_dir отсутствует в записанном YAML ----------------------------


def test_to_yaml_never_writes_base_dir_key(tmp_path: Path) -> None:
    """`to_yaml()` не пишет ключ `base_dir` вовсе — ни в том же каталоге, ни в другом."""
    a = _build_catalog(tmp_path / "A")
    preset = ScenePreset.from_yaml(a / "p.yaml")

    same_dir_path = a / "same.yaml"
    preset.to_yaml(same_dir_path)
    data_same = yaml.safe_load(same_dir_path.read_text(encoding="utf-8"))
    assert "base_dir" not in data_same

    other_dir = tmp_path / "B"
    other_dir.mkdir()
    other_dir_path = other_dir / "other.yaml"
    preset.to_yaml(other_dir_path)
    data_other = yaml.safe_load(other_dir_path.read_text(encoding="utf-8"))
    assert "base_dir" not in data_other


# -- риск 3: чужой base_dir в YAML игнорируется --------------------------------


def test_from_yaml_overrides_stale_base_dir_in_file(tmp_path: Path) -> None:
    """YAML со СВОИМ (неверным/устаревшим) ключом `base_dir` — `from_yaml` его
    игнорирует и ставит base_dir в РЕАЛЬНЫЙ каталог файла; резолюция и рендер идут
    от настоящего расположения, а не от значения, записанного в файле руками."""
    a = _build_catalog(tmp_path / "A")

    stale_yaml = a / "stale.yaml"
    stale_yaml.write_text(
        "base_dir: /nonexistent/stale/dir\ncatalog_dir: sprites\n"
        "layers:\n  - name: cap\n    mode: static\n    sprite_source: cap.png\n",
        encoding="utf-8",
    )
    preset = ScenePreset.from_yaml(stale_yaml)

    assert preset.base_dir == str(a.resolve())
    assert preset.base_dir != "/nonexistent/stale/dir"

    render = _render(preset)
    assert render.shape[2] == 4  # фабрика реально построила объект (каталог найден по base_dir файла)


# -- риск 4: ребейз не трогает абсолютные пути и id-схемы ----------------------


def test_rebase_leaves_absolute_and_scheme_byte_identical(tmp_path: Path) -> None:
    """Абсолютный путь и `fixture://`-id в пресете — побайтово те же строки в
    q.yaml (другой каталог), что были в исходном YAML; `to_yaml` их не ребейзит."""
    abs_sprite = tmp_path / "abs_cap.png"
    _write_rgba_png(abs_sprite, _make_disk_rgba(10, (0, 255, 0)))

    a = tmp_path / "A"
    a.mkdir()
    abs_yaml = a / "p.yaml"
    abs_yaml.write_text(
        f"layers:\n  - name: cap\n    mode: static\n    sprite_source: {abs_sprite}\n"
        "  - name: base\n    mode: static\n    sprite_source: fixture://base\n",
        encoding="utf-8",
    )
    preset = ScenePreset.from_yaml(abs_yaml)

    b = tmp_path / "B"
    b.mkdir()
    q = b / "q.yaml"
    preset.to_yaml(q)
    data = yaml.safe_load(q.read_text(encoding="utf-8"))

    assert data["layers"][0]["sprite_source"] == str(abs_sprite)
    assert data["layers"][1]["sprite_source"] == "fixture://base"


# -- риск 5: from_dict(to_dict()) после from_yaml собирает РАБОЧУЮ фабрику -----


def test_from_dict_roundtrip_builds_working_factory_after_chdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`from_dict(p.to_dict())` пресета, загруженного `from_yaml`, — не просто
    pydantic-равный объект, а РАБОЧИЙ: `ObjectFactory` из него грузит те же
    картинки даже после `chdir` в постороннюю папку (base_dir пережил round-trip
    через dict-границу, а не только через YAML)."""
    a = _build_catalog(tmp_path / "A")
    preset = ScenePreset.from_yaml(a / "p.yaml")
    render_before = _render(preset)

    roundtripped = ScenePreset.from_dict(preset.to_dict())
    assert roundtripped == preset

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    render_after = _render(roundtripped)
    assert np.array_equal(render_before, render_after)


# -- риск 6: пресет без файла-источника не меняет поведение --------------------


def test_preset_without_source_file_behaves_as_before(tmp_path: Path) -> None:
    """`ScenePreset(catalog_dir=<abs>)` (как строит `Plugins/sim/scene_source/plugin.py:254`,
    без `from_yaml`) -> `base_dir` остаётся `None`, `resolve_path` не трогает уже
    абсолютный путь, фабрика грузит каталог как раньше (Task 1.0 её не меняет)."""
    a = _build_catalog(tmp_path / "A")
    abs_catalog_dir = str((a / "sprites").resolve())

    preset = ScenePreset(catalog_dir=abs_catalog_dir)
    assert preset.base_dir is None
    assert preset.resolve_path(abs_catalog_dir) == abs_catalog_dir

    factory = ObjectFactory(preset)
    assert factory.num_classes == 2


# -- риск 7: relpath — потолок кросс-дисковой записи (ponytail) ----------------


def test_rebase_falls_back_to_absolute_when_relpath_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`os.path.relpath` может поднять `ValueError` (Windows, разные диски) —
    `_rebase_value` должен откатиться на абсолютный путь, а не упасть."""
    a = _build_catalog(tmp_path / "A")
    preset = ScenePreset.from_yaml(a / "p.yaml")

    def _boom(*args: object, **kwargs: object) -> str:
        raise ValueError("simulated cross-drive relpath failure")

    monkeypatch.setattr(os.path, "relpath", _boom)

    b = tmp_path / "B"
    b.mkdir()
    q = b / "q.yaml"
    preset.to_yaml(q)  # не должен поднять ValueError

    data = yaml.safe_load(q.read_text(encoding="utf-8"))
    assert Path(data["catalog_dir"]).is_absolute()
    assert data["catalog_dir"] == str((a / "sprites").resolve())


def test_save_as_on_windows_writes_forward_slashes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Пресет, сохранённый «как» на Windows, должен открываться на Mac/Orin: Windows-relpath
    даёт обратные слэши (`..\\A\\sprites`), POSIX читает такую строку как одно имя файла.
    Имитация: `os.path.relpath` подменён на `ntpath.relpath` над Windows-строками."""
    import ntpath

    a_dir, b_dir = tmp_path / "A", tmp_path / "B"
    a_dir.mkdir()
    b_dir.mkdir()
    preset = ScenePreset.from_dict({"catalog_dir": "sprites", "base_dir": str(a_dir)})
    monkeypatch.setattr(
        "Services.line_sim.core.preset.os.path.relpath",
        lambda _path, _start: ntpath.relpath(r"C:\proj\A\sprites", r"C:\proj\B"),
    )
    preset.to_yaml(b_dir / "q.yaml")
    written = yaml.safe_load((b_dir / "q.yaml").read_text(encoding="utf-8"))
    assert written["catalog_dir"] == "../A/sprites"


def test_save_as_from_symlinked_base_dir_writes_short_relative_path(tmp_path: Path) -> None:
    """Ревью 1.0, SHOULD-1: `base_dir` через симлинк (как /tmp -> /private/tmp на macOS),
    цель — в реальном каталоге. Путь в YAML обязан быть `../A/sprites`, а не обходом через
    корень файловой системы, который ломается при переносе папки."""
    real = tmp_path / "real"
    (real / "A").mkdir(parents=True)
    (real / "B").mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    preset = ScenePreset.from_dict({"catalog_dir": "sprites", "base_dir": str(alias / "A")})
    preset.to_yaml(real / "B" / "q.yaml")
    written = yaml.safe_load((real / "B" / "q.yaml").read_text(encoding="utf-8"))
    assert written["catalog_dir"] == "../A/sprites"


def test_from_yaml_by_relative_path_survives_chdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ревью 1.0, SHOULD-2: `from_yaml("A/p.yaml")` относительным путём, затем смена
    текущего каталога — фабрика всё равно находит картинки (base_dir зафиксирован абсолютным)."""
    _build_catalog(tmp_path / "A")
    monkeypatch.chdir(tmp_path)
    preset = ScenePreset.from_yaml("A/p.yaml")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert ObjectFactory(preset).num_classes == 2
