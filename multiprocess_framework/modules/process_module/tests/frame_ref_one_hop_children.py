# -*- coding: utf-8 -*-
"""Код дочерних процессов A6 (Task 4.4): цепочка A -> B -> C, каждый — отдельный ОС-процесс (spawn).

Модуль лежит рядом с ``test_frame_ref_one_hop_mp.py`` и НЕ содержит тестов: на Windows spawn заново
импортирует модуль цели в ребёнке, и тест-модуль с pytest-фикстурами для этого не годится.

Роли (литералы сценария, проверяются родителем):
  * A — писатель кольца (coll=3): шлёт B сообщение ``{frame, foo, n}``; ПОСЛЕ того как B переслал
    дальше, ПЕРЕПИСЫВАЕТ оба своих кольца мусором (ссылка A на любую ячейку после этого — чужой кадр);
  * B — конвейер: читает view у A, плагин пересобирает item свежим dict'ом (``dict(item)`` — входные
    поля, в том числе унаследованные ссылки, при этом остаются), подменяет ``frame`` на
    ``255 - frame_A``, ВЫБРАСЫВАЕТ ``foo``, добавляет НОВЫЙ ключ ``mask``; отправляет через
    send-middleware в C;
  * C — читатель: принимает провод B, снимает с него все значения ключей ``owner``/``shm_owner``
    и восстанавливает item настоящим ``DataReceiver._build_item``.
"""

from __future__ import annotations

import gc
import pickle
import queue
import threading
import time
import traceback
from typing import Any

import numpy as np

from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver
from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)

SHAPES: dict[str, tuple[tuple[int, ...], str]] = {
    "frame": ((48, 64, 3), "uint8"),  # 9216 Б
    "foo": ((100, 100), "uint8"),  # 10000 Б
    "mask": ((100, 120), "uint8"),  # 12000 Б
}
WAIT_S = 45.0


def make_array(key: str, seed: int) -> np.ndarray:
    """Детерминированное содержимое: родитель пересчитывает ожидаемые пиксели теми же сидами."""
    shape, dtype = SHAPES[key]
    return np.random.default_rng(seed).integers(0, 250, size=shape).astype(dtype)


def b_frame_from(frame_a: np.ndarray) -> np.ndarray:
    """Пиксели, которые B пишет под ``frame`` (отличны от A по построению)."""
    return (255 - frame_a).astype(np.uint8)


def _send_msg(mw: FrameShmMiddleware, data: dict) -> dict:
    out = mw.strip_data_frame_on_send({"target": "x", "type": "data", "channel": "data", "data": data})
    assert out is not None, "send-middleware отбросил сообщение"
    return out


def _all_owner_values(obj: Any) -> list[str]:
    """Значения ключей ``owner``/``shm_owner`` на любой глубине сообщения (кто владелец ссылки)."""
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("owner", "shm_owner") and isinstance(v, str):
                found.append(v)
            found += _all_owner_values(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            found += _all_owner_values(v)
    return found


def child_a(q_ab, evt_b_forwarded, evt_garbage_done, evt_done, res_q) -> None:
    mm = None
    try:
        mm = MemoryManager()
        a = FrameShmMiddleware(mm, owner="A", slot="output_frames", coll=3)
        wire = _send_msg(a, {"frame": make_array("frame", 1), "foo": make_array("foo", 2), "n": 1})
        q_ab.put(pickle.dumps(wire))
        if not evt_b_forwarded.wait(WAIT_S):
            raise TimeoutError("B не переслал сообщение за отведённое время")
        for s in range(3):  # оборот обоих колец: любая ссылка A теперь указывает на мусор
            _send_msg(a, {"frame": make_array("frame", 500 + s), "foo": make_array("foo", 600 + s)})
        evt_garbage_done.set()
        evt_done.wait(WAIT_S)
        res_q.put(("a", "ok", None))
    except BaseException:  # noqa: BLE001 — любую ошибку ребёнка вернуть родителю текстом
        evt_garbage_done.set()
        res_q.put(("a", "error", traceback.format_exc()))
    finally:
        _teardown(mm)


class _PluginB:
    """Плагин B: свежий dict (``dict(item)``), подмена frame, выброс foo, новый ключ mask."""

    name = "b_transform"
    enabled = True
    inputs: list = []
    outputs: list = []

    def process(self, items: list[dict]) -> list[dict]:
        out = []
        for item in items:
            new = dict(item)
            new["frame"] = b_frame_from(np.array(item["frame"]))
            new.pop("foo", None)
            new["mask"] = make_array("mask", 3)
            out.append(new)
        return out


def child_b(q_ab, q_bc, evt_b_forwarded, evt_done, res_q) -> None:
    mm = None
    try:
        mm = MemoryManager()
        # B читает у A view'ом (как боевой конвейер) и пишет в СВОЁ кольцо.
        b = FrameShmMiddleware(
            mm, owner="B", slot="output_frames", coll=3, owner_incarnation=True, cache_shm_handles=True, zero_copy=True
        )
        wire = pickle.loads(q_ab.get(timeout=WAIT_S))
        receiver = DataReceiver(
            receive_fn=lambda **_: None,
            shm_middleware=b,
            item_collector=None,
            chain_queue=queue.Queue(),
            node_name="B",
        )
        item = receiver._build_item(b.restore_frame(wire))
        forwarded: list[bytes] = []

        def send_fn(target: str, msg: dict) -> None:
            out = b.strip_data_frame_on_send(msg)  # send-middleware роутера; None = дроп
            if out is not None:
                blob = pickle.dumps(out)  # сразу: очередь сериализует в фоне, а item ещё живой
                forwarded.append(blob)
                q_bc.put(blob)

        ex = PipelineExecutor(
            plugins=[_PluginB()], chain_targets=["C"], shm_middleware=b, send_fn=send_fn, node_name="B"
        )
        work: queue.Queue = queue.Queue()
        work.put([item])
        ex.bind_queue(work)
        stop, pause = threading.Event(), threading.Event()
        worker = threading.Thread(target=ex.run, args=(stop, pause), daemon=True)
        worker.start()
        deadline = time.monotonic() + 20.0
        while not forwarded and time.monotonic() < deadline:
            time.sleep(0.01)
        stop.set()
        worker.join(10.0)
        if not forwarded:
            raise RuntimeError(f"B ничего не отправил в C (stale={b.frame_stale_drops} torn={b.frame_torn_reads})")
        evt_b_forwarded.set()
        evt_done.wait(WAIT_S)
        res_q.put(("b", "ok", {"stale": b.frame_stale_drops, "torn": b.frame_torn_reads}))
    except BaseException:  # noqa: BLE001
        evt_b_forwarded.set()
        res_q.put(("b", "error", traceback.format_exc()))
    finally:
        _teardown(mm)


def child_c(q_bc, evt_garbage_done, res_q) -> None:
    mm = None
    try:
        mm = MemoryManager()
        c = FrameShmMiddleware(mm, owner="C", slot="unused", zero_copy=False)
        wire = pickle.loads(q_bc.get(timeout=WAIT_S))
        if not evt_garbage_done.wait(WAIT_S):
            raise TimeoutError("A не закончил порчу колец за отведённое время")
        owners = sorted(set(_all_owner_values(wire)))
        receiver = DataReceiver(
            receive_fn=lambda **_: None,
            shm_middleware=c,
            item_collector=None,
            chain_queue=queue.Queue(),
            node_name="C",
        )
        item = receiver._build_item(c.restore_frame(wire))
        arrays = {k: (v.tobytes(), tuple(v.shape), str(v.dtype)) for k, v in item.items() if isinstance(v, np.ndarray)}
        res_q.put(
            ("c", "ok", {"owners": owners, "arrays": arrays, "stale": c.frame_stale_drops, "torn": c.frame_torn_reads})
        )
    except BaseException:  # noqa: BLE001
        res_q.put(("c", "error", traceback.format_exc()))
    finally:
        _teardown(mm)


def _teardown(mm: Any) -> None:
    gc.collect()
    if mm is not None:
        try:
            mm.close_all()
        except Exception:  # noqa: BLE001 — teardown ребёнка не должен маскировать причину
            pass
