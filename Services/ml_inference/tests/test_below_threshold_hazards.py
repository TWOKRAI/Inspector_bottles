"""Hazard-тесты автора Task 0.3: подпись всегда + below_threshold (внутренние опасные места).

Слепая приёмка (`test_acceptance_always_label.py`) проверяет контракт по выходу; здесь —
то, что может сломаться именно в этой реализации: кэш inference_every_n, ошибка инференса,
граница с holdout_eval.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.core.model_spec import ModelSpec
from Services.ml_inference.plugin.plugin import MLInferencePlugin

# Хелперы скопированы, а не импортированы из слепого файла приёмки: тот принадлежит tester
# и меняется независимо — этот файл обязан оставаться самодостаточным.
_LABELS = ["А", "К", "Р"]
# logits = ln(p) → softmax возвращает ровно p: А 0.30, К 0.45 (топ-1), Р 0.25.
_LOGITS = np.log(np.array([0.30, 0.45, 0.25], dtype=np.float64)).astype(np.float32)[None, :]


class _FakeBackend(BaseInferenceBackend):
    """Backend-заглушка: фиксированные logits, счётчик вызовов infer."""

    def __init__(self, outputs: dict[str, np.ndarray]) -> None:
        super().__init__()
        self._outputs = outputs
        self.infer_calls = 0

    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        self._spec = spec

    def infer(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        self.infer_calls += 1
        return self._outputs

    def unload(self) -> None:
        self._spec = None


def _make_plugin(
    tmp_path: Path,
    *,
    threshold: float,
    every_n: int = 1,
    draw_overlay: bool = False,
    logits: np.ndarray = _LOGITS,
    state_proxy: object | None = None,
) -> tuple[MLInferencePlugin, _FakeBackend]:
    """Плагин с подставленным backend (модели 'fake' в каталоге нет)."""
    ctx = MagicMock()
    ctx.config = {
        "models_dir": str(tmp_path),
        "model": "fake",
        "confidence_threshold": threshold,
        "top_k": 3,
        "draw_overlay": draw_overlay,
        "inference_every_n": every_n,
    }
    ctx.registers = None
    ctx.state_proxy = state_proxy
    ctx.process_name = "ml_proc"
    plugin = MLInferencePlugin()
    plugin.configure(ctx)
    spec = ModelSpec(name="fake", weights_path=tmp_path / "fake.onnx", input_size=(32, 32))
    backend = _FakeBackend({"logits": logits})
    backend.load(spec)
    plugin._engine._backend = backend
    plugin._engine._spec = spec
    plugin._engine._labels = _LABELS
    return plugin, backend


def _frame() -> np.ndarray:
    """Чёрный кадр: любой нарисованный текст виден как отличие от нуля."""
    return np.zeros((60, 320, 3), dtype=np.uint8)


def _run(plugin: MLInferencePlugin) -> dict:
    return plugin.process([{"frame": _frame()}])[0]


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


def test_inference_error_does_not_serve_stale_cache_next_frame(tmp_path: Path) -> None:
    """Что может сломаться: после ошибки инференса следующий кадр отдаётся из СТАРОГО кэша.

    every_n=3: кадр 1 — инференс (К выше порога, кэш заполнен); кадр 2 — кэш; кадр 3 — backend
    падает (predictions пуст, регистры fail-safe). Кадр 4 раньше брал кэш кадра 1 и отдавал
    «уверенную» К, а регистры при этом были сброшены — predictions и регистры расходились,
    потребитель (word_layout) принимал диск по фантому. Теперь ошибка чистит кэш: кадр 4
    обязан переинференсить (infer_calls растёт), а не отдавать фантом.
    """
    plugin, backend = _make_plugin(tmp_path, threshold=0.4, every_n=3)
    assert _run(plugin)["predictions"][0]["label"] == "К"  # кадр 1
    _run(plugin)  # кадр 2 — из кэша
    assert backend.infer_calls == 1

    def boom(_tensor: np.ndarray) -> dict:
        raise RuntimeError("onnx упал")

    good_infer = backend.infer
    backend.infer = boom  # type: ignore[method-assign]
    assert _run(plugin)["predictions"] == []  # кадр 3 — ошибка
    assert plugin._reg.last_below_threshold is True

    backend.infer = good_infer  # type: ignore[method-assign]
    out = _run(plugin)  # кадр 4
    assert backend.infer_calls == 2  # свежий инференс, не кэш кадра 1
    assert out["predictions"][0]["label"] == "К"
    assert plugin._reg.last_below_threshold is False  # регистры согласованы с predictions


def test_inference_error_with_persistent_failure_never_serves_cache(tmp_path: Path) -> None:
    """Backend падает и дальше: кэш кадра 1 не всплывает на кадрах 4..6 (every_n=3).

    Кадры 1-2 — норма (инференс + кэш). Кадр 3 — первая ошибка; после неё каждый кадр обязан
    пробовать инференс заново (кэш пуст) и отдавать [] — без чистки кэша кадр 4 вернул бы К.
    """
    plugin, backend = _make_plugin(tmp_path, threshold=0.4, every_n=3)
    _run(plugin)
    _run(plugin)

    def boom(_tensor: np.ndarray) -> dict:
        raise RuntimeError("onnx упал")

    backend.infer = boom  # type: ignore[method-assign]
    for _ in range(4):  # кадры 3..6
        assert _run(plugin)["predictions"] == []


def test_nan_confidence_is_below_threshold(tmp_path: Path) -> None:
    """Что может сломаться: NaN-уверенность проходит как «уверенная» (`nan < thr` ложно).

    logits [nan, nan, nan] → softmax NaN → при сравнении `conf < thr` below_threshold=False,
    и word_layout принял бы диск. NaN — «не доверять»: below_threshold=True, регистр True.
    """
    logits = np.full((1, 3), np.nan, dtype=np.float32)
    plugin, _ = _make_plugin(tmp_path, threshold=0.5, logits=logits)
    out = _run(plugin)
    assert out["predictions"], "топ-1 есть всегда, даже при NaN"
    assert out["predictions"][0]["below_threshold"] is True
    assert plugin._reg.last_below_threshold is True


def test_publish_state_includes_last_below_threshold(tmp_path: Path) -> None:
    """Что может сломаться: ключ `last_below_threshold` не доезжает в StateStore (UI/робот его читают).

    Прочие тесты ставят state_proxy=None и путь публикации не видят. Здесь proxy — mock,
    смотрим merged-payload: ниже порога → True, выше → False.
    """
    proxy = MagicMock()
    plugin, _ = _make_plugin(tmp_path, threshold=0.6, state_proxy=proxy)  # топ-1 0.45 < 0.6
    _run(plugin)
    plugin._publish_state(1.0)
    assert proxy.merge.call_args[0][1]["last_below_threshold"] is True

    plugin.cmd_set_threshold({"confidence_threshold": 0.4})
    _run(plugin)
    plugin._publish_state(1.0)
    assert proxy.merge.call_args[0][1]["last_below_threshold"] is False
