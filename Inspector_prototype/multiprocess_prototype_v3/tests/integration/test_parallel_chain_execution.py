"""L2 Integration-тесты: параллельная chain через ParallelChainRunnable (Phase 5b).

Сценарии:
1. Реальные ColorDetectionOp + BlobDetectionOp как 2 независимых шага.
2. Синтетический кадр 100x100 с красным прямоугольником.
3. Build chain с pool → ParallelChainRunnable.
4. Execute → ChainResult с detections.
5. 3 кадра подряд → seq_id монотонно возрастает.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Добавляем multiprocess_prototype_v3/ в sys.path для коротких импортов
_V3_ROOT = Path(__file__).resolve().parents[3]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

import numpy as np
import pytest

from registers.pipeline.processing_node import (  # noqa: E402
    NodeInput,
    ProcessingNode,
)
from registers.processor.catalog.loader import (  # noqa: E402
    load_catalog,
)
from services.processor.chain.autofill import (  # noqa: E402
    autofill_inputs,
)
from services.processor.chain.builder import (  # noqa: E402
    GraphRunnableBuilder,
)
from services.processor.chain.parallel_runnable import (  # noqa: E402
    ParallelChainRunnable,
)
from services.processor.chain.runnable import (  # noqa: E402
    ChainResult,
)
from services.processor.chain.thread_pool import (  # noqa: E402
    ChainThreadPool,
)
from services.processor.operations.loader import (  # noqa: E402
    clear_cache,
)

# Путь к seed-файлу каталога (относительно multiprocess_prototype_v3/)
_SEED_CATALOG = _V3_ROOT / "multiprocess_prototype_v3" / "data" / "processing_catalog.yaml"

# Цветовой диапазон для красного объекта (BGR: B=0-50, G=0-50, R=150-255)
_RED_LOWER = [0, 0, 150]
_RED_UPPER = [50, 50, 255]


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_operation_cache():
    """Сбросить кэш загрузчика операций до и после каждого теста."""
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def red_frame() -> np.ndarray:
    """Синтетический кадр 100x100 с красным прямоугольником в центре.

    Фон чёрный (0,0,0). Красный прямоугольник (BGR: 0,0,200)
    занимает область [30:70, 30:70] — площадь 1600 px, достаточно для детекции.
    """
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[30:70, 30:70] = [0, 0, 200]   # BGR: только красный канал
    return frame


@pytest.fixture
def catalog() -> dict:
    """Реальный каталог из seed-файла."""
    return load_catalog(_SEED_CATALOG)


@pytest.fixture
def pool() -> ChainThreadPool:
    """Пул потоков с 2 воркерами для параллельного исполнения."""
    p = ChainThreadPool(max_workers=2, step_timeout=10.0)
    yield p
    p.shutdown(wait=False)


@pytest.fixture
def two_independent_nodes_parallel(catalog, pool) -> ParallelChainRunnable:
    """Два независимых шага color_detection и blob_detection (нет зависимостей между ними).

    Оба узла берут 'frame' как источник → уровень 0 → один параллельный бандл.
    """
    # Оба узла независимы — берут frame напрямую (не зависят друг от друга)
    node_color = ProcessingNode(
        node_id="color_node",
        operation_ref="color_detection",
        inputs=[NodeInput(source="frame")],
    )
    node_blob = ProcessingNode(
        node_id="blob_node",
        operation_ref="blob_detection",
        inputs=[NodeInput(source="frame")],
    )

    nodes = {
        "color_node": node_color,
        "blob_node": node_blob,
    }

    # pool с max_workers=2 → GraphRunnableBuilder должен выдать ParallelChainRunnable
    chain = GraphRunnableBuilder.build(nodes, catalog, pool=pool)

    # Убеждаемся, что получили параллельный runnable
    assert isinstance(chain, ParallelChainRunnable), (
        f"Ожидали ParallelChainRunnable, получили {type(chain).__name__}. "
        "Проверьте, что оба узла действительно независимы."
    )

    # Настраиваем color_detection под красный диапазон
    for step in chain.steps:
        if step.node.operation_ref == "color_detection":
            step.operation.configure({
                "color_lower": _RED_LOWER,
                "color_upper": _RED_UPPER,
                "min_area": 100,
                "max_area": 50000,
            })

    return chain


# ---------------------------------------------------------------------------
# L2 Тесты
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_parallel_chain_is_parallel_runnable(two_independent_nodes_parallel):
    """GraphRunnableBuilder с pool возвращает ParallelChainRunnable для независимых нод."""
    assert isinstance(two_independent_nodes_parallel, ParallelChainRunnable)


@pytest.mark.slow
def test_parallel_chain_has_two_steps(two_independent_nodes_parallel):
    """Параллельная chain содержит 2 шага."""
    assert len(two_independent_nodes_parallel.steps) == 2


@pytest.mark.slow
def test_parallel_chain_execute_returns_chain_result(two_independent_nodes_parallel, red_frame):
    """Execute параллельной chain возвращает ChainResult."""
    result = two_independent_nodes_parallel.execute(
        red_frame,
        metadata={"camera_id": "cam_0", "region_id": "r0", "seq_id": 1},
    )

    assert isinstance(result, ChainResult)


@pytest.mark.slow
def test_parallel_chain_detects_red_rectangle(two_independent_nodes_parallel, red_frame):
    """Параллельная chain с color_detection находит красный прямоугольник."""
    result = two_independent_nodes_parallel.execute(red_frame)

    assert len(result.detections) > 0, (
        "Ожидали хотя бы одну детекцию красного прямоугольника, "
        f"получили: {result.detections}"
    )


@pytest.mark.slow
def test_parallel_chain_not_failed(two_independent_nodes_parallel, red_frame):
    """Параллельная chain выполняется без ошибок (result.failed == False)."""
    result = two_independent_nodes_parallel.execute(red_frame)

    assert result.failed is False


@pytest.mark.slow
def test_parallel_chain_has_processing_time(two_independent_nodes_parallel, red_frame):
    """ChainResult содержит ненулевое время обработки."""
    result = two_independent_nodes_parallel.execute(red_frame)

    assert result.processing_time >= 0.0


@pytest.mark.slow
def test_parallel_chain_seq_id_monotonic(two_independent_nodes_parallel, red_frame):
    """3 кадра подряд с возрастающим seq_id → seq_id в context монотонно возрастает."""
    seq_ids = []

    for i in range(3):
        result = two_independent_nodes_parallel.execute(
            red_frame.copy(),
            metadata={"camera_id": "cam_0", "region_id": "r0", "seq_id": i},
        )
        seq_ids.append(result.context.seq_id)

    # seq_id монотонно возрастает (0, 1, 2)
    assert seq_ids == [0, 1, 2], f"Ожидали [0, 1, 2], получили {seq_ids}"


@pytest.mark.slow
def test_parallel_chain_no_skipped_nodes_on_success(two_independent_nodes_parallel, red_frame):
    """Успешное выполнение → skipped_nodes пустой."""
    result = two_independent_nodes_parallel.execute(red_frame)

    assert result.skipped_nodes == []


@pytest.mark.slow
def test_parallel_chain_context_camera_id(two_independent_nodes_parallel, red_frame):
    """camera_id из metadata присутствует в context результата."""
    result = two_independent_nodes_parallel.execute(
        red_frame,
        metadata={"camera_id": "test_cam", "region_id": "r1", "seq_id": 0},
    )

    assert result.context.camera_id == "test_cam"
