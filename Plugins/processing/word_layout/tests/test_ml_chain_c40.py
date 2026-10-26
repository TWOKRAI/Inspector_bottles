"""C-40 (A7): цепочка на РЕАЛЬНЫХ объектах line_filter -> center_crop -> ml_inference -> word_layout.

ml_inference — настоящий плагин с подменённым backend: заглушка выбирает класс по среднему входного
тензора и считает вызовы infer (метки по номеру вызова запрещены). В конфиге ml_inference стоит
старый ключ ``"inference_every_n": 2``. Диски Р Р Е Е И И, каждый — свой проход, кадр прохода однотонный:
яркость 40 / 120 / 200 для Р / Е / И (на нулевом кадре кропы всех дисков одинаковы, заглушка их не различит).

Геометрия и слово — как в test_disk_identity_chain.py: «ПЕРЕМИРИЕ», ячейки П0 Е1 Р2 Е3 М4 И5 Р6 И7 Е8.
Жадный матчинг (assembler.offer): Р -> 2, 6; Е -> 1, 3; И -> 5, 7. Угловой головы у заглушки нет:
``angle_valid`` нет, доворот 0.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.filter.line_filter.plugin import LineFilterPlugin
from Plugins.processing.center_crop.plugin import CenterCropPlugin
from Plugins.processing.word_layout.plugin import WordLayoutPlugin
from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.core.model_spec import ModelSpec
from Services.ml_inference.core.preprocess import preprocess
from Services.ml_inference.plugin.plugin import MLInferencePlugin

# Конфиги line_filter / center_crop / word_layout — литералами из test_disk_identity_chain.py.
_LINE_CFG = {
    "center_x": 376,
    "center_y": 262,
    "angle": 90,
    "zone_width": 250,
    "mode": "zone_edge",
    "rearm_frames": 2,
    "max_match_distance": 140,
    "max_age": 2,
}
_CROP_CFG = {
    "size_mode": "radius",
    "radius_scale": 1.0,
    "margin_px": 14,
    "side_px": 256,
    "output_size": 128,
    "drop_partial": False,
    "pad_if_oob": True,
}
_WORD_CFG = {"require_pick": False, "word_source": "", "settle_frames": 1, "target_word": "ПЕРЕМИРИЕ"}
_PASS_XS = (260, 298, 336, 374, 412, 450, 488)

_LABELS = ["Р", "Е", "И"]
_BRIGHTNESS = {"Р": 40, "Е": 120, "И": 200}
_MEAN_LOW = -0.6  # среднее тензора ниже -> Р
_MEAN_HIGH = 0.8  # ниже -> Е, иначе И


class _ContentBackend(BaseInferenceBackend):
    """Backend-заглушка: класс по среднему входного тензора (уверенность топ-1 0.9), счётчик вызовов infer."""

    def __init__(self) -> None:
        super().__init__()
        self.infer_calls = 0
        self.means: list[float] = []

    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        self._spec = spec

    def infer(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        self.infer_calls += 1
        mean = float(tensor.mean())
        self.means.append(mean)
        idx = 0 if mean < _MEAN_LOW else (1 if mean < _MEAN_HIGH else 2)
        p = np.full(3, 0.05, dtype=np.float64)
        p[idx] = 0.9
        return {"logits": np.log(p).astype(np.float32)[None, :]}

    def unload(self) -> None:
        self._spec = None


def _mk(cls: type, cfg: dict):
    plugin = cls()
    plugin.configure(PluginContext(services=MockProcessServices(name="x", config=cfg), config=cfg))
    return plugin


def _make_ml(tmp_path: Path) -> tuple[MLInferencePlugin, _ContentBackend]:
    """MLInferencePlugin со старым ключом inference_every_n=2 и подменённым backend (как в helper-е слоя Services)."""
    ctx = MagicMock()
    ctx.config = {
        "models_dir": str(tmp_path),
        "model": "fake",
        "confidence_threshold": 0.5,
        "top_k": 3,
        "draw_overlay": False,
        "inference_every_n": 2,
    }
    ctx.registers = None
    ctx.state_proxy = None
    ctx.process_name = "ml_proc"
    plugin = MLInferencePlugin()
    plugin.configure(ctx)

    spec = ModelSpec(name="fake", weights_path=tmp_path / "fake.onnx", input_size=(32, 32))
    backend = _ContentBackend()
    backend.load(spec)
    plugin._engine._backend = backend
    plugin._engine._spec = spec
    plugin._engine._labels = list(_LABELS)
    return plugin, backend


def test_a7_real_chain_every_disc_recognised_with_old_every_n_config(tmp_path: Path) -> None:
    line = _mk(LineFilterPlugin, _LINE_CFG)
    crop = _mk(CenterCropPlugin, _CROP_CFG)
    ml, backend = _make_ml(tmp_path)
    word = _mk(WordLayoutPlugin, _WORD_CFG)

    # Сторож заглушки: средние однотонных кадров упорядочены и разведены порогами (кроп квадратный 128x128).
    spec = ml._engine._spec
    means = [float(preprocess(np.full((128, 128, 3), _BRIGHTNESS[c], np.uint8), spec).mean()) for c in "РЕИ"]
    assert means[0] < _MEAN_LOW < means[1] < _MEAN_HIGH < means[2]

    def feed(dets: list[dict], seq: int, frame: np.ndarray) -> list[dict]:
        """Один кадр: line_filter -> center_crop -> ml_inference (всё сразу) -> word_layout."""
        ov = line.process([{"detections": dets, "seq_id": seq}])[0]
        crops = crop.process([{"frame": frame, "filtered": ov["filtered"], "detections": dets, "seq_id": seq}])
        recognised = ml.process(crops) if crops else []
        return [word.process([r])[0] for r in recognised]

    letters: list[str | None] = []
    slots: list[int | None] = []
    seq = 0
    for _ in range(2):  # защёлка line_filter стартует закрытой, взводится rearm_frames пустых кадров
        seq += 1
        feed([], seq, np.zeros((481, 800, 3), np.uint8))
    for label in "РРЕЕИИ":
        frame = np.full((481, 800, 3), _BRIGHTNESS[label], np.uint8)
        for x in _PASS_XS:  # диск проходит зону: событие только на входе
            seq += 1
            for out in feed([{"center": [x, 262], "radius": 40}], seq, frame):
                job = out.get("robot_job")
                letters.append(job["char"] if job else None)
                slots.append(job["slot"] if job else None)
        for _ in range(2):  # пустые кадры >= rearm_frames: line_filter взводится заново
            seq += 1
            feed([], seq, frame)

    assert letters == ["Р", "Р", "Е", "Е", "И", "И"]
    assert slots == [2, 6, 1, 3, 5, 7]
    assert backend.infer_calls == 6  # по одному инференсу на событие line_filter
