# -*- coding: utf-8 -*-
"""Тесты для TopologyMutationHandler (FW)."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, call

import pytest

from multiprocess_framework.modules.frontend_module.actions.handlers.topology_handler import (
    TopologyMutationHandler,
    TopologyBridgeProtocol,
    TopologyHolderProtocol,
)
from multiprocess_framework.modules.frontend_module.actions.schemas import Action


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------

def _make_action(forward_topo: dict, backward_topo: dict) -> Action:
    """Создать Action с topology в патчах."""
    return Action(
        action_type="PROCESS_ADD",
        forward_patch={"topology": forward_topo} if forward_topo is not None else {},
        backward_patch={"topology": backward_topo} if backward_topo is not None else {},
    )


def _make_empty_action(include_forward: bool = False) -> Action:
    """Создать Action с пустым forward_patch (нет ключа topology)."""
    forward = {"topology": {"nodes": []}} if include_forward else {}
    return Action(
        action_type="PROCESS_ADD",
        forward_patch=forward,
        backward_patch={},
    )


# ---------------------------------------------------------------------------
# Тест 1: apply устанавливает topology через holder
# ---------------------------------------------------------------------------

def test_apply_sets_topology_on_holder():
    """apply() вызывает holder.set_topology с данными из forward_patch."""
    holder = MagicMock()
    handler = TopologyMutationHandler(holder)
    topo = {"nodes": ["n1"], "edges": []}
    action = _make_action(forward_topo=topo, backward_topo={})

    handler.apply(action, rm=None)

    holder.set_topology.assert_called_once_with(topo)


# ---------------------------------------------------------------------------
# Тест 2: revert устанавливает topology из backward_patch
# ---------------------------------------------------------------------------

def test_revert_sets_topology_from_backward_patch():
    """revert() вызывает holder.set_topology с данными из backward_patch."""
    holder = MagicMock()
    handler = TopologyMutationHandler(holder)
    old_topo = {"nodes": ["n0"], "edges": []}
    new_topo = {"nodes": ["n0", "n1"], "edges": []}
    action = _make_action(forward_topo=new_topo, backward_topo=old_topo)

    handler.revert(action, rm=None)

    holder.set_topology.assert_called_once_with(old_topo)


# ---------------------------------------------------------------------------
# Тест 3: apply вызывает bridge.apply_topology_diff
# ---------------------------------------------------------------------------

def test_apply_calls_bridge_diff():
    """apply() вызывает bridge.apply_topology_diff(old, new) при наличии bridge."""
    holder = MagicMock()
    bridge = MagicMock()
    handler = TopologyMutationHandler(holder, topology_bridge=bridge)
    old_topo = {"nodes": [], "edges": []}
    new_topo = {"nodes": ["n1"], "edges": []}
    action = _make_action(forward_topo=new_topo, backward_topo=old_topo)

    handler.apply(action, rm=None)

    bridge.apply_topology_diff.assert_called_once_with(old_topo, new_topo)


# ---------------------------------------------------------------------------
# Тест 4: revert вызывает bridge.apply_topology_diff в обратном порядке
# ---------------------------------------------------------------------------

def test_revert_calls_bridge_diff_reversed():
    """revert() вызывает bridge.apply_topology_diff(new, old)."""
    holder = MagicMock()
    bridge = MagicMock()
    handler = TopologyMutationHandler(holder, topology_bridge=bridge)
    old_topo = {"nodes": [], "edges": []}
    new_topo = {"nodes": ["n1"], "edges": []}
    action = _make_action(forward_topo=new_topo, backward_topo=old_topo)

    handler.revert(action, rm=None)

    bridge.apply_topology_diff.assert_called_once_with(new_topo, old_topo)


# ---------------------------------------------------------------------------
# Тест 5: graceful degradation — без bridge apply не падает
# ---------------------------------------------------------------------------

def test_apply_without_bridge_no_crash():
    """apply() без bridge работает корректно — только holder.set_topology."""
    holder = MagicMock()
    handler = TopologyMutationHandler(holder)
    topo = {"nodes": ["n1"], "edges": []}
    action = _make_action(forward_topo=topo, backward_topo={})

    handler.apply(action, rm=None)  # не должно выбросить исключение

    holder.set_topology.assert_called_once_with(topo)


# ---------------------------------------------------------------------------
# Тест 6: apply с пустым forward_patch — ранний выход, holder не вызывается
# ---------------------------------------------------------------------------

def test_apply_empty_forward_patch_skips_holder(caplog):
    """apply() с пустым forward_patch логирует warning и не вызывает holder."""
    holder = MagicMock()
    handler = TopologyMutationHandler(holder)
    action = _make_empty_action(include_forward=False)

    with caplog.at_level(logging.WARNING):
        handler.apply(action, rm=None)

    holder.set_topology.assert_not_called()
    assert "topology пуст" in caplog.text


# ---------------------------------------------------------------------------
# Тест 7: revert с пустым backward_patch — ранний выход
# ---------------------------------------------------------------------------

def test_revert_empty_backward_patch_skips_holder(caplog):
    """revert() с пустым backward_patch логирует warning и не вызывает holder."""
    holder = MagicMock()
    handler = TopologyMutationHandler(holder)
    # backward_patch не содержит topology
    action = Action(
        action_type="PROCESS_REMOVE",
        forward_patch={"topology": {"nodes": ["n1"]}},
        backward_patch={},
    )

    with caplog.at_level(logging.WARNING):
        handler.revert(action, rm=None)

    holder.set_topology.assert_not_called()
    assert "topology пуст" in caplog.text


# ---------------------------------------------------------------------------
# Тест 8: bridge.apply_topology_diff падает — graceful degradation
# ---------------------------------------------------------------------------

def test_apply_bridge_exception_graceful(caplog):
    """bridge.apply_topology_diff() кидает исключение — handler не падает."""
    holder = MagicMock()
    bridge = MagicMock()
    bridge.apply_topology_diff.side_effect = RuntimeError("bridge error")
    handler = TopologyMutationHandler(holder, topology_bridge=bridge)
    topo = {"nodes": ["n1"], "edges": []}
    action = _make_action(forward_topo=topo, backward_topo={})

    handler.apply(action, rm=None)  # не должно пробросить RuntimeError

    holder.set_topology.assert_called_once()
