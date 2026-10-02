# -*- coding: utf-8 -*-
"""Task 4.7d-3 — слепые приёмочные тесты маркера ``not_inspected`` в двери отправителя.

Источник: plans/transport-single-policy/task-4.7.md, acceptance 4.7d-3 (только критерии, без реализации).

Контракт: под ``overflow="every"`` дверь отправки (``FrameShmMiddleware.strip_data_frame_on_send``) при
дропе по ``_inputs_still_valid`` НЕ возвращает ``None``, а заменяет ``msg["data"]`` маркером
``reason="door"`` и отправляет сообщение; под ``latest`` — ``None``, как сегодня. Счётчик ``door_drops``
(всегда) растёт на один item, ``not_inspected_door`` (только ``every``) — на одно рождение маркера.

Стенд — РЕАЛЬНЫЕ объекты и тот же приём, что у дверных тестов 4.7a (``test_t47a_door_owndata.py``):
писатель ``A`` с настоящим SHM-кольцом (coll=3), отправитель ``B`` с zero-copy view на слот ``A``,
перезапись входа = кольцо ``A`` обернулось. Выход со срезом входа (``crop``) смотрит в чужой слот, поэтому
при перезаписанном входе дверь его дропает. Ожидаемые значения — литералы.

Зелёные контроли (поведение не меняется): ``latest`` по умолчанию возвращает ``None``; валидный вход идёт
как раньше; исчерпание займа — ``None``. Всё, что трогает ``overflow=`` / ``door_drops`` /
``not_inspected_door`` — красное до реализации.

Любой вызов двери идёт в daemon-потоке с дедлайном на ``join`` (``_bounded``): pytest-timeout в venv нет.
"""

from __future__ import annotations

import gc
import os
import pickle
import threading

import numpy as np
import pytest

from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import is_marker
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager

SHAPES = {"frame": (48, 64, 3)}  # >= 8192 Б -> уходит в кольцо ссылкой
META = {"trace_id": "tr-1", "capture_ts": 12.5, "frame_id": 7, "camera_id": "cam0"}

# Маркер двери, как его ждёт читатель: литерал из контракта 4.7d-1 + reason="door", source = имя отправителя.
MARKER = {
    "inspection_status": "not_inspected",
    "overflow_marker": True,
    "reason": "door",
    "source": "B",
    "trace_id": "tr-1",
    "capture_ts": 12.5,
    "frame_id": 7,
    "camera_id": "cam0",
}
FORBIDDEN_KEYS = ("frame", "_shm_refs", "_shm_views", "_shm_dropped")

EVERY = {"overflow": "every"}
LATEST_DEFAULT = {}  # конструктор без kwarg == latest (поведение сегодня)
LATEST_EXPLICIT = {"overflow": "latest"}


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


def _mw(made, owner: str, **kw) -> FrameShmMiddleware:
    mm = MemoryManager()
    kw.setdefault("coll", 3)
    mw = FrameShmMiddleware(mm, owner=owner, slot="output_frames", **kw)
    made.append((mw, mm))
    return mw


def _arr(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 250, size=SHAPES["frame"]).astype(np.uint8)


def _bounded(fn, deadline: float = 30.0):
    """Вызов ``fn`` в daemon-потоке с дедлайном: зависание = падение теста, а не висящий прогон."""
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(deadline)
    assert not t.is_alive(), f"вызов завис дольше {deadline} с"
    if "error" in box:
        raise box["error"]
    return box["result"]


def _msg(item: dict, target: str = "t", channel: str = "data") -> dict:
    return {"target": target, "type": "data", "channel": channel, "data": item}


def _send(mw: FrameShmMiddleware, item: dict, target: str = "t", channel: str = "data"):
    return _bounded(lambda: mw.strip_data_frame_on_send(_msg(item, target, channel)))


def _received(made, **sender_kw) -> tuple[FrameShmMiddleware, FrameShmMiddleware, dict]:
    """(писатель A, отправитель B, item B после приёма): ``frame`` — zero-copy view на слот A,
    ``_shm_views`` — билет на него, мета кадра (``META``) едет в data."""
    writer, sender = _mw(made, "A"), _mw(made, "B", **sender_kw)
    out = _send(writer, {"frame": _arr(1), "n": 1, **META})
    msg = sender.restore_frame(out)
    item = dict(msg["data"])
    item["frame"] = msg["frame"]
    assert item["_shm_views"] and not item["frame"].flags.owndata, "стенд неисправен: нет view-билетов"
    assert item["trace_id"] == "tr-1" and item["frame_id"] == 7, "стенд неисправен: мета не доехала до B"
    return writer, sender, item


def _overwrite_input(writer: FrameShmMiddleware) -> None:
    for s in range(3):  # coll=3: кольцо обернулось -> ячейка первой записи перезаписана
        _send(writer, {"frame": _arr(100 + s)})


def _output(received: dict, **outputs) -> dict:
    """Выход обработки: мета item'а + билеты входа + то, что добавил алгоритм (``outputs``)."""
    meta = {k: received[k] for k in META}
    return {"n": received["n"], "_shm_views": received["_shm_views"], **meta, **outputs}


def _door_drop_item(received: dict) -> dict:
    """Условие дропа 4.7a: срез ЧУЖОГО слота во выходе (``crop`` смотрит в память входа)."""
    crop = received["frame"][:8, :8]
    assert not crop.flags.owndata, "стенд неисправен: crop — не view"
    return _output(received, crop=crop)


# ======================================================================= every: одна цель
def test_every_door_drop_delivers_marker_instead_of_none(made):
    """Вход перезаписан, выход смотрит в его слот: под ``every`` сообщение уходит (не ``None``),
    а ``msg["data"]`` — ровно маркер ``reason="door"`` с метой исходного item'а и ``source == owner``."""
    writer, sender, received = _received(made, **EVERY)
    item = _door_drop_item(received)
    _overwrite_input(writer)

    out = _send(sender, item)

    assert out is not None, "под every дверь вернула None вместо маркера"
    assert out["data"] == MARKER


def test_every_marker_has_no_frame_or_shm_keys(made):
    """В маркере нет ни кадра, ни SHM-служебных ключей (ссылки/билеты/метка дропа)."""
    writer, sender, received = _received(made, **EVERY)
    item = _door_drop_item(received)
    _overwrite_input(writer)

    out = _send(sender, item)

    assert out is not None
    leaked = [k for k in FORBIDDEN_KEYS if k in out["data"]]
    assert not leaked, f"в маркере остались ключи {leaked}: {sorted(out['data'])}"


def test_every_door_drop_counters(made):
    """``door_drops == 1``, ``not_inspected_door == 1``, ``frame_stale_drops`` вырос ровно на 1
    (``door_drops`` — подмножество ``frame_stale_drops``)."""
    writer, sender, received = _received(made, **EVERY)
    item = _door_drop_item(received)
    _overwrite_input(writer)
    stale_before = sender.frame_stale_drops

    _send(sender, item)

    assert sender.door_drops == 1
    assert sender.not_inspected_door == 1
    assert sender.frame_stale_drops - stale_before == 1


def test_every_marker_keeps_message_target_type_and_channel(made):
    """Замена содержимого не трогает ``msg["target"]``, ``type``, ``channel``."""
    writer, sender, received = _received(made, **EVERY)
    item = _door_drop_item(received)
    _overwrite_input(writer)

    out = _send(sender, item, target="line_2", channel="data_ch")

    assert out is not None
    assert out["target"] == "line_2"
    assert out["type"] == "data"
    assert out["channel"] == "data_ch"


# ================================================================== every: fan-out на 2 цели
def _fanout(sender: FrameShmMiddleware, item: dict):
    """Как ``_send_results``: два сообщения на разные цели делят ОДИН и тот же ``data``-dict."""
    msg1 = _msg(item, target="t1")
    msg2 = _msg(item, target="t2")
    out1 = _bounded(lambda: sender.strip_data_frame_on_send(msg1))
    out2 = _bounded(lambda: sender.strip_data_frame_on_send(msg2))
    return out1, out2


def test_every_fanout_delivers_same_marker_to_both_targets(made):
    """Оба вызова возвращают сообщение (не ``None``) с одним и тем же маркером; целевые адреса
    своих сообщений сохранены."""
    writer, sender, received = _received(made, **EVERY)
    item = _door_drop_item(received)
    _overwrite_input(writer)

    out1, out2 = _fanout(sender, item)

    assert out1 is not None and out2 is not None, "одна из целей fan-out осталась без маркера"
    assert out1["data"] == MARKER
    assert out2["data"] == MARKER
    assert (out1["target"], out2["target"]) == ("t1", "t2")


def test_every_fanout_birth_counted_once_not_per_target(made):
    """Рождено один раз, доставлено два: ``not_inspected_door == 1`` и ``door_drops == 1``
    (``door_drops`` считает item, а не цель)."""
    writer, sender, received = _received(made, **EVERY)
    item = _door_drop_item(received)
    _overwrite_input(writer)

    _fanout(sender, item)

    assert sender.not_inspected_door == 1, "маркер родился повторно на второй цели"
    assert sender.door_drops == 1


# ================================================================================ latest
@pytest.mark.parametrize("kw", [LATEST_DEFAULT, LATEST_EXPLICIT], ids=["default", "explicit-latest"])
def test_latest_door_drop_returns_none(made, kw):
    """Тот же вход под ``latest`` (по умолчанию и явно): ``None``, как сегодня."""
    writer, sender, received = _received(made, **kw)
    item = _door_drop_item(received)
    _overwrite_input(writer)

    assert _send(sender, item) is None


def test_latest_door_drops_counted(made):
    """Под ``latest`` дроп двери всё равно виден: ``door_drops == 1``."""
    writer, sender, received = _received(made, **LATEST_DEFAULT)
    item = _door_drop_item(received)
    _overwrite_input(writer)

    _send(sender, item)

    assert sender.door_drops == 1


def test_latest_fanout_door_drop_counted_once_not_per_target(made):
    """Fan-out под ``latest``: обе цели получают ``None``, а ``door_drops`` — 1 (на item, не на цель)."""
    writer, sender, received = _received(made, **LATEST_DEFAULT)
    item = _door_drop_item(received)
    _overwrite_input(writer)

    out1, out2 = _fanout(sender, item)

    assert out1 is None and out2 is None
    assert sender.door_drops == 1


def test_door_drop_counted_in_strip_and_write_once_per_item(made):
    """Инкремент живёт в ``strip_and_write``: прямой вызов помечает item ``_shm_dropped`` и считает
    ``door_drops == 1``; повтор на том же (уже отброшенном) item'е счёт не меняет."""
    writer, sender, received = _received(made, **LATEST_DEFAULT)
    item = _door_drop_item(received)
    _overwrite_input(writer)

    assert sender.strip_and_write(item).get("_shm_dropped") is True
    assert sender.strip_and_write(item).get("_shm_dropped") is True

    assert sender.door_drops == 1


# ============================================================== валидный вход / чужой памяти нет
def test_valid_input_sent_unchanged_default(made):
    """CONTROL (зелёный до и после): вход НЕ перезаписан -> срез уходит копией, маркера нет."""
    _, sender, received = _received(made, **LATEST_DEFAULT)
    want = _arr(1)[:8, :8].copy()

    out = _send(sender, _door_drop_item(received))

    assert out is not None
    assert not is_marker(out["data"])
    assert out["data"]["crop"].tobytes() == want.tobytes()


def test_valid_input_sent_unchanged_every(made):
    """``every``: вход валиден -> маркера нет, сообщение идёт как раньше (срез копией)."""
    _, sender, received = _received(made, **EVERY)
    want = _arr(1)[:8, :8].copy()

    out = _send(sender, _door_drop_item(received))

    assert out is not None
    assert not is_marker(out["data"])
    assert out["data"]["crop"].tobytes() == want.tobytes()


@pytest.mark.parametrize("kw", [LATEST_EXPLICIT, EVERY], ids=["latest", "every"])
def test_valid_input_door_drops_zero(made, kw):
    """Вход валиден -> дропа двери нет, ``door_drops == 0`` в обоих режимах."""
    _, sender, received = _received(made, **kw)

    _send(sender, _door_drop_item(received))

    assert sender.door_drops == 0


@pytest.mark.parametrize("kw", [LATEST_EXPLICIT, EVERY], ids=["latest", "every"])
def test_output_without_foreign_memory_sent_and_door_drops_zero(made, kw):
    """4.7a: выход без чужой памяти (только dict) + перезаписанный вход -> уходит как есть, не маркер,
    ``door_drops == 0``."""
    writer, sender, received = _received(made, **kw)
    item = _output(received, result={"count": 3})
    _overwrite_input(writer)

    out = _send(sender, item)

    assert out is not None
    assert not is_marker(out["data"])
    assert out["data"]["result"] == {"count": 3}
    assert sender.door_drops == 0


# ============================================================ исчерпание займа (loan frozen)
def _exhausted_sender(made, **kw) -> FrameShmMiddleware:
    """Отправитель с loan-протоколом и кольцом из двух слотов: два кадра занимают оба (release нет),
    третий упирается в исчерпание."""
    sender = _mw(made, "L", coll=2, loan_protocol=True, num_consumers=1, **kw)
    for i in range(2):
        assert _send(sender, {"frame": _arr(200 + i)}) is not None, "стенд неисправен: займ исчерпан рано"
    return sender


@pytest.mark.parametrize("kw", [LATEST_DEFAULT, EVERY], ids=["latest", "every"])
def test_loan_exhausted_still_returns_none(made, kw):
    """Исчерпание займа — дроп ``None`` в обоих режимах (вне 4.7d, не маркер)."""
    sender = _exhausted_sender(made, **kw)

    out = _send(sender, {"frame": _arr(9)})

    assert sender.frame_loan_exhausted == 1, "стенд неисправен: дроп не по исчерпанию займа"
    assert out is None


def test_loan_exhausted_is_not_a_door_drop(made):
    """Исчерпание займа не входит в ``door_drops`` / ``not_inspected_door`` (дроп по ``_inputs_still_valid``
    — единственный источник этих счётчиков)."""
    sender = _exhausted_sender(made, **EVERY)

    _send(sender, {"frame": _arr(9)})

    assert sender.door_drops == 0
    assert sender.not_inspected_door == 0


# =================================================== реальный путь: писатель -> отправитель -> читатель
def _over_the_wire(msg):
    """IPC-граница: сообщение между процессами едет pickle'ом."""
    return pickle.loads(pickle.dumps(msg))


def test_real_path_every_reader_gets_marker_item(made):
    """Три настоящих middleware: A пишет, B (every) получает view, вход перезаписывается, дверь B
    отправляет маркер -> читатель C (restore_frame, как DataReceiver) получает item, для которого
    ``is_marker`` истинно."""
    writer, sender, received = _received(made, **EVERY)
    reader = _mw(made, "C")
    item = _door_drop_item(received)
    _overwrite_input(writer)

    out = _send(sender, item)
    assert out is not None, "под every дверь ничего не отправила"
    got = reader.restore_frame(_over_the_wire(out))

    assert is_marker(got["data"])
    assert got["data"]["reason"] == "door"
    assert got["data"]["trace_id"] == "tr-1"
    assert "frame" not in got, "у читателя маркер не должен нести кадр"


def test_real_path_latest_reader_gets_nothing(made):
    """То же под ``latest``: дверь возвращает ``None`` -> до читателя ничего не доходит."""
    writer, sender, received = _received(made, **LATEST_DEFAULT)
    item = _door_drop_item(received)
    _overwrite_input(writer)

    assert _send(sender, item) is None


# ======================================================== get_shm_stats: слагаемые двери на стенде
def _router_with(mw: FrameShmMiddleware) -> RouterManager:
    router = RouterManager(manager_name="t47d3_stats_router")
    router.register_frame_middleware(mw)
    return router


def test_shm_stats_every_exposes_door_counters_with_values(made):
    """Под ``every`` ``get_shm_stats`` отдаёт ``door_drops`` и ``not_inspected_door`` с настоящими
    значениями после дропа двери (не константный 0)."""
    writer, sender, received = _received(made, **EVERY)
    router = _router_with(sender)
    item = _door_drop_item(received)
    _overwrite_input(writer)

    _send(sender, item)
    stats = router.get_shm_stats()

    assert stats["door_drops"] == 1
    assert stats["not_inspected_door"] == 1
    assert stats["frame_stale_drops"] == 1


def test_shm_stats_latest_has_door_drops_but_no_not_inspected_door_key(made):
    """Под ``latest`` ключ ``door_drops`` есть и считает; ключа ``not_inspected_door`` нет вовсе (не 0)."""
    writer, sender, received = _received(made, **LATEST_DEFAULT)
    router = _router_with(sender)
    item = _door_drop_item(received)
    _overwrite_input(writer)

    _send(sender, item)
    stats = router.get_shm_stats()

    assert stats["door_drops"] == 1
    assert "not_inspected_door" not in stats
