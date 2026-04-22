"""Unit-тесты для ParallelChainRunnable (Phase 5b)."""

from __future__ import annotations

import sys
from pathlib import Path

# Добавляем multiprocess_prototype_v3/ в sys.path для коротких импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

import numpy as np
import pytest

from registers.pipeline.processing_node import (  # noqa: E402
    NodeInput,
    ProcessingNode,
)
from services.processor.chain.parallel_runnable import (  # noqa: E402
    ParallelChainRunnable,
)
from services.processor.chain.runnable import (  # noqa: E402
    ChainResult,
    RunnableStep,
)
from services.processor.chain.thread_pool import (  # noqa: E402
    ChainThreadPool,
)
from services.processor.operations.base import ChainContext  # noqa: E402


# ---------------------------------------------------------------------------
# Mock-операции с побочными эффектами
# ---------------------------------------------------------------------------

class MockOp:
    """Простая заглушка: возвращает кадр без изменений."""

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        return frame

    def configure(self, params: dict) -> None:
        pass


class DetectingMockOp:
    """Операция с побочным эффектом: создаёт фиктивную детекцию при каждом вызове."""

    def __init__(self) -> None:
        self.last_detections: list[dict] = []
        self.call_count: int = 0

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        self.call_count += 1
        # Фиктивная детекция — bbox, center, area
        self.last_detections = [
            {"bbox": [0, 0, 10, 10], "center": [5, 5], "area": 100}
        ]
        return frame

    def configure(self, params: dict) -> None:
        pass


class FailingMockOp:
    """Операция, всегда бросающая исключение."""

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        raise RuntimeError("Симулированная ошибка операции")

    def configure(self, params: dict) -> None:
        pass


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _make_step(
    node_id: str,
    op=None,
    on_error: str = "skip",
    inputs: list | None = None,
) -> RunnableStep:
    """Создать RunnableStep с заданной операцией и node_id."""
    node_inputs = [NodeInput(source=s) for s in (inputs or [])]
    node = ProcessingNode(
        node_id=node_id,
        operation_ref="mock_op",
        inputs=node_inputs,
    )
    return RunnableStep(node=node, operation=op or MockOp(), on_error=on_error)


@pytest.fixture
def pool():
    """Пул потоков с 2 воркерами для тестов."""
    p = ChainThreadPool(max_workers=2, step_timeout=5.0)
    yield p
    p.shutdown(wait=False)


@pytest.fixture
def frame():
    """Синтетический кадр 50x50 (чёрный)."""
    return np.zeros((50, 50, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Тесты: оба шага параллельного бандла исполняются
# ---------------------------------------------------------------------------


def test_parallel_bundle_both_steps_executed(pool, frame):
    """2 параллельных шага в бандле — оба исполняются (call_count == 1 у каждой операции)."""
    op_a = DetectingMockOp()
    op_b = DetectingMockOp()

    step_a = _make_step("A", op=op_a)
    step_b = _make_step("B", op=op_b)

    # Один параллельный бандл с двумя шагами
    bundles = [[step_a, step_b]]
    runnable = ParallelChainRunnable(bundles=bundles, pool=pool)

    runnable.execute(frame)

    # Оба операции вызваны ровно по одному разу
    assert op_a.call_count == 1
    assert op_b.call_count == 1


# ---------------------------------------------------------------------------
# Тесты: слияние side results из обоих шагов
# ---------------------------------------------------------------------------


def test_parallel_bundle_side_results_merged(pool, frame):
    """Side results (detections) из обоих параллельных шагов попадают в ChainResult."""
    op_a = DetectingMockOp()
    op_b = DetectingMockOp()

    step_a = _make_step("A", op=op_a)
    step_b = _make_step("B", op=op_b)

    bundles = [[step_a, step_b]]
    runnable = ParallelChainRunnable(bundles=bundles, pool=pool)

    result = runnable.execute(frame)

    # Каждая операция создаёт по 1 детекции → итого 2
    assert isinstance(result, ChainResult)
    assert len(result.detections) == 2


# ---------------------------------------------------------------------------
# Тесты: обработка ошибок
# ---------------------------------------------------------------------------


def test_error_on_error_skip_chain_continues(pool, frame):
    """Шаг с on_error=skip при ошибке → chain не прерывается, failed=False."""
    failing_step = _make_step("fail_node", op=FailingMockOp(), on_error="skip")
    normal_step = _make_step("normal_node", op=MockOp(), on_error="skip")

    # Два последовательных бандла: сначала ошибочный (один шаг), затем нормальный
    bundles = [[failing_step], [normal_step]]
    runnable = ParallelChainRunnable(bundles=bundles, pool=pool)

    result = runnable.execute(frame)

    # chain не прерывается при on_error=skip
    assert result.failed is False
    # Ошибочная нода попадает в skipped_nodes
    assert "fail_node" in result.skipped_nodes


def test_error_on_error_fail_region_chain_breaks(pool, frame):
    """Шаг с on_error=fail_region при ошибке → chain прерывается, failed=True, fail_level=region."""
    failing_step = _make_step("fail_node", op=FailingMockOp(), on_error="fail_region")

    bundles = [[failing_step]]
    runnable = ParallelChainRunnable(bundles=bundles, pool=pool)

    result = runnable.execute(frame)

    assert result.failed is True
    assert result.fail_level == "region"


def test_error_in_parallel_bundle_on_error_skip(pool, frame):
    """Ошибка в параллельном бандле (2 шага, 1 падает) с on_error=skip → chain продолжается."""
    op_ok = DetectingMockOp()
    failing_op = FailingMockOp()

    good_step = _make_step("good_node", op=op_ok, on_error="skip")
    bad_step = _make_step("bad_node", op=failing_op, on_error="skip")

    bundles = [[good_step, bad_step]]
    runnable = ParallelChainRunnable(bundles=bundles, pool=pool)

    result = runnable.execute(frame)

    # chain не прерывается
    assert result.failed is False
    # bad_node пропущен
    assert "bad_node" in result.skipped_nodes
    # Детекция от хорошей операции попала в результат
    assert len(result.detections) >= 1


def test_error_in_parallel_bundle_on_error_fail_region(pool, frame):
    """Ошибка в параллельном бандле с on_error=fail_region → chain прерывается."""
    op_ok = MockOp()
    failing_op = FailingMockOp()

    good_step = _make_step("good_node", op=op_ok, on_error="skip")
    bad_step = _make_step("bad_node", op=failing_op, on_error="fail_region")

    bundles = [[good_step, bad_step]]
    runnable = ParallelChainRunnable(bundles=bundles, pool=pool)

    result = runnable.execute(frame)

    assert result.failed is True
    assert result.fail_level == "region"


# ---------------------------------------------------------------------------
# Тесты: один шаг в бандле → синхронное исполнение
# ---------------------------------------------------------------------------


def test_single_step_bundle_executes_synchronously(pool, frame):
    """Бандл с одним шагом выполняется синхронно — операция вызвана 1 раз."""
    op = DetectingMockOp()
    step = _make_step("single_node", op=op)

    # Один бандл с одним шагом
    bundles = [[step]]
    runnable = ParallelChainRunnable(bundles=bundles, pool=pool)

    result = runnable.execute(frame)

    # Операция вызвана один раз
    assert op.call_count == 1
    # Детекция присутствует в результате
    assert len(result.detections) == 1


def test_single_step_bundle_result_not_failed(pool, frame):
    """Бандл с одним успешным шагом → result.failed == False."""
    step = _make_step("single_node", op=MockOp())
    bundles = [[step]]
    runnable = ParallelChainRunnable(bundles=bundles, pool=pool)

    result = runnable.execute(frame)

    assert result.failed is False


# ---------------------------------------------------------------------------
# Тесты: свойство steps
# ---------------------------------------------------------------------------


def test_steps_property_returns_all_steps_flat(pool):
    """steps property возвращает все шаги из всех бандлов в плоском списке."""
    s1 = _make_step("A")
    s2 = _make_step("B")
    s3 = _make_step("C")

    bundles = [[s1, s2], [s3]]
    runnable = ParallelChainRunnable(bundles=bundles, pool=pool)

    all_steps = runnable.steps
    assert len(all_steps) == 3
    assert s1 in all_steps
    assert s2 in all_steps
    assert s3 in all_steps


# ---------------------------------------------------------------------------
# Тесты: ChainResult базовые поля
# ---------------------------------------------------------------------------


def test_execute_returns_chain_result(pool, frame):
    """execute() возвращает объект ChainResult."""
    step = _make_step("n1")
    runnable = ParallelChainRunnable(bundles=[[step]], pool=pool)

    result = runnable.execute(frame)

    assert isinstance(result, ChainResult)


def test_execute_result_has_processing_time(pool, frame):
    """ChainResult.processing_time >= 0."""
    step = _make_step("n1")
    runnable = ParallelChainRunnable(bundles=[[step]], pool=pool)

    result = runnable.execute(frame)

    assert result.processing_time >= 0.0


def test_execute_metadata_passed_to_context(pool, frame):
    """metadata из execute() попадает в context (camera_id, region_id, seq_id)."""
    step = _make_step("n1")
    runnable = ParallelChainRunnable(bundles=[[step]], pool=pool)

    result = runnable.execute(
        frame,
        metadata={"camera_id": "cam_99", "region_id": "zone_A", "seq_id": 42},
    )

    assert result.context.camera_id == "cam_99"
    assert result.context.region_id == "zone_A"
    assert result.context.seq_id == 42
