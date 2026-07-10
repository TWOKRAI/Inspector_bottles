"""Канонический спецификатор predefined ролей.

Используется:
- `Services.auth.bootstrap` — при первичной инициализации `users.yaml`.
- `AuthManager.initialize()` — для auto-merge недостающих permissions
  в существующие predefined-роли (admin/operator/viewer/dev). Custom
  роли не затрагиваются.

Список permissions подобран под актуальный набор табов приложения
(см. `multiprocess_prototype/frontend/tab_factory.TAB_ORDER`). При
добавлении/удалении табов — синхронизировать оба места.
"""

from __future__ import annotations

from .models import Role


_TAB_IDS_ALL_VIEW: tuple[str, ...] = (
    "settings",
    "recipes",
    "processes",
    "services",
    "plugins",
    "pipeline",
    "displays",
    "observability",
)


def _tabs(*tab_ids: str, edit: bool = False) -> list[str]:
    """Развернуть список tab_id в `tabs.<id>.view` (+`.edit` опционально)."""
    out: list[str] = []
    for tab_id in tab_ids:
        out.append(f"tabs.{tab_id}.view")
        if edit:
            out.append(f"tabs.{tab_id}.edit")
    return out


# admin: все табы view+edit, users CRUD, roles read + edit (PR4).
_ADMIN_PERMISSIONS: list[str] = _tabs(*_TAB_IDS_ALL_VIEW, edit=True) + [
    "users.view",
    "users.create",
    "users.edit",
    "users.delete",
    "users.reset_password",
    "roles.view",
    "roles.edit",  # PR4 Group D: admin может редактировать права ролей
]

# operator: все табы view, edit на «рабочих» табах (recipes/processes/pipeline).
# settings/services/plugins/displays — view-only (системные).
_OPERATOR_PERMISSIONS: list[str] = _tabs(*_TAB_IDS_ALL_VIEW) + [
    "tabs.recipes.edit",
    "tabs.processes.edit",
    "tabs.pipeline.edit",
]

# viewer: все табы view, никаких edit.
_VIEWER_PERMISSIONS: list[str] = _tabs(*_TAB_IDS_ALL_VIEW)


PREDEFINED_ROLES: dict[str, Role] = {
    "dev": Role(
        name="dev",
        level=10,
        permissions=["*"],
        hidden_in_ui=True,
        bypass_readonly=True,
        show_hidden=True,
    ),
    "admin": Role(
        name="admin",
        level=9,
        permissions=_ADMIN_PERMISSIONS,
        hidden_in_ui=False,
        bypass_readonly=False,
        show_hidden=False,
    ),
    "operator": Role(
        name="operator",
        level=5,
        permissions=_OPERATOR_PERMISSIONS,
        hidden_in_ui=False,
        bypass_readonly=False,
        show_hidden=False,
    ),
    "viewer": Role(
        name="viewer",
        level=1,
        permissions=_VIEWER_PERMISSIONS,
        hidden_in_ui=False,
        bypass_readonly=False,
        show_hidden=False,
    ),
}


def expected_permissions(role_name: str) -> frozenset[str]:
    """Эталонный набор permissions для predefined роли.

    Returns:
        frozenset с именами permissions. Пустой frozenset, если роль не predefined.
    """
    role = PREDEFINED_ROLES.get(role_name)
    if role is None:
        return frozenset()
    return frozenset(role.permissions)
