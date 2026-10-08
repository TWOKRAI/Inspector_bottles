"""Контрактные тесты IRouterManager (k0 1.1).

Purpose: закрепить набор абстрактных членов IRouterManager и соответствие ему RouterManager.
Public API: нет (только тесты); ``__all__`` пуст.
Stability: lite
"""

import inspect

import pytest

from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.router_module.interfaces import IRouterManager

__all__: list[str] = []

# Литералы из ``atlas ref router_module`` (brief tasks/1.1.md).
_MEMBERS = frozenset(
    {
        "manager_name", "initialize", "shutdown", "send", "send_async", "receive",
        "start_listening", "stop_listening", "add_message_callback", "remove_message_callback",
        "register_channel", "unregister_channel", "get_channel", "get_all_channels",
        "register_route", "register_broadcast_route", "register_message_handler",
        "add_send_middleware", "add_receive_middleware", "clear_middleware", "get_stats",
    }
)  # fmt: skip

# Параметры интерфейса (без self); manager_name — значение, не метод.
_IFACE_PARAMS = {
    "initialize": [], "shutdown": [], "send": ["message"],
    "send_async": ["message", "priority"], "receive": ["timeout", "return_messages"],
    "start_listening": ["poll_interval"], "stop_listening": ["timeout"],
    "add_message_callback": ["callback"], "remove_message_callback": ["callback"],
    "register_channel": ["channel"], "unregister_channel": ["name"],
    "get_channel": ["name"], "get_all_channels": [],
    "register_route": ["key", "channel_name", "strategy", "efficiency", "tags"],
    "register_broadcast_route": ["key", "channel_names", "tags"],
    "register_message_handler": ["key", "handler", "expects_full_message", "metadata", "efficiency", "tags"],
    "add_send_middleware": ["fn"], "add_receive_middleware": ["fn"],
    "clear_middleware": [], "get_stats": [],
}  # fmt: skip


def test_irouter_manager_abstract_set_is_the_21_literal_names_and_uninstantiable():
    assert IRouterManager.__abstractmethods__ == _MEMBERS
    assert len(_MEMBERS) == 21
    with pytest.raises(TypeError):
        IRouterManager()


def test_router_manager_instance_has_every_irouter_manager_member():
    router = RouterManager(manager_name="contract_router")
    assert router.manager_name == "contract_router"
    for name in sorted(_MEMBERS - {"manager_name"}):
        assert callable(getattr(router, name, None)), name


def test_router_manager_signatures_match_irouter_manager_without_drift():
    assert set(_IFACE_PARAMS) == _MEMBERS - {"manager_name"}
    router = RouterManager(manager_name="contract_router")
    mismatch = {}
    for name, iface in _IFACE_PARAMS.items():
        # сторона интерфейса: литерал не заменяет её, а сверяется с ней
        iface_actual = list(inspect.signature(getattr(IRouterManager, name)).parameters)[1:]
        assert iface_actual == iface, name
        params = list(inspect.signature(getattr(router, name)).parameters.values())
        impl = [p.name for p in params]
        extras_ok = all(
            p.default is not inspect.Parameter.empty or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
            for p in params[len(iface):]
        )  # fmt: skip
        if impl[: len(iface)] != iface or not extras_ok:
            mismatch[name] = (iface, impl)
    assert mismatch == {}
