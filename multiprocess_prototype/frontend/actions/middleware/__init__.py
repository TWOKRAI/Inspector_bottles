"""middleware — промежуточные обработчики для ActionBus.

Содержит:
- PreAuthGuard — хук блокировки мутаций до авторизации (PR2).
- AuditMiddleware — post-execute callback для записи аудит-лога (PR4).
"""
from __future__ import annotations

from .audit_middleware import AuditMiddleware

__all__ = ["AuditMiddleware"]
