# -*- coding: utf-8 -*-
"""Live-доказательство Task 1.1: реконнект-аппарат D.1 срабатывает на РЕАЛЬНОМ бэкенде.

``test_conn_lost.py`` доказывает контракт транспорта на голых сокетах (без mcp-слоя),
но ultra-ревью 2026-07-20 прямо указало: 85% тестов backend_ctl гоняются на
fake-транспорте, и именно поэтому худшая находка (``transport.request()`` топил
разрыв соединения в error-dict, ``call_tool`` никогда не звал ``session.reset()``)
уцелела так долго. Этот тест — единственное живое доказательство того, что весь
путь ``SDKToolServer.call_tool → dispatch_tool → DriverSession.ensure()`` реально
реконнектится после смерти НАСТОЯЩЕГО бэкенда (не голого сокета), с durable-
подписками и reconnect-report'ом в ответе — а не только фейкового транспорта.

Сценарий: headless-бэкенд на своём порту → ``call_tool("state_subscribe")``
регистрирует durable-намерение (то же ``state.subscribe``, которым пользуется
``watch_like_gui()`` в заведомо зелёном ``test_reconnect_live.py``) → ``harness.stop()``
убивает бэкенд → дожидаемся, пока reader-поток driver'а сессии опознает смерть
соединения (иначе гонка «harness ещё не долетел» делает сценарий недетерминированным)
→ поднимаем НОВЫЙ бэкенд на ТОМ ЖЕ порту → следующий ``call_tool`` (снова
``state_subscribe`` — заведомо рабочая команда, не introspect.*) реконнектится
ВНУТРИ ``ensure()`` ДО выполнения хендлера, поэтому reconnect-report прилетает
в этом же ответе.

ВАЖНО (пометка владельца задачи): на этой машине 12 live-тестов backend_ctl красные
pre-existing из-за незарегистрированных introspect.*-хендлеров (не наш регресс).
Поэтому здесь сознательно НЕ используются ``introspect.capabilities``/``introspect.status``
(через инструмент ``get_status``) — только ``state_subscribe``, доказанно рабочий
в ``test_reconnect_live.py``.

Свой headless-бэкенд на уникальном порту (изоляция от общих фикстур, см.
``backend_ctl/AGENTS.md``, ``project_concurrent_backends_trap``) — 8770-8799
частично заняты соседними live-тестами (``grep -rn "_PORT = " backend_ctl/tests/``),
8788 на момент написания свободен.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict

import pytest

from backend_ctl.harness import BackendHarness
from backend_ctl.mcp_server_sdk import SDKToolServer

_HOST = "127.0.0.1"
_PORT = 8788  # уникальный порт этого модуля (свободен на момент написания, см. докстроку)

_SUBSCRIBE_PATTERN = "processes.**"


def _as_dict(result: Any) -> Dict[str, Any]:
    """Достать и распарсить JSON успешного (``list[TextContent]``) ответа ``call_tool``.

    Падает с полным телом ответа, если сервер вернул ``CallToolResult(isError=True)`` —
    так неожиданная ошибка инструмента видна прямо в трейсбеке теста, а не тонет в
    невнятном ``AssertionError`` на структуре списка.
    """
    if not isinstance(result, list):
        text = getattr(result.content[0], "text", result) if hasattr(result, "content") else result
        raise AssertionError(f"call_tool вернул ошибку вместо успеха: {text!r}")
    assert result, "call_tool вернул пустой список содержимого"
    return json.loads(result[0].text)


def _wait_conn_lost(server: SDKToolServer, timeout: float = 10.0) -> bool:
    """Дождаться, пока reader-поток ТЕКУЩЕГО driver'а сессии опознает смерть соединения.

    Белый ящик (``server._session._driver.connection_lost``) — тот же приём, что и
    ``_wait_conn_lost`` в ``test_conn_lost.py``. Без явного ожидания тест ловил бы гонку:
    ``harness.stop()`` завершается синхронно на уровне процесса, но reader-поток driver'а
    узнаёт о разрыве асинхронно (следующий ``recv()`` на своём сокете) — рестарт бэкенда
    и следующий вызов инструмента могли бы случиться РАНЬШЕ, чем флаг встанет, и тогда
    ``ensure()`` отдал бы старый (формально ещё «живой») driver, который упал бы на
    самом запросе — сценарий остался бы прежним по сути (реконнект всё равно случится),
    но недетерминированным по тому, ГДЕ именно всплывёт исключение.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        drv = server._session._driver  # noqa: SLF001 — намеренный белый ящик теста
        if drv is not None and drv.connection_lost:
            return True
        time.sleep(0.05)
    return False


@pytest.mark.harness_smoke
def test_reconnect_after_backend_restart_reports_resubscribe() -> None:
    """Acceptance Task 1.1: kill бэкенда → restart → следующий tools/call реконнектится.

    Проверяем именно то, что было недостижимо ДО фикса 452d4431: durable-подписка,
    сделанная через MCP-инструмент, переживает смерть реального бэкенда и restart на
    том же порту, а агент узнаёт об этом из ``reconnected``/``resubscribed`` в ответе
    следующего вызова (а не из тишины/зависшей сессии).
    """
    harness = BackendHarness(with_base=True, port=_PORT)
    harness.start()
    server = SDKToolServer(host=_HOST, port=_PORT, request_timeout=5.0, log=lambda _m: None)
    try:
        # 1. Durable-намерение ДО разрыва — реконнект обязан его переиграть на новом driver'е.
        sub_before = _as_dict(server.call_tool("state_subscribe", {"pattern": _SUBSCRIBE_PATTERN}))
        assert sub_before.get("success") is True, sub_before
        assert sub_before.get("reconnected") is None, "первый вызов не должен нести reconnect-report"

        # 2. Убить бэкенд и дождаться, пока reader-поток ЭТОЙ сессии опознает разрыв.
        harness.stop()
        assert _wait_conn_lost(server), "reader-поток обязан опознать смерть бэкенда за 10с"

        # 3. Поднять НОВЫЙ бэкенд на ТОМ ЖЕ порту — тот же сценарий, что видит агент
        #    при живом MCP-сервере поверх упавшего и перезапущенного backend'а.
        harness = BackendHarness(with_base=True, port=_PORT)
        harness.start()

        # 4. Следующий вызов инструмента (снова state_subscribe — доказанно рабочая
        #    команда, НЕ introspect.*). session.ensure() внутри dispatch_tool видит
        #    connection_lost=True, пересоздаёт driver, replay'ит durable-намерение
        #    ИЗ ШАГА 1 — отчёт о реконнекте прилетает в ЭТОМ ЖЕ ответе, до выполнения
        #    самого хендлера state_subscribe.
        after = _as_dict(server.call_tool("state_subscribe", {"pattern": _SUBSCRIBE_PATTERN}))
        assert after.get("success") is True, after
        assert after.get("reconnected") is True, after
        resubscribed = after.get("resubscribed")
        assert resubscribed, after
        assert any(
            it.get("command") == "state.subscribe" and it.get("target") == "ProcessManager" and it.get("success")
            for it in resubscribed
        ), resubscribed
    finally:
        server.close()
        harness.stop()
