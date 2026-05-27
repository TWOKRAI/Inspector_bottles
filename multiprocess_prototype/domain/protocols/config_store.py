# -*- coding: utf-8 -*-
"""
domain/protocols/config_store.py — Protocol для конфигурационного хранилища.

ConfigStore — минимальный контракт read/write с реактивными подписками.
Реализации создаются в adapters/stores/config_store.py (Phase D).

Принятые решения (Phase D, closed Q3):
  - Subscription re-use из event_bus.py — единый тип для всех unsubscribe-контрактов.
  - subscribe() принимает glob-паттерн (fnmatch) по ключам — backend-agnostic.
  - save() — persist to disk; in-memory реализации (Fake, тесты) — no-op.
  - Phase E может ревизировать если нужна другая семантика Subscription.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from .event_bus import Subscription


@runtime_checkable
class ConfigStore(Protocol):
    """Конфиг-хранилище с реактивным API.

    Минимальный набор для D.5 Settings tab; расширяется в Phase E если нужно.

    Ключи используют dot-notation: ``"display.theme"``, ``"network.host"``.
    subscribe() принимает glob-паттерн (fnmatch): ``"display.*"``, ``"*"``.
    """

    def get(self, key: str, default: Any = None) -> Any:
        """Получить значение по dot-notation ключу. Возвращает default если нет."""
        ...

    def set(self, key: str, value: Any) -> None:
        """Установить значение по dot-notation ключу. Нотифицирует подписчиков."""
        ...

    def get_section(self, section: str) -> Mapping[str, Any]:
        """Вернуть все ключи секции как плоский dict без секционного префикса.

        Пример: get_section("display") для {"display.theme": "dark", "display.dpi": 96}
        → {"theme": "dark", "dpi": 96}.
        """
        ...

    def list_keys(self, prefix: str = "") -> Sequence[str]:
        """Перечислить все ключи, начинающиеся с prefix."""
        ...

    def subscribe(self, key_pattern: str, handler: Callable[[str, Any], None]) -> Subscription:
        """Подписаться на изменения ключей по glob-паттерну.

        Вызывает handler(key, new_value) при каждом set() с ключом,
        совпадающим с key_pattern (fnmatch).

        Возвращает Subscription для управления подпиской.
        """
        ...

    def save(self) -> None:
        """Сохранить конфигурацию на диск. In-memory реализации — no-op."""
        ...


__all__ = [
    "ConfigStore",
]
