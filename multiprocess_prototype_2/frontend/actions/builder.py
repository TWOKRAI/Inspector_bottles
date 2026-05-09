"""V2ActionBuilder — расширение FW ActionBuilder доменными методами v2."""
from __future__ import annotations

import time
from typing import Any

from multiprocess_framework.modules.frontend_module.actions.builder import ActionBuilder
from multiprocess_framework.modules.frontend_module.actions.schemas import Action

from .action_types import FIELD_SET, RECIPE_APPLY, PROCESS_ADD, PROCESS_REMOVE, WIRE_ADD, WIRE_REMOVE, NODE_MOVE


class V2ActionBuilder(ActionBuilder):
    """ActionBuilder с доменными методами прототипа v2."""

    @staticmethod
    def field_set_timed(
        register_name: str,
        field_name: str,
        new_value: Any,
        old_value: Any,
        *,
        description: str = "",
        coalesce_window_s: float = 1.5,
    ) -> Action:
        """Создать field_set Action с time-bucketed coalescing.

        Быстрые изменения одного поля сливаются в одно действие
        в пределах окна coalesce_window_s. После окна — новая строка в истории.
        """
        bucket = int(time.time() / coalesce_window_s)
        return Action(
            action_type=FIELD_SET,
            register_name=register_name,
            field_name=field_name,
            forward_patch={"value": new_value},
            backward_patch={"value": old_value},
            coalesce_key=f"field:{register_name}.{field_name}:{bucket}",
            undoable=True,
            description=description,
        )

    @staticmethod
    def recipe_apply(
        recipe_name: str,
        previous_topology: dict[str, Any],
        new_topology: dict[str, Any],
    ) -> Action:
        """Создать Action для применения рецепта (topology swap).

        Undoable: да — undo восстановит предыдущую topology.
        """
        return Action(
            action_type=RECIPE_APPLY,
            forward_patch={"topology": new_topology, "recipe_name": recipe_name},
            backward_patch={"topology": previous_topology},
            undoable=True,
            description=f"Применить рецепт: {recipe_name}",
        )

    @staticmethod
    def process_add(
        previous_topology: dict[str, Any],
        new_topology: dict[str, Any],
        process_name: str = "",
    ) -> Action:
        """Action для добавления процесса (undoable topology swap)."""
        return Action(
            action_type=PROCESS_ADD,
            forward_patch={"topology": new_topology},
            backward_patch={"topology": previous_topology},
            undoable=True,
            description=f"Добавить процесс: {process_name}",
        )

    @staticmethod
    def process_remove(
        previous_topology: dict[str, Any],
        new_topology: dict[str, Any],
        process_name: str = "",
    ) -> Action:
        """Action для удаления процесса (undoable topology swap)."""
        return Action(
            action_type=PROCESS_REMOVE,
            forward_patch={"topology": new_topology},
            backward_patch={"topology": previous_topology},
            undoable=True,
            description=f"Удалить процесс: {process_name}",
        )

    @staticmethod
    def wire_add(
        previous_topology: dict[str, Any],
        new_topology: dict[str, Any],
        source: str = "",
        target: str = "",
    ) -> Action:
        """Action для добавления wire (undoable topology swap)."""
        return Action(
            action_type=WIRE_ADD,
            forward_patch={"topology": new_topology},
            backward_patch={"topology": previous_topology},
            undoable=True,
            description=f"Добавить wire: {source} → {target}",
        )

    @staticmethod
    def wire_remove(
        previous_topology: dict[str, Any],
        new_topology: dict[str, Any],
        source: str = "",
        target: str = "",
    ) -> Action:
        """Action для удаления wire (undoable topology swap)."""
        return Action(
            action_type=WIRE_REMOVE,
            forward_patch={"topology": new_topology},
            backward_patch={"topology": previous_topology},
            undoable=True,
            description=f"Удалить wire: {source} → {target}",
        )

    @staticmethod
    def node_move(
        node_id: str,
        old_x: float,
        old_y: float,
        new_x: float,
        new_y: float,
        *,
        coalesce_window_s: float = 0.5,
    ) -> Action:
        """Action для перемещения ноды (GUI-only, undoable).

        coalesce_key группирует быстрые drag-тики в одну undo-запись.
        """
        bucket = int(time.time() / coalesce_window_s)
        return Action(
            action_type=NODE_MOVE,
            forward_patch={"node_id": node_id, "x": new_x, "y": new_y},
            backward_patch={"node_id": node_id, "x": old_x, "y": old_y},
            coalesce_key=f"move:{node_id}:{bucket}",
            undoable=True,
            description=f"Переместить узел: {node_id}",
        )
