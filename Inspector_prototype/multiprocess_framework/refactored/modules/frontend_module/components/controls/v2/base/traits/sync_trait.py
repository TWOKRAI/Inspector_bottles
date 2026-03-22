# -*- coding: utf-8 -*-
"""
SyncTrait — синхронизация с регистром через RegisterAdapter.
"""
from __future__ import annotations

from typing import Any, Callable, Optional


class SyncTrait:
    """Трейт: чтение/запись и подписка на поле регистра."""

    def __init__(self, binding: Any, adapter: Any) -> None:
        self._binding = binding
        self._adapter = adapter

    def read(self) -> Any:
        idx = getattr(self._binding, "index", None)
        return self._adapter.read(
            self._binding.register_name,
            self._binding.field_name,
            index=idx,
        )

    def write(self, value: Any) -> tuple[bool, Optional[str]]:
        idx = getattr(self._binding, "index", None)
        return self._adapter.write(
            self._binding.register_name,
            self._binding.field_name,
            value,
            index=idx,
        )

    def subscribe(self, callback: Callable[[Any], None]) -> None:
        idx = getattr(self._binding, "index", None)
        self._adapter.subscribe(
            self._binding.register_name,
            self._binding.field_name,
            callback,
            index=idx,
        )
