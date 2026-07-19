# -*- coding: utf-8 -*-
"""D.2 Step 8 — live-смоук streamable-HTTP мультиклиента.

РЕАЛЬНЫЙ сетевой прогон: uvicorn + StreamableHTTPSessionManager + два независимых
``streamablehttp_client`` через настоящий HTTP. Проверяет то, что fake-транспортные
unit'ы (test_mcp_server_sdk.py) поймать не могут: HTTP-транспорт и per-session
мультиплекс end-to-end — две параллельные MCP-сессии не мешают друг другу и получают
СВОИ ответы (acceptance родителя D.2).

Драйверы — fake (без живого бэкенда): цель этого теста — именно транспортный слой
(HTTP + session-manager + lifespan-мультиплекс). Прогон против ЖИВОГО бэкенда с
``BACKEND_CTL_SESSION_ISOLATION=1`` (observability-tail vs register-crank) — отдельный
харнесс-сценарий владельца (как CAPABILITIES.yaml в D.1: harness-зависимая проверка).

Маркер ``harness_smoke`` — тяжёлый live-тест, скипается в обычном прогоне
(``python -m pytest backend_ctl -m harness_smoke``). Уникальный порт (≥8770) —
изоляция от общих фикстур (project_concurrent_backends_trap).
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from typing import Any, List

import pytest

from backend_ctl.tests.test_mcp_server_sdk import FakeDriver

_PORT = 8907  # уникальный порт этого модуля


@pytest.mark.harness_smoke
def test_http_multiplex_two_clients_over_real_http() -> None:
    import uvicorn
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.routing import Mount

    from backend_ctl.mcp_server_sdk import HTTP_MOUNT_PATH, SDKToolServer, build_server

    created: List[FakeDriver] = []

    def factory() -> SDKToolServer:
        fake = FakeDriver()
        created.append(fake)
        return SDKToolServer(driver_factory=lambda: fake, log=lambda m: None)

    server = build_server(factory)
    manager = StreamableHTTPSessionManager(app=server, stateless=False)

    async def _asgi(scope: Any, receive: Any, send: Any) -> None:
        await manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def _lifespan(_app: Any):
        async with manager.run():
            yield

    app = Starlette(routes=[Mount(HTTP_MOUNT_PATH, app=_asgi)], lifespan=_lifespan)
    config = uvicorn.Config(app, host="127.0.0.1", port=_PORT, log_level="error")
    userver = uvicorn.Server(config)

    thread = threading.Thread(target=userver.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 10.0
        while not userver.started and time.time() < deadline:
            time.sleep(0.05)
        assert userver.started, "uvicorn не поднялся за 10s"

        url = f"http://127.0.0.1:{_PORT}{HTTP_MOUNT_PATH}"

        async def _one_session(process: str) -> bool:
            async with streamablehttp_client(url) as (read, write, _get_sid):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    res = await session.call_tool("get_status", {"process": process})
                    return bool(res.isError is False)

        async def _drive() -> list:
            # две параллельные MCP-сессии на одном сервере
            return await asyncio.gather(_one_session("cam"), _one_session("preprocessor"))

        results = asyncio.run(_drive())
        assert all(results), f"обе HTTP-сессии должны отвечать без ошибок: {results}"
        # две отдельные MCP-сессии → два fake-driver'а: per-session мультиплекс поверх HTTP
        assert len(created) >= 2, f"ожидались ≥2 per-session driver'а, создано {len(created)}"
    finally:
        userver.should_exit = True
        thread.join(timeout=10.0)


if __name__ == "__main__":
    pytest.main([__file__, "-q", "-o", "addopts="])
