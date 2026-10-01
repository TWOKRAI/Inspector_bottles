"""Hazard-тесты автора Task 0.3: подпись всегда + below_threshold (внутренние опасные места).

Слепая приёмка (`test_acceptance_always_label.py`) проверяет контракт по выходу; здесь —
то, что может сломаться именно в этой реализации: кэш inference_every_n, ошибка инференса,
граница с holdout_eval.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from Services.ml_inference.tests.test_acceptance_always_label import _frame, _make_plugin, _run


def test_cached_prediction_flag_follows_current_threshold(tmp_path: Path) -> None:
    """Что может сломаться: флаг на кэше «залипает» по порогу момента инференса.

    every_n=3, топ-1 К=0.45. Кадр 1 (инференс) порог 0.4 → False; set_threshold(0.5) → кадр 2
    (кэш) обязан стать True и в predictions, и в регистре; обратно (кадр 3, свежий инференс) → False.
    На кадре 2 infer остаётся 1: пересчёт флага не должен гонять сеть. Если бы флаг был «as of inference», робот взял бы
    диск по уже поднятому порогу.
    """
    plugin, backend = _make_plugin(tmp_path, threshold=0.4, every_n=3)
    assert _run(plugin)["predictions"][0]["below_threshold"] is False
    plugin.cmd_set_threshold({"confidence_threshold": 0.5})
    out = _run(plugin)
    assert out["predictions"][0]["below_threshold"] is True
    assert plugin._reg.last_below_threshold is True
    assert backend.infer_calls == 1  # кадр 2 — из кэша, сеть не гонялась
    plugin.cmd_set_threshold({"confidence_threshold": 0.4})
    assert _run(plugin)["predictions"][0]["below_threshold"] is False  # кадр 3 — новый инференс
    assert plugin._reg.last_below_threshold is False


def test_cache_marking_does_not_mutate_cached_entries(tmp_path: Path) -> None:
    """Что может сломаться: пометка кэша мутирует выданный ранее список (алиасинг).

    Выданный кадром 1 список потребитель мог сохранить; смена порога не должна его менять.
    """
    plugin, _ = _make_plugin(tmp_path, threshold=0.4, every_n=3)
    first = _run(plugin)["predictions"]
    plugin.cmd_set_threshold({"confidence_threshold": 0.5})
    _run(plugin)
    assert first[0]["below_threshold"] is False


def test_inference_error_resets_registers_to_failsafe(tmp_path: Path) -> None:
    """Что может сломаться: после исключения инференса регистры держат прошлый кадр.

    Кадр 1 выше порога (last_below_threshold=False, label К). Затем backend падает: predictions
    пуст, регистры сброшены — флаг True (fail-safe), label пуст, last_error заполнен. Stale False
    выглядел бы как «уверенное попадание».
    """
    plugin, backend = _make_plugin(tmp_path, threshold=0.4)
    _run(plugin)
    assert plugin._reg.last_below_threshold is False

    def boom(_tensor: np.ndarray) -> dict:
        raise RuntimeError("onnx упал")

    backend.infer = boom  # type: ignore[method-assign]
    out = _run(plugin)
    assert out["predictions"] == []
    assert plugin._reg.last_below_threshold is True
    assert plugin._reg.last_label == ""
    assert "onnx упал" in plugin._reg.last_error


def test_model_reload_resets_below_threshold_register(tmp_path: Path) -> None:
    """Что может сломаться: после смены/перезагрузки модели остаётся флаг прошлой модели."""
    plugin, _ = _make_plugin(tmp_path, threshold=0.4)
    _run(plugin)
    assert plugin._reg.last_below_threshold is False
    plugin.cmd_reload_model({})  # модели 'fake' в каталоге нет → загрузка падает, сброс обязан быть
    assert plugin._reg.last_below_threshold is True


def test_engine_predict_default_threshold_still_filters(tmp_path: Path) -> None:
    """Что может сломаться: правка отсечения «просочилась» в движок → holdout_eval/ml_train меняются.

    engine.predict(threshold=0.5) по-прежнему отбрасывает 0.45 (пустой список) и не добавляет
    поле below_threshold; вызов holdout_eval `predict(top_k=1)` (threshold=0.0) отдаёт топ-1.
    """
    plugin, _ = _make_plugin(tmp_path, threshold=0.5)
    engine = plugin._engine
    assert engine.predict(_frame(), top_k=3, threshold=0.5) == []
    top = engine.predict(_frame(), top_k=1)
    assert len(top) == 1
    assert "below_threshold" not in top[0]
    assert top[0]["label"] == "К"


@pytest.mark.parametrize("below", [True, False])
def test_overlay_on_cached_frame_equals_inference_frame(tmp_path: Path, below: bool) -> None:
    """Что может сломаться: на кэш-кадре оверлей рисуется без пометки (флаг не дошёл до top1).

    every_n=2: кадр 2 — из кэша; он обязан совпасть с кадром 1 пиксель-в-пиксель.
    """
    plugin, _ = _make_plugin(tmp_path, threshold=0.5 if below else 0.4, draw_overlay=True, every_n=2)
    f1 = _run(plugin)["frame"]
    f2 = _run(plugin)["frame"]
    assert f1.any()
    assert np.array_equal(f1, f2)
