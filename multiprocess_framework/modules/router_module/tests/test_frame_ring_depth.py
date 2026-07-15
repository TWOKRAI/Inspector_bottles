# -*- coding: utf-8 -*-
"""Ф7 G.4.b — конфигурируемая глубина кольца SHM per-camera (B-8) + изоляция цепочек.

Раньше глубина была ЖЁСТКО 3 везде, `buffer_slots` из wire-команды игнорировался
(«информативно») → кольцо не настраивалось (де-факто одно-слотовый round-robin). Теперь:
явный coll (рецепт/wire) > QoS-профиль data при FW_QOS_PROFILES > 3. Каждый source =
свой owner = своё независимое кольцо (общего слота нет).
"""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)


def _frame(val: int = 50) -> np.ndarray:
    return np.full((32, 48, 3), val, dtype=np.uint8)


class TestResolveRingDepth:
    def test_explicit_wins(self):
        assert FrameShmMiddleware._resolve_ring_depth(8) == 8
        assert FrameShmMiddleware._resolve_ring_depth(1) == 1

    def test_none_defaults_to_3_without_flag(self, monkeypatch):
        monkeypatch.delenv("FW_QOS_PROFILES", raising=False)
        assert FrameShmMiddleware._resolve_ring_depth(None) == 3

    def test_none_uses_profile_with_flag(self, monkeypatch):
        monkeypatch.setenv("FW_QOS_PROFILES", "1")
        # qos_for("data").history_depth == 4 (боевая глубина «несколько кадров»)
        assert FrameShmMiddleware._resolve_ring_depth(None) == 4

    def test_nonpositive_explicit_falls_through(self, monkeypatch):
        monkeypatch.delenv("FW_QOS_PROFILES", raising=False)
        assert FrameShmMiddleware._resolve_ring_depth(0) == 3
        assert FrameShmMiddleware._resolve_ring_depth(-2) == 3

    def test_ctor_uses_resolved_depth(self, monkeypatch):
        monkeypatch.delenv("FW_QOS_PROFILES", raising=False)
        assert FrameShmMiddleware(MemoryManager(), owner="o", slot="s")._coll == 3
        assert FrameShmMiddleware(MemoryManager(), owner="o", slot="s", coll=6)._coll == 6
        monkeypatch.setenv("FW_QOS_PROFILES", "1")
        assert FrameShmMiddleware(MemoryManager(), owner="o", slot="s")._coll == 4


class TestRingWraps:
    def test_write_index_cycles_over_coll(self):
        """Кадры пишутся round-robin по coll слотам: shm_index циклит 0..coll-1."""
        mw = FrameShmMiddleware(MemoryManager(), owner="cam", slot="output_frames", coll=4)
        indices = []
        for i in range(10):
            out = mw.strip_and_write({"frame": _frame(i), "seq": i})
            indices.append(out.get("shm_index"))
        assert indices == [0, 1, 2, 3, 0, 1, 2, 3, 0, 1]  # депт 4 → цикл

    def test_deeper_ring_holds_more_slots(self):
        """coll=6 → 6 различных слотов до перезаписи (не де-факто одно-слотовый)."""
        mw = FrameShmMiddleware(MemoryManager(), owner="cam", slot="output_frames", coll=6)
        seen = {mw.strip_and_write({"frame": _frame(i)}).get("shm_index") for i in range(6)}
        assert seen == {0, 1, 2, 3, 4, 5}


class TestPerCameraIsolation:
    def test_two_cameras_independent_rings(self, monkeypatch):
        """Два owner'а на одном MemoryManager → независимые регионы/кольца, без коллизий.

        Изоляция OS-имён SHM-сегментов (assert shm_actual_name) держится под флагом
        FW_SHM_OWNER_INCARNATION (owner+incarnation в имени, фундамент G.3) — иначе оба
        owner'а получают `{slot}_{index}` и OS-имена совпадают. Ставим флаг явно: без
        него тест проходил лишь из-за утечки env по порядку прогона (детерминированно
        падал в изоляции). Данные-изоляция (регионы по (owner,slot)) держится и без флага.
        """
        monkeypatch.setenv("FW_SHM_OWNER_INCARNATION", "1")
        mm = MemoryManager()
        cam0 = FrameShmMiddleware(mm, owner="cam0", slot="output_frames", coll=3)
        cam1 = FrameShmMiddleware(mm, owner="cam1", slot="output_frames", coll=3)

        out0 = cam0.strip_and_write({"frame": _frame(11)})
        out1 = cam1.strip_and_write({"frame": _frame(22)})

        # Разные владельцы → разные SHM-сегменты (изоляция цепочек камер).
        assert out0["shm_owner"] == "cam0"
        assert out1["shm_owner"] == "cam1"
        assert out0["shm_actual_name"] != out1["shm_actual_name"]

        # Кадр каждой камеры восстанавливается своим значением (нет перепутывания).
        f0 = cam0.restore_frame({"data": out0})["frame"]
        f1 = cam1.restore_frame({"data": out1})["frame"]
        assert int(f0[0, 0, 0]) == 11
        assert int(f1[0, 0, 0]) == 22

    def test_camera_write_indices_independent(self):
        """write_index каждой камеры считается отдельно (замедление одной не сдвигает другую)."""
        mm = MemoryManager()
        cam0 = FrameShmMiddleware(mm, owner="cam0", slot="output_frames", coll=3)
        cam1 = FrameShmMiddleware(mm, owner="cam1", slot="output_frames", coll=3)
        for _ in range(5):
            cam0.strip_and_write({"frame": _frame(1)})
        cam1.strip_and_write({"frame": _frame(2)})
        assert cam0._write_index == 5
        assert cam1._write_index == 1
