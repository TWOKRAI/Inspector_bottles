# -*- coding: utf-8 -*-
"""Ф7 G.4.d — switch × кадры на уровне FrameShmMiddleware + per-camera изоляция (B-7/B-9).

Корректность «перепутанных кадров» на switch закрыта G.3 на уровне MemoryManager
(`memory/tests/test_owner_incarnation_hp5.py`: owner+incarnation → нет reuse имени, стейл
in-flight не читает новый кадр). Здесь СВЕРЕНО на уровне кадрового middleware (реальный
путь стрипа/восстановления координат) + мультикамера G.4.b:

- switch источника (release_process_memory + новый middleware-инстанс = новый процесс) →
  стейл-координаты старого кадра дают drop (None), НИКОГДА новый кадр (B-7/B-9);
- вторая камера не задета switch'ем первой (изоляция цепочек, G.4.b принцип 7).

B-7 «дренаж очередей получателей / refresh handles protected» на switch: корректность
обеспечена incarnation-fence (стейл-тикет фейл-ридится → drop на ЧТЕНИИ, безопасно, без
гонки с живым получателем); явный кросс-процессный дренаж живых protected-получателей —
НЕ вводим (риск гонки с их reader-потоком > выгоды; read-time drop достаточен). Владение
слотом/refcount/reclaim — G.5.
"""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)

_SHAPE = (16, 24, 3)


def _frame(val: int) -> np.ndarray:
    return np.full(_SHAPE, val, dtype=np.uint8)


def _write(mw: FrameShmMiddleware, val: int) -> dict:
    return mw.strip_and_write({"frame": _frame(val)})


def _reader() -> FrameShmMiddleware:
    """Получатель в ОТДЕЛЬНОМ процессе не держит handles источника → рабочий путь
    восстановления = Попытка 2 по ``shm_actual_name`` (аудит B-7: «рабочий путь —
    fallback по имени из сообщения»). mm=None форсит именно его (кросс-процессный
    raw-open), а не Попытку 1 по owner/slot/index (которая читала бы ТЕКУЩИЙ регион)."""
    return FrameShmMiddleware(memory_manager=None, owner="reader", slot="output_frames")


def _read(reader: FrameShmMiddleware, coords: dict):
    return reader.restore_frame({"data": dict(coords)}).get("frame")


def test_switch_stale_coords_drop_not_wrong_frame():
    """Switch источника: старые координаты у получателя → drop (None), НЕ новый кадр (B-7/B-9)."""
    mm = MemoryManager(owner_incarnation=True)
    reader = _reader()
    try:
        cam_v1 = FrameShmMiddleware(mm, owner="cam0", slot="output_frames", coll=3)
        coords_a = _write(cam_v1, 111)
        # Получатель со свежими координатами A видит старый кадр (рабочий actual_name-путь).
        assert int(_read(reader, coords_a)[0, 0, 0]) == 111

        # SWITCH рецепта: полный teardown SHM источника + новый инстанс (= новый процесс).
        mm.release_process_memory("cam0")
        cam_v2 = FrameShmMiddleware(mm, owner="cam0", slot="output_frames", coll=3)
        coords_b = _write(cam_v2, 222)

        # Имена различны (owner+incarnation) — reuse невозможен.
        assert coords_a["shm_actual_name"] != coords_b["shm_actual_name"]

        # In-flight получатель со СТАРЫМИ координатами A: drop (сегмент ушёл) либо старый
        # кадр (111) — НИКОГДА новый (222). «Перепутанных кадров» нет по построению.
        stale = _read(reader, coords_a)
        assert stale is None or int(stale.max()) != 222

        # Свежие координаты B → новый кадр.
        assert int(_read(reader, coords_b)[0, 0, 0]) == 222
    finally:
        mm.close_all()


def test_switch_of_one_camera_does_not_disturb_another():
    """Изоляция цепочек (G.4.b принцип 7): switch cam0 не трогает кадры cam1."""
    mm = MemoryManager(owner_incarnation=True)
    reader = _reader()
    try:
        cam0_v1 = FrameShmMiddleware(mm, owner="cam0", slot="output_frames", coll=3)
        cam1 = FrameShmMiddleware(mm, owner="cam1", slot="output_frames", coll=3)

        _write(cam0_v1, 10)
        coords_c1 = _write(cam1, 20)
        # cam1 читается своим значением ДО switch'а cam0.
        assert int(_read(reader, coords_c1)[0, 0, 0]) == 20

        # Switch ТОЛЬКО cam0.
        mm.release_process_memory("cam0")
        cam0_v2 = FrameShmMiddleware(mm, owner="cam0", slot="output_frames", coll=3)
        _write(cam0_v2, 99)

        # cam1 по-прежнему читает СВОЙ кадр (20) — switch соседа его не задел.
        assert int(_read(reader, coords_c1)[0, 0, 0]) == 20
        # cam1 продолжает писать/читать нормально после switch cam0.
        coords_c1b = _write(cam1, 30)
        assert int(_read(reader, coords_c1b)[0, 0, 0]) == 30
    finally:
        mm.close_all()
