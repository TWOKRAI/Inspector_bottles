# -*- coding: utf-8 -*-
"""_formatters — вспомогательные функции форматирования для панелей администрирования.

Приватный модуль (подчёркивание в имени). Используется в:
  - audit_log_panel.py
  - sessions_panel.py
"""
from __future__ import annotations

from datetime import datetime, timezone


def format_dt(value: datetime | None) -> str:
    """Отформатировать datetime для отображения в таблице.

    Возвращает строку вида «YYYY-MM-DD HH:MM:SS» либо «—» для None.
    Использует strftime вместо str() для надёжности.
    """
    if value is None:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_duration(login_at: datetime | None, logout_at: datetime | None) -> str:
    """Вернуть строку длительности сессии.

    Если logout_at is None — сессия ещё активна → «активна».
    Иначе: «1ч 23мин», «45мин», «< 1мин».
    """
    if login_at is None:
        return "—"
    if logout_at is None:
        return "активна"

    # Обеспечиваем совместимость naive/aware datetime
    if login_at.tzinfo is not None and logout_at.tzinfo is None:
        logout_at = logout_at.replace(tzinfo=timezone.utc)
    elif login_at.tzinfo is None and logout_at.tzinfo is not None:
        login_at = login_at.replace(tzinfo=timezone.utc)

    delta_seconds = int((logout_at - login_at).total_seconds())
    if delta_seconds < 0:
        return "—"
    if delta_seconds < 60:
        return "< 1мин"

    minutes_total = delta_seconds // 60
    hours = minutes_total // 60
    minutes = minutes_total % 60

    if hours > 0:
        return f"{hours}ч {minutes}мин"
    return f"{minutes}мин"
