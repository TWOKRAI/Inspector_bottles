"""Фабрика ActionBus для v2 — создаёт шину с зарегистрированными handlers.

Phase 12: опциональный topology_bridge для IPC-интеграции.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from multiprocess_framework.modules.actions_module.bus import ActionBus

from .action_types import (
    FIELD_SET,
    NODE_MOVE,
    PROCESS_ADD,
    PROCESS_REMOVE,
    RECIPE_APPLY,
    ROLE_UPDATE,
    WIRE_ADD,
    WIRE_REMOVE,
)
from .handlers import FieldSetHandler, NodeMoveHandler, RecipeApplyHandler, RoleUpdateHandler, TopologyMutationHandler

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.bridge.topology_bridge import TopologyBridge
    from multiprocess_prototype.frontend.topology_holder import TopologyHolder
    from multiprocess_prototype.frontend.state.auth_state import AuthState
    from Services.auth.interfaces import IAuditWriter, IAuthManager


def create_action_bus(
    rm: Any,
    topology_holder: "TopologyHolder",
    *,
    topology_bridge: "TopologyBridge | None" = None,
    auth_state: "AuthState | None" = None,
    audit_writer: "IAuditWriter | None" = None,
    state_store: Any = None,
    auth_manager: "IAuthManager | None" = None,
    max_history: int = 50,
) -> ActionBus:
    """Создать ActionBus v2 с handlers для field_set и recipe_apply.

    Args:
        rm: RegistersManager (совместим с IRegistersManagerGui).
        topology_holder: TopologyHolder для recipe_apply handler.
        topology_bridge: TopologyBridge для IPC-интеграции (Phase 12, опционально).
        auth_state: AuthState для PreAuthGuard (PR2, опционально).
        audit_writer: IAuditWriter для AuditMiddleware (PR4, опционально).
                      Если передан, требуется также state_store.
        state_store: StateStore (или любой объект с .get(key)) для AuditMiddleware.
        auth_manager: IAuthManager для RoleUpdateHandler (PR4 Group D, опционально).
                      Если передан, регистрируется обработчик role_update.
        max_history: максимальный размер undo-стека (по умолчанию 50).

    Returns:
        Готовый к использованию ActionBus.
    """
    bus = ActionBus(rm, max_history=max_history)
    bus.register_handler(FIELD_SET, FieldSetHandler(topology_bridge=topology_bridge))
    bus.register_handler(RECIPE_APPLY, RecipeApplyHandler(topology_holder))

    # Phase 13: topology mutation handlers
    topo_handler = TopologyMutationHandler(
        topology_holder, topology_bridge=topology_bridge,
    )
    bus.register_handler(PROCESS_ADD, topo_handler)
    bus.register_handler(PROCESS_REMOVE, topo_handler)
    bus.register_handler(WIRE_ADD, topo_handler)
    bus.register_handler(WIRE_REMOVE, topo_handler)

    # Phase 13: node move handler (GUI-only, callback устанавливается через set_callback)
    node_move_handler = NodeMoveHandler()
    bus.register_handler(NODE_MOVE, node_move_handler)
    bus.node_move_handler = node_move_handler  # для post-init конфигурации

    # PR2 auth-rbac: PreAuthGuard — блокировка мутаций до авторизации
    if auth_state is not None:
        from .middleware.pre_auth_guard import PreAuthGuard

        guard = PreAuthGuard(auth_state)
        bus.set_pre_execute_hook(guard.hook, on_blocked=guard.show_auth_required)

    # PR4 audit: AuditMiddleware — запись каждого действия в аудит-лог
    if audit_writer is not None and state_store is not None:
        from .middleware.audit_middleware import AuditMiddleware

        middleware = AuditMiddleware(audit_writer, state_store)
        bus.add_post_execute_callback(middleware)

    # PR4 Group D: RoleUpdateHandler — undoable изменение permissions ролей
    if auth_manager is not None:
        bus.register_handler(ROLE_UPDATE, RoleUpdateHandler(auth_manager))

    return bus
