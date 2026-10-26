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


def test_latency_telemetry_populated(dummy_models_dir: Path):
    """После инференса и публикации заполнены avg/last/max latency и inference_fps."""
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(dummy_models_dir), "model": "dummy", "confidence_threshold": 0.0}))
    plugin.process([{"frame": _frame()}])  # один инференс → счётчики заполнены
    plugin._publish_state(elapsed_s=1.0)  # окно 1 c → fps = инференсов/окно

    assert plugin._reg.inference_fps == 1.0  # 1 инференс за 1 c
    assert plugin._reg.last_latency_ms >= 0.0
    # один сэмпл → avg == max == last
    assert plugin._reg.avg_latency_ms == plugin._reg.last_latency_ms
    assert plugin._reg.max_latency_ms == plugin._reg.last_latency_ms


def test_max_latency_resets_last_persists_after_publish(dummy_models_dir: Path):
    """После публикации max/счётчики обнуляются, а last_latency_ms держится."""
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(dummy_models_dir), "model": "dummy", "confidence_threshold": 0.0}))
    plugin.process([{"frame": _frame()}])
    plugin._publish_state(elapsed_s=1.0)
    last = plugin._reg.last_latency_ms

    assert plugin._max_latency_ms == 0.0  # окно сброшено
    assert plugin._latency_count == 0
    assert plugin._reg.last_latency_ms == last  # last не сбрасывается


def test_model_switch_first_frame_gets_fresh_inference(dummy_models_dir: Path):
    """После смены модели первый кадр даёт свежий инференс новой модели (не результат прошлого)."""
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(dummy_models_dir), "model": "dummy", "confidence_threshold": 0.0}))
    plugin.process([{"frame": _frame()}])

    calls: list[int] = []
    real_predict = plugin._engine.predict

    def counting_predict(*args, **kwargs):
        calls.append(1)
        return real_predict(*args, **kwargs)

    plugin._engine.predict = counting_predict
    plugin.cmd_set_model({"model": "dummy"})  # перезагрузка модели
    assert plugin._reg.last_below_threshold is True  # телеметрия сброшена fail-safe до первого кадра

    out = plugin.process([{"frame": _frame()}])  # первый кадр после смены — свежий инференс
    assert calls == [1]
    assert len(out[0]["predictions"]) == 3


def test_empty_preds_resets_stale_telemetry(dummy_models_dir: Path):
    """Пустой результат обнуляет угол/класс — фантом прошлого объекта не остаётся."""
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(dummy_models_dir), "model": "dummy"}))
    # засеять «прошлый объект»
    plugin._reg.last_label = "alpha"
    plugin._reg.last_confidence = 0.9
    plugin._reg.last_angle_deg = 37.0
    plugin._reg.last_angle_valid = True

    plugin._update_last_pred_telemetry([])  # объект пропал

    assert plugin._reg.last_angle_valid is False
    assert plugin._reg.last_angle_deg == 0.0  # число тоже обнулено (не stale)
    assert plugin._reg.last_label == ""
    assert plugin._reg.last_confidence == 0.0


def test_last_error_cleared_on_successful_inference(dummy_models_dir: Path):
    """Транзиентная ошибка снимается после успешного кадра (не висит «красным»)."""
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(dummy_models_dir), "model": "dummy", "confidence_threshold": 0.0}))
    plugin._reg.last_error = "сбой прошлого кадра"
    plugin.process([{"frame": _frame()}])
    assert plugin._reg.last_error == ""


def test_active_providers_populated_after_load(dummy_models_dir: Path):
    """После загрузки видно фактическое устройство инференса (диагностика CPU-fallback)."""
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(dummy_models_dir), "model": "dummy"}))
    assert "CPU" in plugin._reg.active_providers


def test_engine_lock_present(dummy_models_dir: Path):
    """Плагин сериализует доступ к движку (predict vs смена модели на разных потоках)."""
    import threading

    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(dummy_models_dir), "model": "dummy"}))
    assert isinstance(plugin._engine_lock, type(threading.Lock()))
