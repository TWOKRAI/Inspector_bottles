# -*- coding: utf-8 -*-
"""Task 4.4c — item атомарен на приёме в пайплайне (автор, не tester).

Дефект живого стенда (1080p, 100 к/с, пиксельная метка): инспектор получал item, у которого
``frame`` прочитан целым, а ``mask`` перезаписана между двумя чтениями -> ``mask = None`` шёл в
плагин. Для инспекции «нет маски» может превратиться в «нет дефектов» — бракованная бутылка
проходит. Контракт: не читается ХОТЬ ОДНА ссылка сообщения -> сообщение отброшено ЦЕЛИКОМ,
``DataReceiver`` не строит и не кладёт item.

Стенд: НАСТОЯЩИЕ ``DataReceiver.run_loop`` + ``FrameShmMiddleware`` + SHM; провод — pickle.
"""

from __future__ import annotations

import gc
import os
import pickle
import queue
import threading
import time

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver
from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager

SHAPES = {"frame": (48, 64, 3), "mask": (100, 120)}  # оба >= 8192 Б -> ссылкой


@pytest.fixture(autouse=True)
def _clean_shm_flags(monkeypatch):
    for name in [k for k in os.environ if k.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def made():
    items: list[tuple[FrameShmMiddleware, MemoryManager]] = []
    yield items
    gc.collect()
    for mw, mm in reversed(items):
        for fin in (mw.close_handle_cache, mw.release_owned_memory, mm.close_all):
            try:
                fin()
            except Exception:  # noqa: BLE001 — финализатор не маскирует причину падения
                pass


def _mw(made, owner: str, *, view: bool = False) -> FrameShmMiddleware:
    mm = MemoryManager()
    extra = dict(owner_incarnation=True, cache_shm_handles=True, zero_copy=True) if view else {"zero_copy": False}
    mw = FrameShmMiddleware(mm, owner=owner, slot="output_frames", coll=3, **extra)
    made.append((mw, mm))
    return mw


def _arr(key: str, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 250, size=SHAPES[key]).astype(np.uint8)


def _send(writer: FrameShmMiddleware, item: dict) -> dict:
    out = writer.strip_data_frame_on_send({"target": "t", "type": "data", "channel": "data", "data": item})
    assert out is not None
    return pickle.loads(pickle.dumps(out))


class _Collector:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def on_item(self, item: dict) -> None:
        self.items.append(item)

    def check_timeouts(self) -> None:
        return None


def _run_receiver(reader: FrameShmMiddleware, wires: list[dict], chain_queue: queue.Queue) -> _Collector:
    """Прогнать wires через настоящий ``run_loop`` в daemon-потоке с дедлайном (тест не виснет)."""
    pending = list(wires)
    collector = _Collector()

    def receive_fn(timeout: float = 0.05, channel_types=None, return_messages: bool = True):
        if pending:
            return pending.pop(0)
        time.sleep(0.01)
        return None

    recv = DataReceiver(
        receive_fn=receive_fn,
        shm_middleware=reader,
        item_collector=collector,
        chain_queue=chain_queue,
        node_name="B",
    )
    stop, pause = threading.Event(), threading.Event()
    worker = threading.Thread(target=recv.run_loop, args=(stop, pause), daemon=True)
    worker.start()
    deadline = time.monotonic() + 10.0
    while pending and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.2)  # дать обработать последнее сообщение
    stop.set()
    worker.join(5.0)
    assert not worker.is_alive(), "run_loop не остановился"
    return collector


def test_control_healthy_message_reaches_collector(made):
    """CONTROL: целое сообщение (обе ссылки живы) доходит до коллектора с frame и mask."""
    writer, reader = _mw(made, "A"), _mw(made, "B")
    wire = _send(writer, {"frame": _arr("frame", 1), "mask": _arr("mask", 2), "n": 1})

    collector = _run_receiver(reader, [wire], queue.Queue())

    assert len(collector.items) == 1
    item = collector.items[0]
    assert item["frame"].tobytes() == _arr("frame", 1).tobytes()
    assert item["mask"].tobytes() == _arr("mask", 2).tobytes()


@pytest.mark.parametrize("view", [False, True], ids=["copy", "view"])
def test_data_receiver_does_not_enqueue_marked_message(made, view):
    """frame прочитан, mask перезаписана -> в коллектор и в chain_queue не попадает НИЧЕГО (ни item
    с ``mask=None``, ни item без mask); следующее целое сообщение проходит как обычно; счётчик
    ``frame_stale_drops`` == 1 (одно сообщение)."""
    writer, reader = _mw(made, "A"), _mw(made, "B", view=view)
    broken = _send(writer, {"frame": _arr("frame", 1), "mask": _arr("mask", 2), "n": 1})
    for s in range(3):  # coll=3: кольцо mask обернулось -> ссылка broken на mask устарела
        _send(writer, {"mask": _arr("mask", 100 + s)})
    healthy = _send(writer, {"frame": _arr("frame", 3), "mask": _arr("mask", 4), "n": 2})
    chain_queue: queue.Queue = queue.Queue()

    collector = _run_receiver(reader, [broken, healthy], chain_queue)

    assert [it.get("n") for it in collector.items] == [2], (
        f"до коллектора дошли item'ы с n={[it.get('n') for it in collector.items]}, ожидалось только целое n=2"
    )
    assert collector.items[0]["mask"] is not None and collector.items[0]["frame"] is not None
    assert chain_queue.qsize() == 0, "в chain_queue что-то попало из отброшенного сообщения"
    assert reader.frame_stale_drops == 1
