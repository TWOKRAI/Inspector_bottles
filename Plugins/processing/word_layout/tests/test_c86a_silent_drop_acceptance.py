"""C-86(a): слепая приёмка «каждый диск, дошедший до word_layout, оставляет одну строку журнала».

Диск ниже порога уверенности раньше исчезал молча (строки журнала не было). Контракт C-86(a):
такой диск (с ``sidecar.track_id``) даёт ровно одну строку «диск '<Б>' <угол>° → пропуск: ...»,
робот-задание не выдаётся, слот не занимается. Кадр БЕЗ ``track_id`` диском не считается: строки нет.

Тесты написаны ДО реализации, по тексту контракта и по образцу ``test_p3_disk_journal.py``
(плагин + ``MockProcessServices``) и ``test_ml_chain_c40.py`` (настоящая цепочка с заглушкой backend).
Наблюдаемое: ``services.logs[i]["msg"]``, ``robot_job`` в выходном item, ``_reg.jobs_emitted`` /
``_reg.slots_filled``. Ожидаемые значения — литералы; буквы кириллические (М = U+041C).

Слово «ПЕРЕМИРИЕ»: ячейки П0 Е1 Р2 Е3 М4 И5 Р6 И7 Е8.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.filter.line_filter.plugin import LineFilterPlugin
from Plugins.processing.center_crop.plugin import CenterCropPlugin
from Plugins.processing.word_layout.plugin import WordLayoutPlugin
from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.core.model_spec import ModelSpec
from Services.ml_inference.plugin.plugin import MLInferencePlugin

_BASE = {
    "target_word": "ПЕРЕМИРИЕ",
    "word_source": "",
    "settle_frames": 1,
    "require_pick": True,
    "first_x": 320.0,
    "first_y": -440.0,
    "place_z_mm": -132.0,
    "pick_z_mm": -132.0,
}
_PICK = {"x_mm": 458.2, "y_mm": -343.0}

_BELOW_M_30 = "WordLayoutPlugin: диск 'М' 300.0° → пропуск: уверенность ниже порога (М 0.30 < 0.50)"


# --- харнес ------------------------------------------------------------------


def _make(cfg: dict | None = None) -> tuple[WordLayoutPlugin, MockProcessServices]:
    """Настоящий WordLayoutPlugin со словом ПЕРЕМИРИЕ, min_confidence и require_pick — по умолчанию."""
    conf = dict(_BASE)
    conf.update(cfg or {})
    services = MockProcessServices(name="layout", config=conf)
    plugin = WordLayoutPlugin()
    plugin.configure(PluginContext(services=services, config=conf))
    return plugin, services


def _disc(
    label: str,
    tid: object | None = 1,
    angle: float = 0.0,
    *,
    confidence: float = 0.9,
    below: bool | None = None,
) -> dict:
    """Item диска: top-1 предсказание + sidecar.track_id (если tid) + pick_xy.

    ``below`` None — ключа ``below_threshold`` нет вовсе (старый продюсер)."""
    pred: dict = {"label": label, "confidence": confidence, "angle_deg": angle, "angle_valid": True}
    if below is not None:
        pred["below_threshold"] = below
    item: dict = {"predictions": [pred], "pick_xy": dict(_PICK)}
    if tid is not None:
        item["sidecar"] = {"track_id": tid}
    return item


def _weak(tid: object | None = 1, *, label: str = "М", confidence: float = 0.3, angle: float = 300.0) -> dict:
    """Слабый диск: уверенность ниже порога, below_threshold=True."""
    return _disc(label, tid, angle, confidence=confidence, below=True)


def _lines(services: MockProcessServices) -> list[str]:
    """Строки журнала «диск '<буква>' ...» (по одной на диск)."""
    return [e["msg"] for e in services.logs if "диск '" in e["msg"]]


def _run(p: WordLayoutPlugin, item: dict) -> dict:
    return p.process([item])[0]


# --- RED 1: слабый диск с track_id -------------------------------------------


def test_weak_disc_with_tid_leaves_one_literal_line() -> None:
    """Диск М 0.3, below_threshold=True, tid 1 -> ровно одна строка-литерал «уверенность ниже порога»."""
    p, s = _make()
    _run(p, _weak(1))
    assert _lines(s) == [_BELOW_M_30]


def test_weak_disc_with_tid_emits_no_job_and_fills_no_slot() -> None:
    """Слабый диск: в выходе нет ключа robot_job, jobs_emitted == 0, slots_filled == 0."""
    p, _ = _make()
    out = _run(p, _weak(1))
    assert "robot_job" not in out
    assert p._reg.jobs_emitted == 0
    assert p._reg.slots_filled == 0


# --- RED 2: причина зависит от того, кто признал диск слабым -------------------


def test_weak_below_own_min_confidence_line_has_numeric_threshold() -> None:
    """2а: 0.4 < min_confidence 0.5, флаг False -> в скобках числовой порог 0.50."""
    p, s = _make()
    out = _run(p, _disc("М", 1, 300.0, confidence=0.4, below=False))
    assert _lines(s) == ["WordLayoutPlugin: диск 'М' 300.0° → пропуск: уверенность ниже порога (М 0.40 < 0.50)"]
    assert "robot_job" not in out
    assert p._reg.jobs_emitted == 0


def test_weak_flag_only_line_says_ml_inference_threshold() -> None:
    """2б: 0.6 >= min_confidence 0.5, но below_threshold=True (порог ml выше) -> «< порог ml_inference»."""
    p, s = _make()
    out = _run(p, _disc("М", 1, 300.0, confidence=0.6, below=True))
    assert _lines(s) == [
        "WordLayoutPlugin: диск 'М' 300.0° → пропуск: уверенность ниже порога (М 0.60 < порог ml_inference)"
    ]
    assert "robot_job" not in out
    assert p._reg.jobs_emitted == 0


# --- RED 3: один track_id на много слабых кадров = одна строка ----------------


def test_same_tid_five_weak_frames_one_line() -> None:
    """Тот же track_id на 5 подряд слабых кадрах (свежий dict каждый раз) -> одна строка, не пять."""
    p, s = _make()
    for _ in range(5):
        _run(p, _weak(1))
    assert _lines(s) == [_BELOW_M_30]
    assert p._reg.jobs_emitted == 0


def test_same_item_object_five_times_one_line() -> None:
    """Один и тот же объект item 5 раз -> одна строка."""
    p, s = _make()
    item = _weak(1)
    for _ in range(5):
        _run(p, item)
    assert _lines(s) == [_BELOW_M_30]


# --- RED 4: три диска подряд, слабый в середине --------------------------------


def test_three_discs_weak_in_middle_three_lines_in_order() -> None:
    """Р 0.9 (tid 1) -> М 0.3 слабый (tid 2) -> Е 0.9 (tid 3): три строки по порядку, 2 задания."""
    p, s = _make()
    _run(p, _disc("Р", 1, 0.0, confidence=0.9, below=False))
    _run(p, _weak(2))
    _run(p, _disc("Е", 3, 0.0, confidence=0.9, below=False))
    lines = _lines(s)
    assert len(lines) == 3
    assert "→ ячейка 2:" in lines[0]
    assert "→ пропуск: уверенность ниже порога (М 0.30 < 0.50)" in lines[1]
    assert "→ ячейка 1:" in lines[2]
    assert p._reg.jobs_emitted == 2


def test_weak_disc_does_not_burn_slot_for_next_confident_disc() -> None:
    """Слабая М между дисками не занимает ячейку: заполнено 2 из 9, ячейка 4 (М) остаётся свободной."""
    p, _ = _make()
    _run(p, _disc("Р", 1, 0.0, confidence=0.9, below=False))
    _run(p, _weak(2))
    _run(p, _disc("Е", 3, 0.0, confidence=0.9, below=False))
    assert p._reg.slots_filled == 2


# --- RED 5: нет предсказания ---------------------------------------------------


def test_empty_predictions_with_tid_leaves_one_line() -> None:
    """Item с predictions == [] и tid -> строка «диск '?' 0.0° → пропуск: нет предсказания»."""
    p, s = _make()
    out = _run(p, {"predictions": [], "sidecar": {"track_id": 7}, "pick_xy": dict(_PICK)})
    assert _lines(s) == ["WordLayoutPlugin: диск '?' 0.0° → пропуск: нет предсказания"]
    assert "robot_job" not in out
    assert p._reg.jobs_emitted == 0


def test_empty_predictions_same_tid_again_still_one_line() -> None:
    """Тот же item (тот же tid) повторно -> по-прежнему одна строка."""
    p, s = _make()
    item = {"predictions": [], "sidecar": {"track_id": 7}, "pick_xy": dict(_PICK)}
    _run(p, item)
    _run(p, item)
    assert _lines(s) == ["WordLayoutPlugin: диск '?' 0.0° → пропуск: нет предсказания"]


# --- Контроли (зелёные и сейчас, и после) --------------------------------------


def test_control_weak_frame_without_tid_leaves_no_disc_line() -> None:
    """Контроль: слабый кадр БЕЗ sidecar/track_id — не диск, строки «диск '...» нет."""
    p, s = _make()
    out = _run(p, _weak(None))
    assert _lines(s) == []
    assert "robot_job" not in out
    assert p._reg.jobs_emitted == 0


def test_control_confident_disc_with_tid_one_cell_line() -> None:
    """Контроль: уверенный диск Р 0.9 с tid -> одна строка «→ ячейка 2:», задание выдано."""
    p, s = _make()
    out = _run(p, _disc("Р", 1, 0.0, confidence=0.9, below=False))
    lines = _lines(s)
    assert len(lines) == 1
    assert "→ ячейка 2:" in lines[0]
    assert out["robot_job"]["slot"] == 2
    assert p._reg.jobs_emitted == 1


# --- RED 6: настоящая цепочка center_crop -> ml_inference -> word_layout --------

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
# require_pick False, как в test_ml_chain_c40.py: в цепочке нет источника pick_xy, на слабый диск он не влияет.
_WORD_CFG = {"require_pick": False, "word_source": "", "settle_frames": 1, "target_word": "ПЕРЕМИРИЕ"}
_PASS_XS = (260, 298, 336, 374, 412, 450, 488)
_LABELS = ["Р", "М", "Е"]


class _WeakTopMBackend(BaseInferenceBackend):
    """Заглушка backend: вероятности [Р 0.3, М 0.4, Е 0.3] на любой вход — топ-1 М с 0.40 (< порога 0.5)."""

    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        self._spec = spec

    def infer(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        p = np.array([0.3, 0.4, 0.3], dtype=np.float64)
        return {"logits": np.log(p).astype(np.float32)[None, :]}

    def unload(self) -> None:
        self._spec = None


def _mk(cls: type, cfg: dict):
    plugin = cls()
    plugin.configure(PluginContext(services=MockProcessServices(name="x", config=cfg), config=cfg))
    return plugin


def _make_ml(tmp_path: Path) -> MLInferencePlugin:
    """Настоящий MLInferencePlugin (порог 0.5) с подменённым backend — как в test_ml_chain_c40.py."""
    ctx = MagicMock()
    ctx.config = {
        "models_dir": str(tmp_path),
        "model": "fake",
        "confidence_threshold": 0.5,
        "top_k": 3,
        "draw_overlay": False,
    }
    ctx.registers = None
    ctx.state_proxy = None
    ctx.process_name = "ml_proc"
    plugin = MLInferencePlugin()
    plugin.configure(ctx)
    spec = ModelSpec(name="fake", weights_path=tmp_path / "fake.onnx", input_size=(32, 32))
    backend = _WeakTopMBackend()
    backend.load(spec)
    plugin._engine._backend = backend
    plugin._engine._spec = spec
    plugin._engine._labels = list(_LABELS)
    return plugin


def test_real_chain_weak_top1_leaves_one_layout_line(tmp_path: Path) -> None:
    """line_filter -> center_crop -> ml_inference (топ-1 М 0.40 < 0.5) -> word_layout: одна строка слабого диска."""
    line = _mk(LineFilterPlugin, _LINE_CFG)
    crop = _mk(CenterCropPlugin, _CROP_CFG)
    ml = _make_ml(tmp_path)
    services = MockProcessServices(name="layout", config=_WORD_CFG)
    word = WordLayoutPlugin()
    word.configure(PluginContext(services=services, config=_WORD_CFG))

    frame = np.full((481, 800, 3), 120, np.uint8)
    outs: list[dict] = []

    def feed(dets: list[dict], seq: int) -> None:
        ov = line.process([{"detections": dets, "seq_id": seq}])[0]
        crops = crop.process([{"frame": frame, "filtered": ov["filtered"], "detections": dets, "seq_id": seq}])
        recognised = ml.process(crops) if crops else []
        outs.extend(word.process([r])[0] for r in recognised)

    seq = 0
    for _ in range(2):  # защёлка line_filter взводится rearm_frames пустых кадров
        seq += 1
        feed([], seq)
    for x in _PASS_XS:  # один диск проходит зону: событие только на входе
        seq += 1
        feed([{"center": [x, 262], "radius": 40}], seq)

    assert len(outs) == 1, "цепочка должна довести до word_layout ровно один распознанный диск"
    top = outs[0]["predictions"][0]
    assert (top["label"], top["below_threshold"]) == ("М", True), "заглушка должна дать слабый топ-1 М"
    assert "robot_job" not in outs[0]
    assert word._reg.jobs_emitted == 0

    lines = _lines(services)
    assert len(lines) == 1
    assert lines[0].startswith("WordLayoutPlugin: диск 'М' ")
    assert "→ пропуск: уверенность ниже порога (М " in lines[0]
    assert lines[0].endswith("< 0.50)")


@pytest.mark.parametrize("tid", [1, "a-7"])
def test_weak_disc_tid_types(tid: object) -> None:
    """Идентификатор диска — любой хэшируемый (int/str): строка слабого диска одна и для него."""
    p, s = _make()
    _run(p, _weak(tid))
    _run(p, _weak(tid))
    assert _lines(s) == [_BELOW_M_30]
