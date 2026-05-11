# -*- coding: utf-8 -*-
"""
SessionTracker — трекер сессий пользователей.

Открывает и закрывает SessionEntry через SqliteAuditStorage.
Не хранит список активных сессий в памяти — только current_session_id.
Для статистики активных сессий (Group E) — отдельный механизм.

Использование:
    storage = SqliteAuditStorage("sqlite:///audit.db")
    storage.ensure_schema()

    tracker = SessionTracker(storage)
    session_id = tracker.open_session("uid-001", "alice")
    # ... работа ...
    tracker.close_session(session_id)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from .models import SessionEntry
from .storage.audit_storage import SqliteAuditStorage


class SessionTracker:
    """
    Трекер сессий — открывает и закрывает SessionEntry в хранилище.

    Не хранит список всех активных сессий — только текущий session_id
    (per-process, in-memory). При перезапуске сессия «подвисает» в БД
    без logout_at — это допустимо, панель сессий Group C покажет такие
    как «незакрытые».

    Args:
        storage:          SqliteAuditStorage с уже вызванным ensure_schema().
        on_active_change: Опциональный callback(count: int) — вызывается при
                          изменении числа активных сессий. Используется
                          AuthManager'ом для публикации метрики
                          ``auth.sessions.active`` через ObservableMixin.
    """

    def __init__(
        self,
        storage: SqliteAuditStorage,
        on_active_change: Optional[Callable[[int], None]] = None,
    ) -> None:
        self._storage = storage
        # Текущий session_id хранится здесь только как зеркало из AuthManager.
        # AuthManager владеет _current_session_id — это поле для удобства.
        self._current_session_id: Optional[str] = None

        # Счётчик активных сессий (in-memory, сбрасывается при рестарте)
        self._active_sessions_count: int = 0
        # Callback для публикации метрики через ObservableMixin (опциональный)
        self._on_active_change: Optional[Callable[[int], None]] = on_active_change

    def open_session(self, user_id: str, username: str) -> str:
        """
        Создать запись о новой сессии пользователя.

        Создаёт SessionEntry с текущим UTC-временем входа и сохраняет в БД.

        Args:
            user_id:  UUID пользователя.
            username: Имя пользователя (денормализованное для быстрого отображения).

        Returns:
            session_id — UUID4 строка идентификатора созданной сессии.
        """
        session_id = str(uuid.uuid4())
        entry = SessionEntry(
            session_id=session_id,
            user_id=user_id,
            username=username,
            login_at=datetime.now(timezone.utc),
            logout_at=None,
        )
        self._storage.append_session(entry)
        self._current_session_id = session_id

        # Обновляем счётчик и публикуем метрику
        self._active_sessions_count += 1
        if self._on_active_change is not None:
            self._on_active_change(self._active_sessions_count)

        return session_id

    def close_session(self, session_id: str) -> None:
        """
        Зафиксировать завершение сессии (проставить logout_at).

        Если session_id не найден в БД — операция игнорируется
        (safe при повторном вызове или после перезапуска).

        Args:
            session_id: UUID4 идентификатор сессии.
        """
        self._storage.close_session(session_id, datetime.now(timezone.utc))
        if self._current_session_id == session_id:
            self._current_session_id = None

        # Обновляем счётчик (не уходим ниже нуля)
        if self._active_sessions_count > 0:
            self._active_sessions_count -= 1
        if self._on_active_change is not None:
            self._on_active_change(self._active_sessions_count)
