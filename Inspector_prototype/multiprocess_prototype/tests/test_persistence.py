# multiprocess_prototype/tests/test_persistence.py
"""Корень данных и user prefs изолированы от домашнего каталога."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(tmp_path))
    yield tmp_path
    monkeypatch.delenv("INSPECTOR_DATA_DIR", raising=False)


def test_get_data_root_respects_env(isolated_data_dir: Path) -> None:
    from multiprocess_prototype.persistence import get_data_root

    assert get_data_root() == isolated_data_dir.resolve()


def test_set_get_camera_type_roundtrip(isolated_data_dir: Path) -> None:
    from multiprocess_prototype.persistence import get_camera_type, set_camera_type

    assert set_camera_type("webcam") is True
    assert get_camera_type() == "webcam"
    prefs_file = isolated_data_dir / "user_prefs.json"
    assert prefs_file.is_file()
    data = json.loads(prefs_file.read_text(encoding="utf-8"))
    assert data.get("camera_type") == "webcam"


def test_migrate_legacy_prefs(isolated_data_dir: Path, monkeypatch, tmp_path) -> None:
    """Старый .inspector_prefs.json переносится в user_prefs.json."""
    import multiprocess_prototype.persistence.user_prefs as user_prefs_mod

    fake_legacy = tmp_path / ".inspector_prefs.json"
    fake_legacy.write_text(
        json.dumps({"camera_type": "simulator"}), encoding="utf-8"
    )
    monkeypatch.setattr(user_prefs_mod, "legacy_prefs_path", lambda: fake_legacy)

    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(isolated_data_dir))
    from multiprocess_prototype.persistence import get_camera_type

    assert get_camera_type() == "simulator"
    new_file = isolated_data_dir / "user_prefs.json"
    assert new_file.is_file()
