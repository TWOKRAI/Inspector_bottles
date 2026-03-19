# multiprocess_prototype/tests/test_frontend_manager.py
"""
Unit-тесты FrontendManager с моками process и router.

Проверяет инициализацию, регистрацию окон, работу с IRouterLike.
"""

import pytest
from unittest.mock import MagicMock


def test_frontend_manager_accepts_router_like():
    """FrontendManager принимает объект с send_message (IRouterLike)."""
    from frontend_module import FrontendManager
    from registers_module import RegistersManager

    mock_router = MagicMock()
    mock_router.send_message = MagicMock(return_value=True)

    config = {"window": {}, "window_registry": {}}
    registers = RegistersManager({})
    fm = FrontendManager(
        config=config,
        registers=registers,
        router=mock_router,
        connection_map={},
    )
    # Инициализация без падения — router принят
    assert fm._router is mock_router


def test_frontend_manager_works_without_router():
    """FrontendManager может быть создан без router (опционально)."""
    from frontend_module import FrontendManager
    from registers_module import RegistersManager

    config = {"window": {}}
    registers = RegistersManager({})
    fm = FrontendManager(
        config=config,
        registers=registers,
        router=None,
        connection_map={},
    )
    assert fm._router is None


def test_irouter_like_protocol():
    """IRouterLike требует send_message(target, msg) -> bool."""
    from frontend_module.interfaces import IRouterLike

    class MockRouter:
        def send_message(self, target: str, msg: dict) -> bool:
            return True

    router = MockRouter()
    assert isinstance(router, IRouterLike)
    assert router.send_message("camera", {"cmd": "test"}) is True
