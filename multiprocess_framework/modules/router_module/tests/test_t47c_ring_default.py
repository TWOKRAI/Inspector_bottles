# -*- coding: utf-8 -*-
"""Task 4.7c — слепые приёмочные тесты дефолтной глубины кольца = 8 (RED до реализации).

Без env и без настройки глубина кольца generic-писателя 8 и wire ``buffer_slots`` 8;
гейта ``FW_QOS_PROFILES`` на глубину нет. Сегодня: 3 (4 при QoS) и 4.
"""

from __future__ import annotations

import os

import pytest

from multiprocess_framework.modules.frontend_module.bridge.wire_protocol import ShmConfig, WireConfig
from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager


@pytest.fixture(autouse=True)
def _clean_shm_and_qos_env(monkeypatch):
    """Все FW_SHM_* и FW_QOS_PROFILES убраны: тест видит именно «без env и без настройки»."""
    for name in [n for n in os.environ if n.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("FW_QOS_PROFILES", raising=False)


@pytest.mark.parametrize("qos", [None, "1"], ids=["no-env", "qos-profiles-on"])
@pytest.mark.parametrize("explicit", [None, 0, -2], ids=["none", "zero", "negative"])
def test_generic_writer_ring_default_8_without_env(monkeypatch, qos, explicit):
    """Глубина не задана (None / 0 / <0 = «не задана» в рецепте) -> 8, и это не зависит от
    FW_QOS_PROFILES (гейта на глубину нет — при QoS не 4)."""
    if qos is not None:
        monkeypatch.setenv("FW_QOS_PROFILES", qos)
    assert FrameShmMiddleware._resolve_ring_depth(explicit) == 8
    assert FrameShmMiddleware(MemoryManager(), owner="o", slot="s", coll=explicit)._coll == 8


def test_explicit_ring_depth_still_wins_over_default():
    """Контроль: явная глубина по-прежнему выигрывает у дефолта 8 (в обе стороны от 8)."""
    assert FrameShmMiddleware._resolve_ring_depth(12) == 12
    assert FrameShmMiddleware._resolve_ring_depth(5) == 5


@pytest.mark.parametrize(
    "make",
    [
        pytest.param(lambda: ShmConfig().buffer_slots, id="ShmConfig-default"),
        pytest.param(
            lambda: WireConfig.from_topology_entry("w", {"source": "a.p.o", "target": "b.p.i"}).shm_config.buffer_slots,
            id="from_topology_entry-without-shm_config",
        ),
        pytest.param(
            lambda: WireConfig.from_topology_entry("w", {"shm_config": {}}).shm_config.buffer_slots,
            id="from_topology_entry-empty-shm_config",
        ),
    ],
)
def test_wire_buffer_slots_default_8(make):
    """Wire без явного buffer_slots получает 8 — со всех трёх путей построения конфига."""
    assert make() == 8


def test_wire_explicit_buffer_slots_survives_round_trip():
    """Контроль: явный buffer_slots не затирается дефолтом (round-trip в topology dict и обратно)."""
    entry = {"source": "a.p.o", "target": "b.p.i", "shm_config": {"buffer_slots": 12}}
    wire = WireConfig.from_topology_entry("w", entry)
    assert wire.shm_config.buffer_slots == 12
    assert WireConfig.from_topology_entry("w", wire.to_topology_entry()).shm_config.buffer_slots == 12
