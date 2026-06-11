"""device_hub плагин — always-on хаб устройств в процессе devices.

Публичный API:
    DeviceHubPlugin  — ProcessModulePlugin
    DeviceHubClient  — IPC-клиент для вызова команд из других процессов
"""

from Plugins.hub.device_hub.client import DeviceHubClient
from Plugins.hub.device_hub.plugin import DeviceHubPlugin

__all__ = ["DeviceHubPlugin", "DeviceHubClient"]
