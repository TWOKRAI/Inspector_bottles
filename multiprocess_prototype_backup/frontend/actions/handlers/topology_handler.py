# -*- coding: utf-8 -*-
"""TopologyActionHandler — обработчик TOPOLOGY_* actions для undo/redo.

Все TOPOLOGY_* actions используют snapshot-based подход:
forward_patch содержит snapshot_after, backward_patch — snapshot_before.
Apply/revert просто загружают соответствующий snapshot в model.
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.actions.schemas import Action

logger = logging.getLogger(__name__)


class TopologyActionHandler:
    """Обработчик topology-операций для ActionBus.

    apply() загружает snapshot_after, revert() — snapshot_before.
    Model (TopologyEditorModel) передаётся через set_model().
    """

    def __init__(self) -> None:
        self._model: Any = None

    def set_model(self, model: Any) -> None:
        """Привязать модель топологии.

        Args:
            model: TopologyEditorModel экземпляр.
        """
        self._model = model

    def apply(self, action: "Action", rm: Any) -> None:
        """Применить action (forward)."""
        if self._model is None:
            logger.warning("TopologyActionHandler.apply: model не привязан")
            return
        snapshot = action.forward_patch.get("snapshot_after")
        if snapshot is not None:
            # Поддержка обоих API: SourcesSectionView.load_from_snapshot и TopologyEditorModel.load_from_topology
            if hasattr(self._model, "load_from_snapshot"):
                self._model.load_from_snapshot(snapshot)
            else:
                self._model.load_from_topology(snapshot)

    def revert(self, action: "Action", rm: Any) -> None:
        """Откатить action (backward)."""
        if self._model is None:
            logger.warning("TopologyActionHandler.revert: model не привязан")
            return
        snapshot = action.backward_patch.get("snapshot_before")
        if snapshot is not None:
            # Поддержка обоих API: SourcesSectionView.load_from_snapshot и TopologyEditorModel.load_from_topology
            if hasattr(self._model, "load_from_snapshot"):
                self._model.load_from_snapshot(snapshot)
            else:
                self._model.load_from_topology(snapshot)
