# -*- coding: utf-8 -*-
"""Task 4.7d-2 — слепой acceptance помощника ``meta_from_msg`` (``not_inspected_marker.py``).

Правило «meta как в ``DataReceiver._build_item``»: ``trace_id`` / ``capture_ts`` из ``msg["data"]``,
``frame_id`` / ``camera_id`` из ``data``, иначе из ``msg`` (по наличию ключа, не по истинности).
Импорт — внутри теста: пока помощника нет, падает сам тест (ImportError), а не сбор файла.
"""

from __future__ import annotations


def test_meta_from_msg_literal_data_camera_id_wins_and_zero_is_kept():
    """meta_from_msg({"data": {"trace_id": "t1", "capture_ts": 2.0, "camera_id": 0}, "frame_id": 5,
    "camera_id": "x"}) == {"trace_id": "t1", "capture_ts": 2.0, "camera_id": 0, "frame_id": 5}
    (camera_id из data побеждает msg, значение 0 сохраняется)."""
    from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import meta_from_msg

    msg = {"data": {"trace_id": "t1", "capture_ts": 2.0, "camera_id": 0}, "frame_id": 5, "camera_id": "x"}

    assert meta_from_msg(msg) == {"trace_id": "t1", "capture_ts": 2.0, "camera_id": 0, "frame_id": 5}
