# -*- coding: utf-8 -*-
"""Ф7 G.3(b) M5: КРОСС-ПРОЦЕССНЫЙ репродьюсер seqlock (soak-инструмент для ARM/Mac).

Проблема существующего репродьюсера в ``test_seqlock.py``: writer/reader там —
ДВА ПОТОКА одного процесса на общий ``bytearray``. Это доказывает seqlock под GIL
CPython (numpy отпускает GIL на memcpy больших массивов), НО НЕ моделирует реальную
межпроцессную гонку: два ОС-процесса на разных ядрах видят память друг друга через
модель памяти ПРОЦЕССОРА (не GIL), которая на ARM (Apple Silicon) слабее x86 — там
возможно переупорядочивание записей, недостижимое в потоковом репродьюсере.

Здесь writer и reader — РЕАЛЬНЫЕ ``multiprocessing.Process`` на ОБЩЕМ
``multiprocessing.shared_memory.SharedMemory``-сегменте (не bytearray). На x86-64 тест
обязан пройти (torn == 0) — та же гарантия seqlock, что и в потоковом репродьюсере,
только без GIL-подстраховки. На ARM/Apple Silicon этот тест — SOAK-инструмент: гонять
до первого флипа (torn > 0 = регрессия) перед тем, как доверять seqlock на этой
платформе (см. ADR-SRM-011, оговорка ARM).

Windows spawn: writer/reader — ФУНКЦИИ МОДУЛЬНОГО УРОВНЯ (не вложенные), иначе
pickle дочернего процесса падает.
"""

from __future__ import annotations

import multiprocessing as mp
from multiprocessing import shared_memory

import numpy as np
import pytest

from multiprocess_framework.modules.shared_resources_module.memory import format as fmt

# Небольшой кадр — soak-репродьюсер должен быть быстрым (~1-2с), не прод-нагрузочным
# (для прод-размера конкурентного теста см. test_seqlock.py::test_seqlock_full_hd_...).
_MP_SHAPE = (64, 64, 3)
_MP_DTYPE = np.uint8
_MP_ITERS = 400  # reader: столько попыток чтения


def _mp_seqlock_writer(shm_name: str, shape: tuple, iters: int, start_evt, stop_evt) -> None:
    """Писать кадры ОДНИМ значением (v) в общий SHM-сегмент, seqlock=True.

    Модульная функция (не замыкание) — обязательное условие для pickle на Windows
    spawn. Открывает УЖЕ СОЗДАННЫЙ (в родителе) сегмент по имени, не создаёт свой.
    """
    shm = shared_memory.SharedMemory(name=shm_name, create=False)
    mv = shm.buf
    try:
        dtype = np.dtype(_MP_DTYPE)
        start_evt.wait(timeout=5.0)
        v = 2
        # Пишем чуть дольше, чем reader читает (iters), — reader не должен упереться
        # в «мёртвый» writer раньше своих iters попыток.
        n = 0
        while not stop_evt.is_set() and n < iters * 3:
            frame = np.full(shape, v, dtype=_MP_DTYPE)
            fmt.pack_images(mv, [frame], shape, dtype, seqlock=True)
            v = 1 + (v % 254)
            n += 1
    finally:
        # BufferError «cannot close exported pointers exist»: mv (memoryview shm.buf)
        # держит буфер экспортированным — обязан быть release() ДО shm.close().
        mv.release()
        shm.close()


def _mp_seqlock_reader(shm_name: str, shape: tuple, iters: int, start_evt, result_q) -> None:
    """Читать кадры с verify_seqlock=True, считать torn/drops/valid, вернуть через Queue."""
    shm = shared_memory.SharedMemory(name=shm_name, create=False)
    mv = shm.buf
    try:
        dtype = np.dtype(_MP_DTYPE)
        torn = drops = valid = 0
        start_evt.set()
        for _ in range(iters):
            imgs = fmt.unpack_images(mv, shape, dtype, n=1, copy=True, verify_seqlock=True)
            if imgs is None:
                drops += 1
                continue
            frame = imgs[0]
            if int(frame.min()) != int(frame.max()):
                torn += 1
            else:
                valid += 1
        result_q.put((torn, drops, valid))
    finally:
        mv.release()
        shm.close()


def _shm_module_available() -> bool:
    """Проверить, что multiprocessing.shared_memory реально работает в этом окружении
    (на некоторых платформах/контейнерах создание сегмента может упасть)."""
    try:
        probe = shared_memory.SharedMemory(create=True, size=64)
        probe.close()
        probe.unlink()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _shm_module_available(), reason="multiprocessing.shared_memory недоступна в этом окружении")
def test_seqlock_cross_process_never_torn():
    """M5: writer-процесс + reader-процесс на ОБЩЕМ SHM-сегменте — reader НИКОГДА не
    отдаёт порванный кадр (torn == 0). Реальная межпроцессная гонка (не GIL-поток).

    На x86-64 — обязан пройти. На ARM/Apple Silicon — soak-инструмент (см. докстринг
    модуля и ADR-SRM-011): гонять несколько раз до первого флипа перед доверием.
    """
    shape = _MP_SHAPE
    dtype = np.dtype(_MP_DTYPE)
    size = fmt.calculate_buffer_size(1, shape, dtype, seqlock=True)

    shm = shared_memory.SharedMemory(create=True, size=size)
    try:
        # Приваймить буфер ДО старта writer/reader-процессов (валидный слот с самого начала).
        fmt.pack_images(shm.buf, [np.full(shape, 1, dtype=_MP_DTYPE)], shape, dtype, seqlock=True)

        ctx = mp.get_context()
        start_evt = ctx.Event()
        stop_evt = ctx.Event()
        result_q: "mp.Queue" = ctx.Queue()

        writer = ctx.Process(target=_mp_seqlock_writer, args=(shm.name, shape, _MP_ITERS, start_evt, stop_evt))
        reader = ctx.Process(target=_mp_seqlock_reader, args=(shm.name, shape, _MP_ITERS, start_evt, result_q))

        writer.start()
        reader.start()

        # Дать процессам время отработать (spawn на Windows под нагрузкой полного
        # прогона может быть медленным — см. test_handles.py::test_handle_ipc_via_process).
        torn, drops, valid = result_q.get(timeout=15.0)
        stop_evt.set()

        reader.join(timeout=10.0)
        writer.join(timeout=10.0)
        assert reader.exitcode == 0, f"reader-процесс упал: exitcode={reader.exitcode}"
        assert writer.exitcode == 0, f"writer-процесс упал: exitcode={writer.exitcode}"

        assert torn == 0, (
            f"seqlock обязан исключить torn-frame МЕЖДУ ПРОЦЕССАМИ, поймано {torn} "
            f"(drops={drops}, valid={valid}) — на ARM это регрессия, гонять soak до флипа"
        )
    finally:
        shm.close()
        shm.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
