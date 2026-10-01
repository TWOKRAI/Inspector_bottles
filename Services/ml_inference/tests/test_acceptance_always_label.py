"""Слепая приёмка Task 0.3 (letters-retrain): подпись всегда, ниже порога — с пометкой.

Контракт (лид), проверяется ТОЛЬКО по наблюдаемому выходу плагина (predictions, регистры,
кадр) — как именно вызывается движок, тесты не фиксируют:

1. Если модель выдала logits, `predictions` НЕ пуст: топ-1 есть всегда. У каждого элемента
   `below_threshold == (confidence < confidence_threshold)`. Элементы выше порога сохраняют
   прежние поля/значения плюс `below_threshold=False`.
2. Регистры: `last_label` / `last_confidence` — топ-1 ВСЕГДА (и ниже порога); новый readonly
   `last_below_threshold`; угловые регистры — по прежним правилам для топ-1.
3. Оверлей (`draw_overlay`): буква рисуется и ниже порога, с видимой пометкой (кадр отличается
   и от входного, и от «выше порога» с теми же буквой/уверенностью). Шрифт/позиция не фиксируются.

Движок подменён заглушкой backend (точные logits, без ONNX): ожидаемые числа — литералы.
logits = ln(p) → softmax возвращает ровно p.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.plugins import FieldMeta
from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.core.model_spec import ModelSpec
from Services.ml_inference.plugin.plugin import MLInferencePlugin
from Services.ml_inference.plugin.registers import MLInferenceRegisters

_LABELS = ["А", "К", "Р"]
# Вероятности по классам: А 0.30, К 0.45 (топ-1), Р 0.25.
_P = np.array([0.30, 0.45, 0.25], dtype=np.float64)
_LOGITS = np.log(_P).astype(np.float32)[None, :]
_TOP1_LABEL = "К"
_TOP1_CONF = 0.45


class _FakeBackend(BaseInferenceBackend):
    """Backend-заглушка: фиксированные выходы по именам, счётчик вызовов infer."""

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
    logits: np.ndarray = _LOGITS,
    labels: list[str] | None = None,
    top_k: int = 3,
    draw_overlay: bool = False,
    every_n: int = 1,
    angle_deg: float | None = None,
) -> tuple[MLInferencePlugin, _FakeBackend]:
    """Плагин с подставленным движком: модель 'fake' в каталоге нет → подменяем backend руками."""
    ctx = MagicMock()
    ctx.config = {
        "models_dir": str(tmp_path),  # пустой каталог
        "model": "fake",
        "confidence_threshold": threshold,
        "top_k": top_k,
        "draw_overlay": draw_overlay,
        "inference_every_n": every_n,
    }
    ctx.registers = None
    ctx.state_proxy = None
    ctx.process_name = "ml_proc"
    plugin = MLInferencePlugin()
    plugin.configure(ctx)

    labels = labels if labels is not None else _LABELS
    outputs: dict[str, np.ndarray] = {"logits": logits}
    spec_kwargs: dict = {}
    if angle_deg is not None:
        rad = np.deg2rad(angle_deg)
        outputs["angle"] = np.array([[np.sin(rad), np.cos(rad)]], dtype=np.float32)
        spec_kwargs = {"angle_head": True, "symmetry": {lbl: "none" for lbl in labels}}
    spec = ModelSpec(name="fake", weights_path=tmp_path / "fake.onnx", input_size=(32, 32), **spec_kwargs)
    backend = _FakeBackend(outputs)
    backend.load(spec)
    plugin._engine._backend = backend
    plugin._engine._spec = spec
    plugin._engine._labels = labels
    return plugin, backend


def _frame() -> np.ndarray:
    """Чёрный кадр: любой нарисованный текст виден как отличие от нуля."""
    return np.zeros((60, 320, 3), dtype=np.uint8)


def _run(plugin: MLInferencePlugin, frame: np.ndarray | None = None) -> dict:
    return plugin.process([{"frame": _frame() if frame is None else frame}])[0]


# --------------------------------------------------------------------------- #
# Клауза 1: predictions не пуст ниже порога, флаг below_threshold
# --------------------------------------------------------------------------- #


def test_below_threshold_predictions_not_empty(tmp_path: Path) -> None:
    plugin, _ = _make_plugin(tmp_path, threshold=0.5)  # топ-1 0.45 < 0.5
    preds = _run(plugin)["predictions"]
    assert len(preds) >= 1


def test_below_threshold_top1_is_the_argmax_class(tmp_path: Path) -> None:
    plugin, _ = _make_plugin(tmp_path, threshold=0.5)
    top = _run(plugin)["predictions"][0]
    assert (top["class_id"], top["label"]) == (1, _TOP1_LABEL)
    assert top["confidence"] == pytest.approx(_TOP1_CONF, abs=1e-5)


def test_below_threshold_top1_flag_true(tmp_path: Path) -> None:
    plugin, _ = _make_plugin(tmp_path, threshold=0.5)
    assert _run(plugin)["predictions"][0]["below_threshold"] is True


def test_above_threshold_top1_flag_false(tmp_path: Path) -> None:
    plugin, _ = _make_plugin(tmp_path, threshold=0.4)  # 0.45 >= 0.4
    assert _run(plugin)["predictions"][0]["below_threshold"] is False


def test_every_entry_flag_equals_confidence_below_threshold(tmp_path: Path) -> None:
    """Свойство для КАЖДОГО возвращённого элемента: флаг == (confidence < порог).

    Порог 0.4 даёт смесь: К 0.45 выше, остальные (0.30, 0.25) ниже. Сколько нижних элементов
    плагин оставит в списке, контракт не фиксирует — но все оставленные обязаны быть
    помечены верно, а список — не длиннее top_k и отсортирован по убыванию confidence.
    """
    threshold = 0.4
    plugin, _ = _make_plugin(tmp_path, threshold=threshold, top_k=3)
    preds = _run(plugin)["predictions"]
    assert 1 <= len(preds) <= 3
    for p in preds:
        assert p["below_threshold"] is (p["confidence"] < threshold), p
    confs = [p["confidence"] for p in preds]
    assert confs == sorted(confs, reverse=True)


def test_boundary_confidence_equal_to_threshold_is_not_below(tmp_path: Path) -> None:
    """confidence == порог → НЕ ниже порога (строгое `<`). logits [0,0] → ровно 0.5/0.5."""
    plugin, _ = _make_plugin(
        tmp_path, threshold=0.5, logits=np.zeros((1, 2), dtype=np.float32), labels=["А", "К"], top_k=1
    )
    top = _run(plugin)["predictions"][0]
    assert top["confidence"] == 0.5
    assert top["below_threshold"] is False


def test_boundary_just_below_threshold_is_below(tmp_path: Path) -> None:
    """Та же уверенность 0.5, порог чуть выше (0.501) → ниже порога."""
    plugin, _ = _make_plugin(
        tmp_path, threshold=0.501, logits=np.zeros((1, 2), dtype=np.float32), labels=["А", "К"], top_k=1
    )
    top = _run(plugin)["predictions"][0]
    assert top["confidence"] == 0.5
    assert top["below_threshold"] is True


def test_above_threshold_entry_keeps_todays_fields_plus_flag(tmp_path: Path) -> None:
    """Выше порога (без angle-головы): ровно прежние поля + below_threshold=False."""
    plugin, _ = _make_plugin(tmp_path, threshold=0.4, top_k=1)
    top = _run(plugin)["predictions"][0]
    assert set(top) == {"class_id", "label", "confidence", "below_threshold"}
    assert top["class_id"] == 1
    assert top["label"] == _TOP1_LABEL
    assert top["confidence"] == pytest.approx(_TOP1_CONF, abs=1e-5)
    assert top["below_threshold"] is False


def test_below_threshold_top1_carries_angle_fields(tmp_path: Path) -> None:
    """Угол топ-1 вычисляется и ниже порога (прежнее правило: angle_deg/angle_valid у топ-1)."""
    plugin, _ = _make_plugin(tmp_path, threshold=0.5, top_k=1, angle_deg=123.0)
    top = _run(plugin)["predictions"][0]
    assert top["below_threshold"] is True
    assert top["angle_valid"] is True
    assert top["angle_deg"] == pytest.approx(123.0, abs=0.01)


def test_below_threshold_predictions_reused_between_inference_frames(tmp_path: Path) -> None:
    """inference_every_n=3: ниже порога результат кэшируется, а не пересчитывается каждый кадр.

    Кадры 1..4: прогоны на 1-м и 3-м → backend.infer ровно 2 раза; на всех кадрах predictions
    непуст и топ-1 помечен. Пустой кэш (как сейчас ниже порога) заставил бы гонять сеть 4 раза.
    """
    plugin, backend = _make_plugin(tmp_path, threshold=0.5, every_n=3)
    outs = [_run(plugin) for _ in range(4)]
    assert backend.infer_calls == 2
    for out in outs:
        assert out["predictions"][0]["label"] == _TOP1_LABEL
        assert out["predictions"][0]["below_threshold"] is True


# --------------------------------------------------------------------------- #
# Клауза 2: регистры
# --------------------------------------------------------------------------- #


def test_last_label_is_top1_below_threshold(tmp_path: Path) -> None:
    plugin, _ = _make_plugin(tmp_path, threshold=0.5)
    _run(plugin)
    assert plugin._reg.last_label == _TOP1_LABEL


def test_last_confidence_is_top1_confidence_below_threshold(tmp_path: Path) -> None:
    plugin, _ = _make_plugin(tmp_path, threshold=0.5)
    _run(plugin)
    assert plugin._reg.last_confidence == pytest.approx(_TOP1_CONF, abs=1e-4)


def test_last_below_threshold_true_below(tmp_path: Path) -> None:
    plugin, _ = _make_plugin(tmp_path, threshold=0.5)
    _run(plugin)
    assert plugin._reg.last_below_threshold is True


def test_last_below_threshold_false_above(tmp_path: Path) -> None:
    plugin, _ = _make_plugin(tmp_path, threshold=0.4)
    _run(plugin)
    assert plugin._reg.last_below_threshold is False


def test_last_below_threshold_follows_the_latest_frame(tmp_path: Path) -> None:
    """Регистр не залипает: выше порога → ниже порога → снова выше (порог меняется командой)."""
    plugin, _ = _make_plugin(tmp_path, threshold=0.4)
    _run(plugin)
    assert plugin._reg.last_below_threshold is False
    plugin.cmd_set_threshold({"confidence_threshold": 0.5})
    _run(plugin)
    assert plugin._reg.last_below_threshold is True
    plugin.cmd_set_threshold({"confidence_threshold": 0.4})
    _run(plugin)
    assert plugin._reg.last_below_threshold is False


def test_last_below_threshold_register_is_readonly() -> None:
    meta = [m for m in MLInferenceRegisters.model_fields["last_below_threshold"].metadata if isinstance(m, FieldMeta)]
    assert len(meta) == 1
    assert meta[0].readonly is True


def test_angle_registers_follow_top1_below_threshold(tmp_path: Path) -> None:
    """Угловые регистры — по прежним правилам для топ-1, и когда он ниже порога."""
    plugin, _ = _make_plugin(tmp_path, threshold=0.5, top_k=1, angle_deg=123.0)
    _run(plugin)
    assert plugin._reg.last_angle_valid is True
    assert plugin._reg.last_angle_deg == pytest.approx(123.0, abs=0.01)


# --------------------------------------------------------------------------- #
# Клауза 3: оверлей
# --------------------------------------------------------------------------- #


def test_overlay_drawn_below_threshold(tmp_path: Path) -> None:
    """Ниже порога кадр на выходе отличается от входного (буква нарисована)."""
    plugin, _ = _make_plugin(tmp_path, threshold=0.5, draw_overlay=True)
    src = _frame()
    out = _run(plugin, src)["frame"]
    assert not np.array_equal(out, np.zeros_like(src))


def test_overlay_does_not_mutate_input_frame_below_threshold(tmp_path: Path) -> None:
    plugin, _ = _make_plugin(tmp_path, threshold=0.5, draw_overlay=True)
    src = _frame()
    _run(plugin, src)
    assert not src.any()  # исходный кадр остался чёрным: рисуем на копии


def test_overlay_below_threshold_differs_from_above_threshold(tmp_path: Path) -> None:
    """Те же буква и уверенность (К 0.45): ниже порога — с видимой пометкой, выше — без.

    Видимость: отличаются не менее 20 пикселей (шрифт/позиция метки не фиксируются; значок
    «?»/звёздочка/смена цвета проходят, невидимая правка — нет).
    """
    below, _ = _make_plugin(tmp_path, threshold=0.5, draw_overlay=True)  # 0.45 < 0.5
    above, _ = _make_plugin(tmp_path, threshold=0.4, draw_overlay=True)  # 0.45 >= 0.4
    f_below = _run(below)["frame"]
    f_above = _run(above)["frame"]
    assert f_below.any()  # якорь существования: ниже порога вообще что-то нарисовано
    differing = int(np.any(f_below != f_above, axis=-1).sum())
    assert differing >= 20


def test_overlay_drawn_above_threshold_regression_guard(tmp_path: Path) -> None:
    """Выше порога оверлей рисуется, как и раньше (кадр отличается от входного)."""
    plugin, _ = _make_plugin(tmp_path, threshold=0.4, draw_overlay=True)
    out = _run(plugin)["frame"]
    assert out.any()


def test_overlay_off_leaves_frame_untouched_below_threshold(tmp_path: Path) -> None:
    plugin, _ = _make_plugin(tmp_path, threshold=0.5, draw_overlay=False)
    out = _run(plugin)["frame"]
    assert not out.any()
