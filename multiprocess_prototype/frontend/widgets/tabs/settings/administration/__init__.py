# -*- coding: utf-8 -*-
"""Пакет administration — подсекции «Администрация» таба настроек.

Подсекции (UsersPanel, RolesPanel, SessionsPanel, AuditLogPanel, AdminDashboard)
регистрируются через фабрики в `settings/_sections.py` с сигнатурой
`(services, auth_ctx)` и импортируются оттуда напрямую — реэкспорт не нужен.
"""

__all__: list[str] = []
