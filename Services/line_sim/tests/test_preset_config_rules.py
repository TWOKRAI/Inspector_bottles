# -*- coding: utf-8 -*-
"""Общие правила конфига стенда для пресета сцены (`scene_source` и `layer_preview`):
`resolve_repo_path`, `load_scene_preset`, `apply_defect_override` — Services/line_sim/core/preset.py."""

from __future__ import annotations

from pathlib import Path

import yaml

from Services.line_sim.core import ScenePreset, apply_defect_override, load_scene_preset, resolve_repo_path

# Корень репозитория посчитан тестом независимо (не импортом REPO_ROOT).
_ROOT = Path(__file__).resolve().parents[3]


def test_resolve_repo_path_relative_from_repo_root_not_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resolve_repo_path("data/line_sim/x") == str((_ROOT / "data/line_sim/x").resolve())
    assert resolve_repo_path(None) is None
    assert resolve_repo_path(str(tmp_path)) == str(tmp_path)


def _yaml_preset(tmp_path: Path, defect: float) -> Path:
    path = tmp_path / "p.yaml"
    path.write_text(yaml.safe_dump({"catalog_dir": "cat", "defect_probability": defect}), encoding="utf-8")
    return path


def test_load_scene_preset_yaml_keeps_file_value_without_override(tmp_path):
    preset = load_scene_preset(str(_yaml_preset(tmp_path, 0.4)), None)
    assert preset.defect_probability == 0.4
    assert preset.base_dir == str(tmp_path.resolve())


def test_load_scene_preset_yaml_override_wins(tmp_path):
    assert load_scene_preset(str(_yaml_preset(tmp_path, 0.4)), 0.9).defect_probability == 0.9


def test_load_scene_preset_catalog_default_and_explicit(tmp_path):
    default = load_scene_preset(str(tmp_path), None)
    assert default.catalog_dir == str(tmp_path) and default.defect_probability == 0.0
    assert load_scene_preset(str(tmp_path), 0.25).defect_probability == 0.25


def test_apply_defect_override_none_is_identity():
    preset = ScenePreset(catalog_dir="c", defect_probability=0.1)
    assert apply_defect_override(preset, None) is preset
    assert apply_defect_override(preset, 0.5).defect_probability == 0.5
