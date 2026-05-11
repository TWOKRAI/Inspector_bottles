# -*- coding: utf-8 -*-
"""
AuditMiddleware — post-execute callback для ActionBus, пишущий аудит.

Извлекает текущего пользователя из StateStore и формирует AuditEntry
для каждого выполненного действия.

Регистрация:
    middleware = AuditMiddleware(audit_writer, state_store)
    bus.add_post_execute_callback(middleware)

Контракт:
    - middleware(action) → None (post-execute callback)
    - Если пользователь не авторизован — запись пропускается (pre-auth действия
      заблокированы PreAuthGuard, поэтому этот случай не должен возникать,
      но проверяем явно для safety).
    - Запись формируется через AuditEntry.with_truncation() — защита от >10 KB JSON.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from multiprocess_framework.modules.actions_module.schemas import Action
from Services.auth.interfaces import IAuditWriter
from Services.auth.models import AuditEntry


class AuditMiddleware:
    """
    Post-execute callback для ActionBus — записывает каждое действие в аудит-лог.

    Args:
        audit_writer: Реализация IAuditWriter (AuditWriter или mock в тестах).
        state_store:  StateStore или любой объект с методом get(key).
                      Ожидается, что state_store.get("auth/current_user") вернёт
                      dict вида {"user_id": ..., "username": ...} или None.
    """

    def __init__(self, audit_writer: IAuditWriter, state_store: Any) -> None:
        self._writer = audit_writer
        self._state_store = state_store

    def __call__(self, action: Action) -> None:
        """
        Post-execute callback — формирует и ставит AuditEntry в очередь writer'а.

        Вызывается ActionBus сразу после успешного handler.apply().
        Если текущий пользователь не определён — пропускает запись.

        Args:
            action: Выполненное действие.
        """
        # Достаём текущего пользователя из state_store
        current_user = self._state_store.get("auth/current_user")
        if not current_user or not isinstance(current_user, dict):
            return

        user_id: str = current_user.get("user_id", "")
        username: str = current_user.get("username", "")

        if not user_id:
            return

        # Определяем ресурс: register_name → field_name → None
        resource: str | None = action.register_name or action.field_name

        # Сериализуем патчи (если Action содержит пустые dict — None)
        before_json: str | None = None
        after_json: str | None = None

        if action.backward_patch:
            before_json = json.dumps(action.backward_patch, default=str)

        if action.forward_patch:
            after_json = json.dumps(action.forward_patch, default=str)

        entry = AuditEntry.with_truncation(
            entry_id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            user_id=user_id,
            username=username,
            action_type=action.action_type,
            resource=resource,
            before_json=before_json,
            after_json=after_json,
        )

        self._writer.log(entry)
