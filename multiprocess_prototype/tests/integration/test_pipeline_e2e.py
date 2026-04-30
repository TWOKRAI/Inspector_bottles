"""E2E smoke для Pipeline-runtime (Phase 9 финал — Task 9.14).

Проверяет:
  - Простой DAG (SimulatorInput → Resize) исполняется N итераций без исключений.
  - Финальный кадр имеет ожидаемые размеры (Resize.width × Resize.height).
  - Dtype кадра сохраняется (uint8) на всём протяжении цепочки.
  - Фейковый display-приёмник (callback) вызывается ровно N раз.
  - ResizeParams с width=0 бросает ValidationError (Pydantic min=16).
  - SimulatorInput (BGR) → ColorConvert (bgr2gray) → Resize: финальный кадр grayscale.
  - Pipeline-pydantic с DAG simulator_input → resize: validate_graph без ошибок.

Без QApplication / NodeGraphQt — runtime-уровень, headless-совместим.
"""

from __future__ import annotations

from typing import Callable
from unittest.mock import MagicMock

import numpy as np
import pytest
from pydantic import ValidationError

from multiprocess_prototype.services.processor.operations.base import ChainContext
from multiprocess_prototype.services.processor.operations.input.simulator_input_op import (
    SimulatorInputOp,
)
from multiprocess_prototype.services.processor.operations.preprocess.color_convert_op import (
    ColorConvertOp,
)
from multiprocess_prototype.services.processor.operations.preprocess.resize_op import ResizeOp
from multiprocess_prototype.registers.processor.processings.resize_params import ResizeParams

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

_N_FRAMES = 20
_INPUT_WIDTH = 320
_INPUT_HEIGHT = 240
_RESIZE_WIDTH = 160
_RESIZE_HEIGHT = 120


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def simulator_op() -> SimulatorInputOp:
    """SimulatorInputOp с параметрами 320×240."""
    op = SimulatorInputOp()
    op.configure({"width": _INPUT_WIDTH, "height": _INPUT_HEIGHT})
    yield op
    op.close()


@pytest.fixture
def resize_op() -> ResizeOp:
    """ResizeOp с параметрами 160×120, интерполяция linear."""
    op = ResizeOp()
    op.configure({"width": _RESIZE_WIDTH, "height": _RESIZE_HEIGHT, "interpolation": "linear"})
    return op


@pytest.fixture
def color_convert_bgr2gray_op() -> ColorConvertOp:
    """ColorConvertOp в режиме bgr2gray."""
    op = ColorConvertOp()
    op.configure({"mode": "bgr2gray"})
    return op


def _make_ctx() -> ChainContext:
    return ChainContext(camera_id="cam_e2e", region_id="reg_e2e")


# ---------------------------------------------------------------------------
# Кейс 1: Цепочка SimulatorInput → Resize, N=20 кадров
# ---------------------------------------------------------------------------


def test_simulator_to_resize_chain(simulator_op, resize_op):
    """SimulatorInput → Resize: 20 итераций без исключений, shape и dtype корректны.

    Проверяемые инварианты:
      - frame_out.shape[:2] == (120, 160) — Resize применён (cv2: rows=H, cols=W).
      - frame_out.dtype == uint8 — dtype не изменился.
      - Все 20 итераций прошли без исключения.
    """
    for i in range(_N_FRAMES):
        ctx = _make_ctx()
        ctx.seq_id = i

        dag_result = simulator_op.execute_dag({}, ctx)
        frame_in = dag_result["out"]
        assert frame_in is not None, f"Итерация {i}: SimulatorInputOp вернул None"

        frame_out = resize_op.execute(frame_in, ctx)

        assert frame_out.shape[:2] == (_RESIZE_HEIGHT, _RESIZE_WIDTH), (
            f"Итерация {i}: ожидали ({_RESIZE_HEIGHT}, {_RESIZE_WIDTH}), "
            f"получили {frame_out.shape[:2]}"
        )
        assert frame_out.dtype == np.uint8, (
            f"Итерация {i}: dtype должен оставаться uint8, получили {frame_out.dtype}"
        )


# ---------------------------------------------------------------------------
# Кейс 2: Цепочка с фейковым display-callback — кадры доходят до приёмника
# ---------------------------------------------------------------------------


def test_chain_with_display_callback(simulator_op, resize_op):
    """SimulatorInput → Resize → display_sink: callback вызван N раз, все кадры одной формы.

    Имитирует display output: выходной кадр передаётся в функцию-сборщик.
    Проверяем что:
      - `len(collected) == N` — каждый кадр дошёл до приёмника.
      - Все кадры имеют одинаковую форму (resize применён).
    """
    collected: list[np.ndarray] = []

    def display_sink(frame: np.ndarray) -> None:
        collected.append(frame)

    for i in range(_N_FRAMES):
        ctx = _make_ctx()
        ctx.seq_id = i

        frame_in = simulator_op.execute_dag({}, ctx)["out"]
        frame_out = resize_op.execute(frame_in, ctx)
        display_sink(frame_out)

    assert len(collected) == _N_FRAMES, (
        f"Ожидали {_N_FRAMES} кадров в display_sink, получили {len(collected)}"
    )

    expected_shape = (_RESIZE_HEIGHT, _RESIZE_WIDTH, 3)
    for idx, frame in enumerate(collected):
        assert frame.shape == expected_shape, (
            f"Кадр {idx}: ожидали shape {expected_shape}, получили {frame.shape}"
        )


# ---------------------------------------------------------------------------
# Кейс 3: Некорректные params — ResizeParams(width=0) бросает ValidationError
# ---------------------------------------------------------------------------


def test_resize_params_invalid_width_zero():
    """ResizeParams(width=0) должен бросать ValidationError (Pydantic min=16).

    Механизм: SchemaBase + FieldMeta(min=16) генерирует @model_validator,
    который проверяет диапазон и бросает ValueError → Pydantic оборачивает в ValidationError.
    """
    with pytest.raises(ValidationError) as exc_info:
        ResizeParams(width=0, height=_RESIZE_HEIGHT)

    errors = exc_info.value.errors()
    assert len(errors) >= 1, "Ожидали хотя бы одну ошибку валидации"
    # Сообщение должно упомянуть поле width
    all_messages = " ".join(str(e) for e in errors)
    assert "width" in all_messages.lower() or "0" in all_messages, (
        f"Ошибка должна упоминать поле width или значение 0, получили: {errors}"
    )


def test_resize_params_invalid_height_zero():
    """ResizeParams(height=0) должен бросать ValidationError (Pydantic min=16)."""
    with pytest.raises(ValidationError):
        ResizeParams(width=_RESIZE_WIDTH, height=0)


# ---------------------------------------------------------------------------
# Кейс 4 (опциональный): SimulatorInput → ColorConvert (bgr2gray) → Resize
# ---------------------------------------------------------------------------


def test_chain_with_color_convert(simulator_op, color_convert_bgr2gray_op):
    """SimulatorInput (BGR) → ColorConvert (bgr2gray) → Resize → финальный кадр grayscale.

    Проверяем:
      - После ColorConvert кадр 2D (ndim==2, grayscale).
      - После Resize форма (120, 160) — 1 канал сохранён.
    """
    resize_for_gray = ResizeOp()
    resize_for_gray.configure({"width": _RESIZE_WIDTH, "height": _RESIZE_HEIGHT})

    for i in range(_N_FRAMES):
        ctx = _make_ctx()
        ctx.seq_id = i

        frame_bgr = simulator_op.execute_dag({}, ctx)["out"]
        assert frame_bgr.ndim == 3, f"Итерация {i}: SimulatorOp должен дать BGR (ndim=3)"

        frame_gray = color_convert_bgr2gray_op.execute(frame_bgr, ctx)
        assert frame_gray.ndim == 2, (
            f"Итерация {i}: после bgr2gray ожидали ndim=2, получили {frame_gray.ndim}"
        )

        frame_out = resize_for_gray.execute(frame_gray, ctx)
        assert frame_out.shape == (_RESIZE_HEIGHT, _RESIZE_WIDTH), (
            f"Итерация {i}: ожидали ({_RESIZE_HEIGHT}, {_RESIZE_WIDTH}), "
            f"получили {frame_out.shape}"
        )
        assert frame_out.dtype == np.uint8


# ---------------------------------------------------------------------------
# Кейс 5 (опциональный): Pipeline-pydantic + validate_graph для DAG
# ---------------------------------------------------------------------------


def test_pipeline_validate_simulator_to_resize_dag():
    """Pipeline-pydantic с DAG simulator_input → resize: validate_graph возвращает [].

    Использует реальный каталог из data/processing_catalog.yaml.
    """
    from pathlib import Path

    from multiprocess_prototype.registers.pipeline.processing_node import (
        NodeInput,
        ProcessingNode,
    )
    from multiprocess_prototype.registers.pipeline.schemas import (
        CameraNode,
        Pipeline,
        RegionNode,
    )
    from multiprocess_prototype.registers.processor.catalog.loader import load_catalog

    catalog_path = (
        Path(__file__).resolve().parents[2] / "data" / "processing_catalog.yaml"
    )
    catalog = load_catalog(catalog_path)

    sim_node = ProcessingNode(
        node_id="sim",
        operation_ref="simulator_input",
        inputs=[],  # источник DAG — нет входов
    )
    resize_node = ProcessingNode(
        node_id="resize",
        operation_ref="resize",
        inputs=[NodeInput(source="sim", output_port="out", input_port="in")],
    )

    nodes = {"sim": sim_node, "resize": resize_node}
    region = RegionNode(nodes=nodes)
    camera = CameraNode(regions={"reg_e2e": region})
    pipeline = Pipeline(cameras={"cam_e2e": camera})

    errors = pipeline.validate_graph(catalog)
    assert errors == [], (
        f"Ожидали пустой список ошибок для DAG simulator_input → resize, "
        f"получили: {[e.model_dump() for e in errors]}"
    )
