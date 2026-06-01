# -*- coding: utf-8 -*-
"""
backend_ctl_endpoint — поднятие SocketChannel в ProcessManager (dev-гейт).

Тонкий хелпер: при BACKEND_CTL=1 создаёт SocketChannel (bind 127.0.0.1:порт),
регистрирует его в RouterManager хоста и подключает SocketBridgeAdapter как
обработчик входящих сообщений driver'а. Вся доставка — через RouterManager.

Гейт + localhost-bind: в проде endpoint не существует (env не выставлен). Без
аутентификации — это dev-инструмент на localhost (см. P2 дизайн §7).

Выделено из process_manager_process.py, чтобы PM оставался тонким и endpoint
тестировался изолированно.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from ...router_module.adapters import SocketBridgeAdapter
from ...router_module.channels import SocketChannel

#: Имя канала = адрес для channel=-маршрутизации ответа driver'у.
BACKEND_CTL_CHANNEL = "backend_ctl"
#: env-флаг включения (строго "1").
ENV_ENABLE = "BACKEND_CTL"
#: env-переопределение порта.
ENV_PORT = "BACKEND_CTL_PORT"
DEFAULT_PORT = 8765


def is_enabled(env: Optional[dict] = None) -> bool:
    """True, если backend-control включён (BACKEND_CTL=1)."""
    source = env if env is not None else os.environ
    return source.get(ENV_ENABLE) == "1"


def setup_backend_ctl_channel(
    router_manager: Any,
    *,
    host: str = "127.0.0.1",
    port: Optional[int] = None,
    env: Optional[dict] = None,
    log_info: Optional[Any] = None,
    log_error: Optional[Any] = None,
) -> Optional[SocketChannel]:
    """Поднять SocketChannel и зарегистрировать в router (если гейт открыт).

    Args:
        router_manager: RouterManager хоста (register_channel + request/send).
        host: bind-адрес (по умолчанию localhost).
        port: порт; None → env BACKEND_CTL_PORT или DEFAULT_PORT.
        env: источник переменных окружения (для тестов); None → os.environ.
        log_info/log_error: опц. колбэки логирования.

    Returns:
        Запущенный SocketChannel или None (гейт закрыт / router отсутствует /
        bind не удался).
    """
    if not is_enabled(env):
        return None
    if router_manager is None:
        if log_error:
            log_error("[backend_ctl] router_manager отсутствует — endpoint не поднят")
        return None

    source = env if env is not None else os.environ
    resolved_port = port if port is not None else int(source.get(ENV_PORT, DEFAULT_PORT))

    adapter = SocketBridgeAdapter(router_manager, BACKEND_CTL_CHANNEL)
    channel = SocketChannel(
        BACKEND_CTL_CHANNEL,
        host=host,
        port=resolved_port,
        on_inbound=adapter.on_inbound,
    )
    router_manager.register_channel(channel)
    if not channel.start():
        if log_error:
            log_error(f"[backend_ctl] не удалось поднять SocketChannel на {host}:{resolved_port}")
        try:
            router_manager.unregister_channel(BACKEND_CTL_CHANNEL)
        except Exception:  # noqa: BLE001 — best-effort откат
            pass
        return None

    if log_info:
        log_info(
            f"[backend_ctl] endpoint поднят на {host}:{channel.port} (канал '{BACKEND_CTL_CHANNEL}') — DEV-инструмент"
        )
    return channel


def teardown_backend_ctl_channel(
    channel: Optional[SocketChannel],
    router_manager: Any = None,
) -> None:
    """Остановить канал и снять регистрацию (PID-specific, без глобального kill)."""
    if channel is None:
        return
    try:
        channel.close()
    finally:
        if router_manager is not None:
            try:
                router_manager.unregister_channel(BACKEND_CTL_CHANNEL)
            except Exception:  # noqa: BLE001 — best-effort
                pass
