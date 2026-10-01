# -*- coding: utf-8 -*-
"""Task 4.7b2 — hazard-тесты автора: отставка handle'ов ``ShmFrameReader`` при живых view.

Что может сломаться именно в ЭТОМ механизме (ключ -> (имя, handle); ``BufferError`` на ``close()``
при живом exported-view; ``_retired`` + повтор на следующей отставке и в ``close()``):

  * (a) счётчик ``deferred_closes`` врёт — растёт на каждую повторную неудачу того же handle'а, либо
    handle ПОВИСАЕТ в ``_retired`` после отпускания view (утечка);
  * (b) гонка двух потоков на одном ключе: отставка под ``_lock`` + чтение — исключение либо handle,
    осиротевший между pop из кэша и close;
  * (c) ``close()`` при живых view бросает (теряя остальные handle'ы) либо забывает отложенные.

Стенд — реальные SHM-сегменты (``FrameShmMiddleware`` пишет, ``ShmFrameReader`` читает), но имена
сегментов от инкарнации не зависят: ключ кэша задаётся ЯВНО (``key=``), разные сегменты читаются «под
одним ключом» — это и есть смена имени при realloc. Наблюдение «закрыт» на уровне ОС работает только
на Windows (именованный mapping живёт, пока открыт хоть один handle; писатель при этом отпущен); на
POSIX писатель unlink'ает имя сразу и проверка вырождена — там остаются счётчики и ``_retired``.
"""

from __future__ import annotations

import gc
import os
import threading
from multiprocessing import shared_memory

import numpy as np
import pytest

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager
from multiprocess_framework.modules.shared_resources_module.memory.reader import ShmFrameReader

IS_NT = os.name == "nt"
DEADLINE_S = 30.0


class _Seg:
    """Один живой SHM-сегмент с кадром: писатель + ссылка (name, gen)."""

    def __init__(self, tag: str, fill: int) -> None:
        self.mm = MemoryManager()
        self.mw = FrameShmMiddleware(self.mm, owner=f"w_{tag}", slot="s", coll=2)
        item = self.mw.strip_and_write({"frame": np.full((16, 16, 3), fill, np.uint8)})
        ref = item["_shm_refs"]["frame"]
        self.name, self.gen, self.fill = ref["name"], ref["gen"], fill

    def release_writer(self) -> None:
        """Отпустить писателя: дальше на Windows имя живо, пока его держит ТОЛЬКО reader."""
        for fin in (self.mw.release_owned_memory, self.mm.close_all):
            try:
                fin()
            except Exception:  # noqa: BLE001 — уборка не маскирует причину падения
                pass


@pytest.fixture
def segs():
    made: list[_Seg] = []

    def _make(tag: str, fill: int = 1) -> _Seg:
        s = _Seg(tag, fill)
        made.append(s)
        return s

    yield _make
    gc.collect()
    for s in made:
        s.release_writer()


def _name_alive(name: str) -> bool:
    try:
        probe = shared_memory.SharedMemory(name=name, create=False)
    except FileNotFoundError:
        return False
    probe.close()
    return True


KEY = ("w", "s", 0)


def test_a_deferred_closes_exactly_once_and_handle_closed_after_view_released(segs) -> None:
    """(a) handle с живым view при отставке: ``deferred_closes`` == 1 РОВНО раз, даже когда он переживает
    ещё одну отставку; после ``del view`` закрывается на следующей отставке (``_retired`` пуст)."""
    s1, s2, s3, s4 = segs("1", 1), segs("2", 2), segs("3", 3), segs("4", 4)
    reader = ShmFrameReader()
    view = reader.read_ref(s1.name, s1.gen, copy=False, key=KEY)
    assert view is not None and not view.flags.owndata and int(view.min()) == 1
    s1.release_writer()  # на Windows имя s1 дальше держит только handle читателя

    assert reader.read_ref(s2.name, s2.gen, key=KEY) is not None  # отставка handle'а s1 при живом view
    assert reader.deferred_closes == 1 and reader.close_errors == 0
    assert len(reader._retired) == 1 and reader.cache_size == 1
    assert int(view.min()) == int(view.max()) == 1, "живой view испорчен отставкой"
    if IS_NT:
        assert _name_alive(s1.name), "handle с живым view закрыт при отставке"

    s2.release_writer()
    assert reader.read_ref(s3.name, s3.gen, key=KEY) is not None  # ещё отставка, view всё ещё жив
    assert reader.deferred_closes == 1, "повторная неудача того же handle'а посчитана заново"
    assert len(reader._retired) == 1

    del view
    gc.collect()
    assert reader.read_ref(s4.name, s4.gen, key=KEY) is not None  # отставка s3 + повтор закрытия s1
    assert reader._retired == [] and reader.deferred_closes == 1 and reader.close_errors == 0
    if IS_NT:
        assert not _name_alive(s1.name), "отложенный handle не закрыт после освобождения view"
    reader.close()


def test_b_concurrent_read_ref_with_key_retirement_no_leak(segs) -> None:
    """(b) два потока читают под ОДНИМ ключом по очереди разные сегменты (каждое чтение — отставка):
    ни исключения, ни зависания; в кэше ровно один handle, отставленных нет, ошибок close нет."""
    pool = [segs(str(i), 10 + i) for i in range(4)]
    reader = ShmFrameReader()
    errors: list[BaseException] = []
    rounds = 150

    def hammer(offset: int) -> None:
        try:
            for i in range(rounds):
                s = pool[(i + offset) % len(pool)]
                frame = reader.read_ref(s.name, s.gen, copy=True, key=KEY)
                assert frame is not None and int(frame.min()) == int(frame.max()) == s.fill
        except BaseException as exc:  # noqa: BLE001 — доложить из потока
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(o,), daemon=True) for o in (0, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(DEADLINE_S)
    assert not any(t.is_alive() for t in threads), "read_ref завис (deadlock на _lock?)"
    assert not errors, f"поток упал: {errors[0]!r}"
    assert reader.cache_size == 1 and reader._retired == []
    assert reader.deferred_closes == 0 and reader.close_errors == 0

    reader.close()
    for s in pool:
        s.release_writer()
    gc.collect()
    if IS_NT:
        assert not any(_name_alive(s.name) for s in pool), "handle утёк при отставках под гонкой"


def test_c_close_with_live_views_does_not_raise_and_keeps_them_retired(segs) -> None:
    """(c) ``close()`` при живых view: не бросает, закрывает остальное, view оставляет в ``_retired``
    (``deferred_closes`` по числу живых); после ``del`` повторный ``close()`` их закрывает."""
    s1, s2, s3 = segs("1", 1), segs("2", 2), segs("3", 3)
    reader = ShmFrameReader()
    v1 = reader.read_ref(s1.name, s1.gen, copy=False, key=("w", "s", 0))
    v2 = reader.read_ref(s2.name, s2.gen, copy=False, key=("w", "s", 1))
    assert reader.read_ref(s3.name, s3.gen, copy=True, key=("w", "s", 2)) is not None  # без view
    assert v1 is not None and v2 is not None
    for s in (s1, s2, s3):
        s.release_writer()

    reader.close()  # не должно бросать
    assert reader.cache_size == 0
    assert len(reader._retired) == 2 and reader.deferred_closes == 2 and reader.close_errors == 0
    assert int(v1.min()) == 1 and int(v2.min()) == 2, "view испорчен teardown'ом"
    if IS_NT:
        assert _name_alive(s1.name) and _name_alive(s2.name)
        assert not _name_alive(s3.name), "handle без view не закрыт на teardown"

    del v1, v2
    gc.collect()
    reader.close()
    assert reader._retired == []
    if IS_NT:
        assert not _name_alive(s1.name) and not _name_alive(s2.name), "отложенные handles не закрыты повторным close()"


def test_d_view_valid_false_when_key_now_holds_another_segment_with_equal_generation(segs) -> None:
    """(d) realloc писателя под ТЕМ ЖЕ ключом: в кэше уже другой сегмент, и его поколение РАВНО поколению,
    на котором прочитан старый view. ``view_valid(старое_имя, старый_gen, key)`` обязан дать False и
    +1 к ``stale_drops``: сверка одного поколения без имени приняла бы чужой слот за свой view.
    Красный revert: убрать ``entry[0] == shm_view_name`` из ``ShmFrameReader.view_valid``."""
    old, new = segs("old", 1), segs("new", 2)
    assert old.name != new.name and old.gen == new.gen, "предпосылка: разные сегменты, равное поколение"
    reader = ShmFrameReader()
    view = reader.read_ref(old.name, old.gen, copy=False, key=KEY)
    assert view is not None
    assert reader.view_valid(old.name, old.gen, key=KEY) is True  # контроль: до realloc view валиден
    assert reader.stale_drops == 0

    assert reader.read_ref(new.name, new.gen, copy=True, key=KEY) is not None  # realloc: ключ -> новый сегмент
    assert reader.view_valid(old.name, old.gen, key=KEY) is False
    assert reader.stale_drops == 1
    del view
    gc.collect()
    reader.close()
