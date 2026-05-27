"""_deprecated_extras.py — Dict-обёртка для ctx.extras с DeprecationWarning.

При обращении к ключам, мигрированным в AppServices, эмитит DeprecationWarning.
Backward-compat: значение всё равно возвращается (dict не ломается).

Решение Task D.4 (Phase D / cross-tab-architecture).
Q5 decision: pytest.ini filterwarnings игнорирует warnings из этого модуля,
чтобы существующие тесты не падали. Phase F изменит на error::.
"""

from __future__ import annotations

import warnings
from typing import Any

# Mapping: ключ extras → поле AppServices.
# Включает только реально используемые в коде ключи, которые мигрированы в AppServices.
# Ключи НЕ в этом dict (bindings, tab_factory, service_state_adapter и т.д.) остаются тихими.
_DEPRECATED_KEYS_MAP: dict[str, str] = {
    # PluginCatalog
    "plugin_registry": "plugins",
    "plugin_manager": "plugins",
    # RegistersBackend
    "registers_manager": "registers",
    # ServiceManager
    "service_registry": "services",
    # DisplayCatalog
    "display_registry": "displays",
    # TopologyRepository
    "topology_holder": "topology",
    "topology_bridge": "topology",
    # CommandDispatcher
    "command_catalog": "commands",
    "action_bus": "commands",
    # RecipeStore
    "recipe_manager": "recipes",
    # AuthFacade
    "auth_manager": "auth",
    "auth_state": "auth",
    "audit_storage": "auth",
}


class _DeprecatedExtrasDict(dict):  # type: ignore[type-arg]
    """Dict-обёртка, эмитит DeprecationWarning для ключей, мигрированных в AppServices.

    Использование: ctx.extras = _DeprecatedExtrasDict({"key": value, ...}).
    При обращении к key из _DEPRECATED_KEYS_MAP через __getitem__ или get() —
    предупреждение с указанием замены в ctx.app_services.

    Не варнит при:
    - __setitem__ (запись)
    - __contains__ / in operator
    - итерации (dict(), items(), keys(), values())
    - __delitem__

    Только чтение (__getitem__ и get()) эмитит warnings — это типичный паттерн
    в presenter'ах Phase E, где migrate с ctx.extras на ctx.app_services.
    """

    def __getitem__(self, key: Any) -> Any:
        self._maybe_warn(key)
        return super().__getitem__(key)

    def get(self, key: Any, default: Any = None) -> Any:  # type: ignore[override]
        self._maybe_warn(key)
        return super().get(key, default)

    def _maybe_warn(self, key: Any) -> None:
        """Эмитит DeprecationWarning если key мигрирован в AppServices."""
        if key in _DEPRECATED_KEYS_MAP:
            replacement = _DEPRECATED_KEYS_MAP[key]
            warnings.warn(
                f"ctx.extras[{key!r}] deprecated; use ctx.app_services.{replacement}",
                DeprecationWarning,
                # stacklevel=3: пропустить _maybe_warn + __getitem__/get + caller
                stacklevel=3,
            )


__all__ = [
    "_DeprecatedExtrasDict",
    "_DEPRECATED_KEYS_MAP",
]
