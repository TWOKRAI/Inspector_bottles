# multiprocess_prototype_v3/tests/test_stage7_gui.py
"""Stage 7: PyQt GUI процесс (offscreen / autoclose)."""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from multiprocess_prototype_v3.backend.processes.aggregator.config import AggregatorConfig
from multiprocess_prototype_v3.backend.processes.camera_sim.config import CameraSimConfig
from multiprocess_prototype_v3.backend.processes.gui.config import GuiConfig
from multiprocess_prototype_v3.backend.processes.processor.config import ProcessorConfig
from multiprocess_prototype_v3.tests.support.harness import SystemTestHarness


def test_stage7_gui_process_autoclose(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INSPECTOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("V3_GUI_AUTOCLOSE_MS", "600")

    h = SystemTestHarness(stop_timeout=15.0)
    h.add_from_schema(
        CameraSimConfig(fps=5),
        ProcessorConfig(),
        AggregatorConfig(report_interval=2.0),
        GuiConfig(),
    )
    h.start_background(5.0)
    try:
        time.sleep(2.0)
    finally:
        h.stop()


def test_stage7_launcher_importable() -> None:
    from multiprocess_prototype_v3.frontend import launcher

    assert callable(getattr(launcher, "run_v3_gui", None))
