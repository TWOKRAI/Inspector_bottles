"""Hazard-тест автора Task 0.3: NaN-уверенность не должна давать robot_job в word_layout.

`float('nan') < min_confidence` ложно, поэтому прежний страж `conf < min_confidence` пропускал
NaN как «уверенное» предсказание. Файл самодостаточен (слепой файл приёмки не импортируется).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.word_layout.plugin import WordLayoutPlugin


def _make_plugin() -> WordLayoutPlugin:
    cfg = {"require_pick": False, "target_word": "К", "word_source": "", "settle_frames": 1}
    services = MockProcessServices(name="layout", config=cfg)
    plugin = WordLayoutPlugin()
    plugin.configure(PluginContext(services=services, config=cfg))
    return plugin


def _pred(conf: float, below: bool = False) -> dict:
    return {"label": "К", "confidence": conf, "below_threshold": below, "angle_deg": 30.0, "angle_valid": True}


def test_nan_confidence_is_not_taken_even_if_flag_says_confident() -> None:
    """NaN + below_threshold=False (флаг потерян/не выставлен) → задания нет, слот пуст."""
    p = _make_plugin()
    out = p.process([{"predictions": [_pred(float("nan"))]}])[0]
    assert "robot_job" not in out
    assert p._reg.slots_filled == 0


def test_control_finite_confidence_still_taken() -> None:
    """Контроль: конечная уверенность выше min_confidence → диск взят (страж не режет лишнего)."""
    p = _make_plugin()
    out = p.process([{"predictions": [_pred(0.9)]}])[0]
    assert out["robot_job"]["char"] == "К"
