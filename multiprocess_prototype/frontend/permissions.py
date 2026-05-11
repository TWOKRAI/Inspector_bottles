"""Декларативный каталог permissions приложения.

Заполняется один раз при старте `run_gui()` после инициализации
`AuthManager` (его внутренний `PermissionsRegistry`). Используется
админ-панелью «Роли» и audit-трейлом (PR4) для перечисления всех
известных прав без сканирования кода.

Namespace: `<scope>.<resource>.<action>` (см. metaplan §4).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .tab_factory import TAB_ORDER

if TYPE_CHECKING:
    from Services.auth.security import PermissionsRegistry


def register_all_permissions(registry: "PermissionsRegistry") -> None:
    """Зарегистрировать все permissions приложения в `PermissionsRegistry`.

    Идемпотентна — повторные вызовы не дублируют записи.

    Регистрирует:
    - `tabs.<id>.view` / `tabs.<id>.edit` для каждой вкладки из TAB_ORDER.
    - `users.*` — CRUD пользователей через админ-панель.
    - `roles.*` — операции над ролями (read-only в PR2/PR3, edit в PR4).
    """
    # Tabs: <id>.view / <id>.edit для каждой вкладки приложения
    for tab in TAB_ORDER:
        tab_id = tab["id"]
        title = tab.get("title", tab_id)
        registry.register(
            f"tabs.{tab_id}.view",
            f"Просмотр вкладки «{title}»",
        )
        registry.register(
            f"tabs.{tab_id}.edit",
            f"Редактирование во вкладке «{title}»",
        )

    # Users CRUD (Administration → Users)
    registry.register("users.view", "Просмотр списка пользователей")
    registry.register("users.create", "Создание пользователей")
    registry.register("users.edit", "Редактирование пользователей")
    registry.register("users.delete", "Удаление пользователей")
    registry.register("users.reset_password", "Сброс пароля пользователя")

    # Roles read (CRUD ролей — PR4, editable matrix)
    registry.register("roles.view", "Просмотр ролей и прав")
    registry.register("roles.edit", "Редактирование прав ролей (PR4)")
    registry.register("roles.create", "Создание ролей (PR4)")
    registry.register("roles.delete", "Удаление ролей (PR4)")
