"""server — тестовый Modbus-TCP slave для приёма (симуляция PLC).

Публичный API::

    from Services.modbus.server import run_test_server
    run_test_server(host="127.0.0.1", port=5020)

CLI::

    python -m Services.modbus.server --tcp 127.0.0.1:5020
"""

from Services.modbus.server.sim_server import (
    MODBUS_AVAILABLE,
    format_recv,
    run_test_server,
    trace_write,
)

__all__ = [
    "run_test_server",
    "format_recv",
    "trace_write",
    "MODBUS_AVAILABLE",
]
