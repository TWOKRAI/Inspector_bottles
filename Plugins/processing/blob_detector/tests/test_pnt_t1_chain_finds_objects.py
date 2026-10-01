"""pipeline-node-timing T1 (PC-1): эталонная цепочка color_mask -> blob_detector находит объекты.

Слепые приёмочные тесты по контракту из плана (реализацию не читали):
- ColorMaskPlugin оставляет `frame` как есть и добавляет `mask` (uint8, (H, W), {0, 255});
- BlobDetectorPlugin при наличии `mask` того же размера ищет контуры на ней и сам цвет не порогует;
  без маски (или при несовпадении размера) работает по-старому; рисует на КОПИИ кадра.

Параметры плагинов берутся ЛИТЕРАЛЬНО из топологий inspection_full.yaml / inspection_basic.yaml.
"""

from __future__ import annotations

import statistics
import time
import warnings
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import yaml

from Plugins.processing.blob_detector.plugin import BlobDetectorPlugin
from Plugins.processing.color_mask.plugin import ColorMaskPlugin

_TOPOLOGY_DIR = Path(__file__).resolve().parents[4] / "multiprocess_prototype" / "backend" / "topology"

_H, _W = 1080, 1920
# (центр x, центр y, радиус): 3 колонки x 2 ряда, радиусы 60..110, не пересекаются.
_CIRCLES = [
    (320, 300, 60),
    (960, 300, 70),
    (1600, 300, 80),
    (320, 780, 90),
    (960, 780, 100),
    (1600, 780, 110),
]
_RED_BGR = (20, 20, 220)
_SERVICE_KEYS = {"plugin_class", "plugin_name", "category"}
_TIMING_BUDGET_MS = 5.0
_TIMING_RUNS = 50


def _make_mock_ctx(config: dict) -> MagicMock:
    """Mock PluginContext (как в test_plugin.py)."""
    ctx = MagicMock()
    ctx.config = config
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    return ctx


def _processor_params(topology: str) -> dict[str, dict]:
    """Параметры плагинов процесса `processor` из YAML топологии: {plugin_name: config}."""
    data = yaml.safe_load((_TOPOLOGY_DIR / topology).read_text(encoding="utf-8"))
    proc = next(p for p in data["processes"] if p["process_name"] == "processor")
    return {p["plugin_name"]: {k: v for k, v in p.items() if k not in _SERVICE_KEYS} for p in proc["plugins"]}


def _make_frame() -> np.ndarray:
    """1080p BGR: серый фон 120 и 6 залитых красных кругов."""
    frame = np.full((_H, _W, 3), 120, dtype=np.uint8)
    for cx, cy, r in _CIRCLES:
        cv2.circle(frame, (cx, cy), r, _RED_BGR, -1)
    return frame


def _color_mask(params: dict) -> ColorMaskPlugin:
    plugin = ColorMaskPlugin()
    plugin.configure(_make_mock_ctx(params))
    return plugin


def _blob(params: dict) -> BlobDetectorPlugin:
    plugin = BlobDetectorPlugin()
    plugin.configure(_make_mock_ctx(params))
    return plugin


def _run_chain(topology: str, frame: np.ndarray) -> list[dict]:
    params = _processor_params(topology)
    out = _color_mask(params["color_mask"]).process([{"frame": frame}])
    return _blob(params["blob_detector"]).process(out)


def _rect_mask(h: int, w: int) -> np.ndarray:
    """Маска с ОДНИМ прямоугольником 200x200 (значения 0/255, uint8, 2D)."""
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[100:300, 100:300] = 255
    return mask


def test_pnt_t1_full_chain_finds_six_objects():
    """inspection_full: color_mask -> blob_detector на кадре с 6 красными кругами -> 6 детекций."""
    result = _run_chain("inspection_full.yaml", _make_frame())

    assert len(result) == 1
    assert len(result[0]["detections"]) == 6


def test_pnt_t1_basic_chain_finds_six_objects():
    """inspection_basic: color_mask -> blob_detector на кадре с 6 красными кругами -> 6 детекций."""
    result = _run_chain("inspection_basic.yaml", _make_frame())

    assert len(result) == 1
    assert len(result[0]["detections"]) == 6


def test_pnt_t1_color_mask_keeps_frame_and_adds_binary_mask():
    """color_mask: frame не изменён, mask — uint8 (1080, 1920), {0,255}, площадь ~ площади кругов (+-2 %)."""
    frame = _make_frame()
    original = frame.copy()
    params = _processor_params("inspection_full.yaml")["color_mask"]

    result = _color_mask(params).process([{"frame": frame}])

    assert len(result) == 1
    out = result[0]
    assert np.array_equal(out["frame"], original)
    assert "mask" in out
    mask = out["mask"]
    assert mask.dtype == np.uint8
    assert mask.shape == (_H, _W)
    assert set(np.unique(mask).tolist()) <= {0, 255}

    # Эталонная площадь — независимый рисунок тех же кругов на пустом одноканальном холсте.
    ref = np.zeros((_H, _W), dtype=np.uint8)
    for cx, cy, r in _CIRCLES:
        cv2.circle(ref, (cx, cy), r, 255, -1)
    expected_area = int(np.count_nonzero(ref))
    assert abs(int(np.count_nonzero(mask)) - expected_area) <= 0.02 * expected_area


def test_pnt_t1_blob_detector_uses_upstream_mask_not_colours():
    """Маска с ОДНИМ прямоугольником, кадр с 6 красными кругами -> ровно 1 детекция (по маске, не по цвету)."""
    params = _processor_params("inspection_full.yaml")["blob_detector"]

    result = _blob(params).process([{"frame": _make_frame(), "mask": _rect_mask(_H, _W)}])

    assert len(result) == 1
    assert len(result[0]["detections"]) == 1


def test_pnt_t1_blob_detector_raw_frame_without_mask_finds_six():
    """Регресс старого пути: без маски детектор сам порогует цвет -> 6 (ожидается GREEN уже сейчас)."""
    params = _processor_params("inspection_full.yaml")["blob_detector"]

    result = _blob(params).process([{"frame": _make_frame()}])

    assert len(result) == 1
    assert len(result[0]["detections"]) == 6


def test_pnt_t1_draw_contours_does_not_modify_input_frame():
    """draw_contours: true — входной массив кадра после process не изменён (рисуем на копии).

    В эталонных топологиях рисование выключено (его делает render_overlay), поэтому
    включаем его здесь явно: свойство «рисуем на копии» нужно при любом значении в YAML.
    """
    params = {**_processor_params("inspection_full.yaml")["blob_detector"], "draw_contours": True}
    frame = _make_frame()
    before = frame.copy()

    _blob(params).process([{"frame": frame}])

    assert np.array_equal(frame, before)


def test_pnt_t1_chain_timing_within_budget_or_warns():
    """Медиана времени цепочки на эталонном кадре — информационно, бюджет не блокирует.

    Решение владельца 2026-10-01: порог 5 мс machine-dependent (ревью этой задачи получило 6.33 мс
    median на другой машине против 4.6 мс у лида), поэтому превышение — предупреждение, не red.
    Детекции проверяются литералом, чтобы тест не стал пустым при превышении бюджета.
    """
    params = _processor_params("inspection_full.yaml")
    color_mask = _color_mask(params["color_mask"])
    blob = _blob(params["blob_detector"])
    frame = _make_frame()

    def _run_once() -> list[dict]:
        return blob.process(color_mask.process([{"frame": frame.copy()}]))

    for _ in range(5):
        _run_once()

    samples_ms = []
    out = None
    for _ in range(_TIMING_RUNS):
        start = time.perf_counter()
        out = _run_once()
        samples_ms.append((time.perf_counter() - start) * 1000)

    assert len(out[0]["detections"]) == 6

    median_ms = statistics.median(samples_ms)
    if median_ms > _TIMING_BUDGET_MS:
        warnings.warn(
            f"цепочка inspection_full: median {median_ms:.2f} мс > бюджета {_TIMING_BUDGET_MS} мс "
            "(не блокирует, machine-dependent — см. docs/reviews/2026-10-01_task-T1-review.md); "
            "оптимизация color_mask (HSV) отложена до фреймворковых задач",
            UserWarning,
            stacklevel=1,
        )


def test_pnt_t1_mask_of_different_size_falls_back_to_own_thresholding():
    """Маска 540x960 при кадре 1080x1920 -> откат на собственный порог -> 6, без исключения."""
    params = _processor_params("inspection_full.yaml")["blob_detector"]

    result = _blob(params).process([{"frame": _make_frame(), "mask": _rect_mask(540, 960)}])

    assert len(result) == 1
    assert len(result[0]["detections"]) == 6
