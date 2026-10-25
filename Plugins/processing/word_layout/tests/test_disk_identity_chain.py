"""C-32: цепочка на РЕАЛЬНЫХ плагинах line_filter(zone_edge) -> center_crop -> word_layout.

Конфиги line_filter и center_crop — литералами из ``multiprocess_prototype/recipes/letter_robot_sim.yaml``
(процессы ``line`` и ``recog``). Распознавание не нужно: ``predictions`` дописываются к item от center_crop.
Ячейки «ПЕРЕМИРИЕ»: П0 Е1 Р2 Е3 М4 И5 Р6 И7 Е8.
"""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.filter.line_filter.plugin import LineFilterPlugin
from Plugins.processing.center_crop.plugin import CenterCropPlugin
from Plugins.processing.word_layout.plugin import WordLayoutPlugin

_LINE_CFG = {
    "center_x": 376,
    "center_y": 262,
    "angle": 90,
    "zone_width": 250,
    "mode": "zone_edge",
    "rearm_frames": 2,
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
_DET = {"center": [376, 262], "radius": 40}  # диск в зоне линии


def _mk(cls: type, cfg: dict):
    plugin = cls()
    plugin.configure(PluginContext(services=MockProcessServices(name="x", config=cfg), config=cfg))
    return plugin


def test_real_chain_two_same_letters_two_cells() -> None:
    line = _mk(LineFilterPlugin, _LINE_CFG)
    crop = _mk(CenterCropPlugin, _CROP_CFG)
    word = _mk(WordLayoutPlugin, _WORD_CFG)
    frame = np.zeros((481, 800, 3), np.uint8)

    def feed(dets: list[dict], seq: int, label: str) -> list[dict]:
        """Один кадр: line_filter -> center_crop -> predictions -> word_layout. Вернуть выход word_layout."""
        ov = line.process([{"detections": dets, "seq_id": seq}])[0]
        crops = crop.process([{"frame": frame, "filtered": ov["filtered"], "detections": dets, "seq_id": seq}])
        pred = {"label": label, "confidence": 0.9, "angle_deg": 0.0, "angle_valid": True}
        return [word.process([{**c, "predictions": [pred]}])[0] for c in crops]

    tids: list[object] = []
    slots: list[int | None] = []
    seq = 0
    for label in ("Р", "Р", "Е"):
        for _ in range(3):  # диск несколько кадров в зоне: событие только на входе
            seq += 1
            for out in feed([_DET], seq, label):
                tids.append(out["sidecar"].get("track_id"))
                slots.append(out["robot_job"]["slot"] if out.get("robot_job") else None)
        for _ in range(2):  # пустые кадры >= rearm_frames: line_filter взводится заново
            seq += 1
            feed([], seq, label)

    assert slots == [2, 6, 1]
    # Достижимость: цепочка действительно дала три разных события (тест не проходит вхолостую).
    assert len(tids) == 3
    assert len(set(tids)) == 3
