# -*- coding: utf-8 -*-
"""Ф3.1 (routing-epoch): примитивы PSR — clear/drop идемпотентны, reuse_queues.

- ProcessData.clear_queues / PSR.drop_process_queues: очистка in-place, идемпотентны;
- SharedResourcesManager.register_process(reuse_queues=True): создаёт только
  недостающие qtype, identity существующих очередей сохраняется;
- дефолт reuse_queues=False: очереди пересоздаются (identity меняется) — как раньше.
"""

from __future__ import annotations

from multiprocessing import Queue

import pytest

from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager
from multiprocess_framework.modules.shared_resources_module.state.process_data import ProcessData


def _ids(pd) -> dict:
    return {qt: id(q) for qt, q in pd.queues.items()}


@pytest.fixture
def srm():
    m = SharedResourcesManager()
    m.initialize()
    yield m
    m.shutdown()


# ---------------------------------------------------------------------------
# clear_queues / drop_process_queues
# ---------------------------------------------------------------------------


def test_clear_queues_empties_proxy():
    pd = ProcessData(name="p")
    pd.add_queue("system", Queue())
    pd.add_queue("data", Queue())
    assert len(pd.queues) == 2
    pd.clear_queues()
    assert len(pd.queues) == 0
    # Идемпотентно.
    pd.clear_queues()
    assert len(pd.queues) == 0


def test_drop_process_queues_idempotent(srm):
    srm.register_process("p", {"queues": {"system": {"maxsize": 5}, "data": {"maxsize": 5}}})
    psr = srm.process_state_registry
    assert len(srm.get_process_data("p").queues) == 2
    # Первый сброс — True, очереди пусты.
    assert psr.drop_process_queues("p") is True
    assert len(srm.get_process_data("p").queues) == 0
    # Повтор — снова True (запись есть, очередей нет).
    assert psr.drop_process_queues("p") is True
    # Несуществующий процесс — False.
    assert psr.drop_process_queues("no_such") is False


# ---------------------------------------------------------------------------
# reuse_queues
# ---------------------------------------------------------------------------


def test_reuse_queues_preserves_identity(srm):
    cfg = {"queues": {"system": {"maxsize": 5}, "data": {"maxsize": 5}}}
    srm.register_process("p", cfg)
    ids_before = _ids(srm.get_process_data("p"))
    # Повторная регистрация с reuse — identity очередей сохранена.
    srm.register_process("p", cfg, reuse_queues=True)
    ids_after = _ids(srm.get_process_data("p"))
    assert ids_after == ids_before


def test_reuse_creates_only_missing(srm):
    srm.register_process("p", {"queues": {"system": {"maxsize": 5}}})
    id_sys = id(srm.get_process_data("p").queues["system"])
    # Добавился qtype data — создаётся только он, system сохранён.
    srm.register_process("p", {"queues": {"system": {"maxsize": 5}, "data": {"maxsize": 5}}}, reuse_queues=True)
    pd = srm.get_process_data("p")
    assert id(pd.queues["system"]) == id_sys
    assert "data" in pd.queues


def test_default_recreates_queues(srm):
    srm.register_process("p", {"queues": {"system": {"maxsize": 5}}})
    id_before = id(srm.get_process_data("p").queues["system"])
    # Дефолт reuse_queues=False — очередь пересоздаётся (identity меняется).
    srm.register_process("p", {"queues": {"system": {"maxsize": 5}}})
    id_after = id(srm.get_process_data("p").queues["system"])
    assert id_after != id_before
