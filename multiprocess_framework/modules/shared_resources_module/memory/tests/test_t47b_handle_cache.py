# -*- coding: utf-8 -*-
"""Task 4.7b — кэш SHM-handles читателя: один режим, ключ (owner, slot, idx), отставка, без кэпа 8.

Слепой acceptance-тест (tester, от критериев приёмки 4.7b, без чтения реализации 4.7b).

Контракт (литералы):
  * без env (все ``FW_SHM_*`` и ``FW_QOS_PROFILES`` сняты) кэш handles работает: чтение кадра оседает
    открытым handle'ом (``frame_handle_cache_size`` > 0);
  * ключ кэша — ``(owner, slot, idx)`` из ссылки; НОВОЕ имя сегмента для того же ключа отправляет старый
    handle в отставку (закрывается), а не копится. Кэпа «8» нет: кольцо глубиной 12 держит 12 handles;
  * 100 realloc писателя подряд (кольцо глубиной 3, один ключ ``frame``): открытых handles у читателя
    ≤ глубина × ключи = 3 в КАЖДЫЙ момент; ``close_errors`` остаётся 0, живых view нет;
  * handle с ЖИВЫМ view при отставке не закрывается и не ломает чтение (ни нового кадра, ни старого view);
    после освобождения view закрывается на следующей отставке ИЛИ на teardown.

Стенд: реальные ``MemoryManager`` + ``FrameShmMiddleware`` — писатель ``cam0`` и отдельный читатель со
своим ``MemoryManager`` (тракт SHM настоящий, без подмены reader'а).

Допущения (имена не из спеки, а из текущего кода; после 4.7b могут сместиться):
  * ``reader._reader.close_errors`` — счётчик ошибок close у reader'а (у middleware публичного нет);
  * счётчика отложенных закрытий НЕ называю: «закрыт» наблюдаю на уровне ОС — на Windows именованный
    mapping живёт, пока открыт хоть один handle, поэтому ``SharedMemory(name=old)`` после закрытия
    всех handles даёт ``FileNotFoundError``. На POSIX writer unlink'ает имя сразу, и это наблюдение
    вырождено — там проверяются только чтение и счётчики.
"""

from __future__ import annotations

import gc
import os
from multiprocessing import shared_memory

import numpy as np
import pytest

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager

IS_NT = os.name == "nt"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in [k for k in os.environ if k.startswith("FW_SHM_") or k == "FW_QOS_PROFILES"]:
        monkeypatch.delenv(name, raising=False)


class _Pair:
    """Писатель + читатель; убирает SHM в конце — даже при падении теста."""

    def __init__(self, depth: int) -> None:
        self.wmm, self.rmm = MemoryManager(), MemoryManager()
        self.writer = FrameShmMiddleware(self.wmm, owner="cam0", slot="output_frames", coll=depth)
        self.reader = FrameShmMiddleware(self.rmm, owner="reader", slot="unused")

    def send(self, shape: tuple, fill: int) -> dict:
        """Кадр -> слот писателя; возвращает item со ссылкой (``_shm_refs``)."""
        return self.writer.strip_and_write({"frame": np.full(shape, fill, np.uint8)})

    @staticmethod
    def ref_name(out: dict) -> str:
        return out["_shm_refs"]["frame"]["name"]

    def close(self) -> None:
        gc.collect()
        for fin in (
            self.reader.close_handle_cache,
            self.writer.release_owned_memory,
            self.rmm.close_all,
            self.wmm.close_all,
        ):
            try:
                fin()
            except Exception:  # noqa: BLE001 — уборка не должна маскировать причину падения
                pass


@pytest.fixture
def make_pair():
    pairs: list[_Pair] = []

    def _make(depth: int) -> _Pair:
        p = _Pair(depth)
        pairs.append(p)
        return p

    yield _make
    for p in pairs:
        p.close()


def _name_alive(name: str) -> bool:
    """Сегмент с этим именем ещё открывается (на Windows — жив, пока открыт хоть один handle)."""
    try:
        probe = shared_memory.SharedMemory(name=name, create=False)
    except FileNotFoundError:
        return False
    probe.close()
    return True


def _frame_of(msg: dict):
    return msg.get("frame") if msg.get("frame") is not None else msg["data"].get("frame")


def _copy_read(pair: _Pair, out: dict) -> np.ndarray:
    """Copy-out чтение (``on_receive``): независимая копия, живых view за собой не оставляет."""
    msg = pair.reader.on_receive({"data": out})
    assert msg is not None, "on_receive отбросил кадр"
    frame = _frame_of(msg)
    assert frame is not None, "кадр не восстановлен"
    return frame


@pytest.mark.xfail(strict=True, reason="RED-спека 4.7b, реализации нет")
def test_100_reallocs_bounded_open_handles(make_pair) -> None:
    pair = make_pair(3)
    depth, keys = 3, 1
    sizes: list[int] = []
    names: set[str] = set()
    for i in range(100):
        shape = (8, 8 + i, 3)  # строго растёт -> grow-only realloc кольца на КАЖДОМ шаге
        for _ in range(depth):  # по кругу idx 0,1,2 — читатель видит все слоты кольца
            out = pair.send(shape, 10 + i)
            names.add(pair.ref_name(out))
            frame = _copy_read(pair, out)
            assert frame.shape == shape and int(frame.min()) == int(frame.max()) == 10 + i
            del frame
        sizes.append(pair.reader.frame_handle_cache_size)
    assert all(s <= depth * keys for s in sizes), f"открытых handles больше глубина x ключи={depth * keys}: {sizes}"
    assert sizes == [3] * 100, "после каждого шага кэш должен держать ровно по handle на слот кольца"
    assert pair.reader._reader.close_errors == 0, "close_errors вырос без живых view"
    assert len(names) == 300, f"предпосылка: ожидалось 100 realloc x 3 слота = 300 разных имён, получено {len(names)}"


@pytest.mark.xfail(strict=True, reason="RED-спека 4.7b, реализации нет")
def test_cache_not_capped_at_8_for_depth_12(make_pair) -> None:
    pair = make_pair(12)
    for i in range(12):
        out = pair.send((8, 8, 3), i)
        frame = _copy_read(pair, out)
        del frame
    assert pair.reader.frame_handle_cache_size == 12, "кэп 8 не снят: кольцо глубиной 12 должно держать 12 handles"


@pytest.mark.parametrize("trigger", ["next_retirement", "teardown"])
@pytest.mark.xfail(strict=True, reason="RED-спека 4.7b, реализации нет")
def test_retired_handle_with_live_view_closed_later(make_pair, trigger: str) -> None:
    pair = make_pair(2)
    # 1. читатель держит ЖИВОЙ view на слот idx0 первого сегмента (zero-copy по умолчанию, без env)
    out1 = pair.send((8, 8, 3), 7)
    old_name = pair.ref_name(out1)
    msg1 = pair.reader.restore_frame({"data": out1})
    view = _frame_of(msg1)
    assert view is not None and not view.flags.owndata, "предпосылка: restore_frame без env отдаёт view, не копию"
    del msg1

    # 2. realloc писателя: тот же ключ (cam0, output_frames, 0), НОВОЕ имя -> старый handle в отставке
    out2 = pair.send((8, 16, 3), 9)
    new_name = pair.ref_name(out2)
    assert new_name != old_name, "realloc обязан дать новое имя сегмента"
    msg2 = pair.reader.restore_frame({"data": out2})  # не должно упасть на отставке handle'а с живым view
    got2 = _frame_of(msg2)
    assert got2 is not None and int(got2.min()) == int(got2.max()) == 9, "чтение нового кадра сломано отставкой"
    del got2, msg2
    assert int(view.min()) == int(view.max()) == 7, "живой view испорчен отставкой handle'а"
    if IS_NT:
        assert _name_alive(old_name), "handle с живым view закрыт при отставке (должен ждать освобождения view)"

    # 3. view освобождён -> закрытие на следующей отставке или на teardown
    del view
    gc.collect()
    if trigger == "next_retirement":
        out3 = pair.send((8, 24, 3), 11)  # ещё один realloc -> отставка handle'а out2 и отложенного old_name
        msg3 = pair.reader.restore_frame({"data": out3})
        del msg3
        gc.collect()
    else:
        pair.reader.close_handle_cache()
    if IS_NT:
        assert not _name_alive(old_name), f"отложенный handle не закрыт после освобождения view ({trigger})"
