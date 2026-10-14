# -*- coding: utf-8 -*-
"""Hazard-тесты ревью 6.2: `confine_preset_paths` огораживает и пути `tile` секции `train.background_layers`.

Секцию `train` клиент присылает в `preset.commit` (`scene_source`), а генератор обучения читает её тайлы —
путь за пределами корней не должен пройти ограду. Ожидаемый текст — литерал `OUTSIDE_ROOTS_MESSAGE` без эха пути.
Файловую систему картинок ограда не читает: тайлы в тестах не создаются.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from Services.layer_render import ScenePreset
from Services.layer_render.preview import OUTSIDE_ROOTS_MESSAGE, confine_preset_paths


def _preset(base: Path, train: dict | None) -> ScenePreset:
    data: dict = {"catalog_dir": "cat", "base_dir": str(base)}
    if train is not None:
        data["train"] = train
    return ScenePreset.from_dict(data)


def _tiles(*paths: str) -> dict:
    return {"background_layers": [{"solid": [0, 0, 0]}, *({"tile": p} for p in paths)]}


def test_absolute_tile_outside_roots_is_rejected(tmp_path):
    root = tmp_path / "root"
    outside = (tmp_path / "elsewhere" / "secret.png").resolve()
    with pytest.raises(ValueError) as info:
        confine_preset_paths(_preset(root, _tiles(str(outside))), [root])
    assert str(info.value) == OUTSIDE_ROOTS_MESSAGE
    assert "secret" not in str(info.value)


def test_relative_tile_escaping_root_is_rejected(tmp_path):
    root = tmp_path / "a" / "b"
    with pytest.raises(ValueError) as info:
        confine_preset_paths(_preset(root, _tiles("../../x.png")), [root])
    assert str(info.value) == OUTSIDE_ROOTS_MESSAGE


def test_second_tile_outside_is_rejected_even_after_inside_one(tmp_path):
    root = tmp_path / "root"
    with pytest.raises(ValueError, match="вне разрешённых"):
        confine_preset_paths(_preset(root, _tiles("belt.png", "../../x.png")), [root])


def test_tile_inside_roots_passes(tmp_path):
    root = tmp_path / "root"
    confine_preset_paths(_preset(root, _tiles("belt.png", "tiles/belt2.png", str(root / "abs.png"))), [root])


def test_preset_without_train_unchanged(tmp_path):
    """Без `train` поведение прежнее: каталог внутри — ок, каталог снаружи — тот же отказ."""
    root = tmp_path / "root"
    confine_preset_paths(_preset(root, None), [root])
    outside = ScenePreset.from_dict({"catalog_dir": str(tmp_path / "other"), "base_dir": str(root)})
    with pytest.raises(ValueError, match="вне разрешённых"):
        confine_preset_paths(outside, [root])


@pytest.mark.parametrize(
    "train",
    [
        {"background_layers": "not-a-list"},
        {"background_layers": [42, ["tile", "../../x.png"], {"tile": 7}, {"solid": [1, 2, 3]}]},
        {"crop": {"side_px": 64}},
    ],
    ids=["not-list", "malformed-items", "no-background"],
)
def test_malformed_background_entries_are_ignored(tmp_path, train):
    """Не-список, не-словари и не-строковый `tile` ограда пропускает: их отвергает схема генератора до чтения."""
    root = tmp_path / "root"
    confine_preset_paths(_preset(root, train), [root])
