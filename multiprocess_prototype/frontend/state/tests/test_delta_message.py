"""Тесты контракта state_delta_message (Delta → bridge-envelope, 5.9)."""

from __future__ import annotations

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from multiprocess_prototype.frontend.state.delta_message import (
    STATE_DELTA,
    state_delta_message,
)


def test_set_delta_carries_all_fields():
    d = Delta(
        path="processes.cam.state.fps",
        old_value=10,
        new_value=30,
        source="camera_0",
        transaction_id="tx-1",
    )
    msg = state_delta_message(d)
    assert msg["data_type"] == STATE_DELTA
    assert msg["path"] == "processes.cam.state.fps"
    assert msg["value"] == 30
    assert msg["deleted"] is False
    assert msg["old_value"] == 10
    assert msg["transaction_id"] == "tx-1"
    assert msg["source"] == "camera_0"


def test_delete_delta_marks_deleted_and_nulls_value():
    d = Delta(
        path="processes.cam.state.fps",
        old_value=30,
        new_value=MISSING,
        source="gui",
        transaction_id="tx-del",
    )
    msg = state_delta_message(d)
    assert msg["deleted"] is True
    assert msg["value"] is None  # sentinel MISSING не протекает
    assert msg["old_value"] == 30
    assert msg["transaction_id"] == "tx-del"


def test_create_delta_nulls_old_value():
    d = Delta(
        path="processes.cam.state.fps",
        old_value=MISSING,
        new_value=30,
        source="camera_0",
    )
    msg = state_delta_message(d)
    assert msg["deleted"] is False
    assert msg["value"] == 30
    assert msg["old_value"] is None  # создание: old_value был MISSING


def test_set_none_value_is_not_delete():
    """value=None при обычном set — deleted=False (None ≠ удаление)."""
    d = Delta(
        path="processes.cam.state.status",
        old_value="running",
        new_value=None,
        source="camera_0",
    )
    msg = state_delta_message(d)
    assert msg["deleted"] is False
    assert msg["value"] is None
