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

import os
import subprocess
import sys
from multiprocessing import shared_memory

import numpy as np

from multiprocess_framework.modules.shared_resources_module.memory import format as fmt
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager
from multiprocess_framework.modules.shared_resources_module.memory.platform.shm import (
    _MAX_BASE_NAME_LEN,
    _unique_base_name,
)

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
    """ФИКС (after): owner+incarnation → имена различны; FRESH-open старого имени после
    switch НЕ возвращает новый кадр. H6: ассерты БЕЗУСЛОВНЫ по обеим веткам."""
    name_a, name_b, frame_old = _switch_and_probe(owner_incarnation=True)
    assert name_a != name_b, "с флагом каждое создание — свежая инкарнация (нет reuse)"
    # H6: branch-ассерты явные — а не «if frame_old is not None» (который скипался 15/15).
    if frame_old is None:
        # Ожидаемо и УТВЕРЖДАЕТСЯ: сегмент name_a ушёл (unlink) → in-flight честно дропнется.
        assert frame_old is None
    else:
        # Если сегмент ещё жив (держится где-то) — обязан отдать СТАРЫЙ кадр (111), не 222.
        assert int(frame_old.max()) != 222, "старое имя не должно читать новый кадр"


def test_hp5_inflight_held_handle_reads_old_frame_not_new():
    """H6 (контентная безопасность): реальный in-flight держатель открыл сегмент ДО
    switch и держит handle. После release+recreate чтение через ЭТОТ handle обязано
    вернуть СТАРЫЙ кадр (111), НИКОГДА новый (222) — с owner_incarnation по построению."""
    mm = MemoryManager(owner_incarnation=True)
    inflight = None
    try:
        mm.create_memory_dict("cam", {"of": (1, _SHAPE, "uint8")}, coll=2)
        mm.write_images("cam", "of", [np.full(_SHAPE, 111, _DTYPE)], 0)
        name_a = mm.get_actual_shm_name("cam", "of", 0)

        # In-flight держатель открывает сегмент ДО switch (реальная гонка «кадр в полёте»).
        inflight = shared_memory.SharedMemory(name=name_a, create=False)
        before = fmt.read_single_frame(inflight.buf, verify_seqlock=False)
        assert before is not None and int(before.max()) == 111

        # Switch: release + recreate + записать НОВЫЙ кадр (222) в свежую инкарнацию.
        mm.release_process_memory("cam")
        mm.create_memory_dict("cam", {"of": (1, _SHAPE, "uint8")}, coll=2)
        mm.write_images("cam", "of", [np.full(_SHAPE, 222, _DTYPE)], 0)
        name_b = mm.get_actual_shm_name("cam", "of", 0)
        assert name_a != name_b

        # Чтение через УДЕРЖАННЫЙ handle: старый сегмент (111), не перепутанный новый (222).
        after = fmt.read_single_frame(inflight.buf, verify_seqlock=False)
        assert after is not None and int(after.max()) == 111, "in-flight держатель прочитал НОВЫЙ кадр (confusion)"
    finally:
        if inflight is not None:
            inflight.close()
        mm.close_all()


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


# --- H2: PID в имени на всех платформах (POSIX-коллизия двух интерпретаторов) ------


def test_h2_name_contains_pid_when_short():
    """H2: короткое имя несёт литеральный pid (для cross-process уникальности)."""
    name = _unique_base_name("of", owner="cam", owner_incarnation=True)
    assert str(os.getpid()) in name, f"pid обязателен в имени, получено '{name}'"


def test_h2_two_interpreters_produce_distinct_names():
    """H2 РЕПРОДЬЮСЕР: два ОТДЕЛЬНЫХ интерпретатора → РАЗНЫЕ имена (на POSIX без pid
    в имени `_incarnation` сбрасывается в каждом процессе → коллизия `..._1`)."""
    import multiprocess_framework

    root = os.path.dirname(os.path.dirname(os.path.abspath(multiprocess_framework.__file__)))
    code = (
        "from multiprocess_framework.modules.shared_resources_module.memory.platform.shm "
        "import _unique_base_name; "
        "print(_unique_base_name('output_frames', owner='camera_0', owner_incarnation=True))"
    )
    env = dict(os.environ, PYTHONPATH=root)
    n1 = subprocess.check_output([sys.executable, "-c", code], env=env, text=True).strip()
    n2 = subprocess.check_output([sys.executable, "-c", code], env=env, text=True).strip()
    assert n1 and n2 and n1 != n2, f"два интерпретатора дали одно имя: {n1!r} (H2 коллизия)"


# --- H3: длина имени ≤ лимита macOS (PSHMNAMLEN) ----------------------------------


def test_h3_long_owner_name_bounded_for_macos():
    """H3: длинный owner (process_grayscale из modbus_demo.yaml) → базовое имя ≤ 26."""
    name = _unique_base_name("output_frames", owner="process_grayscale", owner_incarnation=True)
    assert len(name) <= _MAX_BASE_NAME_LEN, f"имя '{name}' длиной {len(name)} > {_MAX_BASE_NAME_LEN}"
    # + суффикс _{idx} от create_shm_blocks (до _63) обязан уложиться в ~30.
    assert len(f"{name}_63") <= 30


def test_h3_short_name_not_compacted():
    """H3: короткое имя НЕ схлопывается (остаётся человекочитаемым)."""
    name = _unique_base_name("of", owner="cam", owner_incarnation=True)
    assert name.startswith("of_cam_") and len(name) <= _MAX_BASE_NAME_LEN
