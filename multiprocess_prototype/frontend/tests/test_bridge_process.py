# -*- coding: utf-8 -*-
"""RED-приёмка ``FrameBridge`` на фейковом роутере (Task 1.3, gui-service, слепой tester).

Видел только ``bridge_process.py`` (докстринги/сигнатуры, тела — ``NotImplementedError``)
и ``remote_frame_source.py`` для протокола push-сообщения (``DESCRIPTOR_KEYS`` в этом
файле — ЛИТЕРАЛ, не импорт из SUT: импорт константы из кода под тестом ничего не
доказывает, если константа сама неверна).

``FrameBridge`` — чистая логика без процесса (докстринг класса: «тестируется на
фейковом роутере»), поэтому реальный IPC/сокет здесь не нужен — фейковый роутер
просто записывает вызовы ``send_async``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from multiprocess_prototype.frontend.bridge_process import FrameBridge

#: Ключи дескриптора — ровно эти, в этом порядке (см. remote_frame_source.py DESCRIPTOR_KEYS).
_DESCRIPTOR_KEYS = ("sender", "name", "idx", "seqlock", "bseq", "ts")


class _FakeRouter:
    """Записывает каждый ``send_async`` — ничего не проверяет сам, проверяет тест."""

    def __init__(self) -> None:
        self.calls: List[Tuple[Dict[str, Any], str]] = []

    def send_async(self, message: Dict[str, Any], priority: str = "normal") -> None:
        self.calls.append((message, priority))


def _shm_msg(sender: str, name: str = "shmslot0", idx: int = 0) -> Dict[str, Any]:
    """data-конверт продюсера с кадром через SHM (поля по DESIGN п.3, ``frame_shm_middleware``)."""
    return {
        "sender": sender,
        "data": {
            "shm_actual_name": name,
            "shm_index": idx,
            "shm_seqlock": False,
            "owner": "camera_0",
            "shm_name": "camera_0_ring",
            "width": 640,
            "height": 480,
        },
    }


def _no_shm_msg(sender: str) -> Dict[str, Any]:
    """data-конверт без кадра (не через SHM) — build_frame_descriptor вернул бы None."""
    return {"sender": sender, "data": {"note": "не кадр, нет shm_actual_name"}}


def _new_bridge(router: _FakeRouter, **flags: bool) -> FrameBridge:
    return FrameBridge(
        router,
        "gui",
        seqlock=flags.get("seqlock", False),
        owner_incarnation=flags.get("owner_incarnation", False),
        loan_protocol=flags.get("loan_protocol", False),
    )


def test_b1_no_subscribers_zero_pushes() -> None:
    """B1: без подписчиков — 0 send_async, даже если в пачке есть полноценные кадры
    (docstring on_drained: «подписчиков нет — ни одного build_frame_descriptor и send_async»)."""
    router = _FakeRouter()
    bridge = _new_bridge(router)

    bridge.on_drained([_shm_msg("camA"), _shm_msg("camB")])

    assert router.calls == []


def test_b2_subscribe_then_frame_push_exact_shape_and_size() -> None:
    """B2: subscribe + data-сообщение с shm_* → РОВНО один push, targets=[адрес],
    command="frames.frame", ключи дескриптора дословно DESCRIPTOR_KEYS, JSON ≤ 300 байт."""
    router = _FakeRouter()
    bridge = _new_bridge(router)

    resp = bridge.cmd_subscribe({"subscriber": "pult.sess1"})
    assert resp == {"success": True, "seqlock": False, "owner_incarnation": False}

    bridge.on_drained([_shm_msg("camA", name="shmslotA", idx=3)])

    assert len(router.calls) == 1, "ожидался ровно один push"
    message, priority = router.calls[0]
    assert priority == "normal"
    assert message["type"] == "event"
    assert message["targets"] == ["pult.sess1"]
    assert message["queue_type"] == "observability"
    assert message["command"] == "frames.frame"
    assert message["sender"] == "gui"

    descriptor = message["data"]
    assert tuple(descriptor.keys()) == _DESCRIPTOR_KEYS, f"ключи дескриптора не совпали: {tuple(descriptor.keys())}"
    assert descriptor["sender"] == "camA"
    assert descriptor["name"] == "shmslotA"
    assert descriptor["idx"] == 3
    assert descriptor["seqlock"] is False
    assert descriptor["bseq"] == 1  # первый дескриптор — bseq == 1

    encoded = json.dumps(descriptor).encode()
    assert len(encoded) <= 300, f"дескриптор {len(encoded)} байт > 300"


def test_b3_unsubscribe_stops_further_pushes() -> None:
    """B3: unsubscribe → 0 push'ей после (адрес удалён из подписчиков)."""
    router = _FakeRouter()
    bridge = _new_bridge(router)
    bridge.cmd_subscribe({"subscriber": "pult.sess1"})

    unsub_resp = bridge.cmd_unsubscribe({"subscriber": "pult.sess1"})
    assert unsub_resp["success"] is True
    assert unsub_resp["removed"] is True

    bridge.on_drained([_shm_msg("camA")])

    assert router.calls == []


def test_b4_msg_without_shm_actual_name_is_skipped() -> None:
    """B4: сообщение без shm_actual_name (не кадр) → 0 push'ей, даже с активным подписчиком."""
    router = _FakeRouter()
    bridge = _new_bridge(router)
    bridge.cmd_subscribe({"subscriber": "pult.sess1"})

    bridge.on_drained([_no_shm_msg("camA")])

    assert router.calls == []


def test_b5_senders_filter_excludes_other_producers() -> None:
    """B5: подписчик с senders=["a"] получает кадры "a", но не "b" (docstring on_drained:
    «фильтр хотя бы одного подписчика пропускает msg["sender"]»)."""
    router = _FakeRouter()
    bridge = _new_bridge(router)
    resp = bridge.cmd_subscribe({"subscriber": "pult.sess1", "senders": ["a"]})
    assert resp["success"] is True

    bridge.on_drained([_shm_msg("b"), _shm_msg("a")])

    assert len(router.calls) == 1, "должен пройти ровно один кадр (от 'a'), не два"
    message, _priority = router.calls[0]
    assert message["data"]["sender"] == "a"
