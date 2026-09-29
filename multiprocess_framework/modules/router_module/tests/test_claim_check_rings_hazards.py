# -*- coding: utf-8 -*-
"""Task 4.1 — авторские тесты опасных мест механизма «кольцо на ключ» (teamlead).

Дополняют независимую приёмку (``test_claim_check_any_key*.py``), не заменяют её. Каждый
тест назван по тому, что ломается, и в докстринге — какая правка его красит.

Опасности, которые видны только изнутри механизма:
  * займы сообщения берутся по кольцам по очереди — исчерпание ПОЗДНЕГО кольца обязано
    отменить займы, уже взятые ранними (иначе слот ``frame`` навсегда в WRITING);
  * повтор fan-out того же item не пишет и не занимает заново ни одно кольцо;
  * realloc одного кольца сбрасывает ТОЛЬКО свой пул (сброс чужого = двойная выдача
    слота, который ещё держит читатель);
  * смена dtype ключа между сообщениями = realloc его кольца, чтение не путает формы.
"""

from __future__ import annotations

import os
import pickle
import threading
from typing import Any, Callable

import numpy as np
import pytest

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)

DEADLINE_S = 30.0


@pytest.fixture(autouse=True)
def _clean_shm_flags(monkeypatch):
    for name in [k for k in os.environ if k.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def loan(monkeypatch):
    monkeypatch.setenv("FW_SHM_LOAN_PROTOCOL", "1")
    monkeypatch.setenv("FW_SHM_SEQLOCK", "1")


@pytest.fixture
def made():
    """Реестр (middleware, mm) для гарантированной уборки SHM (Windows: сегменты текут)."""
    items: list[tuple[FrameShmMiddleware, MemoryManager]] = []
    yield items
    for mw, mm in items:
        for fin in (mw.close_handle_cache, mw.release_owned_memory, mm.close_all):
            try:
                fin()
            except Exception:  # noqa: BLE001 — финализатор не маскирует причину падения
                pass


def _owner(made, *, coll: int, num_consumers: int = 1) -> FrameShmMiddleware:
    mm = MemoryManager()
    mw = FrameShmMiddleware(
        memory_manager=mm, owner="own", slot="output_frames", coll=coll, num_consumers=num_consumers
    )
    made.append((mw, mm))
    return mw


def _reader(made) -> FrameShmMiddleware:
    mm = MemoryManager()
    mw = FrameShmMiddleware(mm, owner="gui", slot="output_frames", zero_copy=False)
    made.append((mw, mm))
    return mw


def _bounded(fn: Callable[[], Any]) -> Any:
    """Сценарий в daemon-потоке с дедлайном: зависание = FAIL, а не висящий прогон."""
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(DEADLINE_S)
    if t.is_alive():
        pytest.fail(f"сценарий завис (> {DEADLINE_S} с)")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _arr(shape: tuple[int, ...], dtype: str = "uint8", seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    if np.dtype(dtype).kind == "f":
        return rng.random(shape).astype(dtype)
    return rng.integers(0, 250, size=shape).astype(dtype)


def _send(mw: FrameShmMiddleware, item: dict) -> dict | None:
    return mw.strip_data_frame_on_send({"target": "t", "type": "data", "channel": "data", "data": item})


FRAME = (48, 64, 3)  # 9216 Б
FOO = (100, 100)  # 10000 Б


def test_exhaustion_on_late_ring_aborts_loans_of_earlier_rings(loan, made):
    """Кольцо ``foo`` исчерпано, кольцо ``frame`` свободно: сообщение {frame, foo} дропается,
    и заём, взятый под него кольцом ``frame``, ОТМЕНЯЕТСЯ — следующий одиночный ``frame``
    уходит. Красит: убрать цикл ``abort`` в ``_write_item_arrays`` (слот ``frame`` остаётся
    WRITING → одиночный ``frame`` упирается в исчерпание)."""
    mw = _owner(made, coll=1)

    def scenario() -> None:
        assert _send(mw, {"foo": _arr(FOO, seed=1)}) is not None  # кольцо foo: 1/1 занято
        assert _send(mw, {"frame": _arr(FRAME, seed=2), "foo": _arr(FOO, seed=3)}) is None
        assert mw.frame_loan_exhausted == 1
        out = _send(mw, {"frame": _arr(FRAME, seed=4)})
        assert out is not None, "заём кольца frame утёк: исчерпание соседнего кольца его не отменило"
        assert mw.frame_loan_exhausted == 1

    _bounded(scenario)


def test_exhausted_message_keeps_arrays_in_item(loan, made):
    """Дроп по исчерпанию не портит item: массивы остались в нём, ссылок не появилось
    (producer может переотправить тот же item позже). Красит: pop массива до фазы займов."""
    mw = _owner(made, coll=1)

    def scenario() -> dict:
        assert _send(mw, {"foo": _arr(FOO, seed=1)}) is not None
        item = {"frame": _arr(FRAME, seed=2), "foo": _arr(FOO, seed=3)}
        assert _send(mw, item) is None
        return item

    item = _bounded(scenario)
    assert isinstance(item.get("frame"), np.ndarray) and isinstance(item.get("foo"), np.ndarray)
    assert "_shm_refs" not in item and "shm_name" not in item


def test_fanout_replay_counts_boundary_but_writes_nothing(loan, made):
    """Три send'а ОДНОГО item {frame, foo} (fan-out на 3 цели): граница посчитана 3 раза,
    ``frame_hops`` = 1, займов взято по одному на кольцо — при coll=2 ещё РОВНО одно новое
    сообщение проходит, следующее исчерпано. Красит: повтор, пишущий заново (займы 3 на кольцо
    → уже второе новое сообщение исчерпано), или счёт границы только на первом send."""
    mw = _owner(made, coll=2)

    def scenario() -> None:
        item = {"frame": _arr(FRAME, seed=1), "foo": _arr(FOO, seed=2)}
        for _ in range(3):
            assert _send(mw, item) is not None
        assert mw.frame_boundary_crossings == 3
        assert item["frame_hops"] == 1
        assert _send(mw, {"frame": _arr(FRAME, seed=3), "foo": _arr(FOO, seed=4)}) is not None
        assert mw.frame_loan_exhausted == 0
        assert _send(mw, {"frame": _arr(FRAME, seed=5), "foo": _arr(FOO, seed=6)}) is None

    _bounded(scenario)


def test_realloc_of_one_ring_does_not_reset_other_rings_pool(loan, made):
    """Рост ``foo`` (realloc его кольца) сбрасывает ТОЛЬКО пул ``foo``: два займа кольца
    ``frame`` (читатель их не отпускал) остаются → третий ``frame`` исчерпан. Красит: reset
    пулов всех колец при realloc одного (кольцо ``frame`` выдало бы слот под живым займом)."""
    mw = _owner(made, coll=2)

    def scenario() -> None:
        assert _send(mw, {"frame": _arr(FRAME, seed=1), "foo": _arr(FOO, seed=2)}) is not None
        assert _send(mw, {"frame": _arr(FRAME, seed=3), "foo": _arr((200, 200), seed=4)}) is not None
        assert mw.frame_loan_exhausted == 0
        assert _send(mw, {"frame": _arr(FRAME, seed=5)}) is None, "realloc foo освободил займы кольца frame"
        assert mw.frame_loan_exhausted == 1

    _bounded(scenario)


def test_dtype_change_of_key_reallocs_its_ring_and_reads_back(made):
    """``foo`` меняет dtype между сообщениями (uint8 → float32): кольцо ``foo`` пересоздаётся
    под новый dtype, второе сообщение читается побайтно с верными формой и dtype, ``frame``
    рядом не страдает. Красит: сравнение ёмкости без dtype — float32 той же формы (40000 Б)
    не влезает в uint8-слот (10000 Б), запись падает, ``foo`` уезжает inline pickle'ом.
    (Форма (50, 50) float32 = 10000 Б была слепа к этой правке: байтом влезала в старый слот.)"""
    mw, gui = _owner(made, coll=2), _reader(made)
    frame = _arr(FRAME, seed=1)
    foo2 = _arr(FOO, "float32", seed=3)  # 40000 Б, та же форма, что у uint8-предшественника

    def scenario() -> dict:
        assert _send(mw, {"frame": _arr(FRAME, seed=0), "foo": _arr(FOO, seed=2)}) is not None
        out = _send(mw, {"frame": frame, "foo": foo2})
        assert out is not None
        assert "foo" not in out["data"], "foo уехал inline: кольцо не пересоздано под новый dtype"
        assert mw.frame_pickle_fallbacks == 0
        return gui.on_receive(pickle.loads(pickle.dumps(out)))

    got = _bounded(scenario)
    foo = got["data"]["foo"]
    assert isinstance(foo, np.ndarray) and foo.shape == foo2.shape and foo.dtype == foo2.dtype
    assert foo.tobytes() == foo2.tobytes()
    assert got["frame"].tobytes() == frame.tobytes()


def test_small_frame_still_by_reference_small_key_inline(made):
    """``frame`` ссылкой ВСЕГДА (как до 4.1, на это опирается test_g5d_loan), мелкий
    не-frame ключ — inline тем же объектом. Красит: порог, применённый и к ``frame``."""
    mw = _owner(made, coll=2)
    small = _arr((8, 8, 3), seed=1)  # 192 Б
    item = {"frame": _arr((8, 8, 3), seed=2), "small": small}

    out = _bounded(lambda: _send(mw, item))
    assert out is not None
    assert "frame" not in out["data"] and out["data"].get("shm_name") == "output_frames"
    assert out["data"]["small"] is small and "_shm_refs" not in out["data"]


# ============================ 4.1-fix (ревью 4.1, находки 1 и 3) ============================
def _not_image_like() -> dict[str, np.ndarray]:
    """Крупные (>= 8192 Б) массивы, которые SHM-слот не восстанавливает: едут inline."""
    obj = np.empty((40, 40), dtype=object)
    obj[:] = "x"
    return {
        "unicode": np.full((20, 8), "abcdefghijklmnop", dtype="<U16"),  # 10240 Б
        "object": obj,  # 12800 Б на 64-бит
        "datetime": np.arange(2048).astype("datetime64[s]").reshape(32, 64),  # 16384 Б
        "one_d": _arr((2048,), "float32", seed=1),  # 8192 Б
        "four_d": _arr((4, 16, 16, 8), seed=2),  # 8192 Б
    }


@pytest.mark.parametrize("key", list(_not_image_like()))
def test_non_image_array_travels_inline_and_arrives_intact(made, key):
    """Строки, object, ``datetime64``, 1D и 4D крупнее порога едут inline и доходят как были:
    без ссылки, без pickle-fallback, dtype (с единицей) и значения сохранены. Красит: убрать
    из ``_is_large_array`` условие ``dtype.kind`` (unicode/object/datetime уходят ссылкой и
    теряются) или ``ndim`` (1D — ERROR и fallback на каждое сообщение, 4D — ссылкой)."""
    value = _not_image_like()[key]
    assert value.nbytes >= 8192  # литерал порога, иначе тест ничего не проверяет
    mw, gui = _owner(made, coll=2), _reader(made)

    def scenario() -> dict:
        out = _send(mw, {key: value, "n": 1})
        assert out is not None
        assert out["data"][key] is value, f"{key}: массив не остался inline"
        assert key not in out["data"].get("_shm_refs", {}), f"{key}: ушёл ссылкой"
        assert mw.frame_pickle_fallbacks == 0
        return gui.on_receive(pickle.loads(pickle.dumps(out)))

    got = _bounded(scenario)["data"][key]
    assert got.dtype == value.dtype and got.shape == value.shape
    assert (got == value).all()


def test_release_with_unknown_slot_is_dropped_not_routed_to_frame_ring(loan, made):
    """Тикет вытеснения с неизвестным ``slot`` отбрасывается и считается: займ кольца
    ``frame`` остаётся, следующий ``frame`` исчерпан. Контроль: тот же тикет БЕЗ ``slot``
    (back-compat) займ снимает. Красит: fallback неизвестного slot на кольцо ``frame``
    в ``_ring_by_slot`` (чужой тикет снимает займ кадра, который ещё читают)."""
    mw = _owner(made, coll=1)
    stray = {"slot": "output_frames__nope", "index": 0, "generation": -1, "reader": "p"}

    def scenario() -> None:
        assert _send(mw, {"frame": _arr(FRAME, seed=1)}) is not None  # кольцо frame: 1/1
        mw.release_slots([stray], evicted=True)
        assert mw.frame_release_unknown_slot == 1
        assert _send(mw, {"frame": _arr(FRAME, seed=2)}) is None, "чужой тикет снял займ кадра"
        assert mw.frame_loan_exhausted == 1

        no_slot = {k: v for k, v in stray.items() if k != "slot"}
        mw.release_slots([no_slot], evicted=True)
        assert _send(mw, {"frame": _arr(FRAME, seed=3)}) is not None, "тикет без slot не снял займ"
        assert mw.frame_release_unknown_slot == 1

    _bounded(scenario)
