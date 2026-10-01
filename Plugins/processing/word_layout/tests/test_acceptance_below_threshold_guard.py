"""Слепая приёмка Task 0.3 (letters-retrain), клауза 4: робот не берёт диск ниже порога.

После Task 0.3 `ml_inference` отдаёт топ-1 ВСЕГДА, с флагом `below_threshold`. Тесты гоняют
НАСТОЯЩИЙ WordLayoutPlugin (не fake) на списке predictions в формате нового контракта:
наблюдаемое — `robot_job` в выходе кадра и `slots_filled`.

Граничный случай, из-за которого флаг вообще нужен: порог ml_inference (скажем 0.8) выше
порога word_layout (`min_confidence` 0.5). Предсказание 0.6 для word_layout «уверенное», но
для ml_inference — ниже порога. Контракт лида: ниже порога диск НЕ принимается, значит
word_layout обязан уважать `below_threshold`, а не только свой `min_confidence`.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.word_layout.plugin import WordLayoutPlugin


def _make_plugin(extra: dict | None = None) -> WordLayoutPlugin:
    cfg = {"require_pick": False, "target_word": "К", "word_source": "", "settle_frames": 1}
    cfg.update(extra or {})
    services = MockProcessServices(name="layout", config=cfg)
    plugin = WordLayoutPlugin()
    plugin.configure(PluginContext(services=services, config=cfg))
    return plugin


def _pred(conf: float, below: bool, label: str = "К") -> dict:
    """Топ-1 в формате нового контракта ml_inference."""
    return {
        "class_id": 1,
        "label": label,
        "confidence": conf,
        "below_threshold": below,
        "angle_deg": 30.0,
        "angle_valid": True,
    }


def test_control_above_threshold_is_accepted() -> None:
    """Контроль: 0.9, below_threshold=False → диск взят, как сейчас."""
    p = _make_plugin()
    out = p.process([{"predictions": [_pred(0.9, False)]}])[0]
    assert out["robot_job"]["char"] == "К"
    assert out["robot_job"]["slot"] == 0
    assert p._reg.slots_filled == 1


def test_below_threshold_low_confidence_not_taken() -> None:
    """0.3 + below_threshold=True (ниже и порога word_layout 0.5) → задания нет."""
    p = _make_plugin()
    out = p.process([{"predictions": [_pred(0.3, True)]}])[0]
    assert "robot_job" not in out


def test_below_threshold_low_confidence_leaves_slot_unfilled() -> None:
    p = _make_plugin()
    p.process([{"predictions": [_pred(0.3, True)]}])
    assert p._reg.slots_filled == 0


def test_below_threshold_flag_blocks_even_when_confidence_clears_min_confidence() -> None:
    """0.6 >= min_confidence 0.5, но below_threshold=True (порог ml 0.8) → НЕ брать."""
    p = _make_plugin({"min_confidence": 0.5})
    out = p.process([{"predictions": [_pred(0.6, True)]}])[0]
    assert "robot_job" not in out


def test_below_threshold_flag_leaves_slot_unfilled_even_when_confidence_clears_min_confidence() -> None:
    p = _make_plugin({"min_confidence": 0.5})
    p.process([{"predictions": [_pred(0.6, True)]}])
    assert p._reg.slots_filled == 0


def test_below_threshold_flag_blocks_in_trigger_mode() -> None:
    """Триггер-режим: сигнал есть, диск ниже порога (0.6, флаг True) → всё равно не берём."""
    p = _make_plugin({"use_trigger": True})
    out = p.process([{"predictions": [_pred(0.6, True)], "trigger": True}])[0]
    assert "robot_job" not in out


def test_below_threshold_frame_does_not_burn_the_slot() -> None:
    """Кадр ниже порога, затем уверенный той же буквы: диск берётся ровно один раз, слот 0."""
    p = _make_plugin()
    first = p.process([{"predictions": [_pred(0.6, True)]}])[0]
    second = p.process([{"predictions": [_pred(0.9, False)]}])[0]
    assert "robot_job" not in first
    assert second["robot_job"]["slot"] == 0
    assert p._reg.slots_filled == 1


@pytest.mark.parametrize("conf", [0.0, 0.1, 0.49])
def test_below_threshold_never_taken_across_low_confidences(conf: float) -> None:
    p = _make_plugin()
    out = p.process([{"predictions": [_pred(conf, True)]}])[0]
    assert "robot_job" not in out
