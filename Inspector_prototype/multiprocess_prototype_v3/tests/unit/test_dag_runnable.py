"""Unit-тесты для DagRunnable (Task 8.2)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

# Добавляем multiprocess_prototype_v3/ в sys.path для коротких импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
_V3_ROOT_STR = str(_V3_ROOT)
if _V3_ROOT_STR not in sys.path:
    sys.path.insert(0, _V3_ROOT_STR)

from multiprocess_prototype_v3.registers.pipeline.processing_node import (  # noqa: E402
    NodeInput,
    ProcessingNode,
)
from multiprocess_prototype_v3.services.processor.chain.dag_runnable import (  # noqa: E402
    DagRunnable,
)
from multiprocess_prototype_v3.services.processor.chain.runnable import (  # noqa: E402
    RunnableStep,
)
from multiprocess_prototype_v3.services.processor.operations.base import (  # noqa: E402
    ChainContext,
    execute_dag_default,
)

# ---------------------------------------------------------------------------
# Фейковые операции для тестирования
# ---------------------------------------------------------------------------


class FakeBrightnessOp:
    """Увеличивает яркость кадра на 10 (clipped)."""

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        return np.clip(frame.astype(np.int16) + 10, 0, 255).astype(np.uint8)

    def configure(self, params: dict) -> None:
        pass


class FakeInvertOp:
    """Инвертирует кадр (255 - pixel)."""

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        return (255 - frame).astype(np.uint8)

    def configure(self, params: dict) -> None:
        pass


class FakeMaskOp:
    """Создаёт маску (пороговая бинаризация по первому каналу)."""

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        gray = frame[:, :, 0] if len(frame.shape) == 3 else frame
        return (gray > 128).astype(np.uint8) * 255

    def configure(self, params: dict) -> None:
        pass


class FakeMergeOp:
    """DAG-native операция: merge двух входов (image_in + mask_in → out)."""

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        # Legacy fallback — не используется в DAG
        return frame

    def configure(self, params: dict) -> None:
        pass

    def execute_dag(self, inputs: dict[str, Any], context: ChainContext) -> dict[str, Any]:
        """Накладывает маску на изображение."""
        image = inputs.get("image_in")
        mask = inputs.get("mask_in")
        if image is None:
            return {"out": np.zeros((10, 10, 3), dtype=np.uint8)}
        if mask is None:
            return {"out": image}
        # Применяем маску: зануляем пиксели где mask == 0
        result = image.copy()
        mask_3ch = np.stack([mask, mask, mask], axis=-1) if len(mask.shape) == 2 else mask
        result[mask_3ch == 0] = 0
        return {"out": result}


class FakeFailOp:
    """Операция, которая всегда падает."""

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        raise RuntimeError("Тестовая ошибка")

    def configure(self, params: dict) -> None:
        pass


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _test_frame(value: int = 100) -> np.ndarray:
    """Создать тестовый кадр 10x10 BGR."""
    return np.full((10, 10, 3), value, dtype=np.uint8)


def _make_step(
    node_id: str,
    operation: Any,
    inputs: list[NodeInput] | None = None,
    on_error: str = "skip",
    enabled: bool = True,
) -> RunnableStep:
    """Создать RunnableStep для тестирования."""
    node = ProcessingNode(
        node_id=node_id,
        operation_ref="fake_op",
        inputs=inputs or [],
        enabled=enabled,
    )
    return RunnableStep(node=node, operation=operation, on_error=on_error)


# ---------------------------------------------------------------------------
# Тесты DagRunnable
# ---------------------------------------------------------------------------


class TestDagRunnableLinearFallback:
    """DagRunnable работает и с линейными графами (хотя builder предпочтёт ChainRunnable)."""

    def test_single_node(self):
        """Одна нода — применяется к кадру."""
        step = _make_step("a", FakeBrightnessOp())
        dag = DagRunnable(
            steps=[step],
            topology=["a"],
            node_inputs={"a": []},
        )

        frame = _test_frame(100)
        result = dag.execute(frame)

        assert not result.failed
        # Яркость +10 → 110
        assert result.frame[0, 0, 0] == 110

    def test_two_nodes_linear(self):
        """Линейный граф A→B через DagRunnable."""
        step_a = _make_step("a", FakeBrightnessOp())
        step_b = _make_step(
            "b",
            FakeInvertOp(),
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
        )
        dag = DagRunnable(
            steps=[step_a, step_b],
            topology=["a", "b"],
            node_inputs={
                "a": [],
                "b": [NodeInput(source="a", output_port="out", input_port="in")],
            },
        )

        frame = _test_frame(100)
        result = dag.execute(frame)

        assert not result.failed
        # 100 + 10 = 110, затем 255 - 110 = 145
        assert result.frame[0, 0, 0] == 145


class TestDagRunnableBranching:
    """Тесты ветвления 1→2 и merge 2→1."""

    def test_branch_and_merge(self):
        """DAG: A→{B,C}→D. A=brightness, B=invert, C=mask, D=merge."""
        step_a = _make_step("a", FakeBrightnessOp())
        step_b = _make_step(
            "b",
            FakeInvertOp(),
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
        )
        step_c = _make_step(
            "c",
            FakeMaskOp(),
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
        )
        step_d = _make_step(
            "d",
            FakeMergeOp(),
            inputs=[
                NodeInput(source="b", output_port="out", input_port="image_in"),
                NodeInput(source="c", output_port="out", input_port="mask_in"),
            ],
        )

        dag = DagRunnable(
            steps=[step_a, step_b, step_c, step_d],
            topology=["a", "b", "c", "d"],
            node_inputs={
                "a": [],
                "b": [NodeInput(source="a", output_port="out", input_port="in")],
                "c": [NodeInput(source="a", output_port="out", input_port="in")],
                "d": [
                    NodeInput(source="b", output_port="out", input_port="image_in"),
                    NodeInput(source="c", output_port="out", input_port="mask_in"),
                ],
            },
        )

        frame = _test_frame(100)
        result = dag.execute(frame)

        assert not result.failed
        assert result.frame.shape == (10, 10, 3)
        # a: 100+10=110, b: 255-110=145, c: mask(110) → 0 (110 < 128)
        # d: merge(145, mask=0) → все пиксели = 0 (маска зануляет)
        assert result.frame[0, 0, 0] == 0

    def test_branch_data_copied(self):
        """Ветвление 1→2: данные из A доступны обоим B и C."""
        step_a = _make_step("a", FakeBrightnessOp())
        step_b = _make_step(
            "b",
            FakeBrightnessOp(),
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
        )
        step_c = _make_step(
            "c",
            FakeInvertOp(),
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
        )

        dag = DagRunnable(
            steps=[step_a, step_b, step_c],
            topology=["a", "b", "c"],
            node_inputs={
                "a": [],
                "b": [NodeInput(source="a", output_port="out", input_port="in")],
                "c": [NodeInput(source="a", output_port="out", input_port="in")],
            },
        )

        frame = _test_frame(100)
        result = dag.execute(frame)

        assert not result.failed
        # Последняя нода — c: 255 - 110 = 145
        assert result.frame[0, 0, 0] == 145


class TestDagRunnableErrorHandling:
    """Тесты обработки ошибок в DAG."""

    def test_skip_error_continues(self):
        """on_error=skip — пропускает ошибочную ноду, продолжает."""
        step_a = _make_step("a", FakeBrightnessOp())
        step_b = _make_step(
            "b",
            FakeFailOp(),
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
            on_error="skip",
        )
        step_c = _make_step(
            "c",
            FakeInvertOp(),
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
        )

        dag = DagRunnable(
            steps=[step_a, step_b, step_c],
            topology=["a", "b", "c"],
            node_inputs={
                "a": [],
                "b": [NodeInput(source="a", output_port="out", input_port="in")],
                "c": [NodeInput(source="a", output_port="out", input_port="in")],
            },
        )

        frame = _test_frame(100)
        result = dag.execute(frame)

        assert not result.failed
        assert "b" in result.skipped_nodes
        # Последняя нода c выполнилась: 255 - 110 = 145
        assert result.frame[0, 0, 0] == 145

    def test_fail_region_stops_dag(self):
        """on_error=fail_region — прерывает DAG."""
        step_a = _make_step("a", FakeBrightnessOp())
        step_b = _make_step(
            "b",
            FakeFailOp(),
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
            on_error="fail_region",
        )
        step_c = _make_step(
            "c",
            FakeInvertOp(),
            inputs=[NodeInput(source="a", output_port="out", input_port="in")],
        )

        dag = DagRunnable(
            steps=[step_a, step_b, step_c],
            topology=["a", "b", "c"],
            node_inputs={
                "a": [],
                "b": [NodeInput(source="a", output_port="out", input_port="in")],
                "c": [NodeInput(source="a", output_port="out", input_port="in")],
            },
        )

        frame = _test_frame(100)
        result = dag.execute(frame)

        assert result.failed
        assert result.fail_level == "region"


class TestExecuteDagDefault:
    """Тесты для execute_dag_default."""

    def test_legacy_operation_wrapped(self):
        """Legacy execute() оборачивается: inputs["in"] → execute → {"out": result}."""
        op = FakeBrightnessOp()
        frame = _test_frame(100)
        ctx = ChainContext()

        outputs = execute_dag_default(op, {"in": frame}, ctx)

        assert "out" in outputs
        assert outputs["out"][0, 0, 0] == 110

    def test_dag_native_operation_called(self):
        """Операция с execute_dag — вызывается напрямую, не через legacy."""
        op = FakeMergeOp()
        image = _test_frame(200)
        mask = np.full((10, 10), 255, dtype=np.uint8)
        ctx = ChainContext()

        outputs = execute_dag_default(op, {"image_in": image, "mask_in": mask}, ctx)

        assert "out" in outputs
        # Маска вся 255 → изображение не изменилось
        assert outputs["out"][0, 0, 0] == 200

    def test_optional_input_none(self):
        """Опциональный вход = None — передаётся в операцию как есть."""
        op = FakeMergeOp()
        image = _test_frame(150)
        ctx = ChainContext()

        outputs = execute_dag_default(op, {"image_in": image, "mask_in": None}, ctx)

        assert "out" in outputs
        # mask=None → merge возвращает image без изменений
        assert outputs["out"][0, 0, 0] == 150


class TestDagRunnableProperties:
    """Тесты свойств DagRunnable."""

    def test_steps_readonly(self):
        """steps возвращает копию списка."""
        step = _make_step("a", FakeBrightnessOp())
        dag = DagRunnable(
            steps=[step],
            topology=["a"],
            node_inputs={"a": []},
        )
        steps = dag.steps
        steps.clear()
        # Оригинальный список не изменился
        assert len(dag.steps) == 1

    def test_processing_time_recorded(self):
        """processing_time записывается в результат."""
        step = _make_step("a", FakeBrightnessOp())
        dag = DagRunnable(
            steps=[step],
            topology=["a"],
            node_inputs={"a": []},
        )

        frame = _test_frame(100)
        result = dag.execute(frame)

        assert result.processing_time > 0
