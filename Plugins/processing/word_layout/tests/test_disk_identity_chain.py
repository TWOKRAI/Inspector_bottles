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
    # C-42: zone_edge помнит место пропажи; значения — как в рецепте letter_robot_sim.yaml.
    "max_match_distance": 60,
    "max_age": 20,
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
# Физическая геометрия: линия angle=90 вертикальна, зона |x - 376| <= 125 (x в [251, 501]).
# Диск едет по x слева направо (шаг 38 px/кадр): входит у левого края (x=260), последний раз
# виден у правого (x=488). Новый диск снова входит слева: 228 px от места выхода прежнего
# (> max_match_distance=60) — это новый диск, а не повторное появление прежнего.
_PASS_XS = (260, 298, 336, 374, 412, 450, 488)


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
    for _ in range(2):  # C-42/О1: защёлка стартует закрытой, взводится rearm_frames пустых кадров
        seq += 1
        feed([], seq, "Р")
    for label in ("Р", "Р", "Е"):
        for x in _PASS_XS:  # диск проходит зону: событие только на входе
            seq += 1
            for out in feed([{"center": [x, 262], "radius": 40}], seq, label):
                tids.append(out["sidecar"].get("track_id"))
                slots.append(out["robot_job"]["slot"] if out.get("robot_job") else None)
        for _ in range(2):  # пустые кадры >= rearm_frames: line_filter взводится заново
            seq += 1
            feed([], seq, label)

    assert slots == [2, 6, 1]
    # Достижимость: цепочка действительно дала три разных события (тест не проходит вхолостую).
    assert len(tids) == 3
    assert len(set(tids)) == 3


def test_real_chain_loss_inside_zone_one_disc_one_slot() -> None:
    """C-42: потеря детекции на 3 кадра внутри зоны (> rearm_frames=2) — тот же диск: один track_id, одно задание.

    Диск едет по x с шагом 6 px/кадр (физика ленты ~6.6): v × (L + 1) = 24 px <= max_match_distance=60.
    До правки второе событие давало track_id 2 и второе задание на слот 6.
    """
    line = _mk(LineFilterPlugin, _LINE_CFG)
    crop = _mk(CenterCropPlugin, _CROP_CFG)
    word = _mk(WordLayoutPlugin, _WORD_CFG)
    frame = np.zeros((481, 800, 3), np.uint8)
    lost = {357, 363, 369}  # три кадра подряд без детекции, середина прохода

    tids: list[object] = []
    slots: list[int | None] = []
    seq = 0
    for x in [None, None, *range(255, 500, 6)]:  # два пустых кадра взвода (О1), затем проход зоны x в [251, 501]
        seq += 1
        dets = [] if x is None or x in lost else [{"center": [x, 262], "radius": 40}]
        ov = line.process([{"detections": dets, "seq_id": seq}])[0]
        crops = crop.process([{"frame": frame, "filtered": ov["filtered"], "detections": dets, "seq_id": seq}])
        pred = {"label": "Р", "confidence": 0.9, "angle_deg": 0.0, "angle_valid": True}
        for c in crops:
            out = word.process([{**c, "predictions": [pred]}])[0]
            tids.append(out["sidecar"].get("track_id"))
            slots.append(out["robot_job"]["slot"] if out.get("robot_job") else None)

    assert 357 in range(255, 500, 6) and 369 in range(255, 500, 6)  # потеря действительно внутри прохода
    assert tids == [1]
    assert slots == [2]
