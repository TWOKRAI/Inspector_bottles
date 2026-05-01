# frontend_module/core/app_context.py
"""Generic DI-контейнер для frontend-приложения."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FrontendAppContext:
    """Generic DI-контейнер для frontend-приложения.

    Хранит ссылки на общие сервисы. Домен-специфичные поля
    добавляются через наследование в конкретном приложении.
    """

    config: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Получить значение из extras по ключу."""
        return self.extras.get(key, default)
