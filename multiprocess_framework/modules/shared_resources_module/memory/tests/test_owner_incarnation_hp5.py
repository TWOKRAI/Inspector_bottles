# -*- coding: utf-8 -*-
"""Ф7 G.3(b) B-6/B-7/HP-5: имя SHM с owner+incarnation — репродьюсер «перепутанных кадров».

HP-5 (audit 2026-07-12): при switch рецепта старый сегмент unlink'ается, новый процесс
создаёт сегмент С ТЕМ ЖЕ именем → in-flight сообщение со старым именем читает НОВЫЙ кадр
(«перепутанные кадры»). Статус «митигировано 5cd23192» — не сверен.

Здесь СВЕРЕНО замером: без owner+incarnation имя переиспользуется (name_a == name_b) и
старое in-flight имя читает новый кадр (confusion). С owner+incarnation имена различны,
старое имя недоступно/держит старый контент — confusion невозможен по построению.
"""

from __future__ import annotations

from multiprocessing import shared_memory

import numpy as np

from multiprocess_framework.modules.shared_resources_module.memory import format as fmt
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager

_SHAPE = (8, 8, 3)
_DTYPE = np.uint8


def _switch_and_probe(owner_incarnation: bool):
    """Создать слот, записать A, «switch» (release+recreate), записать B.

    Returns: (name_a, name_b, frame_via_old_name | None).
    """
    mm = MemoryManager(owner_incarnation=owner_incarnation)
    try:
        mm.create_memory_dict("cam", {"of": (1, _SHAPE, "uint8")}, coll=2)
        mm.write_images("cam", "of", [np.full(_SHAPE, 111, _DTYPE)], 0)
        name_a = mm.get_actual_shm_name("cam", "of", 0)

        # Switch рецепта: полный teardown памяти процесса + пересоздание нового.
        mm.release_process_memory("cam")
        mm.create_memory_dict("cam", {"of": (1, _SHAPE, "uint8")}, coll=2)
        mm.write_images("cam", "of", [np.full(_SHAPE, 222, _DTYPE)], 0)
        name_b = mm.get_actual_shm_name("cam", "of", 0)

        # In-flight сообщение держит СТАРОЕ имя (name_a) — что оно прочитает?
        frame_old: np.ndarray | None
        try:
            shm = shared_memory.SharedMemory(name=name_a, create=False)
            try:
                frame_old = fmt.read_single_frame(shm.buf, verify_seqlock=False)
            finally:
                shm.close()
        except FileNotFoundError:
            frame_old = None  # сегмент ушёл — in-flight честно дропнется
        return name_a, name_b, frame_old
    finally:
        mm.close_all()


def test_hp5_without_owner_incarnation_reuses_name_and_confuses_frames():
    """РЕПРОДЬЮСЕР (before): без owner+incarnation имя переиспользуется → старое
    in-flight имя читает НОВЫЙ кадр (222) = «перепутанные кадры» (HP-5 подтверждён,
    митигация 5cd23192 недостаточна)."""
    name_a, name_b, frame_old = _switch_and_probe(owner_incarnation=False)
    assert name_a == name_b, "без флага имя слота переиспользуется при switch"
    assert frame_old is not None, "старое имя указывает на переиспользованный сегмент"
    # Confusion: читаем по СТАРОМУ имени, а получаем НОВЫЙ кадр (все 222).
    assert int(frame_old.min()) == int(frame_old.max()) == 222


def test_hp5_owner_incarnation_prevents_frame_confusion():
    """ФИКС (after): owner+incarnation → имена различны; старое in-flight имя НЕ
    возвращает новый кадр (сегмент ушёл → drop, либо держит старый контент)."""
    name_a, name_b, frame_old = _switch_and_probe(owner_incarnation=True)
    assert name_a != name_b, "с флагом каждое создание — свежая инкарнация (нет reuse)"
    # Старое имя никогда не отдаёт НОВЫЙ кадр (222): либо None (ушёл), либо старый (111).
    if frame_old is not None:
        assert int(frame_old.max()) != 222, "старое имя не должно читать новый кадр"


def test_owner_incarnation_names_distinct_per_owner():
    """B-7 мультикамера: два владельца с одним slot-именем → разные фактические имена."""
    mm = MemoryManager(owner_incarnation=True)
    try:
        mm.create_memory_dict("cam0", {"of": (1, _SHAPE, "uint8")}, coll=1)
        mm.create_memory_dict("cam1", {"of": (1, _SHAPE, "uint8")}, coll=1)
        n0 = mm.get_actual_shm_name("cam0", "of", 0)
        n1 = mm.get_actual_shm_name("cam1", "of", 0)
        assert n0 != n1 and "cam0" in n0 and "cam1" in n1
    finally:
        mm.close_all()


def test_owner_incarnation_off_by_default():
    """Дефолт (нет ctor-флага и env) → прежняя схема имён (без owner в имени)."""
    mm = MemoryManager()
    try:
        mm.create_memory_dict("cam", {"of": (1, _SHAPE, "uint8")}, coll=1)
        name = mm.get_actual_shm_name("cam", "of", 0)
        assert "cam" not in name  # owner не вшит в имя при выключенном флаге
    finally:
        mm.close_all()
