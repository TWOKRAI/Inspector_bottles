"""Канонический спецификатор predefined ролей.

Используется:
- `Services.auth.bootstrap` — при первичной инициализации `users.yaml`.
- `AuthManager.initialize()` — для auto-merge недостающих permissions
  в существующие predefined-роли (admin/operator/viewer/dev). Custom
  роли не затрагиваются.

## Граница слоёв и единый источник вкладок (NEW-D1 / D-5, ADR-135)

Единый источник состава вкладок приложения — `multiprocess_prototype.frontend
.tabs_registry.TABS`. Этот модуль (`Services/auth`) **не может** импортировать
его: обратный импорт `Services → prototype` запрещён правилом слоёв №9
(`framework → Services → Plugins → prototype`) и enforced `.sentrux/rules.toml`.
Причём tab-id нужны Services-слою автономно: bootstrap CLI (`python -m
Services.auth.bootstrap`) работает ДО и БЕЗ прототипа.

Поэтому Services держит собственный список `DEFAULT_TAB_IDS`, а **паритет
`DEFAULT_TAB_IDS == tabs_registry.tab_ids()` enforced характеризационным тестом
на слое prototype** (тест видит оба слоя). Дрейф ловится в CI красным тестом.
Наборы permissions строятся через `build_predefined_roles(tab_ids)`.
"""

from __future__ import annotations

from typing import Sequence

from .models import Role


# Канонический список tab-id на слое Services (см. docstring о границе слоёв).
# Паритет с prototype `tabs_registry.tab_ids()` — enforced parity-тестом.
DEFAULT_TAB_IDS: tuple[str, ...] = (
    "settings",
    "recipes",
    "processes",
    "services",
    "plugins",
    "pipeline",
    "displays",
    "observability",
)

# Табы, на которых у operator есть право редактирования («рабочие» табы);
# остальные (settings/services/plugins/displays) — view-only (системные).
_OPERATOR_EDIT_TABS: tuple[str, ...] = ("recipes", "processes", "pipeline")


def _tabs(tab_ids: Sequence[str], *, edit: bool = False) -> list[str]:
    """Развернуть список tab_id в `tabs.<id>.view` (+`.edit` опционально)."""
    out: list[str] = []
    for tab_id in tab_ids:
        out.append(f"tabs.{tab_id}.view")
        if edit:
            out.append(f"tabs.{tab_id}.edit")
    return out


def build_predefined_roles(
    tab_ids: Sequence[str] = DEFAULT_TAB_IDS,
    *,
    operator_edit_tabs: Sequence[str] = _OPERATOR_EDIT_TABS,
) -> dict[str, "Role"]:
    """Построить predefined роли из списка tab-id (единый билдер, D-5).

    Наборы permissions деривятся из `tab_ids` — единственный источник состава
    вкладок для ролей. `operator_edit_tabs` задаёт «рабочие» табы, где у
    operator есть `.edit`.

    Returns:
        dict `{role_name: Role}` для dev/admin/operator/viewer.
    """
    # admin: все табы view+edit, users CRUD, roles read + edit (PR4).
    admin_permissions = _tabs(tab_ids, edit=True) + [
        "users.view",
        "users.create",
        "users.edit",
        "users.delete",
        "users.reset_password",
        "roles.view",
        "roles.edit",  # PR4 Group D: admin может редактировать права ролей
    ]
    # operator: все табы view, edit на «рабочих» табах.
    operator_permissions = _tabs(tab_ids) + [f"tabs.{tab_id}.edit" for tab_id in operator_edit_tabs]
    # viewer: все табы view, никаких edit.
    viewer_permissions = _tabs(tab_ids)

    return {
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
            permissions=admin_permissions,
            hidden_in_ui=False,
            bypass_readonly=False,
            show_hidden=False,
        ),
        "operator": Role(
            name="operator",
            level=5,
            permissions=operator_permissions,
            hidden_in_ui=False,
            bypass_readonly=False,
            show_hidden=False,
        ),
        "viewer": Role(
            name="viewer",
            level=1,
            permissions=viewer_permissions,
            hidden_in_ui=False,
            bypass_readonly=False,
            show_hidden=False,
        ),
    }


# Канонический словарь predefined ролей — построен из DEFAULT_TAB_IDS.
PREDEFINED_ROLES: dict[str, Role] = build_predefined_roles()


def expected_permissions(role_name: str) -> frozenset[str]:
    """Эталонный набор permissions для predefined роли.

    Returns:
        frozenset с именами permissions. Пустой frozenset, если роль не predefined.
    """
    role = PREDEFINED_ROLES.get(role_name)
    if role is None:
        return frozenset()
    return frozenset(role.permissions)
