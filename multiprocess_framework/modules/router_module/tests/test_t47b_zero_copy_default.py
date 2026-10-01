# -*- coding: utf-8 -*-
"""Task 4.7b — zero-copy по умолчанию для читателя-пайплайна, copy-out для остальных.

Слепой acceptance-тест (tester, от критериев приёмки 4.7b, без чтения реализации 4.7b).

Контракт (литералы):
  * ``restore_frame`` (читатель-пайплайн, ``allow_view=True``) БЕЗ env (``FW_SHM_*`` и ``FW_QOS_PROFILES``
    сняты) отдаёт массив-VIEW только для чтения: ``flags.writeable == False``, ``flags.owndata == False``,
    пиксели лежат в самом SHM-слоте (после оборота кольца писателя тот же view показывает новую запись);
    объём засчитан как отображённый (``bytes_mapped``), не как скопированный (``bytes_read``);
  * ``on_receive`` (copy-out: GUI, мост) отдаёт НЕЗАВИСИМУЮ записываемую копию (``owndata``, ``writeable``),
    не меняющуюся при перезаписи слота, со сверкой ``gen``: ссылка на уже перезаписанный слот → ``None``.

Конструкторы middleware вызываются БЕЗ флагов zero_copy / cache / owner_incarnation: после 4.7b этих
kwargs может не быть, а режим обязан быть единым.

GREEN-by-design (предохранитель, не RED): ``test_on_receive_returns_independent_writable_copy`` и
``test_on_receive_stale_gen_returns_none`` пинят поведение, которое уже есть и обязано пережить смену режима.
"""

from __future__ import annotations

import gc
import os

import numpy as np
import pytest

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager

DEPTH = 3
SHAPE = (8, 8, 3)
NBYTES = 192  # 8 * 8 * 3, uint8


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in [k for k in os.environ if k.startswith("FW_SHM_") or k == "FW_QOS_PROFILES"]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def pair():
    wmm, rmm = MemoryManager(), MemoryManager()
    writer = FrameShmMiddleware(wmm, owner="cam0", slot="output_frames", coll=DEPTH)
    reader = FrameShmMiddleware(rmm, owner="reader", slot="unused")
    yield writer, reader
    gc.collect()
    for fin in (reader.close_handle_cache, writer.release_owned_memory, rmm.close_all, wmm.close_all):
        try:
            fin()
        except Exception:  # noqa: BLE001 — уборка не должна маскировать причину падения теста
            pass


def _send(writer: FrameShmMiddleware, fill: int) -> dict:
    return writer.strip_and_write({"frame": np.full(SHAPE, fill, np.uint8)})


def _frame_of(msg: dict):
    return msg.get("frame") if msg.get("frame") is not None else msg["data"].get("frame")


@pytest.mark.xfail(strict=True, reason="RED-спека 4.7b, реализации нет")
def test_restore_frame_view_readonly_without_env(pair) -> None:
    writer, reader = pair
    out = _send(writer, 1)  # слот idx0
    msg = reader.restore_frame({"data": out})
    view = _frame_of(msg)
    assert view is not None, "кадр не восстановлен"
    assert view.flags.writeable is False, "view читателя-пайплайна должен быть read-only (без env)"
    assert view.flags.owndata is False, "это копия, а не view в SHM-слот"
    assert reader.bytes_mapped == NBYTES and reader.bytes_read == 0, "view засчитан не как отображённый"
    # view разделяет SHM-буфер: оборот кольца писателя (idx1, idx2, снова idx0) виден через тот же массив
    for fill in (2, 3, 4):
        _send(writer, fill)
    assert int(view.min()) == int(view.max()) == 4, "view не разделяет память слота с писателем"
    with pytest.raises(ValueError):
        view[0, 0, 0] = 9  # запись в read-only view запрещена
    del view, msg


def test_on_receive_returns_independent_writable_copy(pair) -> None:
    writer, reader = pair
    out = _send(writer, 1)
    msg = reader.on_receive({"data": out})
    assert msg is not None, "on_receive отбросил свежий кадр"
    frame = _frame_of(msg)
    assert frame is not None
    assert frame.flags.owndata is True and frame.flags.writeable is True, "copy-out обязан отдавать записываемую копию"
    for fill in (2, 3, 4):  # оборот кольца: исходный слот перезаписан
        _send(writer, fill)
    assert int(frame.min()) == int(frame.max()) == 1, "копия изменилась вслед за слотом — это view"
    frame[0, 0, 0] = 9  # записываемость — наблюдаемым эффектом
    assert int(frame[0, 0, 0]) == 9


def test_on_receive_stale_gen_returns_none(pair) -> None:
    writer, reader = pair
    stale = _send(writer, 1)  # ссылка на слот idx0
    for fill in (2, 3, 4):  # слот idx0 перезаписан -> поколение ссылки устарело
        _send(writer, fill)
    assert reader.on_receive({"data": stale}) is None, "устаревшее поколение должно дать None (drop), не чужие пиксели"
