# -*- coding: utf-8 -*-
"""Ф7 G.6 — интеграционный тест acceptance: «по trace_id в логах восстанавливается
путь кадра» (лог↔кадр коррелируются, кадр проходит ≥2 звена pipeline'а).

Сценарий: source-процесс camera_0 (SourceProducer, звено 1) рождает кадр,
назначает trace_id, шлёт через IPC (FrameShmMiddleware.strip_data_frame_on_send —
тот же send-middleware, что регистрирует GenericProcess в проде); detector-процесс
(DataReceiver, звено 2) принимает, восстанавливает frame из SHM (restore_frame) и
логирует. Обе TRACE-записи (звено 1 и звено 2) должны нести ОДИН trace_id.

Заодно проверяется runtime-счётчик границ (frame_hops): ровно 1 после единственного
send-middleware прохода.
"""

import queue
import threading
import time

import numpy as np

from multiprocess_framework.modules.process_module.generic.data_receiver import (
    DataReceiver,
)
from multiprocess_framework.modules.process_module.generic.inspector_registry import (
    PassThroughInspector,
)
from multiprocess_framework.modules.process_module.generic.source_producer import (
    SourceProducer,
)
from multiprocess_framework.modules.process_module.plugins.base import (
    ProcessModulePlugin,
)
from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)


class _CameraSource(ProcessModulePlugin):
    """Источник с реальным numpy-кадром прод-размера (не строка-заглушка)."""

    name = "camera_0"
    category = "source"

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def produce(self) -> list[dict]:
        return [{"frame": np.full((600, 800, 3), 50, dtype=np.uint8), "camera_id": 0}]


def test_trace_id_correlates_logs_across_two_nodes():
    """G.6 acceptance: кадр проходит ≥2 звена, лог-записи обоих несут один trace_id."""
    node1_logs: list[dict] = []

    def log_debug_node1(msg, **extra):
        if extra.get("trace_id"):
            node1_logs.append(extra)

    shm = FrameShmMiddleware(MemoryManager(), owner="camera_0", slot="output_frames", coll=3)
    sent: list = []
    producer = SourceProducer(
        plugin=_CameraSource(),
        shm_middleware=shm,
        send_fn=lambda t, m: sent.append((t, m)),
        chain_targets=["detector"],
        target_fps=100.0,
        log_debug=log_debug_node1,
        node_name="camera_0",
    )

    stop_event = threading.Event()
    pause_event = threading.Event()
    t = threading.Thread(target=producer.run_loop, args=(stop_event, pause_event))
    t.start()
    time.sleep(0.15)
    stop_event.set()
    t.join(timeout=1)

    assert sent, "SourceProducer должен был отправить хотя бы один item"
    assert node1_logs, "звено 1 (source) должно было залогировать trace_id — первый кадр всегда do_trace=True"
    trace_id = node1_logs[0]["trace_id"]
    assert trace_id and len(trace_id) == 32

    # Router send-middleware (в проде — GenericProcess регистрирует его через
    # router.add_send_middleware) выносит frame в SHM ДО фактической IPC-отправки.
    # SourceProducer сам middleware не зовёт (P3.1.2) — применяем явно, как это
    # реально делает router на границе процесса.
    _, first_msg = sent[0]
    shm.strip_data_frame_on_send(first_msg)
    assert first_msg["data"]["trace_id"] == trace_id
    assert first_msg["data"]["frame_hops"] == 1  # ровно одна граница пройдена

    # --- звено 2: DataReceiver ("detector") принимает то же сообщение ---
    node2_logs: list[dict] = []

    def log_debug_node2(msg, **extra):
        if extra.get("trace_id"):
            node2_logs.append(extra)

    chain_q: queue.Queue = queue.Queue()
    inspector = PassThroughInspector()
    receiver = DataReceiver(
        receive_fn=lambda **kw: None,
        shm_middleware=shm,
        inspector_manager=inspector,
        chain_queue=chain_q,
        log_debug=log_debug_node2,
        node_name="detector",
    )
    inspector._on_ready = receiver.on_items_ready

    messages = iter([first_msg])
    receiver._receive = lambda **kw: next(messages, None)

    stop_event2 = threading.Event()
    pause_event2 = threading.Event()
    t2 = threading.Thread(target=receiver.run_loop, args=(stop_event2, pause_event2))
    t2.start()
    time.sleep(0.15)
    stop_event2.set()
    t2.join(timeout=1)

    assert not chain_q.empty()
    delivered = chain_q.get_nowait()
    assert delivered[0]["trace_id"] == trace_id
    assert delivered[0]["frame_hops"] == 1

    # Оба звена залогировали ОДИН trace_id — суть acceptance G.6.
    assert node2_logs, "звено 2 (detector) должно было залогировать trace_id"
    assert node2_logs[0]["trace_id"] == trace_id


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
