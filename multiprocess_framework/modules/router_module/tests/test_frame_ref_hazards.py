# -*- coding: utf-8 -*-
"""Task 4.4 — авторские тесты опасных мест механизма «ссылка = кадр» (роль author, не tester).

Что может сломаться именно в ЭТОМ механизме, как он устроен:
  * дверь отправки помечает item ``_shm_dropped``, а fan-out повторяет ТОТ ЖЕ dict — повтор
    обязан быть дропнут без повторной записи и без повторного счёта stale (один раз на item);
  * две устаревшие входные ссылки считаются ОДНИМ дропом (проверка останавливается на первой);
  * здоровый item на повторе не пишет заново и не несёт ни ``_shm_views``, ни чужих ссылок;
  * унаследованные ссылки не переживают send-дверь, даже когда своих массивов нет;
  * тикеты loan/evict строятся из ссылки ``{owner, slot, idx, gen, name}``;
  * 4.4c: item атомарен — если ХОТЬ ОДНА ссылка сообщения не читается (stale/torn), сообщение
    отбрасывается ЦЕЛИКОМ (никаких ``mask=None`` при живом ``frame``), чтение останавливается на
    первой неудаче, счётчик считает СООБЩЕНИЯ.
"""

from __future__ import annotations

import gc
import os
from types import SimpleNamespace

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager

SHAPES = {"frame": (48, 64, 3), "foo": (100, 100), "mask": (100, 120)}  # все >= 8192 Б


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


def _mw(made, owner: str, *, view: bool = False, **kw) -> FrameShmMiddleware:
    mm = MemoryManager()
    extra = dict(owner_incarnation=True, cache_shm_handles=True, zero_copy=True) if view else {"zero_copy": False}
    mw = FrameShmMiddleware(mm, owner=owner, slot="output_frames", coll=3, **extra, **kw)
    made.append((mw, mm))
    return mw


def _arr(key: str, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 250, size=SHAPES[key]).astype(np.uint8)


def _send(mw: FrameShmMiddleware, item: dict):
    return mw.strip_data_frame_on_send({"target": "t", "type": "data", "channel": "data", "data": item})


def _overwrite(writer: FrameShmMiddleware, key: str) -> None:
    for s in range(3):  # coll=3: кольцо обернулось -> ячейка первой записи перезаписана
        _send(writer, {key: _arr(key, 100 + s)})


def _receive_views(writer, reader, keys=("frame", "foo")) -> dict:
    out = _send(writer, {k: _arr(k, 1) for k in keys} | {"n": 1})
    msg = reader.restore_frame(out)
    item = dict(msg["data"])
    item["frame"] = msg["frame"]
    return item


def test_dropped_item_fan_out_replay_drops_every_target_counts_stale_once_writes_once(made):
    """Оба входных view (frame и foo) перезаписаны, пока item копировали: первая цель -> None,
    повтор на вторую цель -> None, ``frame_stale_drops`` == 1 (не 2 по числу ссылок и не 3 по
    числу отправок), а новая запись в кольцо ровно одна (повтор не пишет заново)."""
    writer, sender = _mw(made, "A"), _mw(made, "B", view=True)
    item = _receive_views(writer, sender)
    assert len(item["_shm_views"]) == 2
    _overwrite(writer, "frame")
    _overwrite(writer, "foo")
    hops_before = sender.frame_boundary_crossings

    assert _send(sender, item) is None
    assert _send(sender, item) is None
    assert _send(sender, item) is None
    assert sender.frame_stale_drops == 1, f"stale = {sender.frame_stale_drops}, ожидалось 1 на item"
    assert sender.frame_boundary_crossings == hops_before + 1, "повтор дропнутого item'а считан как граница/запись"


def test_healthy_item_replay_keeps_same_refs_no_views_no_inbound_refs(made):
    """Здорового item'а: второй send несёт ТЕ ЖЕ ссылки (запись одна), ни ``_shm_views``, ни ссылок
    предыдущего хопа на выходе нет; граница считается на каждый send."""
    writer, sender = _mw(made, "A"), _mw(made, "B", view=True)
    item = _receive_views(writer, sender)
    first = _send(sender, item)
    refs_first = dict(first["data"]["_shm_refs"])
    hops = sender.frame_boundary_crossings
    second = _send(sender, item)

    assert second is not None and second["data"]["_shm_refs"] == refs_first
    assert {r["owner"] for r in refs_first.values()} == {"B"}
    assert "_shm_views" not in second["data"] and "_shm_dropped" not in second["data"]
    assert sender.frame_boundary_crossings == hops + 1


def test_inbound_refs_are_stripped_even_without_own_arrays(made):
    """Item несёт ссылки A, но ни одного своего крупного массива (плагин всё выбросил): исходящее
    сообщение не содержит ни ``_shm_refs``, ни ``_shm_views`` — иначе C прочёл бы ссылку A."""
    writer, sender = _mw(made, "A"), _mw(made, "B", view=True)
    item = _receive_views(writer, sender)
    item.pop("frame")
    item.pop("foo")
    out = _send(sender, item)
    assert out is not None
    assert "_shm_refs" not in out["data"] and "_shm_views" not in out["data"]


def test_loan_ticket_is_built_from_the_ref(made):
    """Loan-тикет executor'а: ``{slot, index, generation, reader}`` из ссылки (slot=кольцо, index=idx,
    generation=gen), владелец = ``ref["owner"]``."""
    writer = _mw(made, "A")
    reader = _mw(made, "B", view=True, loan_protocol=True)
    item = _receive_views(writer, reader, keys=("frame",))
    ref = item["_shm_views"][0]
    ex = PipelineExecutor(plugins=[], chain_targets=[], shm_middleware=reader, send_fn=lambda *_: None, node_name="B")
    tickets = ex._collect_view_tickets([item])
    ex._accumulate_releases(tickets)
    assert ex._pending_releases == {
        "A": [{"slot": ref["slot"], "index": ref["idx"], "generation": ref["gen"], "reader": "B"}]
    }
    assert ref["slot"] == "output_frames" and ref["gen"] % 2 == 0


def test_evicted_release_tickets_come_from_refs():
    """``_on_frame_evicted``: по тикету на каждую ссылку ``_shm_refs`` (frame и крупные ключи), с
    ``generation`` из ссылки и ``evicted=True``; сообщение без ссылок ничего не шлёт."""
    sent: list[tuple[str, str, dict]] = []
    qr = SimpleNamespace(send_to_queue=lambda owner, qtype, msg: sent.append((owner, qtype, msg)))
    router = SimpleNamespace(queue_registry=qr, _log_debug=lambda *_: None)
    refs = {
        "frame": {"owner": "A", "slot": "output_frames", "idx": 1, "gen": 4, "name": "n1"},
        "foo": {"owner": "A", "slot": "output_frames__foo", "idx": 2, "gen": 6, "name": "n2"},
    }
    RouterManager._on_frame_evicted(router, {"data": {"_shm_refs": refs}}, "B")
    assert len(sent) == 1
    owner, qtype, msg = sent[0]
    assert (owner, qtype) == ("A", "system")
    assert msg["data"]["evicted"] is True
    assert msg["data"]["releases"] == [
        {"slot": "output_frames", "index": 1, "generation": 4, "reader": "B"},
        {"slot": "output_frames__foo", "index": 2, "generation": 6, "reader": "B"},
    ]
    sent.clear()
    RouterManager._on_frame_evicted(router, {"data": {"n": 1}}, "B")
    assert sent == []


# ===================== 4.4c: item атомарен (frame прочитан, mask перезаписана) =====================
def _wire_frame_and_mask(writer):
    """Провод-сообщение с двумя ссылками (frame, mask) + ссылка на mask, которую потом перепишут."""
    import pickle

    out = _send(writer, {"frame": _arr("frame", 1), "mask": _arr("mask", 2), "n": 1})
    return pickle.loads(pickle.dumps(out))


@pytest.mark.parametrize("view", [False, True], ids=["copy", "view"])
def test_frame_ok_mask_stale_drops_whole_message_restore(made, view):
    """Живой стенд 1080p: frame прочитан целым, mask перезаписана -> сообщение отброшено ЦЕЛИКОМ:
    ни ``frame``, ни ``mask`` не восстановлены, метка ``_shm_dropped`` стоит, view-билетов нет,
    ``frame_stale_drops`` == 1 (одно сообщение), torn == 0."""
    writer, reader = _mw(made, "A"), _mw(made, "B", view=view)
    wire = _wire_frame_and_mask(writer)
    _overwrite(writer, "mask")  # кольцо mask обернулось, кольцо frame не тронуто

    msg = reader.restore_frame(wire)
    data = msg["data"]
    assert msg.get("frame") is None and data.get("frame") is None, "frame доставлен при потерянной mask"
    assert "mask" not in data, "под ключом mask лежит значение (None тоже нельзя: ключ обязан отсутствовать)"
    assert data.get("_shm_dropped") is True
    assert "_shm_views" not in data
    assert reader.frame_stale_drops == 1 and reader.frame_torn_reads == 0


def test_frame_ok_mask_stale_on_receive_returns_none(made):
    """Copy-out (GUI): frame цел, mask перезаписана -> ``on_receive`` возвращает ``None``
    (RouterManager считает это middleware_dropped), ``frame_stale_drops`` == 1."""
    writer, gui = _mw(made, "A"), _mw(made, "gui")
    wire = _wire_frame_and_mask(writer)
    _overwrite(writer, "mask")

    assert gui.on_receive(wire) is None
    assert gui.frame_stale_drops == 1 and gui.frame_torn_reads == 0


def test_first_ref_stale_second_not_read(made):
    """Чтение останавливается на первой неудаче: frame перезаписан, mask жива -> сегмент mask
    НЕ открыт reader'ом (граница reader'а: view-режим кэширует каждый открытый handle, в кэше
    только сегмент frame), stale == 1."""
    writer, reader = _mw(made, "A"), _mw(made, "B", view=True)
    wire = _wire_frame_and_mask(writer)
    _overwrite(writer, "frame")
    assert reader.frame_handle_cache_size == 0

    msg = reader.restore_frame(wire)
    assert msg["data"].get("_shm_dropped") is True
    assert reader.frame_handle_cache_size == 1, "сегмент mask прочитан, хотя frame уже провалился"
    assert reader.frame_stale_drops == 1


def test_torn_on_second_ref_counts_one_torn_message(made):
    """frame цел, mask рвётся (ссылка на нечётное поколение слота — writer «в процессе»): сообщение
    отброшено целиком, ``frame_torn_reads`` == 1, ``frame_stale_drops`` == 0."""
    from multiprocess_framework.modules.shared_resources_module.memory.format import buffer as buf_mod

    writer, reader = _mw(made, "A"), _mw(made, "B")
    wire = _wire_frame_and_mask(writer)
    ref = wire["data"]["_shm_refs"]["mask"]
    handle = writer._mm.get_memory_data("A", ref["slot"])["handles"][ref["idx"]]
    odd = buf_mod.read_generation(handle.buf) + 1
    buf_mod._write_generation(handle.buf, odd)
    ref["gen"] = odd

    msg = reader.restore_frame(wire)
    assert msg.get("frame") is None and msg["data"].get("frame") is None
    assert "mask" not in msg["data"] and msg["data"].get("_shm_dropped") is True
    assert reader.frame_torn_reads == 1 and reader.frame_stale_drops == 0


def test_unlinked_segment_ref_is_stale_drop_counted_without_error_log(made):
    """Сегмент ссылки отвязан (realloc кольца у владельца): открытие бросает раньше проверки
    поколения — это тот же stale: сообщение отброшено целиком, ``frame_stale_drops`` == 1, ERROR-лога
    на каждое такое сообщение нет."""
    logs: list[str] = []
    writer = _mw(made, "A")
    reader = _mw(made, "B", log_error=logs.append)
    wire = _wire_frame_and_mask(writer)
    wire["data"]["_shm_refs"]["mask"]["name"] = "no_such_segment_4_4c"

    msg = reader.restore_frame(wire)
    assert msg["data"].get("_shm_dropped") is True and "mask" not in msg["data"]
    assert msg.get("frame") is None
    assert reader.frame_stale_drops == 1 and reader.frame_torn_reads == 0
    assert logs == [], f"stale-дроп отвязанного сегмента залогирован как ошибка: {logs}"
