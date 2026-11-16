"""Hazard-тесты автора Task 2.1: ``--run-gate/--no-run-gate`` в ``stand_gate``.

Что может сломаться: (1) ``__main__`` не передаёт ``run_gate`` в ``run.run_case``; (2) ``run_case`` при гейте
не зовёт ``start_run()`` до ожидания кадра (система в «готов» -> кадров 0 -> ложный красный стенда); (3) отказ
``start_run`` (AssertionError или обрыв транспорта) уходит не в ``StandRunError`` (код 2), а сырым исключением.
Стенд не поднимается: ``BackendHarness`` — фейк.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend_ctl.mcp_errors import BackendUnavailable
from scripts.stand_gate import __main__ as cli
from scripts.stand_gate import run as R


@pytest.mark.parametrize(("argv", "expected"), [([], True), (["--run-gate"], True), (["--no-run-gate"], False)])
def test_cli_passes_run_gate_to_run_case(monkeypatch, tmp_path: Path, argv: list[str], expected: bool) -> None:
    got: list[Any] = []
    monkeypatch.setattr(R, "default_lock_path", lambda tree: tmp_path / "lock")
    monkeypatch.setattr(R, "check_stand_lock", lambda lock, token: None)
    monkeypatch.setattr(R, "QUICK_CASES", [("E0", 0, False)])
    monkeypatch.setattr(R, "run_case", lambda *a, **kw: got.append(kw.get("run_gate", "ABSENT")) or {})

    args = cli._parser().parse_args([*argv, "--out-dir", str(tmp_path / "out"), "--lock-token", "t"])
    cli._live(args)

    assert got == [expected]


class _Stop(BaseException):
    """Обрывает ``run_case`` на первом опросе кадра (BaseException: мимо ``except Exception`` цикла)."""


class _FakeHarness:
    events: list[str] = []
    start_run_error: BaseException | None = None

    def __init__(self, **kwargs: Any) -> None:
        self.events.append(f"init:run_gate={kwargs.get('run_gate')}")

    def start(self):
        self.events.append("start")
        events = self.events

        class Drv:
            def introspect_status(self, name, **kw):
                events.append("introspect_status")
                raise _Stop

        return Drv()

    def start_run(self, timeout: float = 30.0) -> None:
        self.events.append("start_run")
        if self.start_run_error is not None:
            raise self.start_run_error

    def stop(self) -> None:
        self.events.append("stop")


@pytest.fixture
def fake_harness(monkeypatch, tmp_path: Path):
    import backend_ctl.harness as harness_module

    _FakeHarness.events = []
    _FakeHarness.start_run_error = None
    monkeypatch.setattr(harness_module, "BackendHarness", _FakeHarness)
    monkeypatch.setattr(R, "render", lambda tree, case_dir, transit_ms: tmp_path / "recipe.yaml")
    return _FakeHarness


def test_run_case_with_gate_calls_start_run_before_the_first_frame_wait(fake_harness, tmp_path: Path) -> None:
    with pytest.raises(_Stop):
        R.run_case(tmp_path, "E0", 0, False, 8775, run_gate=True)

    events = fake_harness.events
    assert events[0] == "init:run_gate=True", events
    assert events.index("start") < events.index("start_run") < events.index("introspect_status"), events


def test_run_case_without_gate_never_calls_start_run(fake_harness, tmp_path: Path) -> None:
    with pytest.raises(_Stop):
        R.run_case(tmp_path, "E0", 0, False, 8775, run_gate=False)

    assert "start_run" not in fake_harness.events, fake_harness.events
    assert fake_harness.events[0] == "init:run_gate=False", fake_harness.events


@pytest.mark.parametrize("error", [AssertionError("не running"), BackendUnavailable("сокет закрыт")])
def test_start_run_failure_is_a_stand_run_error(fake_harness, tmp_path: Path, error: BaseException) -> None:
    fake_harness.start_run_error = error

    with pytest.raises(R.StandRunError):
        R.run_case(tmp_path, "E0", 0, False, 8775, run_gate=True)

    assert "stop" in fake_harness.events  # harness остановлен
