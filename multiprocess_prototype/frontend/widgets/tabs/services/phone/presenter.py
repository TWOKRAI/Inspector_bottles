"""PhoneServicePresenter — логика секции «Телефон» (без Qt).

Включение/выключение сервера приёма с телефона через live-команды плагину
phone_camera (TopologyBridge.on_action_command). Bridge=None → no-op с логом.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_PLUGIN = "phone_camera"


class PhoneServicePresenter:
    """Презентер сервиса «Телефон»: тумблер сервера через bridge."""

    def __init__(self, *, bridge: Any = None) -> None:
        self._bridge = bridge

    def start_server(self) -> bool:
        """Включить приём с телефона (поднять HTTP-сервер)."""
        return self._send("start_server")

    def stop_server(self) -> bool:
        """Выключить приём с телефона (погасить HTTP-сервер)."""
        return self._send("stop_server")

    def _send(self, command: str, args: dict | None = None) -> bool:
        if self._bridge is None:
            logger.debug("PhoneService: bridge недоступен — %s пропущена", command)
            return False
        try:
            return bool(self._bridge.on_action_command(_PLUGIN, command, args or {}))
        except Exception as exc:
            logger.warning("PhoneService: команда %s провалилась: %s", command, exc)
            return False
