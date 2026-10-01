# -*- coding: utf-8 -*-
"""Task 4.7a (P-2) — слепые приёмочные тесты двери отправки ``FrameShmMiddleware.strip_and_write``.

Контракт (дизайн лида): дверь проверяет входные view (``_inputs_still_valid``) и дропает item ТОЛЬКО
если что-то, скопированное в двери, — ndarray с ``flags.owndata == False`` (срез / view входа).
Выход без массивов или только с массивами-владельцами данных (``owndata``) ничего не скопировал из
слота входа -> отправляется, а перезапись слота входа не считается: ``frame_stale_drops`` не растёт.
Выход с не-owndata массивом (срез входа) + перезаписанный вход -> дроп, как сегодня.

Стенд — РЕАЛЬНЫЕ объекты: писатель ``A`` с настоящим SHM-кольцом (coll=3), отправитель ``B`` с
zero-copy view на слот ``A``, stale = настоящая перезапись ячейки писателем (кольцо обернулось).
Никаких подмен ``frame_view_valid``. Дроп наблюдаем так, как его видит роутер:
``strip_data_frame_on_send`` -> ``None`` (метка ``_shm_dropped`` у item'а).
"""

from __future__ import annotations

import gc
import os

import numpy as np
import pytest

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager

SHAPES = {"frame": (48, 64, 3), "mask": (100, 120)}  # оба >= 8192 Б -> уходят в кольцо ссылкой


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
            except Exception:  # noqa: BLE001
                pass


def _mw(made, owner: str, *, view: bool = False) -> FrameShmMiddleware:
    mm = MemoryManager()
    extra: dict = {}
    mw = FrameShmMiddleware(mm, owner=owner, slot="output_frames", coll=3, **extra)
    made.append((mw, mm))
    return mw


def _pair(made) -> tuple[FrameShmMiddleware, FrameShmMiddleware]:
    return _mw(made, "A"), _mw(made, "B", view=True)


def _arr(key: str, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 250, size=SHAPES[key]).astype(np.uint8)


def _send(mw: FrameShmMiddleware, item: dict):
    return mw.strip_data_frame_on_send({"target": "t", "type": "data", "channel": "data", "data": item})


def _overwrite_input(writer: FrameShmMiddleware) -> None:
    for s in range(3):  # coll=3: кольцо обернулось -> ячейка первой записи перезаписана
        _send(writer, {"frame": _arr("frame", 100 + s)})


def _received(writer: FrameShmMiddleware, sender: FrameShmMiddleware) -> dict:
    """Item, как он выглядит у отправителя после приёма: ``frame`` — zero-copy view на слот A,
    ``_shm_views`` — билет на него."""
    out = _send(writer, {"frame": _arr("frame", 1), "n": 1})
    msg = sender.restore_frame(out)
    item = dict(msg["data"])
    item["frame"] = msg["frame"]
    assert item["_shm_views"], "стенд неисправен: у принятого item'а нет view-билетов"
    assert not item["frame"].flags.owndata, "стенд неисправен: frame — не view"
    return item


def _output_item(received: dict, **outputs) -> dict:
    """Выход обработки: мета + билеты входа, БЕЗ самого входного ``frame`` — только то, что добавил
    алгоритм (``outputs``)."""
    return {"n": received["n"], "_shm_views": received["_shm_views"], **outputs}


# ----------------------------------------------------------------------------- RED сегодня
def test_dict_without_arrays_not_dropped_on_stale(made):
    """RED сегодня: выход — только словарь (счётчики/результат), ни одного массива -> ничего не
    скопировано из слота входа -> item уходит, хотя слот входа перезаписан; stale не посчитан.
    Сегодня ветка ``has_views`` дропает по перезаписи (None, frame_stale_drops == 1)."""
    writer, sender = _pair(made)
    received = _received(writer, sender)
    item = _output_item(received, result={"count": 3, "label": "ok"})
    _overwrite_input(writer)

    out = _send(sender, item)

    assert out is not None, "выход без массивов дропнут из-за перезаписи входа, который он не копировал"
    assert out["data"]["result"] == {"count": 3, "label": "ok"}
    assert "_shm_dropped" not in out["data"]
    assert sender.frame_stale_drops == 0


def test_owndata_copy_not_dropped_on_stale(made):
    """RED сегодня: малый inline-массив-владелец данных (``.copy()`` среза входа, owndata=True) ->
    пиксели уже снаружи слота -> item уходит с ОРИГИНАЛЬНЫМИ пикселями; stale не посчитан."""
    writer, sender = _pair(made)
    received = _received(writer, sender)
    want = _arr("frame", 1)[:8, :8].copy()
    own = received["frame"][:8, :8].copy()
    assert own.flags.owndata, "стенд неисправен: copy() не owndata"
    item = _output_item(received, crop=own)
    _overwrite_input(writer)

    out = _send(sender, item)

    assert out is not None, "owndata-копия дропнута из-за перезаписи входа"
    assert out["data"]["crop"].tobytes() == want.tobytes()
    assert sender.frame_stale_drops == 0


def test_owndata_large_array_not_dropped_on_stale(made):
    """RED сегодня: КРУПНЫЙ новый массив-владелец (mask >= 8192 Б — уходит в кольцо отправителя ссылкой)
    без единого view входа в выходе -> не дроп, ссылка на mask в ``_shm_refs``, stale не посчитан."""
    writer, sender = _pair(made)
    received = _received(writer, sender)
    mask = _arr("mask", 7)
    assert mask.flags.owndata
    item = _output_item(received, mask=mask)
    _overwrite_input(writer)

    out = _send(sender, item)

    assert out is not None, "крупный owndata-массив дропнут из-за перезаписи входа"
    assert "mask" in out["data"]["_shm_refs"], f"mask не ушёл ссылкой: {sorted(out['data'])}"
    assert sender.frame_stale_drops == 0


def test_strip_and_write_returns_item_without_drop_mark_for_owndata_output(made):
    """RED сегодня: тот же контракт на уровне самого ``strip_and_write`` (без обёртки send-middleware):
    возвращённый item НЕ несёт метку ``_shm_dropped``, локальная мета ``_shm_views`` снята."""
    writer, sender = _pair(made)
    received = _received(writer, sender)
    item = _output_item(received, result={"count": 3})
    _overwrite_input(writer)

    out = sender.strip_and_write(item)

    assert not out.get("_shm_dropped"), f"strip_and_write пометил item дропнутым: {out}"
    assert "_shm_views" not in out
    assert out["result"] == {"count": 3}


# ----------------------------------------------------------------------------- preservation
def test_view_slice_output_dropped_on_stale(made):
    """GREEN-by-design (preservation, зелёный до и после): малый срез входа (``owndata=False``) в
    выходе + перезаписанный вход -> дроп: ``strip_data_frame_on_send`` -> None, stale == 1."""
    writer, sender = _pair(made)
    received = _received(writer, sender)
    crop = received["frame"][:8, :8]
    assert not crop.flags.owndata
    item = _output_item(received, crop=crop)
    _overwrite_input(writer)

    assert _send(sender, item) is None, "срез view входа ушёл при перезаписанном входе"
    assert sender.frame_stale_drops == 1


def test_view_slice_output_marked_dropped_by_strip_and_write(made):
    """GREEN-by-design (preservation): то же на уровне ``strip_and_write`` — возвращён item с меткой
    ``_shm_dropped`` == True."""
    writer, sender = _pair(made)
    received = _received(writer, sender)
    item = _output_item(received, crop=received["frame"][:8, :8])
    _overwrite_input(writer)

    out = sender.strip_and_write(item)

    assert out.get("_shm_dropped") is True


def test_passthrough_input_frame_dropped_on_stale(made):
    """GREEN-by-design (preservation): сам входной ``frame`` (view, крупный -> копируется в кольцо
    двери, owndata=False) + перезаписанный вход -> дроп. Копия из слота входа реально снималась."""
    writer, sender = _pair(made)
    received = _received(writer, sender)
    item = _output_item(received, frame=received["frame"])
    _overwrite_input(writer)

    assert _send(sender, item) is None, "проброшенный frame (view) ушёл при перезаписанном входе"
    assert sender.frame_stale_drops == 1


def test_mixed_owndata_and_view_output_dropped_on_stale(made):
    """GREEN-by-design (preservation): в выходе и owndata-массив, и срез view входа -> одного
    не-owndata достаточно, чтобы проверять и дропнуть; stale посчитан один раз."""
    writer, sender = _pair(made)
    received = _received(writer, sender)
    item = _output_item(received, mask=_arr("mask", 7), crop=received["frame"][:8, :8])
    _overwrite_input(writer)

    assert _send(sender, item) is None
    assert sender.frame_stale_drops == 1


def test_not_stale_view_slice_output_sent(made):
    """CONTROL (зелёный до и после): вход НЕ перезаписан -> даже срез view уходит копией, stale 0.
    Привязывает красные тесты выше именно к перезаписи входа, а не к чему-то иному в стенде."""
    writer, sender = _pair(made)
    received = _received(writer, sender)
    want = _arr("frame", 1)[:8, :8].copy()
    item = _output_item(received, crop=received["frame"][:8, :8])

    out = _send(sender, item)

    assert out is not None
    assert out["data"]["crop"].tobytes() == want.tobytes()
    assert out["data"]["crop"].flags.owndata
    assert sender.frame_stale_drops == 0


def test_not_stale_dict_without_arrays_sent(made):
    """CONTROL (зелёный до и после): выход без массивов при НЕ перезаписанном входе уходит."""
    writer, sender = _pair(made)
    received = _received(writer, sender)
    out = _send(sender, _output_item(received, result={"count": 3}))
    assert out is not None and out["data"]["result"] == {"count": 3}
    assert sender.frame_stale_drops == 0
