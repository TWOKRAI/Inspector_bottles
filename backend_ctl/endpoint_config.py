# -*- coding: utf-8 -*-
"""
endpoint_config — единый источник адреса backend_ctl-endpoint для клиента.

Проблема: порт 8765 был захардкожен в 5 местах клиентской стороны (driver,
mcp_server, harness, dump_capabilities), из-за чего клиент не читал те же env,
что сервер, и рассинхрон легко было проглядеть.

Решение: один резолвер `resolve_endpoint()` с явным приоритетом, число порта
импортируется из серверного модуля `backend_ctl_endpoint.DEFAULT_PORT` (единственный
источник числа). Имя env-порта тоже переиспользуется (`ENV_PORT`), чтобы клиент и
сервер читали ровно одну переменную.

Слой: клиентский top-level `backend_ctl/` (tooling над framework) легально импортирует
константу из framework — обратный импорт запрещён, прямой разрешён.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

# Единственный источник числа порта и имени env-порта (серверная сторона).
from multiprocess_framework.modules.process_manager_module.process.backend_ctl_endpoint import (
    DEFAULT_PORT,
    ENV_PORT,
)

#: env-переопределение адреса хоста на стороне клиента (у сервера bind-host свой,
#: из config; клиент по умолчанию ходит на localhost).
ENV_HOST = "BACKEND_CTL_HOST"
#: Хост по умолчанию — endpoint биндится на 127.0.0.1 (dev-инструмент на localhost).
DEFAULT_HOST = "127.0.0.1"

__all__ = ["resolve_endpoint", "DEFAULT_PORT", "ENV_PORT", "ENV_HOST", "DEFAULT_HOST"]


def resolve_endpoint(
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> Tuple[str, int]:
    """Разрешить (host, port) endpoint'а с единым приоритетом.

    Приоритет для каждого поля независимо:
      явный аргумент > env (`BACKEND_CTL_HOST` / `BACKEND_CTL_PORT`) > дефолт.

    Дефолты: host = ``127.0.0.1``, port = ``DEFAULT_PORT`` (8765, из серверного
    ``backend_ctl_endpoint`` — единый источник числа).

    Args:
        host: явный хост; ``None`` → env ``BACKEND_CTL_HOST`` → ``127.0.0.1``.
        port: явный порт; ``None`` → env ``BACKEND_CTL_PORT`` → ``DEFAULT_PORT``.

    Returns:
        Кортеж ``(host, port)``.
    """
    resolved_host = host if host is not None else os.environ.get(ENV_HOST, DEFAULT_HOST)

    if port is not None:
        resolved_port = port
    else:
        env_port = os.environ.get(ENV_PORT)
        resolved_port = int(env_port) if env_port else DEFAULT_PORT

    return resolved_host, resolved_port
