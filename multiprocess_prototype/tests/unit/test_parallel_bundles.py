"""Unit-тесты для detect_parallel_bundles() (Phase 5b)."""

from __future__ import annotations

import sys
from pathlib import Path

# Добавляем multiprocess_prototype/ в sys.path для коротких импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

import pytest

from registers.pipeline.processing_node import (  # noqa: E402
    NodeInput,
    ProcessingNode,
)
from services.processor.chain.parallel import (  # noqa: E402
    detect_parallel_bundles,
)
from services.processor.chain.runnable import (  # noqa: E402
    RunnableStep,
)
from services.processor.operations.base import ChainContext  # noqa: E402


# ---------------------------------------------------------------------------
# Mock-операция: минимальная реализация протокола ProcessingOperation
# ---------------------------------------------------------------------------

class MockOp:
    """Заглушка операции — просто возвращает кадр без изменений."""

    def execute(self, frame, context: ChainContext):
        return frame

    def configure(self, params: dict) -> None:
        pass


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _make_step(node: ProcessingNode, on_error: str = "skip") -> RunnableStep:
    """Создать RunnableStep с mock-операцией."""
    return RunnableStep(node=node, operation=MockOp(), on_error=on_error)


def _make_node(
    node_id: str,
    sources: list[str] | None = None,
    worker_id: str | None = None,
) -> ProcessingNode:
    """Создать ProcessingNode с заданным node_id и опциональными входами."""
    inputs = [NodeInput(source=s) for s in (sources or [])]
    return ProcessingNode(
        node_id=node_id,
        operation_ref="mock_op",
        inputs=inputs,
        worker_id=worker_id,
    )


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def test_empty_steps_returns_empty_list():
    """Пустой список шагов → пустой список бандлов."""
    result = detect_parallel_bundles([], {})
    assert result == []


def test_single_node_returns_one_bundle_with_one_step():
    """Одна нода → ровно 1 бандл с 1 шагом."""
    node = _make_node("A")
    step = _make_step(node)
    nodes = {"A": node}

    bundles = detect_parallel_bundles([step], nodes)

    assert len(bundles) == 1
    assert len(bundles[0]) == 1
    assert bundles[0][0] is step


def test_linear_chain_abc_gives_three_bundles():
    """Линейная цепочка A→B→C: каждая нода на отдельном уровне → 3 бандла по 1 шагу."""
    node_a = _make_node("A")
    node_b = _make_node("B", sources=["A"])
    node_c = _make_node("C", sources=["B"])

    step_a = _make_step(node_a)
    step_b = _make_step(node_b)
    step_c = _make_step(node_c)

    nodes = {"A": node_a, "B": node_b, "C": node_c}
    # Topological order: A, B, C
    bundles = detect_parallel_bundles([step_a, step_b, step_c], nodes)

    assert len(bundles) == 3
    # Каждый бандл содержит ровно 1 шаг
    assert all(len(b) == 1 for b in bundles)
    # Порядок должен соответствовать уровням: A(0), B(1), C(2)
    assert bundles[0][0] is step_a
    assert bundles[1][0] is step_b
    assert bundles[2][0] is step_c


def test_dag_two_independent_inputs_merged_into_one_bundle():
    """DAG: A→C, B→C. A и B независимы (уровень 0) → bundle[0]=[A,B], bundle[1]=[C]."""
    node_a = _make_node("A")
    node_b = _make_node("B")
    node_c = _make_node("C", sources=["A", "B"])

    step_a = _make_step(node_a)
    step_b = _make_step(node_b)
    step_c = _make_step(node_c)

    nodes = {"A": node_a, "B": node_b, "C": node_c}
    # Topological order: A, B затем C
    bundles = detect_parallel_bundles([step_a, step_b, step_c], nodes)

    # Должно быть 2 бандла: [A, B] (уровень 0) и [C] (уровень 1)
    assert len(bundles) == 2

    # Первый бандл содержит A и B
    first_bundle_steps = set(id(s) for s in bundles[0])
    assert id(step_a) in first_bundle_steps
    assert id(step_b) in first_bundle_steps

    # Второй бандл содержит C
    assert len(bundles[1]) == 1
    assert bundles[1][0] is step_c


def test_different_worker_id_splits_bundle():
    """Ноды на одном уровне с разными явными worker_id → разные бандлы."""
    # A и B на уровне 0, но с разными worker_id
    node_a = _make_node("A", worker_id="w1")
    node_b = _make_node("B", worker_id="w2")

    step_a = _make_step(node_a)
    step_b = _make_step(node_b)

    nodes = {"A": node_a, "B": node_b}
    bundles = detect_parallel_bundles([step_a, step_b], nodes)

    # Разные worker_id → разные бандлы (не объединяются)
    assert len(bundles) == 2
    # Каждый бандл содержит ровно 1 шаг
    assert all(len(b) == 1 for b in bundles)


def test_same_worker_id_stays_in_one_bundle():
    """Ноды на одном уровне с одинаковым worker_id → один бандл."""
    node_a = _make_node("A", worker_id="w1")
    node_b = _make_node("B", worker_id="w1")

    step_a = _make_step(node_a)
    step_b = _make_step(node_b)

    nodes = {"A": node_a, "B": node_b}
    bundles = detect_parallel_bundles([step_a, step_b], nodes)

    # Одинаковый worker_id → один бандл с обоими шагами
    assert len(bundles) == 1
    assert len(bundles[0]) == 2


def test_none_worker_id_nodes_merged_freely():
    """Ноды с worker_id=None на одном уровне объединяются в один бандл."""
    node_a = _make_node("A")   # worker_id=None
    node_b = _make_node("B")   # worker_id=None

    step_a = _make_step(node_a)
    step_b = _make_step(node_b)

    nodes = {"A": node_a, "B": node_b}
    bundles = detect_parallel_bundles([step_a, step_b], nodes)

    # Оба с worker_id=None → один общий бандл
    assert len(bundles) == 1
    assert len(bundles[0]) == 2


def test_bundle_order_preserves_topological_levels():
    """Бандлы упорядочены по уровням: level 0 идёт раньше level 1."""
    node_a = _make_node("A")
    node_b = _make_node("B", sources=["A"])

    step_a = _make_step(node_a)
    step_b = _make_step(node_b)

    nodes = {"A": node_a, "B": node_b}
    bundles = detect_parallel_bundles([step_a, step_b], nodes)

    # Level 0 (A) должен идти первым
    assert bundles[0][0].node.node_id == "A"
    assert bundles[1][0].node.node_id == "B"
