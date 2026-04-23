# -*- coding: utf-8 -*-
"""
ActionBuilder — фабрика для создания Action.

Статические методы гарантируют корректное заполнение полей:
- field_set() — изменение поля регистра с coalesce_key
- from_field() — то же, но принимает RegisterBinding
- command() — side-effect без undo
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from frontend_module.schemas.register_binding import RegisterBinding

from .schemas import Action, ActionType


class ActionBuilder:
    """Фабрика Action с удобными статическими методами."""

    @staticmethod
    def _make_id() -> str:
        """Генерация уникального идентификатора."""
        return str(uuid.uuid4())

    @staticmethod
    def field_set(
        register_name: str,
        field_name: str,
        new_value: Any,
        old_value: Any,
        *,
        description: str = "",
    ) -> Action:
        """
        Создать Action для изменения поля регистра.

        coalesce_key формируется как "field:{register_name}.{field_name}",
        что позволяет группировать последовательные изменения одного поля
        (например, тики слайдера) в одно действие.
        """
        return Action(
            action_type=ActionType.FIELD_SET,
            register_name=register_name,
            field_name=field_name,
            forward_patch={"value": new_value},
            backward_patch={"value": old_value},
            coalesce_key=f"field:{register_name}.{field_name}",
            undoable=True,
            description=description,
        )

    @staticmethod
    def from_field(
        binding: RegisterBinding,
        new_value: Any,
        old_value: Any,
        *,
        description: str = "",
    ) -> Action:
        """
        Создать Action из RegisterBinding.

        Удобная обёртка над field_set() для случаев,
        когда привязка к регистру уже есть в виде RegisterBinding.
        """
        return ActionBuilder.field_set(
            register_name=binding.register_name,
            field_name=binding.field_name,
            new_value=new_value,
            old_value=old_value,
            description=description,
        )

    @staticmethod
    def command(description: str) -> Action:
        """
        Создать Action-команду (side-effect без undo).

        COMMAND не имеет forward/backward патчей и не может быть отменён.
        """
        return Action(
            action_type=ActionType.COMMAND,
            undoable=False,
            description=description,
        )

    @staticmethod
    def profile_switch(
        profile_id: str,
        registers_snapshot_before: Any,
        registers_snapshot_after: Any,
    ) -> "Action":
        """
        Создать Action для переключения профиля настроек.

        forward_patch содержит profile_id и снимок регистров после переключения.
        backward_patch содержит снимок регистров до переключения для отката.

        Один profile switch = 1 Action (не N по числу полей).
        """
        return Action(
            action_type=ActionType.PROFILE_SWITCH,
            forward_patch={
                "profile_id": profile_id,
                "snapshot": registers_snapshot_after,
            },
            backward_patch={
                "snapshot": registers_snapshot_before,
            },
            undoable=True,
            description=f"Профиль: {profile_id}",
        )

    @staticmethod
    def recipe_switch(
        slot_id: str,
        registers_snapshot_before: Any,
        registers_snapshot_after: Any,
    ) -> "Action":
        """
        Создать Action для переключения рецепта.

        forward_patch содержит slot_id и снимок регистров после переключения.
        backward_patch содержит снимок регистров до переключения для отката.

        Один recipe switch = 1 Action (не N по числу полей).
        """
        return Action(
            action_type=ActionType.RECIPE_SWITCH,
            forward_patch={
                "slot_id": slot_id,
                "snapshot": registers_snapshot_after,
            },
            backward_patch={
                "snapshot": registers_snapshot_before,
            },
            undoable=True,
            description=f"Рецепт: {slot_id}",
        )

    @staticmethod
    def region_add(
        camera_id: str,
        region_data: Any,
        pipeline_snapshot_before: Any,
        *,
        register_name: str,
    ) -> "Action":
        """
        Создать Action для добавления региона.

        forward_patch содержит camera_id, region_data и pipeline_after (None — вычисляется при apply).
        backward_patch содержит pipeline_before для отката.
        """
        region_name = (
            region_data.get("name", "") if isinstance(region_data, dict) else str(region_data)
        )
        return Action(
            action_type=ActionType.REGION_ADD,
            register_name=register_name,
            field_name="vision_pipeline",
            forward_patch={
                "camera_id": camera_id,
                "region_data": region_data,
                "pipeline_after": None,  # заполняется перед execute
            },
            backward_patch={
                "pipeline_before": pipeline_snapshot_before,
            },
            undoable=True,
            description=f"Добавить регион «{region_name}» камера {camera_id}",
        )

    @staticmethod
    def region_remove(
        camera_id: str,
        region_name: str,
        pipeline_before: Any,
        pipeline_after: Any,
        *,
        register_name: str,
    ) -> "Action":
        """
        Создать Action для удаления региона.

        forward_patch содержит pipeline_after (состояние после удаления).
        backward_patch содержит pipeline_before для отката.
        """
        return Action(
            action_type=ActionType.REGION_REMOVE,
            register_name=register_name,
            field_name="vision_pipeline",
            forward_patch={
                "pipeline_after": pipeline_after,
            },
            backward_patch={
                "pipeline_before": pipeline_before,
            },
            undoable=True,
            description=f"Удалить регион «{region_name}» камера {camera_id}",
        )

    @staticmethod
    def region_modify(
        camera_id: str,
        region_name: str,
        pipeline_before: Any,
        pipeline_after: Any,
        *,
        register_name: str,
    ) -> "Action":
        """
        Создать Action для изменения региона.

        Использует FIELD_SET (нет отдельного REGION_MODIFY в ActionType),
        поэтому обрабатывается стандартным FieldSetHandler через ключ "value".
        coalesce_key обеспечивает группировку последовательных изменений
        одного и того же региона (например, перетаскивание границы).
        """
        return Action(
            action_type=ActionType.FIELD_SET,
            register_name=register_name,
            field_name="vision_pipeline",
            forward_patch={"value": pipeline_after},
            backward_patch={"value": pipeline_before},
            coalesce_key=f"region_modify:{register_name}:{camera_id}:{region_name}",
            undoable=True,
            description=f"Изменить регион «{region_name}» камера {camera_id}",
        )

    # ------------------------------------------------------------------
    # STEP_* — операции над шагами цепочки обработки
    # ------------------------------------------------------------------

    @staticmethod
    def step_add(
        region_id: str,
        node_data: Any,
        nodes_snapshot_before: Any,
    ) -> "Action":
        """
        Создать Action для добавления шага в цепочку обработки.

        forward_patch содержит node_data (данные нового узла) и region_id.
        backward_patch содержит nodes_snapshot_before для отката через revert.

        Args:
            region_id: Идентификатор региона (используется как register_name).
            node_data: Данные добавляемого узла (ProcessingNode или dict).
            nodes_snapshot_before: Снимок всех узлов до добавления.
        """
        node_label = node_data if isinstance(node_data, str) else str(node_data)
        return Action(
            action_type=ActionType.STEP_ADD,
            register_name=region_id,
            field_name="nodes",
            forward_patch={
                "region_id": region_id,
                "node_data": node_data,
            },
            backward_patch={
                "nodes_snapshot_before": nodes_snapshot_before,
            },
            undoable=True,
            description=f"Добавить шаг в цепочку региона {region_id}: {node_label}",
        )

    @staticmethod
    def step_remove(
        region_id: str,
        node_id: str,
        nodes_snapshot_before: Any,
        nodes_snapshot_after: Any,
    ) -> "Action":
        """
        Создать Action для удаления шага из цепочки обработки.

        forward_patch содержит nodes_snapshot_after (состояние после удаления).
        backward_patch содержит nodes_snapshot_before для отката.

        Args:
            region_id: Идентификатор региона.
            node_id: Идентификатор удаляемого узла.
            nodes_snapshot_before: Снимок узлов до удаления.
            nodes_snapshot_after: Снимок узлов после удаления.
        """
        return Action(
            action_type=ActionType.STEP_REMOVE,
            register_name=region_id,
            field_name="nodes",
            forward_patch={
                "nodes_snapshot_after": nodes_snapshot_after,
            },
            backward_patch={
                "nodes_snapshot_before": nodes_snapshot_before,
            },
            undoable=True,
            description=f"Удалить шаг {node_id} из цепочки региона {region_id}",
        )

    @staticmethod
    def step_modify(
        region_id: str,
        node_id: str,
        node_before: Any,
        node_after: Any,
    ) -> "Action":
        """
        Создать Action для изменения параметров шага цепочки.

        coalesce_key группирует последовательные изменения одного узла
        (например, редактирование числового параметра посимвольно).

        Args:
            region_id: Идентификатор региона.
            node_id: Идентификатор изменяемого узла.
            node_before: Состояние узла до изменения.
            node_after: Состояние узла после изменения.
        """
        return Action(
            action_type=ActionType.STEP_MODIFY,
            register_name=region_id,
            field_name="nodes",
            forward_patch={
                "node_id": node_id,
                "node_after": node_after,
            },
            backward_patch={
                "node_id": node_id,
                "node_before": node_before,
            },
            coalesce_key=f"step_modify:{region_id}:{node_id}",
            undoable=True,
            description=f"Изменить шаг {node_id} в цепочке региона {region_id}",
        )

    @staticmethod
    def step_reorder(
        region_id: str,
        node_id: str,
        direction: str,
        nodes_before: Any,
        nodes_after: Any,
    ) -> "Action":
        """
        Создать Action для перемещения шага в цепочке обработки.

        forward_patch содержит nodes_after (состояние после перестановки).
        backward_patch содержит nodes_before для отката.

        Args:
            region_id: Идентификатор региона.
            node_id: Идентификатор перемещаемого узла.
            direction: Направление перемещения ('up' или 'down').
            nodes_before: Снимок узлов до перемещения.
            nodes_after: Снимок узлов после перемещения.
        """
        return Action(
            action_type=ActionType.STEP_REORDER,
            register_name=region_id,
            field_name="nodes",
            forward_patch={
                "nodes_after": nodes_after,
            },
            backward_patch={
                "nodes_before": nodes_before,
            },
            undoable=True,
            description=f"Переместить шаг {node_id} {direction} в цепочке региона {region_id}",
        )

    # ------------------------------------------------------------------
    # DISPLAY_* — операции над display-подписками
    # ------------------------------------------------------------------

    @staticmethod
    def display_subscribe(
        source_ref: str,
        subscription_data: Any,
    ) -> "Action":
        """
        Создать Action для подписки display-окна на источник кадров.

        undoable=False: display-подписки не попадают в undo/redo стек.

        Args:
            source_ref: Идентификатор источника (camera_N, processor_N.region.step).
            subscription_data: Данные подписки (DisplaySubscription или dict).
        """
        return Action(
            action_type=ActionType.DISPLAY_SUBSCRIBE,
            forward_patch={
                "source_ref": source_ref,
                "subscription_data": subscription_data,
            },
            backward_patch={},
            undoable=False,
            description=f"Подписать display-окно на источник {source_ref}",
        )

    @staticmethod
    def display_unsubscribe(
        source_ref: str,
    ) -> "Action":
        """
        Создать Action для отписки display-окна от источника кадров.

        undoable=False: отписки не попадают в undo/redo стек.

        Args:
            source_ref: Идентификатор источника кадров для отписки.
        """
        return Action(
            action_type=ActionType.DISPLAY_UNSUBSCRIBE,
            forward_patch={
                "source_ref": source_ref,
            },
            backward_patch={},
            undoable=False,
            description=f"Отписать display-окно от источника {source_ref}",
        )

    # ------------------------------------------------------------------
    # GRAPH_* — операции в графовом редакторе (Phase 8)
    # ------------------------------------------------------------------

    @staticmethod
    def graph_connect(
        region_id: str,
        source_node_id: str,
        output_port: str,
        target_node_id: str,
        input_port: str,
        nodes_before: Any,
        nodes_after: Any,
    ) -> "Action":
        """
        Создать Action для соединения двух узлов графа портами.

        forward_patch содержит nodes_after — снимок после добавления связи.
        backward_patch содержит nodes_before для отката (разрыв связи).

        Args:
            region_id: Идентификатор региона (register_name).
            source_node_id: Идентификатор узла-источника.
            output_port: Имя выходного порта источника.
            target_node_id: Идентификатор узла-приёмника.
            input_port: Имя входного порта приёмника.
            nodes_before: Снимок узлов до создания связи.
            nodes_after: Снимок узлов после создания связи.
        """
        return Action(
            action_type=ActionType.GRAPH_CONNECT,
            register_name=region_id,
            field_name="nodes",
            forward_patch={"nodes_after": nodes_after},
            backward_patch={"nodes_before": nodes_before},
            undoable=True,
            description=f"Соединить {source_node_id}.{output_port} → {target_node_id}.{input_port}",
        )

    @staticmethod
    def graph_disconnect(
        region_id: str,
        source_node_id: str,
        output_port: str,
        target_node_id: str,
        input_port: str,
        nodes_before: Any,
        nodes_after: Any,
    ) -> "Action":
        """
        Создать Action для разрыва связи между узлами графа.

        forward_patch содержит nodes_after — снимок после удаления связи.
        backward_patch содержит nodes_before для отката (восстановление связи).

        Args:
            region_id: Идентификатор региона (register_name).
            source_node_id: Идентификатор узла-источника.
            output_port: Имя выходного порта источника.
            target_node_id: Идентификатор узла-приёмника.
            input_port: Имя входного порта приёмника.
            nodes_before: Снимок узлов до удаления связи.
            nodes_after: Снимок узлов после удаления связи.
        """
        return Action(
            action_type=ActionType.GRAPH_DISCONNECT,
            register_name=region_id,
            field_name="nodes",
            forward_patch={"nodes_after": nodes_after},
            backward_patch={"nodes_before": nodes_before},
            undoable=True,
            description=f"Разъединить {source_node_id}.{output_port} → {target_node_id}.{input_port}",
        )

    @staticmethod
    def graph_node_add(
        region_id: str,
        node_data: Any,
        nodes_before: Any,
        nodes_after: Any,
    ) -> "Action":
        """
        Создать Action для добавления узла в граф региона.

        forward_patch содержит nodes_after и node_data нового узла.
        backward_patch содержит nodes_before для отката (удаление узла).

        Args:
            region_id: Идентификатор региона (register_name).
            node_data: Данные добавляемого узла (dict или объект).
            nodes_before: Снимок узлов до добавления.
            nodes_after: Снимок узлов после добавления.
        """
        return Action(
            action_type=ActionType.GRAPH_NODE_ADD,
            register_name=region_id,
            field_name="nodes",
            forward_patch={"nodes_after": nodes_after, "node_data": node_data},
            backward_patch={"nodes_before": nodes_before},
            undoable=True,
            description=f"Добавить узел в граф региона {region_id}",
        )

    @staticmethod
    def graph_node_remove(
        region_id: str,
        node_id: str,
        nodes_before: Any,
        nodes_after: Any,
    ) -> "Action":
        """
        Создать Action для удаления узла из графа региона.

        forward_patch содержит nodes_after — снимок после удаления.
        backward_patch содержит nodes_before для отката (восстановление узла).

        Args:
            region_id: Идентификатор региона (register_name).
            node_id: Идентификатор удаляемого узла.
            nodes_before: Снимок узлов до удаления.
            nodes_after: Снимок узлов после удаления.
        """
        return Action(
            action_type=ActionType.GRAPH_NODE_REMOVE,
            register_name=region_id,
            field_name="nodes",
            forward_patch={"nodes_after": nodes_after},
            backward_patch={"nodes_before": nodes_before},
            undoable=True,
            description=f"Удалить узел {node_id} из графа региона {region_id}",
        )

    @staticmethod
    def graph_node_move(
        region_id: str,
        node_id: str,
        old_pos: "tuple[float, float] | None",
        new_pos: "tuple[float, float]",
    ) -> "Action":
        """
        Создать Action для перемещения узла графа.

        coalesce_key группирует серию перемещений одного узла в одно действие
        (аналогично слайдеру — перетаскивание = 1 Action в стеке).
        Позиция хранится в patch-ах; presenter обновит UI при undo/redo.

        Args:
            region_id: Идентификатор региона (register_name).
            node_id: Идентификатор перемещаемого узла.
            old_pos: Координаты узла до перемещения (x, y) или None.
            new_pos: Новые координаты узла (x, y).
        """
        return Action(
            action_type=ActionType.GRAPH_NODE_MOVE,
            register_name=region_id,
            field_name="nodes",
            forward_patch={"node_id": node_id, "new_pos": new_pos},
            backward_patch={"node_id": node_id, "old_pos": old_pos},
            coalesce_key=f"graph_move:{region_id}:{node_id}",
            undoable=True,
            description=f"Переместить узел {node_id}",
        )

    @staticmethod
    def layout_change(
        preset_name: str,
        subscriptions_before: Any,
        subscriptions_after: Any,
    ) -> "Action":
        """
        Создать Action для смены layout-пресета display-окон.

        undoable=True: смену раскладки можно отменить через undo.

        Args:
            preset_name: Имя пресета (SINGLE, DUAL, QUAD и т.д.).
            subscriptions_before: Список подписок до смены (для revert).
            subscriptions_after: Список подписок после смены (для apply).
        """
        return Action(
            action_type=ActionType.LAYOUT_CHANGE,
            forward_patch={
                "preset_name": preset_name,
                "subscriptions_after": subscriptions_after,
            },
            backward_patch={
                "subscriptions_before": subscriptions_before,
            },
            undoable=True,
            description=f"Изменить раскладку display на {preset_name}",
        )
