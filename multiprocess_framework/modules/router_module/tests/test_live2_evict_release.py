# -*- coding: utf-8 -*-
"""LIVE-2 — release-on-evict: вытеснение кадра из полной очереди отпускает его займ.

Кадр, вытесненный из полной data-очереди раньше прочтения, потребитель не увидит →
его loan-тикет не отпустит НИКТО → free-list владельца утекает до перманентной смерти
кольца («кадры не сохраняются», skipped растёт со скоростью FPS — воспроизведено live).

RouterManager навешивает on_evict-хук на send_to_queue (только под активным loan-протоколом);
хук шлёт владельцу shm_release(evicted=True) той же system-почтой, что и штатный release.
"""

from __future__ import annotations

import time

import numpy as np

from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)
from multiprocess_framework.modules.shared_resources_module.queues import QueueRegistry
from multiprocess_framework.modules.shared_resources_module.state.process_state_registry import (
    ProcessStateRegistry,
)


def _frame(val: int = 1, h: int = 16, w: int = 16) -> np.ndarray:
    return np.full((h, w, 3), val, dtype=np.uint8)


class _FakeQR:
    """Захватывает send_to_queue для проверки почты release-on-evict."""

    def __init__(self):
        self.sent: list = []

    def send_to_queue(self, process, qtype, msg, timeout: float = 0.0, on_evict=None):
        self.sent.append((process, qtype, msg))
        return True

    def get_queue(self, process, qtype):
        return None


class _LoanMw:
    def __init__(self, enabled: bool):
        self.loan_protocol_enabled = enabled


class TestFrameLoanActiveGate:
    """on_evict навешивается ТОЛЬКО когда где-то активен loan-протокол (иначе — ноль
    оверхеда, бит-в-бит прежний send_to_queue)."""

    def test_inactive_by_default(self):
        rm = RouterManager(manager_name="seg", queue_registry=_FakeQR())
        assert rm._frame_loan_active is False

    def test_active_after_register_loan_middleware(self):
        rm = RouterManager(manager_name="seg", queue_registry=_FakeQR())
        mw = _LoanMw(enabled=True)
        rm.register_frame_middleware(mw)
        assert rm._frame_loan_active is True
        rm.unregister_frame_middleware(mw)
        assert rm._frame_loan_active is False

    def test_stays_inactive_for_loan_off_middleware(self):
        rm = RouterManager(manager_name="seg", queue_registry=_FakeQR())
        rm.register_frame_middleware(_LoanMw(enabled=False))
        assert rm._frame_loan_active is False


class TestOnFrameEvictedEnvelope:
    """_on_frame_evicted строит корректную shm_release-почту владельцу."""

    def test_builds_release_to_owner_with_evicted_flag(self):
        qr = _FakeQR()
        rm = RouterManager(manager_name="seg", queue_registry=qr)
        evicted = {"type": "data", "data": {"owner": "seg", "shm_name": "output_frames", "shm_index": 5}}
        rm._on_frame_evicted(evicted, reader_process="lines")

        assert len(qr.sent) == 1
        target, qtype, msg = qr.sent[0]
        assert target == "seg"  # владелец слота
        assert qtype == "system"  # надёжная почта (её поллит message_processor)
        assert msg["type"] == "shm_release"
        assert msg["data"]["evicted"] is True
        rel = msg["data"]["releases"][0]
        assert rel["index"] == 5
        assert rel["reader"] == "lines"  # непрочитавший потребитель
        assert rel["generation"] == -1  # тикет вытеснения поколения не несёт

    def test_owner_from_shm_owner_fallback(self):
        qr = _FakeQR()
        rm = RouterManager(manager_name="seg", queue_registry=qr)
        rm._on_frame_evicted({"data": {"shm_owner": "cam0", "shm_name": "s", "shm_index": 0}}, "lines")
        assert qr.sent and qr.sent[0][0] == "cam0"

    def test_non_frame_eviction_ignored(self):
        qr = _FakeQR()
        rm = RouterManager(manager_name="seg", queue_registry=qr)
        rm._on_frame_evicted({"type": "data", "data": {"nothing": 1}}, "lines")  # нет SHM-координат
        rm._on_frame_evicted("garbage", "lines")  # не dict
        rm._on_frame_evicted({"data": None}, "lines")  # data не dict
        assert qr.sent == []  # займа нет — почты нет


class TestEvictReleaseIntegration:
    """Полная цепочка: полная очередь → вытеснение loan-кадра → shm_release владельцу →
    handler release_evicted → слот вернулся в free-list (иначе кольцо мертво навсегда)."""

    def test_full_queue_eviction_frees_owner_slot(self, monkeypatch):
        monkeypatch.setenv("FW_SHM_LOAN_PROTOCOL", "1")
        monkeypatch.setenv("FW_SHM_SEQLOCK", "1")

        psr = ProcessStateRegistry()
        qr = QueueRegistry(process_state_registry=psr)
        qr.initialize()
        # seg — владелец (его system-очередь примет release); lines — потребитель (data, глубина 1).
        psr.register_process("seg")
        qr.create_and_register_queues("seg", {"system": {"maxsize": 8}})
        psr.register_process("lines")
        qr.create_and_register_queues("lines", {"data": {"maxsize": 1}})

        rm = RouterManager(manager_name="seg", queue_registry=qr)
        mw = FrameShmMiddleware(MemoryManager(), owner="seg", slot="output_frames", coll=2, num_consumers=1)
        rm.register_frame_middleware(mw)
        try:
            # seg записывает 2 кадра → оба слота заняты займом (refcount=[1,1]).
            item_a = mw.strip_and_write({"frame": _frame(0)})
            idx_a = item_a["shm_index"]
            item_b = mw.strip_and_write({"frame": _frame(1)})
            assert mw._pool._refcount == [1, 1]

            # Кадр A уже лежит в очереди lines (заполняет её, maxsize=1).
            ticket_a = {"type": "data", "targets": ["lines"], "data": dict(item_a)}
            assert qr.send_to_queue("lines", "data", ticket_a) is True
            time.sleep(0.1)  # дать feeder-потоку осесть → full()=True

            # Кадр B уходит в lines через router → очередь полна → вытеснение A →
            # on_evict → shm_release владельцу seg в его system-очередь.
            ticket_b = {"type": "data", "targets": ["lines"], "data": dict(item_b)}
            rm.send(ticket_b)
            time.sleep(0.1)

            # Владелец разгребает свою system-очередь (роль message_processor).
            release = qr.receive_from_queue("seg", "system", timeout=1.0)
            assert release is not None
            assert release["type"] == "shm_release"
            assert release["data"]["evicted"] is True

            # Owner-handler: делегирует в middleware с evicted=True (как _handle_shm_release).
            mw.release_slots(release["data"]["releases"], evicted=True)

            # Слот кадра A вернулся в free-list — кольцо живо.
            assert mw._pool._refcount[idx_a] == 0
            assert mw.frame_loans_released_on_evict == 1
            # Доказательство восстановления: новый write снова проходит (занимает освобождённый слот).
            out = mw.strip_and_write({"frame": _frame(2)})
            assert "frame" not in out
        finally:
            mw.release_owned_memory()
