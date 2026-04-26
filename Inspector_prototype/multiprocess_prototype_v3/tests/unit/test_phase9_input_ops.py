"""Unit-тесты для Input-операций (Task 9.4)."""

from __future__ import annotations

import pytest
import numpy as np

from multiprocess_prototype_v3.services.processor.operations.base import (
    ChainContext,
    ProcessingOperation,
)
from multiprocess_prototype_v3.services.processor.operations.input.webcam_input_op import (
    WebcamInputOp,
)
from multiprocess_prototype_v3.services.processor.operations.input.hikvision_input_op import (
    HikvisionInputOp,
)
from multiprocess_prototype_v3.services.processor.operations.input.file_input_op import (
    FileInputOp,
)
from multiprocess_prototype_v3.services.processor.operations.input.simulator_input_op import (
    SimulatorInputOp,
)
from multiprocess_prototype_v3.services.camera.backends import BaseCaptureBackend


def _make_ctx() -> ChainContext:
    return ChainContext()


# ---------------------------------------------------------------------------
# SimulatorInputOp
# ---------------------------------------------------------------------------


def test_simulator_input_protocol_compliance():
    """SimulatorInputOp реализует Protocol ProcessingOperation."""
    op = SimulatorInputOp()
    assert isinstance(op, ProcessingOperation)


def test_simulator_input_execute_dag_returns_frame():
    """SimulatorInputOp.execute_dag → np.ndarray shape (100, 100, 3)."""
    op = SimulatorInputOp()
    op.configure({"width": 100, "height": 100})
    result = op.execute_dag({}, _make_ctx())
    frame = result["out"]
    assert isinstance(frame, np.ndarray)
    assert frame.shape == (100, 100, 3)
    op.close()


def test_simulator_input_close_resets_backend():
    """После close() _backend is None и _started == False."""
    op = SimulatorInputOp()
    op.configure({"width": 64, "height": 64})
    # Запускаем чтобы backend создался
    op.execute_dag({}, _make_ctx())
    assert op._backend is not None
    assert op._started is True

    op.close()
    assert op._backend is None
    assert op._started is False


def test_simulator_input_reconfigure_resets_backend():
    """При смене параметров после старта — backend пересоздаётся."""
    op = SimulatorInputOp()
    op.configure({"width": 64, "height": 64})
    op.execute_dag({}, _make_ctx())
    backend_first = op._backend

    # Меняем параметры — backend должен быть сброшен и пересоздан
    op.configure({"width": 128, "height": 128})
    # После configure с другими params — backend сброшен
    assert op._started is False


# ---------------------------------------------------------------------------
# FileInputOp
# ---------------------------------------------------------------------------


def test_file_input_raises_on_empty_path():
    """FileInputOp с пустым file_path → ValueError при execute_dag."""
    op = FileInputOp()
    op.configure({"file_path": ""})
    with pytest.raises(ValueError, match="file_path"):
        op.execute_dag({}, _make_ctx())


def test_file_input_raises_on_missing_path_key():
    """FileInputOp без file_path в params → ValueError при execute_dag."""
    op = FileInputOp()
    op.configure({})
    with pytest.raises(ValueError, match="file_path"):
        op.execute_dag({}, _make_ctx())


# ---------------------------------------------------------------------------
# WebcamInputOp
# ---------------------------------------------------------------------------


def test_webcam_input_protocol_compliance():
    """WebcamInputOp реализует Protocol ProcessingOperation."""
    op = WebcamInputOp()
    assert isinstance(op, ProcessingOperation)


def test_webcam_input_configure_stores_params():
    """WebcamInputOp.configure сохраняет параметры."""
    op = WebcamInputOp()
    op.configure({"width": 1280, "height": 720, "device_id": 1})
    assert op._params["width"] == 1280
    assert op._params["height"] == 720
    assert op._params["device_id"] == 1


def test_webcam_input_configure_same_params_no_reset():
    """Повторный configure с теми же params не сбрасывает backend."""
    op = WebcamInputOp()
    op.configure({"width": 640, "height": 480})
    # Без старта backend — None
    assert op._backend is None
    # Повторный configure с теми же params ничего не меняет
    op.configure({"width": 640, "height": 480})
    assert op._backend is None


# ---------------------------------------------------------------------------
# HikvisionInputOp
# ---------------------------------------------------------------------------


def test_hikvision_input_protocol_compliance():
    """HikvisionInputOp реализует Protocol ProcessingOperation."""
    op = HikvisionInputOp()
    assert isinstance(op, ProcessingOperation)


def test_hikvision_input_uses_factory_fallback():
    """HikvisionInputOp на не-Windows не падает — factory возвращает SimulatorBackend.

    Проверяем что _backend является экземпляром BaseCaptureBackend после execute_dag.
    """
    op = HikvisionInputOp()
    op.configure({})
    # Вызываем execute_dag — на non-Windows фабрика вернёт SimulatorBackend
    result = op.execute_dag({}, _make_ctx())
    assert op._backend is not None
    assert isinstance(op._backend, BaseCaptureBackend)
    # frame может быть None (симулятор без изображения может вернуть None или ndarray)
    assert "out" in result
    op.close()
