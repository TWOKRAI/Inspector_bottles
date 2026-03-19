# multiprocess_prototype/tests/test_registers_bridge.py
"""
Unit-тесты FrontendRegistersBridge с моками router.
"""

import pytest
from unittest.mock import MagicMock

from registers_module import RegistersManager
from shared_registers import DrawRegisters


def test_registers_bridge_send_callback():
    """FrontendRegistersBridge при set_field_value вызывает router.send_message."""
    from frontend_module.core.registers_bridge import FrontendRegistersBridge

    mock_router = MagicMock()
    mock_router.send_message = MagicMock(return_value=True)

    registers = RegistersManager({"draw": DrawRegisters()})
    connection_map = {"draw": "renderer"}
    bridge = FrontendRegistersBridge(
        registers_manager=registers,
        router=mock_router,
        connection_map=connection_map,
    )

    success, err = bridge.set_field_value("draw", "draw", True)
    assert success
    assert mock_router.send_message.called
    call_args = mock_router.send_message.call_args
    assert call_args[0][0] == "renderer"
    assert call_args[0][1].get("data_type") == "register_update"


def test_registers_bridge_without_router():
    """FrontendRegistersBridge без router не падает при set_field_value."""
    from frontend_module.core.registers_bridge import FrontendRegistersBridge

    registers = RegistersManager({"draw": DrawRegisters()})
    bridge = FrontendRegistersBridge(
        registers_manager=registers,
        router=None,
        connection_map={},
    )
    success, err = bridge.set_field_value("draw", "draw", True)
    assert success
