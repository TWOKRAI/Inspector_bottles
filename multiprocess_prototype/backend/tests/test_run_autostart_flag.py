# -*- coding: utf-8 -*-
"""Срез S3c′ (system-run-state 2.7) — флаг ``--autostart`` прототипа: argv -> ``main`` -> фабрика ->
``build_launcher`` -> ``SystemBuilder.from_manifest`` -> ``orchestrator_config["run_autostart"]`` -> PM.

Авторские тесты (REDS S3c′ 1a–1d, 2, 3 текста ``tasks/2.7.md``). Ожидаемые значения — литералы.

* 1a — ``run.launch()`` снимает ``--autostart`` из argv (как ``--headless``) и передаёт ``autostart=True``;
* 1b — ``build_launcher(..., run_autostart=True)`` кладёт ключ в ``orchestrator_config``;
* 1c — ``_prototype_launcher_factory(..., autostart=True)`` передаёт ``run_autostart=True`` в ``build_launcher``;
* 1d — ключи ``RunConfig`` из ``orchestrator_config`` в PM (повтор шва ``spawner.py:95-96``) взводят латч;
* 2 — без аргумента и без ключа в yaml ключа в ``orchestrator_config`` нет (PM берёт умолчание);
* 3 — второй путь: ``run_autostart: true`` в ``user_overrides.yaml`` рядом с ``system.yaml``.

Побочный эффект ``build()``: ставит ``os.environ["INSPECTOR_LOG_DIR"]`` — откат фикстурой ``_no_log_dir_env``
(образец ``test_run_gate_manifest.py``). Процессы не поднимаются.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

#: Корень репозитория: файл — multiprocess_prototype/backend/tests/<файл>.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_APP_YAML = _REPO_ROOT / "multiprocess_prototype" / "app.yaml"
_PM_MOD = "multiprocess_framework.modules.process_manager_module.process.process_manager_process"


@pytest.fixture(autouse=True)
def _no_log_dir_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from multiprocess_prototype.backend import launch

    monkeypatch.setattr(launch, "_ENV_LOG_DIR_OVERRIDE", None)
    monkeypatch.setenv("MULTIPROCESS_LOG_DIR", "x")
    monkeypatch.setenv("INSPECTOR_LOG_DIR", "x")
    monkeypatch.delenv("MULTIPROCESS_LOG_DIR")
    monkeypatch.delenv("INSPECTOR_LOG_DIR")


def _app() -> Any:
    from multiprocess_prototype.backend.config.manifest import load_manifest

    return load_manifest(_APP_YAML)


def _tmp_app(tmp_path: Path, *, overrides: str | None = None) -> Any:
    """Манифест прототипа с ``system.yaml`` в tmp: текст боевого файла (без ключа ``run_autostart``);
    ``overrides`` — текст ``user_overrides.yaml`` рядом (``None`` — файла нет, локальный файл разработчика
    рядом с боевым ``system.yaml`` не влияет)."""
    app = _app()
    system = tmp_path / "system.yaml"
    system.write_text(Path(app.system).read_text(encoding="utf-8"), encoding="utf-8")
    if overrides is not None:
        (tmp_path / "user_overrides.yaml").write_text(overrides, encoding="utf-8")
    return app.model_copy(update={"system": system})


# --------------------------------------------------------------------------- #
# 1a. argv -> main
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("argv", "args", "kwargs"),
    [
        (["run.py", "--headless", "--autostart"], (None,), {"headless": True, "autostart": True}),
        (["run.py", "letter_robot_sim", "--autostart"], ("letter_robot_sim",), {"headless": None, "autostart": True}),
        (["run.py", "letter_robot_sim"], ("letter_robot_sim",), {"headless": None, "autostart": None}),
    ],
    ids=["headless-autostart", "recipe-autostart", "recipe-only"],
)
def test_launch_strips_autostart_from_argv(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], args: tuple, kwargs: dict
) -> None:
    """1a. ``--autostart`` убран из argv (не принят за рецепт) и передан ``main`` как ``autostart=True``."""
    from multiprocess_prototype import main as proto_main
    from multiprocess_prototype import run

    calls: list[tuple[tuple, dict]] = []

    def fake_main(*a: Any, **k: Any) -> int:
        calls.append((a, k))
        return 0

    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(run, "venv_guard", lambda *a, **k: None)
    monkeypatch.setattr(proto_main, "main", fake_main)

    assert run.launch() == 0
    assert calls == [(args, kwargs)], calls


# --------------------------------------------------------------------------- #
# 1b, 1c. main -> фабрика -> build_launcher -> orchestrator_config
# --------------------------------------------------------------------------- #


def test_build_launcher_puts_run_autostart_into_orchestrator_config() -> None:
    """1b. ``build_launcher(..., run_autostart=True)`` -> ``orchestrator_config["run_autostart"] is True``."""
    from multiprocess_prototype.main import build_launcher

    launcher = build_launcher(_app(), None, include_presentation=False, run_autostart=True)

    assert launcher._orchestrator_config["run_autostart"] is True


def test_factory_passes_autostart_to_build_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    """1c. Фабрика с ``headless=True, autostart=True`` -> ``build_launcher`` получил ``include_presentation=False``
    и ``run_autostart=True``."""
    from multiprocess_prototype import main as proto_main

    calls: list[tuple[tuple, dict]] = []

    def fake_build_launcher(*a: Any, **k: Any) -> str:
        calls.append((a, k))
        return "launcher"

    monkeypatch.setattr(proto_main, "build_launcher", fake_build_launcher)

    result = proto_main._prototype_launcher_factory(
        SimpleNamespace(source=_APP_YAML), None, headless=True, autostart=True
    )

    assert result == "launcher"
    assert len(calls) == 1, calls
    assert calls[0][1] == {"include_presentation": False, "run_autostart": True}, calls


def test_main_binds_autostart_into_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main(..., autostart=True)`` привязывает ``autostart=True`` к фабрике ``run_app`` (``functools.partial``)."""
    from multiprocess_framework.modules import app_module
    from multiprocess_prototype import main as proto_main

    specs: list[Any] = []
    monkeypatch.setattr(app_module, "run_app", lambda spec: specs.append(spec) or 0)
    monkeypatch.setattr(app_module, "apply_env_aliases", lambda: None)  # env-алиасы — побочный эффект процесса

    assert proto_main.main(None, headless=True, autostart=True) == 0

    assert len(specs) == 1
    assert specs[0].launcher_factory.keywords == {"headless": True, "autostart": True}


# --------------------------------------------------------------------------- #
# 1d. orchestrator_config -> PM
# --------------------------------------------------------------------------- #


def test_orchestrator_config_arms_pm_latch(tmp_path: Path) -> None:
    """1d. ``run_gate``/``run_autostart`` из ``system.yaml`` -> ``orchestrator_config`` -> PM (шов ``update_config``):
    гейт включён, латч взведён."""
    from multiprocess_framework.modules.process_manager_module.process.run_config import RUN_CONFIG_KEYS
    from multiprocess_framework.modules.process_manager_module.process.run_state import RunState
    from multiprocess_framework.modules.process_manager_module.tests.conftest import make_monitor_double, make_pm
    from multiprocess_prototype.backend.launch import SystemBuilder
    from multiprocess_prototype.main import DEFAULT_BLUEPRINT

    system = tmp_path / "system.yaml"
    system.write_text("run_gate: true\nrun_autostart: true\n", encoding="utf-8")
    config = SystemBuilder.from_topology_path(system, DEFAULT_BLUEPRINT).build()._orchestrator_config

    pm = make_pm()
    for key in RUN_CONFIG_KEYS:
        if key in config:
            pm.update_config(key, config[key])
    with (
        patch(f"{_PM_MOD}.ProcessRegistry"),
        patch(f"{_PM_MOD}.ProcessPriority"),
        patch(f"{_PM_MOD}.ProcessStatusMonitor"),
        patch(f"{_PM_MOD}.ProcessMonitor", return_value=make_monitor_double()),
        patch(f"{_PM_MOD}.QueueRegistry"),
    ):
        pm._create_components()

    assert pm.get_config("run_autostart") is True
    assert pm._run_gate is True
    assert pm._run_autostart.observe("settled", RunState.booting, RunState.ready, None) is True


# --------------------------------------------------------------------------- #
# 2, 3. Без флага ключа нет; второй путь — user_overrides.yaml
# --------------------------------------------------------------------------- #


def test_no_argument_no_key_in_orchestrator_config(tmp_path: Path) -> None:
    """2. ``build_launcher`` без ``run_autostart``, в ``system.yaml`` ключа нет -> ключа в ``orchestrator_config``
    нет (``system.yaml`` — копия боевого в tmp, ``user_overrides.yaml`` рядом нет)."""
    from multiprocess_prototype.main import build_launcher

    app = _tmp_app(tmp_path)

    launcher = build_launcher(app, None, include_presentation=False)

    assert "run_autostart" not in launcher._orchestrator_config, launcher._orchestrator_config


def test_user_overrides_run_autostart_reaches_orchestrator_config(tmp_path: Path) -> None:
    """3. ``run_autostart: true`` в ``user_overrides.yaml`` рядом с ``system.yaml`` -> ключ в конфиге оркестратора."""
    from multiprocess_prototype.main import build_launcher

    app = _tmp_app(tmp_path, overrides="run_autostart: true\n")

    launcher = build_launcher(app, None, include_presentation=False)

    assert launcher._orchestrator_config["run_autostart"] is True


def test_explicit_false_overrides_user_overrides(tmp_path: Path) -> None:
    """Явный ``run_autostart=False`` перебивает ``user_overrides.yaml`` (присваивание при ``is not None``)."""
    from multiprocess_prototype.main import build_launcher

    app = _tmp_app(tmp_path, overrides="run_autostart: true\n")

    launcher = build_launcher(app, None, include_presentation=False, run_autostart=False)

    assert launcher._orchestrator_config["run_autostart"] is False
