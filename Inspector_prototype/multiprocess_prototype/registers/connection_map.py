# multiprocess_prototype/registers/connection_map.py
"""
Connection map: register_name -> backend channel.

При изменении регистра через RegistersManager отправка идёт в control_{channel}.
"""

DEFAULT_CONNECTION_MAP = {
    "draw": "renderer",
    "processor": "processor",
    "renderer": "renderer",
}
