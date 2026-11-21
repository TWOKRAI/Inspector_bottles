# -*- coding: utf-8 -*-
"""Патч перед коммитом B 2.1 (``run_gate: true``): входы без кнопки ЗАПУСТИТЬ не встают в ``ready`` без кадров.

Слово координатора 2026-11-21: ``--autostart`` во фронтовом входе и kwarg ``run_gate`` в ``bootstrap()``
(правка в самом ``bootstrap()``, а не в 8 скриптах-вызывающих). Ожидаемые значения — литералы; процессы не
поднимаются (``build()`` — только сборка лаунчера).

* A — ``frontend/run.py launch()`` снимает ``--autostart`` из argv (не рецепт) и передаёт ``autostart=True``;
* B — ``SystemBuilder.from_topology_path(..., run_gate=...)``: ``None`` — как в yaml, ``True``/``False`` перебивает;
* C — ``main.bootstrap()``: по умолчанию гейт ВЫКЛЮЧЕН при ``run_gate: true`` в yaml; ``None`` — как в yaml.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _no_log_dir_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``build()`` ставит ``os.environ["INSPECTOR_LOG_DIR"]`` — откат (образец ``test_run_autostart_flag.py``)."""
    from multiprocess_prototype.backend import launch

    monkeypatch.setattr(launch, "_ENV_LOG_DIR_OVERRIDE", None)
    monkeypatch.setenv("MULTIPROCESS_LOG_DIR", "x")
    monkeypatch.setenv("INSPECTOR_LOG_DIR", "x")
    monkeypatch.delenv("MULTIPROCESS_LOG_DIR")
    monkeypatch.delenv("INSPECTOR_LOG_DIR")
    # launch() пишет INSPECTOR_PRESENTATION, build() — setdefault MPF_APP_NAME на весь процесс: откат
    # (setenv+delenv — monkeypatch запоминает «переменной не было» и удаляет при откате).
    for name in ("INSPECTOR_PRESENTATION", "MPF_APP_NAME"):
        monkeypatch.setenv(name, "x")
        monkeypatch.delenv(name)


def _system_yaml(tmp_path: Path, value: bool) -> Path:
    path = tmp_path / "system.yaml"
    path.write_text(f"run_gate: {'true' if value else 'false'}\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# A. frontend/run.py: argv -> main
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("argv", "args", "kwargs"),
    [
        (["run.py", "--headless", "--autostart"], (None,), {"headless": True, "autostart": True}),
        (["run.py", "--autostart", "--headless"], (None,), {"headless": True, "autostart": True}),
        (["run.py", "letter_robot_sim", "--autostart"], ("letter_robot_sim",), {"headless": None, "autostart": True}),
        (["run.py", "--autostart", "letter_robot_sim"], ("letter_robot_sim",), {"headless": None, "autostart": True}),
        (["run.py", "--headless"], (None,), {"headless": True, "autostart": None}),
        (["run.py", "letter_robot_sim"], ("letter_robot_sim",), {"headless": None, "autostart": None}),
    ],
    ids=["headless-autostart", "autostart-headless", "recipe-autostart", "autostart-recipe", "headless-only", "recipe-only"],
)
def test_frontend_launch_strips_autostart_from_argv(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], args: tuple, kwargs: dict
) -> None:
    """A. ``--autostart`` убран из argv (не принят за рецепт) и передан ``main`` как ``autostart=True``."""
    from multiprocess_prototype import main as proto_main
    from multiprocess_prototype.frontend import run as frontend_run

    calls: list[tuple[tuple, dict]] = []

    def fake_main(*a: Any, **k: Any) -> int:
        calls.append((a, k))
        return 0

    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(frontend_run, "venv_guard", lambda *a, **k: None)
    monkeypatch.setattr(proto_main, "main", fake_main)

    assert frontend_run.launch() == 0
    assert calls == [(args, kwargs)], calls


# --------------------------------------------------------------------------- #
# B. SystemBuilder.from_topology_path(run_gate=...)
# --------------------------------------------------------------------------- #


def _build(system: Path, **kwargs: Any) -> Any:
    from multiprocess_prototype.backend.launch import SystemBuilder
    from multiprocess_prototype.main import DEFAULT_BLUEPRINT

    return SystemBuilder.from_topology_path(system, DEFAULT_BLUEPRINT, **kwargs).build()


@pytest.mark.parametrize("yaml_value", [True, False])
def test_from_topology_path_without_kwarg_keeps_yaml_value(tmp_path: Path, yaml_value: bool) -> None:
    """B1. Без kwarg значение из yaml сохраняется (ключ ``run_gate`` в конфиге оркестратора, ``is``)."""
    launcher = _build(_system_yaml(tmp_path, yaml_value))

    assert launcher._orchestrator_config["run_gate"] is yaml_value


@pytest.mark.parametrize(("yaml_value", "override"), [(True, False), (False, True)])
def test_from_topology_path_kwarg_overrides_yaml(tmp_path: Path, yaml_value: bool, override: bool) -> None:
    """B2. ``run_gate=True/False`` перебивает значение yaml — в обе стороны."""
    launcher = _build(_system_yaml(tmp_path, yaml_value), run_gate=override)

    assert launcher._orchestrator_config["run_gate"] is override


# --------------------------------------------------------------------------- #
# C. main.bootstrap()
# --------------------------------------------------------------------------- #


def _bootstrap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, yaml_value: bool, **kwargs: Any) -> Any:
    from multiprocess_prototype import main as proto_main

    monkeypatch.setattr(proto_main, "CONFIG_PATH", _system_yaml(tmp_path, yaml_value))
    return proto_main.bootstrap(**kwargs)


def test_bootstrap_default_disables_gate_even_if_yaml_enables_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """C1. ``system.yaml: run_gate: true`` (коммит B) + ``bootstrap()`` без аргументов -> гейт выключен."""
    launcher = _bootstrap(monkeypatch, tmp_path, True)

    assert launcher._orchestrator_config["run_gate"] is False


def test_bootstrap_run_gate_none_follows_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """C2. ``bootstrap(run_gate=None)`` -> как в yaml (``True``)."""
    launcher = _bootstrap(monkeypatch, tmp_path, True, run_gate=None)

    assert launcher._orchestrator_config["run_gate"] is True


def test_bootstrap_run_gate_true_enables_gate_over_yaml_false(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """C3. ``bootstrap(run_gate=True)`` включает гейт при ``run_gate: false`` в yaml."""
    launcher = _bootstrap(monkeypatch, tmp_path, False, run_gate=True)

    assert launcher._orchestrator_config["run_gate"] is True
