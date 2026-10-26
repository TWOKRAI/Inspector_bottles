"""Слепая приёмка C-40: ml_inference распознаёт КАЖДЫЙ кадр; `inference_every_n` и кэш повтора убраны.

Контракт — plans/word-layout/tasks/C-40.md, раздел «Приёмка» (A1-A6). Проверяется только наблюдаемый
выход плагина: `predictions`, регистры (`plugin._reg`, только чтение), число вызовов `infer` у заглушки.

Заглушка backend выбирает класс ПО СОДЕРЖИМОМУ входного тензора (среднее против порогов) и считает
свои вызовы `infer`. Метки по номеру вызова запрещены: такая заглушка не отличает предсказание этого
кадра от предсказания другого.

Кадры однотонные: Р -> яркость 40, Е -> 120, И -> 200. Кадры квадратные: letterbox не даёт серого
паддинга 114, который сдвинул бы среднее.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.core.model_spec import ModelSpec
from Services.ml_inference.core.preprocess import preprocess
from Services.ml_inference.plugin.plugin import MLInferencePlugin
from Services.ml_inference.plugin.registers import MLInferenceRegisters

_LABELS = ["Р", "Е", "И"]
_B_R, _B_E, _B_I = 40, 120, 200
_BRIGHTNESS = {"Р": _B_R, "Е": _B_E, "И": _B_I}
# Пороги среднего тензора (нормализация ImageNet по умолчанию): Р ~ -1.29, Е ~ +0.10, И ~ +1.49.
_MEAN_LOW = -0.6  # ниже -> Р
_MEAN_HIGH = 0.8  # ниже -> Е, иначе И


def _frame(label: str) -> np.ndarray:
    """Однотонный квадратный кадр диска: яркость задаёт класс."""
    return np.full((64, 64, 3), _BRIGHTNESS[label], dtype=np.uint8)


def _spec(tmp_path: Path) -> ModelSpec:
    return ModelSpec(name="fake", weights_path=tmp_path / "fake.onnx", input_size=(32, 32))


def _logits(top_idx: int, top_conf: float) -> np.ndarray:
    """logits = ln(p): softmax возвращает ровно p. Остальным двум классам — поровну."""
    rest = (1.0 - top_conf) / 2.0
    p = np.full(3, rest, dtype=np.float64)
    p[top_idx] = top_conf
    return np.log(p).astype(np.float32)[None, :]


class _ContentBackend(BaseInferenceBackend):
    """Backend-заглушка: класс по среднему входного тензора, счётчик вызовов infer.

    `fail_on` — множество индексов класса, на которых infer бросает исключение (вызов всё равно считается).
    """

    def __init__(self, top_conf: float = 0.9, fail_on: frozenset[int] = frozenset()) -> None:
        super().__init__()
        self._top_conf = top_conf
        self._fail_on = fail_on
        self.infer_calls = 0

    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        self._spec = spec

    def infer(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        self.infer_calls += 1
        mean = float(tensor.mean())
        idx = 0 if mean < _MEAN_LOW else (1 if mean < _MEAN_HIGH else 2)
        if idx in self._fail_on:
            raise RuntimeError(f"infer failed on class {idx}")
        return {"logits": _logits(idx, self._top_conf)}

    def unload(self) -> None:
        self._spec = None


def _make_plugin(
    tmp_path: Path,
    *,
    threshold: float = 0.5,
    top_conf: float = 0.9,
    fail_on: frozenset[int] = frozenset(),
    extra_config: dict | None = None,
) -> tuple[MLInferencePlugin, _ContentBackend]:
    """Плагин с подставленным движком (как в test_acceptance_always_label._make_plugin, без every_n)."""
    ctx = MagicMock()
    ctx.config = {
        "models_dir": str(tmp_path),  # пустой каталог
        "model": "fake",
        "confidence_threshold": threshold,
        "top_k": 3,
        "draw_overlay": False,
        **(extra_config or {}),
    }
    ctx.registers = None
    ctx.state_proxy = None
    ctx.process_name = "ml_proc"
    plugin = MLInferencePlugin()
    plugin.configure(ctx)

    spec = _spec(tmp_path)
    backend = _ContentBackend(top_conf=top_conf, fail_on=fail_on)
    backend.load(spec)
    plugin._engine._backend = backend
    plugin._engine._spec = spec
    plugin._engine._labels = list(_LABELS)
    return plugin, backend


def _top_label(out: dict) -> str:
    return out["predictions"][0]["label"]


# --------------------------------------------------------------------------- #
# Сторож заглушки: средние тензора после препроцессинга строго упорядочены
# --------------------------------------------------------------------------- #


def test_preprocessed_tensor_means_strictly_ordered_and_split_by_thresholds(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    m_r = float(preprocess(_frame("Р"), spec).mean())
    m_e = float(preprocess(_frame("Е"), spec).mean())
    m_i = float(preprocess(_frame("И"), spec).mean())
    assert m_r < m_e < m_i
    assert m_r < _MEAN_LOW < m_e < _MEAN_HIGH < m_i


# --------------------------------------------------------------------------- #
# A1: поле регистра удалено
# --------------------------------------------------------------------------- #


def test_a1_register_has_no_inference_every_n_field() -> None:
    assert "inference_every_n" not in MLInferenceRegisters.model_fields


# --------------------------------------------------------------------------- #
# A2: старый конфиг с inference_every_n=2, шесть кадров по одному на вызов process
# --------------------------------------------------------------------------- #


def test_a2_old_config_every_n_2_each_frame_recognised_one_call_each(tmp_path: Path) -> None:
    plugin, backend = _make_plugin(tmp_path, extra_config={"inference_every_n": 2})  # configure не бросил
    labels = [_top_label(plugin.process([{"frame": _frame(c)}])[0]) for c in "РРЕЕИИ"]
    assert labels == ["Р", "Р", "Е", "Е", "И", "И"]
    assert backend.infer_calls == 6


# --------------------------------------------------------------------------- #
# A3: те же шесть кадров одним вызовом process(items)
# --------------------------------------------------------------------------- #


def test_a3_old_config_every_n_2_batch_of_six_frames_in_one_call(tmp_path: Path) -> None:
    plugin, backend = _make_plugin(tmp_path, extra_config={"inference_every_n": 2})
    outs = plugin.process([{"frame": _frame(c)} for c in "РРЕЕИИ"])
    assert [_top_label(o) for o in outs] == ["Р", "Р", "Е", "Е", "И", "И"]
    assert backend.infer_calls == 6


# --------------------------------------------------------------------------- #
# A4: cmd_set_threshold с устаревшим ключом inference_every_n
# --------------------------------------------------------------------------- #


def test_a4_set_threshold_ignores_inference_every_n_and_every_frame_recognised(tmp_path: Path) -> None:
    plugin, backend = _make_plugin(tmp_path)
    resp = plugin.cmd_set_threshold({"inference_every_n": 3, "confidence_threshold": 0.4})
    assert resp == {"status": "ok"}
    assert plugin._reg.confidence_threshold == pytest.approx(0.4)
    labels = [_top_label(plugin.process([{"frame": _frame(c)}])[0]) for c in "ЕИР"]
    assert labels == ["Е", "И", "Р"]
    assert backend.infer_calls == 3


# --------------------------------------------------------------------------- #
# A5: ошибка инференса на кадре Е не отравляет соседей
# --------------------------------------------------------------------------- #


def test_a5_inference_error_on_one_frame_does_not_poison_neighbours(tmp_path: Path) -> None:
    plugin, backend = _make_plugin(tmp_path, fail_on=frozenset({1}))  # класс 1 = кадр Е

    out_r = plugin.process([{"frame": _frame("Р")}])[0]
    assert _top_label(out_r) == "Р"

    out_e = plugin.process([{"frame": _frame("Е")}])[0]
    assert out_e["predictions"] == []
    assert plugin._reg.last_below_threshold is True

    out_i = plugin.process([{"frame": _frame("И")}])[0]
    assert _top_label(out_i) == "И"
    assert backend.infer_calls == 3  # упавший кадр тоже дошёл до infer


# --------------------------------------------------------------------------- #
# A6: порог из регистра действует со следующего кадра
# --------------------------------------------------------------------------- #


def test_a6_threshold_change_applies_from_next_frame(tmp_path: Path) -> None:
    plugin, _ = _make_plugin(tmp_path, threshold=0.4, top_conf=0.45)

    first = plugin.process([{"frame": _frame("Е")}])[0]
    assert first["predictions"][0]["below_threshold"] is False  # 0.45 >= 0.4

    assert plugin.cmd_set_threshold({"confidence_threshold": 0.5}) == {"status": "ok"}

    second = plugin.process([{"frame": _frame("Е")}])[0]
    assert second["predictions"][0]["below_threshold"] is True  # 0.45 < 0.5
