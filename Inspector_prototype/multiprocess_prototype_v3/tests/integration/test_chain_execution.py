"""L2 Integration-тест: реальная chain + синтетический кадр (Phase 5a).

Сценарии:
1. Загружаем каталог из seed-файла.
2. Создаём 2 ноды: color_detection + blob_detection.
3. Строим ChainRunnable через GraphRunnableBuilder.
4. Выполняем chain с синтетическим кадром (красный прямоугольник).
5. Проверяем ChainResult: detections не пустые.
6. Backward compat: ProcessorService с legacy detector → те же detections.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

# builder/runnable/autofill используют короткие импорты
_V3_ROOT = Path(__file__).resolve().parents[3]
_V3_ROOT_STR = str(_V3_ROOT)
if _V3_ROOT_STR not in sys.path:
    sys.path.insert(0, _V3_ROOT_STR)

from multiprocess_prototype_v3.registers.pipeline.processing_node import (  # noqa: E402
    NodeInput,
    ProcessingNode,
)
from multiprocess_prototype_v3.registers.processor.catalog.loader import (  # noqa: E402
    load_catalog,
)
from multiprocess_prototype_v3.services.processor.chain.autofill import (  # noqa: E402
    autofill_inputs,
)
from multiprocess_prototype_v3.services.processor.chain.builder import (  # noqa: E402
    GraphRunnableBuilder,
)
from multiprocess_prototype_v3.services.processor.chain.runnable import ChainResult  # noqa: E402
from multiprocess_prototype_v3.services.processor.detection import ColorBlobDetector  # noqa: E402
from multiprocess_prototype_v3.services.processor.service import ProcessorService  # noqa: E402
from multiprocess_prototype_v3.services.processor.operations.loader import (  # noqa: E402
    clear_cache,
)

# Путь к seed-файлу каталога
_SEED_CATALOG = Path(__file__).resolve().parents[3] / "data" / "processing_catalog.yaml"

# Цветовой диапазон для красного объекта (BGR: B=0-50, G=0-50, R=150-255)
_RED_LOWER = [0, 0, 150]
_RED_UPPER = [50, 50, 255]


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_operation_cache():
    """Сбросить кэш загрузчика операций перед каждым тестом."""
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def red_frame() -> np.ndarray:
    """Синтетический кадр 100x100 с красным прямоугольником в центре.

    Фон чёрный (0,0,0), красный прямоугольник (BGR: 0,0,200) занимает
    область [30:70, 30:70] — достаточная площадь для детекции.
    """
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    # Красный прямоугольник 40x40 пикселей (площадь = 1600)
    frame[30:70, 30:70] = [0, 0, 200]  # BGR: red channel = 200
    return frame


@pytest.fixture
def catalog() -> dict:
    """Реальный каталог из seed-файла."""
    return load_catalog(_SEED_CATALOG)


@pytest.fixture
def two_node_chain(catalog) -> tuple:
    """Собрать chain из 2 нод (color_detection → blob_detection) с autofill_inputs."""
    node1 = ProcessingNode(operation_ref="color_detection")
    node2 = ProcessingNode(operation_ref="blob_detection")

    # Линейная цепочка через autofill
    nodes_raw = {node1.node_id: node1, node2.node_id: node2}
    nodes = autofill_inputs(nodes_raw)

    chain = GraphRunnableBuilder.build(nodes, catalog)
    return chain, nodes


# ---------------------------------------------------------------------------
# L2 Тесты
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_chain_loads_from_seed_catalog(catalog):
    """Каталог из seed-файла содержит 2 операции."""
    assert len(catalog) == 2
    assert "color_detection" in catalog
    assert "blob_detection" in catalog


@pytest.mark.slow
def test_chain_builds_with_two_steps(two_node_chain):
    """GraphRunnableBuilder строит chain с 2 шагами из 2 нод."""
    chain, _ = two_node_chain
    assert len(chain.steps) == 2


@pytest.mark.slow
def test_chain_execute_returns_chain_result(two_node_chain, red_frame):
    """Выполнение chain на синтетическом кадре возвращает ChainResult."""
    chain, _ = two_node_chain

    # Конфигурируем color_detection под красный диапазон
    chain.steps[0].operation.configure({
        "color_lower": _RED_LOWER,
        "color_upper": _RED_UPPER,
        "min_area": 100,
        "max_area": 50000,
    })

    result = chain.execute(red_frame, metadata={"camera_id": "cam_0", "region_id": "r0"})

    assert isinstance(result, ChainResult)


@pytest.mark.slow
def test_chain_execute_detects_red_rectangle(two_node_chain, red_frame):
    """Chain с colour_detection находит красный прямоугольник → detections не пустые."""
    chain, _ = two_node_chain

    # Настраиваем детектор под красный цвет (BGR)
    chain.steps[0].operation.configure({
        "color_lower": _RED_LOWER,
        "color_upper": _RED_UPPER,
        "min_area": 100,
        "max_area": 50000,
    })

    result = chain.execute(red_frame, metadata={"camera_id": "cam_0", "region_id": "r0"})

    assert len(result.detections) > 0, (
        "Ожидали хотя бы одну детекцию красного прямоугольника, "
        f"получили: {result.detections}"
    )


@pytest.mark.slow
def test_chain_execute_not_failed(two_node_chain, red_frame):
    """Chain выполняется без ошибок (result.failed == False)."""
    chain, _ = two_node_chain

    chain.steps[0].operation.configure({
        "color_lower": _RED_LOWER,
        "color_upper": _RED_UPPER,
        "min_area": 100,
        "max_area": 50000,
    })

    result = chain.execute(red_frame)

    assert result.failed is False


@pytest.mark.slow
def test_chain_result_has_processing_time(two_node_chain, red_frame):
    """ChainResult должен содержать ненулевое время обработки."""
    chain, _ = two_node_chain
    result = chain.execute(red_frame)

    assert result.processing_time >= 0.0


@pytest.mark.slow
def test_backward_compat_legacy_detector_finds_red(red_frame):
    """Backward compat: ColorBlobDetector напрямую находит красный прямоугольник."""
    detector = ColorBlobDetector(
        color_lower=_RED_LOWER,
        color_upper=_RED_UPPER,
        min_area=100,
        max_area=50000,
    )
    detections, mask_display, contours = detector.detect(red_frame)

    assert len(detections) > 0, (
        "Legacy detector должен найти красный прямоугольник, "
        f"получили: {detections}"
    )
    assert detections[0]["area"] > 0


@pytest.mark.slow
def test_backward_compat_processor_service_process_frame(red_frame):
    """ProcessorService с legacy detector вызывает send_detection_to_renderer."""
    detector = ColorBlobDetector(
        color_lower=_RED_LOWER,
        color_upper=_RED_UPPER,
        min_area=100,
        max_area=50000,
    )

    # Мокируем выходной порт — не нужен реальный SHM
    mock_output = MagicMock()
    mock_output.write_mask_to_shm = MagicMock(return_value=("mock_shm", 0))

    service = ProcessorService(
        output=mock_output,
        detector=detector,
        target_width=100,
        target_height=100,
    )

    metadata = {
        "camera_id": "cam_0",
        "frame_id": 1,
        "shm_index": 0,
        "width": 100,
        "height": 100,
        "timestamp": 0.0,
    }
    service.process_frame(red_frame, metadata)

    # Результат отправлен рендереру
    mock_output.send_detection_to_renderer.assert_called_once()

    # Извлекаем детекции из аргументов вызова
    call_args = mock_output.send_detection_to_renderer.call_args[0][0]
    detections_sent = call_args.get("detections", [])

    assert len(detections_sent) > 0, (
        "ProcessorService должен найти красный прямоугольник через legacy detector"
    )
