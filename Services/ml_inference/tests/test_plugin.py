"""Тесты MLInferencePlugin — configure / process / команды (MagicMock ctx)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from Services.ml_inference.plugin.plugin import MLInferencePlugin


def _make_ctx(config: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.registers = None  # → локальный register (defaults + config overrides)
    ctx.state_proxy = None
    ctx.process_name = "ml_proc"
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    return ctx


def _frame() -> np.ndarray:
    return (np.random.rand(120, 160, 3) * 255).astype(np.uint8)


def test_configure_no_model_passthrough(dummy_models_dir: Path):
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(dummy_models_dir)}))
    assert plugin._reg.model == ""
    out = plugin.process([{"frame": _frame()}])
    assert len(out) == 1
    assert out[0]["predictions"] == []  # модель не выбрана → pass-through


def test_process_no_frame_dropped(dummy_models_dir: Path):
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(dummy_models_dir)}))
    assert plugin.process([{}]) == []


def test_configure_with_model_runs_inference(dummy_models_dir: Path):
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(dummy_models_dir), "model": "dummy", "confidence_threshold": 0.0}))
    assert plugin._engine.is_ready
    out = plugin.process([{"frame": _frame()}])
    preds = out[0]["predictions"]
    assert len(preds) == 3
    assert plugin._reg.last_label in {"alpha", "beta", "gamma"}
    # softmax-инвариант: сумма вероятностей ≈ 1.0 (3 класса, порог 0)
    assert abs(sum(p["confidence"] for p in preds) - 1.0) < 0.01


def test_overlay_drawn_when_enabled(dummy_models_dir: Path):
    plugin = MLInferencePlugin()
    plugin.configure(
        _make_ctx(
            {"models_dir": str(dummy_models_dir), "model": "dummy", "draw_overlay": True, "confidence_threshold": 0.0}
        )
    )
    frame = _frame()
    out = plugin.process([{"frame": frame}])
    # overlay рисуется на копии — исходный кадр не мутирован
    assert out[0]["frame"] is not frame


def test_cmd_set_model_loads_and_unloads(dummy_models_dir: Path):
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(dummy_models_dir)}))
    assert not plugin._engine.is_ready

    resp = plugin.cmd_set_model({"model": "dummy"})
    assert resp["status"] == "ok"
    assert plugin._engine.is_ready
    assert plugin._reg.loaded_model == "Dummy Classifier"

    resp = plugin.cmd_set_model({"model": ""})  # снять модель
    assert not plugin._engine.is_ready


def test_cmd_set_threshold(dummy_models_dir: Path):
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(dummy_models_dir)}))
    resp = plugin.cmd_set_threshold({"confidence_threshold": 0.9, "top_k": 1})
    assert resp["status"] == "ok"
    assert plugin._reg.confidence_threshold == 0.9
    assert plugin._reg.top_k == 1


def test_bad_model_sets_error_not_crash(dummy_models_dir: Path):
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(dummy_models_dir), "model": "ghost"}))
    # несуществующая модель → last_error заполнен, плагин жив, pass-through
    assert plugin._reg.last_error != ""
    out = plugin.process([{"frame": _frame()}])
    assert out[0]["predictions"] == []


def test_inference_every_n_reuses_result(dummy_models_dir: Path):
    plugin = MLInferencePlugin()
    plugin.configure(
        _make_ctx(
            {"models_dir": str(dummy_models_dir), "model": "dummy", "inference_every_n": 3, "confidence_threshold": 0.0}
        )
    )
    # все кадры получают предсказания (между прогонами — reuse)
    for _ in range(5):
        out = plugin.process([{"frame": _frame()}])
        assert len(out[0]["predictions"]) == 3


def test_model_switch_clears_stale_predictions(dummy_models_dir: Path):
    """Смена модели сбрасывает кэш предсказаний и счётчик кадров (не reuse старого)."""
    plugin = MLInferencePlugin()
    plugin.configure(
        _make_ctx(
            {"models_dir": str(dummy_models_dir), "model": "dummy", "inference_every_n": 3, "confidence_threshold": 0.0}
        )
    )
    plugin.process([{"frame": _frame()}])  # кадр 1 — инференс
    plugin.process([{"frame": _frame()}])  # кадр 2 — reuse
    assert plugin._last_predictions  # кэш заполнен

    plugin.cmd_set_model({"model": "dummy"})  # перезагрузка модели
    assert plugin._last_predictions == []  # кэш сброшен
    assert plugin._frame_idx == 0

    out = plugin.process([{"frame": _frame()}])  # первый кадр после смены — свежий инференс
    assert len(out[0]["predictions"]) == 3
