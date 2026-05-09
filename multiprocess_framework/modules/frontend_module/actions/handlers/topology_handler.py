# -*- coding: utf-8 -*-
"""TopologyMutationHandler — apply/revert мутаций topology с bridge-синхронизацией.

Protocol-заглушки (TopologyHolderProtocol, TopologyBridgeProtocol) определены
здесь, чтобы FW не импортировал ничего из прототипа в runtime.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.actions.schemas import Action

logger = logging.getLogger(__name__)


class TopologyHolderProtocol(Protocol):
    """Минимальный интерфейс объекта, хранящего topology в GUI."""

    def set_topology(self, topology: dict) -> None:
        """Установить новую topology."""
        ...


class TopologyBridgeProtocol(Protocol):
    """Минимальный интерфейс bridge для синхронизации topology с бэкендом."""

    def apply_topology_diff(self, old_topo: dict, new_topo: dict) -> None:
        """Применить diff topology (old → new) к бэкенду."""
        ...


class TopologyMutationHandler:
    """Обработчик мутаций topology: PROCESS_ADD/REMOVE, WIRE_ADD/REMOVE.

    apply: устанавливает topology из forward_patch + bridge.apply_topology_diff().
    revert: восстанавливает topology из backward_patch + bridge.apply_topology_diff().
    Graceful degradation: без bridge — только GUI (topology_holder swap).
    """

    def __init__(
        self,
        topology_holder: TopologyHolderProtocol,
        *,
        topology_bridge: TopologyBridgeProtocol | None = None,
    ) -> None:
        self._holder = topology_holder
        self._bridge = topology_bridge

    def apply(self, action: "Action", rm: Any) -> None:
        """Применить мутацию topology (forward_patch)."""
        new_topology = action.forward_patch.get("topology", {})
        old_topology = action.backward_patch.get("topology", {})
        if not new_topology:
            logger.warning("topology_mutation apply: topology пуст в forward_patch")
            return
        self._holder.set_topology(new_topology)
        self._apply_bridge_diff(old_topology, new_topology)

    def revert(self, action: "Action", rm: Any) -> None:
        """Откатить мутацию topology (backward_patch)."""
        old_topology = action.backward_patch.get("topology", {})
        new_topology = action.forward_patch.get("topology", {})
        if not old_topology:
            logger.warning("topology_mutation revert: topology пуст в backward_patch")
            return
        self._holder.set_topology(old_topology)
        self._apply_bridge_diff(new_topology, old_topology)

    def _apply_bridge_diff(self, old_topo: dict, new_topo: dict) -> None:
        """Вызвать bridge.apply_topology_diff() если bridge доступен."""
        if self._bridge is None:
            return
        try:
            self._bridge.apply_topology_diff(old_topo, new_topo)
        except Exception:
            logger.debug(
                "bridge.apply_topology_diff() failed — graceful degradation",
                exc_info=True,
            )
