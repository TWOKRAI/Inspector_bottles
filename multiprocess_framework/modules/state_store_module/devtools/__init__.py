"""devtools — DevTools для отладки StateStore в runtime.

Предоставляет StateInspector — инструмент инспекции состояния:
- inspect() — просмотр дерева состояния
- subscriptions() — список активных подписок
- history() — история последних изменений (ring buffer)
- stats() — метрики из MetricsMiddleware
- summary() — краткая сводка
"""
from .inspector import StateInspector

__all__ = ["StateInspector"]
