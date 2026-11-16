# -*- coding: utf-8 -*-
"""Приёмка вслепую (срез S3b2): Save вкладки «Система» и плоские ключи работы PM в ``system.yaml``.

Контракт: ``save_settings`` пишет ключи ``RunConfig`` (``run_gate``, ``run_autostart``, ``run_stop_timeout_s``,
``run_restart_grace_s``) такими, какими они были в исходном ``system.yaml`` на диске; ключа нет в файле -> не
пишет; значение из ``user_overrides.yaml`` (подмешивается при загрузке) в ``system.yaml`` не попадает.

Состояние на базе ``7ac65bb49``: 10b и 10c красные (Save пишет слитое ``run_gate``; полей ``run_stop_timeout_s``
нет в модели); 10a зелёный, но пустой (полей ещё нет).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from multiprocess_prototype.backend.config.schemas import load_system_config
from multiprocess_prototype.frontend.widgets.tabs.settings.yaml_io import save_settings


@pytest.fixture(autouse=True)
def _no_log_dir_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``build()`` присваивает ``os.environ["INSPECTOR_LOG_DIR"]``: ставим-удаляем, чтобы monkeypatch откатил."""
    from multiprocess_prototype.backend import launch

    monkeypatch.setattr(launch, "_ENV_LOG_DIR_OVERRIDE", None)
    monkeypatch.setenv("MULTIPROCESS_LOG_DIR", "x")
    monkeypatch.setenv("INSPECTOR_LOG_DIR", "x")
    monkeypatch.delenv("MULTIPROCESS_LOG_DIR")
    monkeypatch.delenv("INSPECTOR_LOG_DIR")


def _build(system_path: Path) -> Any:
    from multiprocess_prototype.backend.launch import SystemBuilder
    from multiprocess_prototype.main import DEFAULT_BLUEPRINT

    return SystemBuilder.from_topology_path(system_path, DEFAULT_BLUEPRINT).build()


def _save_and_read(tmp_path: Path, system_text: str, overrides_text: str | None) -> dict:
    """Записать ``system.yaml`` (и опционально ``user_overrides.yaml`` рядом), прогнать load -> Save, вернуть raw."""
    p = tmp_path / "system.yaml"
    p.write_text(system_text, encoding="utf-8")
    if overrides_text is not None:
        (tmp_path / "user_overrides.yaml").write_text(overrides_text, encoding="utf-8")

    save_settings(load_system_config(p), p)

    return yaml.safe_load(p.read_text(encoding="utf-8"))


def test_save_does_not_leak_run_keys_from_user_overrides(tmp_path: Path) -> None:
    """10a: override несёт ``run_autostart`` / ``run_stop_timeout_s``, исходный ``system.yaml`` их не имел ->
    после Save их в файле нет, ``run_gate`` сохранён; сборка без override их тоже не видит."""
    raw = _save_and_read(tmp_path, "run_gate: false\n", "run_autostart: true\nrun_stop_timeout_s: 3\n")

    assert raw["run_gate"] is False
    for key in ("run_autostart", "run_stop_timeout_s", "run_restart_grace_s"):
        assert key not in raw, (key, raw[key])

    (tmp_path / "user_overrides.yaml").unlink()
    cfg = _build(tmp_path / "system.yaml")._orchestrator_config

    assert "run_autostart" not in cfg
    assert "run_stop_timeout_s" not in cfg
    assert cfg["run_gate"] is False


def test_save_keeps_disk_run_gate_over_override(tmp_path: Path) -> None:
    """10b: ``run_gate: true`` на диске, ``run_gate: false`` в override -> в ``system.yaml`` остаётся ``True``."""
    raw = _save_and_read(tmp_path, "run_gate: true\n", "run_gate: false\n")

    assert raw["run_gate"] is True


def test_save_keeps_run_stop_timeout_s_set_on_disk(tmp_path: Path) -> None:
    """10c: ``run_stop_timeout_s: 4`` на диске, без override -> Save его не теряет."""
    raw = _save_and_read(tmp_path, "run_stop_timeout_s: 4\n", None)

    assert raw.get("run_stop_timeout_s") == 4
