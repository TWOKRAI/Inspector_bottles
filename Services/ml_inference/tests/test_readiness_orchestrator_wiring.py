"""Task 1.6 (system-run-state) — связка настоящих объектов: ``MLInferencePlugin`` в ``PluginOrchestrator``.

Остальные тесты 1.6 проверяют плагин и оркестратор по отдельности; форму элемента ``readiness()``
(dict ``{"severity", "reason"}``) на стыке держит только этот тест: оркестратор отвергает кортеж как
«неверную форму», и ``readiness()`` плагина, возвращающий пары, прошёл бы все тесты по отдельности.

Ожидаемые значения — литералы. Блокирующих вызовов нет (оркестратор синхронный).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.core.model_spec import ModelSpec

_PROC = "ml_wiring_proc"
_SIDECAR = "name: m1\ninput_size: [8, 8]\nresize_policy: stretch\nlabels: m1_classes.txt\n"


class _FakeBackend(BaseInferenceBackend):
    """Backend-заглушка без onnxruntime."""

    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        self._spec = spec

    def infer(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        return {"logits": np.array([[1.0]], dtype=np.float32)}

    def unload(self) -> None:
        self._spec = None


def _write_assets(root: Path, *, weights: bool) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "m1.yaml").write_text(_SIDECAR, encoding="utf-8")
    (root / "m1_classes.txt").write_text("A\n", encoding="utf-8")
    if weights:
        (root / "m1.onnx").write_bytes(b"x")


def test_missing_weights_reason_reaches_snapshot_and_clears_after_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Нет весов: в снимке одна причина ``failure`` «ml_inference: …», ``ready`` ложно; после перезагрузки — чисто."""
    monkeypatch.setattr("Services.ml_inference.engine._make_backend", lambda _t: _FakeBackend())
    _write_assets(tmp_path, weights=False)
    services = MockProcessServices(name=_PROC)
    services._current_process_status = "running"  # процесс объявил готовность
    orch = PluginOrchestrator(services=services)
    orch.load_and_configure_managers(
        [
            {
                "plugin_class": "Services.ml_inference.plugin.plugin.MLInferencePlugin",
                "plugin_name": "ml_inference",
                "model": "m1",
                "models_dir": str(tmp_path),
            }
        ]
    )
    orch.boot()
    assert [p.state.value for p in orch.plugins] == ["running"]  # boot не упал, плагин поднят

    snap = orch.readiness_snapshot()

    assert snap["ready"] is False, snap
    assert len(snap["reasons"]) == 1, snap["reasons"]
    reason = snap["reasons"][0]
    assert reason["node"] == f"{_PROC}.ml_inference", reason
    assert reason["severity"] == "failure", reason
    assert reason["source"] == "readiness", reason
    assert reason["reason"].startswith("ml_inference: "), reason
    assert "m1" in reason["reason"], reason

    _write_assets(tmp_path, weights=True)
    orch.plugins[0].cmd_reload_model({})

    after = orch.readiness_snapshot()
    assert after["reasons"] == [], after
    assert after["ready"] is True, after
