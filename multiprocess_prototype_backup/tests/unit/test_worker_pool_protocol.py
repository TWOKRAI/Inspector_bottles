"""Unit-тесты для WorkerTaskRequest / WorkerTaskResponse (Phase 5c, protocol.py)."""

from __future__ import annotations

import sys
from pathlib import Path

_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

import pytest

from services.processor.worker_pool.protocol import WorkerTaskRequest, WorkerTaskResponse


# ---------------------------------------------------------------------------
# Тесты WorkerTaskRequest
# ---------------------------------------------------------------------------


class TestWorkerTaskRequestCreate:
    def test_create_generates_unique_task_id(self):
        """Два вызова create() → разные task_id."""
        r1 = WorkerTaskRequest.create(
            camera_id="cam0",
            region_id="r0",
            seq_id=1,
            operation_ref="op_a",
            input_shm_name="shm_0",
            input_shm_index=0,
            frame_shape=(480, 640, 3),
        )
        r2 = WorkerTaskRequest.create(
            camera_id="cam0",
            region_id="r0",
            seq_id=2,
            operation_ref="op_a",
            input_shm_name="shm_0",
            input_shm_index=0,
            frame_shape=(480, 640, 3),
        )
        assert r1.task_id != r2.task_id

    def test_create_task_id_is_non_empty_string(self):
        """task_id создаётся как непустая строка."""
        req = WorkerTaskRequest.create(
            camera_id="cam0",
            region_id="r0",
            seq_id=0,
            operation_ref="op_a",
            input_shm_name="shm_0",
            input_shm_index=0,
            frame_shape=(480, 640, 3),
        )
        assert isinstance(req.task_id, str)
        assert len(req.task_id) > 0

    def test_create_sets_fields_correctly(self):
        """create() заполняет все поля переданными значениями."""
        req = WorkerTaskRequest.create(
            correlation_id="corr-123",
            camera_id="cam1",
            region_id="r5",
            seq_id=42,
            operation_ref="blob_detection",
            params={"threshold": 0.5},
            input_shm_name="shm_blob",
            input_shm_index=2,
            frame_shape=(720, 1280, 3),
        )
        assert req.correlation_id == "corr-123"
        assert req.camera_id == "cam1"
        assert req.region_id == "r5"
        assert req.seq_id == 42
        assert req.operation_ref == "blob_detection"
        assert req.params == {"threshold": 0.5}
        assert req.input_shm_name == "shm_blob"
        assert req.input_shm_index == 2
        assert req.frame_shape == (720, 1280, 3)

    def test_create_default_correlation_id_is_empty(self):
        """Если correlation_id не передан — по умолчанию пустая строка."""
        req = WorkerTaskRequest.create(
            camera_id="cam0",
            region_id="r0",
            seq_id=0,
            operation_ref="op_a",
            input_shm_name="shm_0",
            input_shm_index=0,
            frame_shape=(480, 640, 3),
        )
        assert req.correlation_id == ""

    def test_create_default_params_is_empty_dict(self):
        """Если params не передан — по умолчанию пустой dict."""
        req = WorkerTaskRequest.create(
            camera_id="cam0",
            region_id="r0",
            seq_id=0,
            operation_ref="op_a",
            input_shm_name="shm_0",
            input_shm_index=0,
            frame_shape=(480, 640, 3),
        )
        assert req.params == {}

    def test_create_frame_shape_stored_as_tuple(self):
        """frame_shape сохраняется как tuple внутри объекта."""
        req = WorkerTaskRequest.create(
            camera_id="cam0",
            region_id="r0",
            seq_id=0,
            operation_ref="op_a",
            input_shm_name="shm_0",
            input_shm_index=0,
            frame_shape=(480, 640, 3),
        )
        assert isinstance(req.frame_shape, tuple)
        assert req.frame_shape == (480, 640, 3)


class TestWorkerTaskRequestRoundTrip:
    @pytest.fixture
    def sample_request(self) -> WorkerTaskRequest:
        return WorkerTaskRequest.create(
            correlation_id="corr-abc",
            camera_id="cam2",
            region_id="r3",
            seq_id=10,
            operation_ref="color_detection",
            params={"color": "red", "min_area": 100},
            input_shm_name="shm_input",
            input_shm_index=1,
            frame_shape=(480, 640, 3),
        )

    def test_to_dict_returns_dict(self, sample_request):
        """to_dict() возвращает dict."""
        assert isinstance(sample_request.to_dict(), dict)

    def test_to_dict_frame_shape_is_list(self, sample_request):
        """В dict frame_shape сериализуется как list (для JSON-совместимости)."""
        d = sample_request.to_dict()
        assert isinstance(d["frame_shape"], list)
        assert d["frame_shape"] == [480, 640, 3]

    def test_from_dict_frame_shape_is_tuple(self, sample_request):
        """После from_dict() frame_shape восстанавливается как tuple."""
        d = sample_request.to_dict()
        restored = WorkerTaskRequest.from_dict(d)
        assert isinstance(restored.frame_shape, tuple)

    def test_round_trip_preserves_all_fields(self, sample_request):
        """to_dict() → from_dict() сохраняет все поля без потерь."""
        d = sample_request.to_dict()
        restored = WorkerTaskRequest.from_dict(d)

        assert restored.task_id == sample_request.task_id
        assert restored.correlation_id == sample_request.correlation_id
        assert restored.camera_id == sample_request.camera_id
        assert restored.region_id == sample_request.region_id
        assert restored.seq_id == sample_request.seq_id
        assert restored.operation_ref == sample_request.operation_ref
        assert restored.params == sample_request.params
        assert restored.input_shm_name == sample_request.input_shm_name
        assert restored.input_shm_index == sample_request.input_shm_index
        assert restored.frame_shape == sample_request.frame_shape

    def test_from_dict_with_missing_optional_fields(self):
        """from_dict() с минимальным dict (только обязательные поля) не падает."""
        minimal = {
            "task_id": "abc123",
            "operation_ref": "some_op",
        }
        req = WorkerTaskRequest.from_dict(minimal)
        assert req.task_id == "abc123"
        assert req.operation_ref == "some_op"
        assert req.correlation_id == ""
        assert req.camera_id == ""
        assert req.region_id == ""
        assert req.seq_id == 0
        assert req.params == {}
        assert req.input_shm_name == ""
        assert req.input_shm_index == 0
        assert req.frame_shape == ()


# ---------------------------------------------------------------------------
# Тесты WorkerTaskResponse
# ---------------------------------------------------------------------------


class TestWorkerTaskResponseErrorResponse:
    def test_error_response_success_is_false(self):
        """error_response() устанавливает success=False."""
        resp = WorkerTaskResponse.error_response(
            task_id="t1",
            error="timeout",
        )
        assert resp.success is False

    def test_error_response_error_field_filled(self):
        """error_response() заполняет поле error переданной строкой."""
        resp = WorkerTaskResponse.error_response(
            task_id="t1",
            error="worker crashed",
        )
        assert resp.error == "worker crashed"

    def test_error_response_task_id_set(self):
        """error_response() устанавливает task_id из аргумента."""
        resp = WorkerTaskResponse.error_response(
            task_id="xyz-999",
            error="some error",
        )
        assert resp.task_id == "xyz-999"

    def test_error_response_correlation_id_default_empty(self):
        """Без correlation_id → пустая строка по умолчанию."""
        resp = WorkerTaskResponse.error_response(
            task_id="t1",
            error="err",
        )
        assert resp.correlation_id == ""

    def test_error_response_with_correlation_id(self):
        """correlation_id передаётся и сохраняется."""
        resp = WorkerTaskResponse.error_response(
            task_id="t1",
            error="err",
            correlation_id="corr-abc",
        )
        assert resp.correlation_id == "corr-abc"


class TestWorkerTaskResponseRoundTrip:
    @pytest.fixture
    def success_response(self) -> WorkerTaskResponse:
        """Успешный ответ с детекциями."""
        return WorkerTaskResponse(
            task_id="t-success",
            correlation_id="corr-1",
            success=True,
            error=None,
            output_shm_name="shm_out",
            output_shm_index=3,
            detections=[{"bbox": [10, 20, 100, 200], "label": "defect"}],
            processing_time=0.042,
        )

    @pytest.fixture
    def error_response(self) -> WorkerTaskResponse:
        """Ответ с ошибкой."""
        return WorkerTaskResponse.error_response(
            task_id="t-error",
            error="operation failed",
            correlation_id="corr-2",
        )

    def test_success_round_trip_preserves_all_fields(self, success_response):
        """Успешный response: to_dict() → from_dict() сохраняет все поля."""
        d = success_response.to_dict()
        restored = WorkerTaskResponse.from_dict(d)

        assert restored.task_id == success_response.task_id
        assert restored.correlation_id == success_response.correlation_id
        assert restored.success == success_response.success
        assert restored.error == success_response.error
        assert restored.output_shm_name == success_response.output_shm_name
        assert restored.output_shm_index == success_response.output_shm_index
        assert restored.detections == success_response.detections
        assert pytest.approx(restored.processing_time) == success_response.processing_time

    def test_error_round_trip_preserves_fields(self, error_response):
        """Ответ с ошибкой: round-trip сохраняет success=False и error."""
        d = error_response.to_dict()
        restored = WorkerTaskResponse.from_dict(d)

        assert restored.success is False
        assert restored.error == "operation failed"
        assert restored.task_id == "t-error"
        assert restored.correlation_id == "corr-2"

    def test_to_dict_returns_dict(self, success_response):
        """to_dict() возвращает dict."""
        assert isinstance(success_response.to_dict(), dict)

    def test_from_dict_with_minimal_data(self):
        """from_dict() с только task_id не падает, заполняет defaults."""
        minimal = {"task_id": "min-id"}
        resp = WorkerTaskResponse.from_dict(minimal)
        assert resp.task_id == "min-id"
        assert resp.correlation_id == ""
        assert resp.success is True
        assert resp.error is None
        assert resp.output_shm_name == ""
        assert resp.output_shm_index == 0
        assert resp.detections == []
        assert resp.processing_time == pytest.approx(0.0)

    def test_error_field_is_none_in_success_response(self, success_response):
        """Успешный response: поле error == None."""
        d = success_response.to_dict()
        restored = WorkerTaskResponse.from_dict(d)
        assert restored.error is None
