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
#: env-флаг session-isolation (D.1); строго "1".
ENV_SESSION_ISOLATION = "BACKEND_CTL_SESSION_ISOLATION"
DEFAULT_PORT = 8765


def is_enabled(env: Optional[dict] = None, config: Optional[dict] = None) -> bool:
    """True, если backend-control включён.

    Источников два (OR): конфиг (`system.yaml` → `backend_ctl.enabled`) ИЛИ
    env-флаг `BACKEND_CTL=1`. Конфиг — основной способ для dev-запуска прототипа;
    env остаётся escape-hatch для тестов/smoke и CI (включить без правки yaml).
    """
    source = env if env is not None else os.environ
    if source.get(ENV_ENABLE) == "1":
        return True
    return bool(config and config.get("enabled"))


def _resolve_port(source: dict, config: Optional[dict], port: Optional[int]) -> int:
    """Порт: явный аргумент > env BACKEND_CTL_PORT > config.port > DEFAULT_PORT."""
    if port is not None:
        return port
    if ENV_PORT in source:
        return int(source[ENV_PORT])
    if config and config.get("port"):
        return int(config["port"])
    return DEFAULT_PORT


def _resolve_session_isolation(source: dict, config: Optional[dict]) -> bool:
    """Флаг session-isolation (D.1). Источников два (OR, зеркально `is_enabled`):
    env `BACKEND_CTL_SESSION_ISOLATION=1` ИЛИ config `backend_ctl.session_isolation`.
    Default False (broadcast) — остаётся дефолтом до доказательства (§9)."""
    if source.get(ENV_SESSION_ISOLATION) == "1":
        return True
    return bool(config and config.get("session_isolation"))


def setup_backend_ctl_channel(
    router_manager: Any,
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    env: Optional[dict] = None,
    config: Optional[dict] = None,
    log_info: Optional[Any] = None,
    log_error: Optional[Any] = None,
) -> Optional[SocketChannel]:
    """Поднять SocketChannel и зарегистрировать в router (если гейт открыт).

    Args:
        router_manager: RouterManager хоста (register_channel + request/send).
        host: bind-адрес; None → config.host или 127.0.0.1.
        port: порт; None → env BACKEND_CTL_PORT > config.port > DEFAULT_PORT.
        env: источник переменных окружения (для тестов); None → os.environ.
        config: секция `backend_ctl` из system.yaml (`enabled`/`port`/`host`).
        log_info/log_error: опц. колбэки логирования.

    Returns:
        Запущенный SocketChannel или None (гейт закрыт / router отсутствует /
        bind не удался).
    """
    if not is_enabled(env, config):
        return None
    if router_manager is None:
        if log_error:
            log_error("[backend_ctl] router_manager отсутствует — endpoint не поднят")
        return None

    source = env if env is not None else os.environ
    resolved_port = _resolve_port(source, config, port)
    resolved_host = host if host is not None else ((config or {}).get("host") or "127.0.0.1")
    session_isolation = _resolve_session_isolation(source, config)

    adapter = SocketBridgeAdapter(router_manager, BACKEND_CTL_CHANNEL, session_isolation=session_isolation)
    channel = SocketChannel(
        BACKEND_CTL_CHANNEL,
        host=resolved_host,
        port=resolved_port,
        on_inbound=adapter.on_inbound,
        session_isolation=session_isolation,
    )
    router_manager.register_channel(channel)
    if not channel.start():
        if log_error:
            log_error(f"[backend_ctl] не удалось поднять SocketChannel на {resolved_host}:{resolved_port}")
        try:
            router_manager.unregister_channel(BACKEND_CTL_CHANNEL)
        except Exception:  # noqa: BLE001 — best-effort откат
            pass
        return None

    if log_info:
        log_info(
            f"[backend_ctl] endpoint поднят на {resolved_host}:{channel.port} "
            f"(канал '{BACKEND_CTL_CHANNEL}', session_isolation={'on' if session_isolation else 'off'}) "
            f"— DEV-инструмент"
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
