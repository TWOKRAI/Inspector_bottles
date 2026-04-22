"""Unit-тесты для ChainThreadPool (Phase 5b)."""

from __future__ import annotations

import sys
import time
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
from services.processor.chain.runnable import (  # noqa: E402
    RunnableStep,
)
from services.processor.chain.thread_pool import (  # noqa: E402
    ChainThreadPool,
)
from services.processor.operations.base import ChainContext  # noqa: E402


# ---------------------------------------------------------------------------
# Mock-операции
# ---------------------------------------------------------------------------

class MockOp:
    """Заглушка: мгновенно возвращает кадр."""

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        return frame

    def configure(self, params: dict) -> None:
        pass


class SlowMockOp:
    """Медленная заглушка: засыпает на 20 секунд — для проверки timeout."""

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        time.sleep(20)
        return frame

    def configure(self, params: dict) -> None:
        pass


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _make_step(
    node_id: str = "test_node",
    op=None,
    on_error: str = "skip",
) -> RunnableStep:
    """Создать RunnableStep с заданной операцией."""
    node = ProcessingNode(node_id=node_id, operation_ref="mock_op")
    return RunnableStep(node=node, operation=op or MockOp(), on_error=on_error)


@pytest.fixture
def pool_2workers():
    """Пул потоков с 2 воркерами, timeout=5.0."""
    pool = ChainThreadPool(max_workers=2, step_timeout=5.0)
    yield pool
    pool.shutdown(wait=False)


@pytest.fixture
def frame_100():
    """Синтетический кадр 100x100 пикселей (чёрный)."""
    return np.zeros((100, 100, 3), dtype=np.uint8)


@pytest.fixture
def context():
    """Базовый ChainContext."""
    return ChainContext(camera_id="cam_test", region_id="r_test", seq_id=0)


# ---------------------------------------------------------------------------
# Тесты создания
# ---------------------------------------------------------------------------


def test_pool_created_with_correct_max_workers():
    """Пул создаётся с корректным max_workers."""
    pool = ChainThreadPool(max_workers=4)
    try:
        assert pool.max_workers == 4
    finally:
        pool.shutdown(wait=False)


def test_pool_created_with_correct_step_timeout():
    """Пул создаётся с корректным step_timeout."""
    pool = ChainThreadPool(max_workers=2, step_timeout=3.5)
    try:
        assert pool.step_timeout == pytest.approx(3.5)
    finally:
        pool.shutdown(wait=False)


def test_pool_default_max_workers():
    """Дефолтный max_workers=2."""
    pool = ChainThreadPool()
    try:
        assert pool.max_workers == 2
    finally:
        pool.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Тесты submit_bundle
# ---------------------------------------------------------------------------


def test_submit_bundle_returns_two_futures(pool_2workers, frame_100, context):
    """submit_bundle с 2 шагами возвращает 2 futures."""
    steps = [_make_step("node_1"), _make_step("node_2")]
    futures = pool_2workers.submit_bundle(steps, frame_100, context)

    assert len(futures) == 2


def test_submit_bundle_futures_complete(pool_2workers, frame_100, context):
    """Futures завершаются без исключений."""
    steps = [_make_step("node_1"), _make_step("node_2")]
    futures = pool_2workers.submit_bundle(steps, frame_100, context)

    # Ждём завершения с большим timeout
    for f in futures:
        result = f.result(timeout=5.0)
        assert result is not None


def test_submit_bundle_frame_copy_independence(pool_2workers, context):
    """Каждый step получает независимую копию кадра (изменение не влияет на соседей)."""
    original = np.zeros((50, 50, 3), dtype=np.uint8)
    original[10, 10] = [255, 0, 0]

    class ModifyingOp:
        """Операция, модифицирующая входной кадр."""
        def execute(self, frame, ctx):
            frame[:] = 0   # зануляем полностью
            return frame
        def configure(self, params):
            pass

    steps = [
        _make_step("n1", op=ModifyingOp()),
        _make_step("n2", op=ModifyingOp()),
    ]

    # Выполняем submit — каждый должен получить копию
    futures = pool_2workers.submit_bundle(steps, original, context)
    for f in futures:
        f.result(timeout=5.0)

    # Оригинальный кадр не должен быть изменён
    assert original[10, 10, 0] == 255


# ---------------------------------------------------------------------------
# Тесты collect_results
# ---------------------------------------------------------------------------


def test_collect_results_returns_list_of_step_result_pairs(pool_2workers, frame_100, context):
    """collect_results возвращает список пар (step, result) в правильном порядке."""
    step_1 = _make_step("node_1")
    step_2 = _make_step("node_2")
    steps = [step_1, step_2]

    futures = pool_2workers.submit_bundle(steps, frame_100, context)
    results = pool_2workers.collect_results(futures, steps)

    assert len(results) == 2
    # Порядок должен совпадать со steps
    assert results[0][0] is step_1
    assert results[1][0] is step_2


def test_collect_results_normal_returns_ndarray(pool_2workers, frame_100, context):
    """Успешное завершение → result является numpy array."""
    steps = [_make_step("node_1")]
    futures = pool_2workers.submit_bundle(steps, frame_100, context)
    results = pool_2workers.collect_results(futures, steps)

    _, result = results[0]
    assert isinstance(result, np.ndarray)


def test_collect_results_timeout_returns_timeout_error():
    """Медленная операция при timeout=0.5 → TimeoutError в результате."""
    pool = ChainThreadPool(max_workers=2, step_timeout=0.5)
    try:
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        ctx = ChainContext()

        slow_step = _make_step("slow_node", op=SlowMockOp())
        steps = [slow_step]

        futures = pool.submit_bundle(steps, frame, ctx)
        results = pool.collect_results(futures, steps, timeout=0.5)

        assert len(results) == 1
        _, result = results[0]
        # Должен вернуть TimeoutError, а не выбросить
        assert isinstance(result, TimeoutError)
    finally:
        pool.shutdown(wait=False)


def test_collect_results_uses_step_timeout_by_default():
    """collect_results использует step_timeout пула при timeout=None."""
    pool = ChainThreadPool(max_workers=2, step_timeout=0.3)
    try:
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        ctx = ChainContext()

        slow_step = _make_step("slow_node", op=SlowMockOp())
        futures = pool.submit_bundle([slow_step], frame, ctx)
        # timeout=None → должен использовать pool.step_timeout=0.3
        results = pool.collect_results(futures, [slow_step], timeout=None)

        _, result = results[0]
        assert isinstance(result, TimeoutError)
    finally:
        pool.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Тесты resize
# ---------------------------------------------------------------------------


def test_resize_updates_max_workers():
    """resize() обновляет max_workers до нового значения."""
    pool = ChainThreadPool(max_workers=2)
    try:
        pool.resize(4)
        assert pool.max_workers == 4
    finally:
        pool.shutdown(wait=False)


def test_resize_new_pool_can_accept_tasks(frame_100, context):
    """После resize() пул принимает и выполняет новые задачи."""
    pool = ChainThreadPool(max_workers=2)
    pool.resize(3)

    try:
        steps = [_make_step("after_resize")]
        futures = pool.submit_bundle(steps, frame_100, context)
        results = pool.collect_results(futures, steps)

        _, result = results[0]
        assert isinstance(result, np.ndarray)
    finally:
        pool.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Тесты shutdown
# ---------------------------------------------------------------------------


def test_shutdown_completes_without_error():
    """shutdown() вызывается без исключений."""
    pool = ChainThreadPool(max_workers=2)
    # Не должно бросать исключений
    pool.shutdown(wait=True)


def test_shutdown_wait_false_completes_without_error():
    """shutdown(wait=False) вызывается без исключений."""
    pool = ChainThreadPool(max_workers=2)
    pool.shutdown(wait=False)
