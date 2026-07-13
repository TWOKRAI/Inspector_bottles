# -*- coding: utf-8 -*-
"""Ф7 G.6 — интеграционный тест acceptance: «по trace_id в логах восстанавливается
путь кадра» (лог↔кадр коррелируются, кадр проходит ≥2 звена pipeline'а).

Сценарий: source-процесс camera_0 (SourceProducer, звено 1) рождает кадр,
назначает trace_id, шлёт через IPC (FrameShmMiddleware.strip_data_frame_on_send —
тот же send-middleware, что регистрирует GenericProcess в проде); detector-процесс
(DataReceiver, звено 2) принимает, восстанавливает frame из SHM (restore_frame).
Проверяется, что ОДИН trace_id доезжает без искажений через оба звена реального
hot-path (Dict at Boundary — поле пережило SHM/pickle round-trip само по себе),
а ЕСЛИ узел логирует через LoggerManager (штатный факад), trace_id корректно
коррелируется между записями двух разных модулей через LogRecord.extra.

Заодно проверяется runtime-счётчик границ (frame_hops): ровно 1 после единственного
send-middleware прохода.

Ф7 G.1 (перф-ревью 2026-07-13): периодический per-frame TRACE-лог (каждый 30-й
кадр) снят с hot path SourceProducer/DataReceiver — раньше корреляция
проверялась через него (do_trace=True на первом кадре). Теперь: (1) сама
трасса кадра (trace_id/frame_hops) проверяется по полям item/msg — они
переживают round-trip БЕЗ логирования, это и есть суть Dict at Boundary; (2)
механизм «лог↔кадр коррелируются» проверяется отдельно через реальный
LoggerManager + tap-sink (см. test_logger_manager.TestTraceIdExtraField —
тот же приём), а не через ad-hoc callback на hot path.
"""

import queue
import threading
import time

import numpy as np

from multiprocess_framework.modules.logger_module.core.log_config import LogLevel
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
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


class _FakeTapChannel:
    """Минимальный IChannel-совместимый tap: только write(dict) (Task 1.5 API).

    Дублирует ``test_logger_manager._FakeTapChannel`` — небольшой тестовый
    хелпер, локальная копия дешевле кросс-модульного импорта тестового кода.
    """

    def __init__(self):
        self.records: list = []

    def write(self, record: dict) -> None:
        self.records.append(record)

    def close(self) -> None:
        pass


def test_trace_id_survives_two_hot_path_nodes():
    """G.6 acceptance (часть 1): кадр проходит ≥2 звена hot-path, trace_id и
    frame_hops не искажаются (Dict at Boundary, без единого лога)."""
    shm = FrameShmMiddleware(MemoryManager(), owner="camera_0", slot="output_frames", coll=3)
    sent: list = []
    producer = SourceProducer(
        plugin=_CameraSource(),
        shm_middleware=shm,
        send_fn=lambda t, m: sent.append((t, m)),
        chain_targets=["detector"],
        target_fps=100.0,
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
    _, first_msg = sent[0]
    trace_id_before_send = first_msg["data"]["trace_id"]
    assert trace_id_before_send and len(trace_id_before_send) == 32

    # Router send-middleware (в проде — GenericProcess регистрирует его через
    # router.add_send_middleware) выносит frame в SHM ДО фактической IPC-отправки.
    # SourceProducer сам middleware не зовёт (P3.1.2) — применяем явно, как это
    # реально делает router на границе процесса.
    shm.strip_data_frame_on_send(first_msg)
    trace_id = first_msg["data"]["trace_id"]
    assert trace_id == trace_id_before_send  # звено 1 не исказило trace_id
    assert first_msg["data"]["frame_hops"] == 1  # ровно одна граница пройдена

    # --- звено 2: DataReceiver ("detector") принимает то же сообщение ---
    chain_q: queue.Queue = queue.Queue()
    inspector = PassThroughInspector()
    receiver = DataReceiver(
        receive_fn=lambda **kw: None,
        shm_middleware=shm,
        inspector_manager=inspector,
        chain_queue=chain_q,
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
    # Звено 2 получило ТОТ ЖЕ trace_id, что был назначен у источника — путь кадра
    # восстановим по этому полю без единого лога (Dict at Boundary).
    assert delivered[0]["trace_id"] == trace_id
    assert delivered[0]["frame_hops"] == 1


def test_trace_id_correlates_across_nodes_via_logger_tap():
    """G.6 acceptance (часть 2): ЕСЛИ узел логирует (LoggerManager — штатный
    факад проекта, не print/ad-hoc), запись несёт trace_id в LogRecord.extra —
    и по нему коррелируются записи двух РАЗНЫХ модулей (source/detector).

    trace_id здесь — тот же, что реально назначается у источника
    (``frame_trace.new_trace_id()``, формат подтверждён предыдущим тестом),
    не строка-заглушка: доказывает, что механизм переноса trace_id в extra
    (``mgr.info(msg, trace_id=..., module=...)``) работает для настоящего
    производственного trace_id, а не только для примера из test_logger_manager.
    """
    from multiprocess_framework.modules.process_module.generic import frame_trace

    trace_id = frame_trace.new_trace_id()
    assert len(trace_id) == 32

    mgr = LoggerManager(manager_name="TestG6TraceCorrelate")
    mgr.initialize()
    tap = _FakeTapChannel()
    mgr.add_log_tap(tap, min_level=LogLevel.DEBUG)

    # Звено 1 (source) и звено 2 (detector) логируют через ОДИН и тот же факад —
    # ровно так, как это делают реальные ctx.log_info/_log_debug в проде.
    mgr.info("SourceProducer(camera_0): produce()", module="camera_0", trace_id=trace_id)
    mgr.info("DataReceiver: item built", module="detector", trace_id=trace_id)

    correlated = [r for r in tap.records if r["extra"].get("trace_id") == trace_id]
    assert len(correlated) == 2, "оба звена должны были залогировать один trace_id"
    assert {r["module"] for r in correlated} == {"camera_0", "detector"}
    mgr.shutdown()


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
