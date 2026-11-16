"""Hazard-тесты автора Task 2.1: флаг ``--run-gate/--no-run-gate`` доезжает до ``run_case`` и до harness.

Что может сломаться: (1) ``run_one`` не передаёт флаг подпроцессу — замер идёт без гейта молча;
(2) ``run_case`` при гейте не зовёт ``start_run()`` или зовёт после ожидания/замера — на системе в «готов»
кадров нет; (3) без гейта harness получает лишний kwarg (baseline-дерево старше 2.1 его не знает).
Стенд не поднимается: ``_run_tree`` и ``BackendHarness`` — фейки.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.capacity_bench import __main__ as bench
from scripts.capacity_bench import run_case


@pytest.mark.parametrize(
    ("run_gate", "present", "absent"),
    [(True, "--run-gate", "--no-run-gate"), (False, "--no-run-gate", "--run-gate")],
)
def test_run_one_passes_the_flag_to_the_case_process(monkeypatch, run_gate: bool, present: str, absent: str) -> None:
    seen: list[list[str]] = []

    def fake_run_tree(cmd, *, cwd, env, timeout):
        seen.append(list(cmd))
        Path(cmd[cmd.index("--out") + 1]).write_text(json.dumps({"processes": {}, "total_ext_cores": 0.0}))
        return 0, "", ""

    monkeypatch.setattr(bench, "_run_tree", fake_run_tree)
    monkeypatch.setattr(bench, "_git_head", lambda tree: "f" * 40)

    bench.run_one(Path.cwd(), "candidate", 480, 25, 6, 8775, run_gate)

    assert present in seen[0] and absent not in seen[0], seen[0]


class _Stop(BaseException):
    """Обрывает ``run_case.run`` на первом обращении к драйверу (BaseException: мимо ``except Exception``)."""


class _FakeHarness:
    events: list[str] = []

    def __init__(self, **kwargs: Any) -> None:
        self.events.append(f"init:{sorted(kwargs)}")
        self.kwargs = kwargs

    def start(self):
        self.events.append("start")
        harness = self

        class Drv:
            def introspect_status(self, name, **kw):
                harness.events.append("introspect_status")
                raise _Stop

        return Drv()

    def start_run(self, timeout: float = 30.0) -> None:
        self.events.append("start_run")

    def stop(self) -> None:
        self.events.append("stop")


@pytest.fixture
def fake_harness(monkeypatch, tmp_path: Path):
    import backend_ctl.harness as harness_module

    _FakeHarness.events = []
    monkeypatch.setattr(harness_module, "BackendHarness", _FakeHarness)
    monkeypatch.setattr(run_case, "WARMUP_S", 0)
    recipe = tmp_path / "r.yaml"
    recipe.write_text(yaml.safe_dump({"processes": [{"process_name": "camera_0"}]}), encoding="utf-8")
    return recipe


def test_run_case_with_gate_calls_start_run_before_any_measurement(fake_harness: Path) -> None:
    with pytest.raises(_Stop):
        run_case.run(str(fake_harness), 0.0, 8775, run_gate=True)

    events = _FakeHarness.events
    assert events.index("start") < events.index("start_run") < events.index("introspect_status"), events
    assert "'run_gate'" in events[0], events


def test_run_case_without_gate_does_not_start_run_nor_pass_the_kwarg(fake_harness: Path) -> None:
    with pytest.raises(_Stop):
        run_case.run(str(fake_harness), 0.0, 8775, run_gate=False)

    events = _FakeHarness.events
    assert "start_run" not in events, events
    assert "run_gate" not in events[0], events
