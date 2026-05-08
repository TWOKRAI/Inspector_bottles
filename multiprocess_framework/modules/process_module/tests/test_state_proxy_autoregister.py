"""Тесты авто-регистрации state.changed handler (ADR-SS-006).

Проверяет что ProcessModule._init_state_proxy() корректно регистрирует
handler когда state_proxy задан, и пропускает когда не задан.
"""

from unittest.mock import MagicMock, call

from multiprocess_framework.modules.process_module.core.process_module import (
    ProcessModule,
)


def _make_process(state_proxy=None) -> ProcessModule:
    """Создать ProcessModule с минимальными mock-зависимостями."""
    proc = ProcessModule.__new__(ProcessModule)
    proc.name = "test_process"
    proc.state_proxy = state_proxy
    proc.router_manager = MagicMock()
    # _log_debug / _log_warning нужны для _init_state_proxy
    proc._log_debug = MagicMock()
    proc._log_warning = MagicMock()
    return proc


class TestStateProxyAutoRegister:
    """Авто-регистрация state.changed handler в ProcessModule."""

    def test_state_proxy_set_handler_registered(self):
        """Если state_proxy задан — handler регистрируется."""
        mock_proxy = MagicMock()
        proc = _make_process(state_proxy=mock_proxy)

        proc._init_state_proxy()

        proc.router_manager.register_message_handler.assert_called_once_with(
            "state.changed", mock_proxy.on_state_changed
        )

    def test_state_proxy_none_no_handler(self):
        """Если state_proxy=None — ничего не регистрируется."""
        proc = _make_process(state_proxy=None)

        proc._init_state_proxy()

        proc.router_manager.register_message_handler.assert_not_called()

    def test_no_router_no_crash(self):
        """Если router_manager=None — не падает."""
        mock_proxy = MagicMock()
        proc = _make_process(state_proxy=mock_proxy)
        proc.router_manager = None

        proc._init_state_proxy()  # не должно бросить исключение

    def test_router_error_logged_not_raised(self):
        """Если register_message_handler бросает — ловится и логируется."""
        mock_proxy = MagicMock()
        proc = _make_process(state_proxy=mock_proxy)
        proc.router_manager.register_message_handler.side_effect = RuntimeError("boom")

        proc._init_state_proxy()  # не должно бросить

        proc._log_warning.assert_called_once()
