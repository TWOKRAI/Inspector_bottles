# -*- coding: utf-8 -*-
"""Task 1.1 — контракт смерти соединения: исключение, а не error-dict.

Худшая находка ultra-ревью 2026-07-20: ``transport.request()`` превращал разрыв сокета
в ``{"success": False, "error": "connection closed"}``. Наружу не летело НИЧЕГО, поэтому
``call_tool`` никогда не звал ``session.reset()``, а весь reconnect-аппарат D.1
(reset → replay durable-подписок → resume watch) был недостижим: сессия оставалась
мёртвой до пересоздания MCP-сервера.

Тесты гоняют РЕАЛЬНЫЕ сокеты (не fake-транспорт): именно на фейках находка и уцелела —
они моделировали разрыв тем же error-dict'ом, который проверяли. Сервер здесь —
крошечный TCP-listener, которым тест управляет вручную (accept / молчать / закрыть).

Граница контракта, которую тесты стерегут с обеих сторон:
  * сокет УМЕР → :class:`BackendUnavailable` (реконнект возможен и обязан случиться);
  * сокет ЖИВ, ответа нет → error-dict ``timeout`` (реконнектить нечего, бэкенд жив);
  * закрыли САМИ (``close()``) → error-dict, не исключение (закрытие намеренное).
"""

from __future__ import annotations

import socket
import threading
import time
from typing import List, Optional

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.mcp_driver_session import BackendUnavailable, DriverSession

_HOST = "127.0.0.1"


class _ToyServer:
    """TCP-listener на эфемерном порту с ручным управлением судьбой соединения.

    Не отвечает на запросы вообще — ответ здесь ни разу не нужен: проверяем реакцию
    клиента на молчание и на разрыв, а не разбор ответа.
    """

    def __init__(self, *, close_after: Optional[float] = None) -> None:
        self._close_after = close_after
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.bind((_HOST, 0))
        self._srv.listen(1)
        self._srv.settimeout(5.0)
        self.port: int = self._srv.getsockname()[1]
        self._conns: List[socket.socket] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            conn, _ = self._srv.accept()
        except OSError:
            return
        self._conns.append(conn)
        if self._close_after is not None:
            time.sleep(self._close_after)
            self.drop_client()

    def drop_client(self) -> None:
        """Закрыть соединение со стороны сервера — ровно это видит reader-поток клиента."""
        for conn in self._conns:
            try:
                conn.close()
            except OSError:
                pass
        self._conns.clear()

    def stop(self) -> None:
        self.drop_client()
        try:
            self._srv.close()
        except OSError:
            pass


def _wait_conn_lost(drv: BackendDriver, timeout: float = 5.0) -> bool:
    """Дождаться, пока reader-поток опознает смерть соединения."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if drv.connection_lost:
            return True
        time.sleep(0.02)
    return False


# --- Смерть соединения → исключение ---


def test_server_disconnect_makes_next_request_raise() -> None:
    """Сервер закрыл сокет → следующий request() поднимает BackendUnavailable."""
    server = _ToyServer()
    drv = BackendDriver(host=_HOST, port=server.port, default_timeout=1.0)
    try:
        drv.connect()
        server.drop_client()
        assert _wait_conn_lost(drv), "reader-поток обязан опознать закрытие сервером"

        with pytest.raises(BackendUnavailable) as ei:
            drv.request({"command": "introspect.status"})
        # Текст обязан быть actionable: адрес + причина + что будет дальше.
        message = str(ei.value)
        assert f"{_HOST}:{server.port}" in message
        assert "BACKEND_CTL=1" in message
    finally:
        drv.close()
        server.stop()


def test_inflight_request_wakes_immediately_on_disconnect() -> None:
    """Разрыв ПОСРЕДИ запроса будит ожидающего сразу, а не по истечении таймаута.

    До Task 1.1 in-flight request досиживал полный таймаут (reader молча выходил из
    цикла, никого не разбудив) и возвращал error-dict. Здесь таймаут заведомо огромный:
    если тест уложился — значит разбудил именно разрыв, а не он.
    """
    server = _ToyServer(close_after=0.3)
    drv = BackendDriver(host=_HOST, port=server.port, default_timeout=30.0)
    try:
        drv.connect()
        started = time.monotonic()
        with pytest.raises(BackendUnavailable):
            drv.request({"command": "introspect.status"})
        elapsed = time.monotonic() - started
        assert elapsed < 5.0, f"ожидающего разбудил таймаут ({elapsed:.1f}s), а не разрыв"
        # Слот pending снят — утечки ожиданий нет.
        assert not drv._pending, "pending-слоты обязаны сниматься даже на аварийном выходе"
    finally:
        drv.close()
        server.stop()


# --- Живой сокет: контракт НЕ изменился ---


def test_timeout_on_live_socket_still_returns_error_dict() -> None:
    """Молчащий, но живой бэкенд → error-dict timeout. Это не смерть, реконнект не нужен."""
    server = _ToyServer()
    drv = BackendDriver(host=_HOST, port=server.port, default_timeout=0.3)
    try:
        drv.connect()
        res = drv.request({"command": "introspect.status"})
        assert res["success"] is False
        assert res["error"] == "timeout"
        assert drv.connection_lost is False, "таймаут не должен помечать соединение мёртвым"
    finally:
        drv.close()
        server.stop()


def test_deliberate_close_returns_error_dict_not_exception() -> None:
    """Мы закрыли соединение сами → error-dict. Реконнектить нечего: это наше решение."""
    server = _ToyServer()
    drv = BackendDriver(host=_HOST, port=server.port, default_timeout=0.3)
    try:
        drv.connect()
        drv.close()
        res = drv.request({"command": "introspect.status"})
        assert res["success"] is False
        assert res["error"] == "not connected"
        assert drv.connection_lost is False
    finally:
        server.stop()


def test_reconnect_clears_conn_lost_flag() -> None:
    """Новый connect() снимает флаг смерти — иначе живой driver вечно бросал бы."""
    server = _ToyServer()
    drv = BackendDriver(host=_HOST, port=server.port, default_timeout=0.3)
    try:
        drv.connect()
        server.drop_client()
        assert _wait_conn_lost(drv)
        drv.close()

        server2 = _ToyServer()
        try:
            drv2 = BackendDriver(host=_HOST, port=server2.port, default_timeout=0.3)
            drv2.connect()
            assert drv2.connection_lost is False
            drv2.close()
        finally:
            server2.stop()
    finally:
        drv.close()
        server.stop()


# --- Сессия: мёртвый driver пересоздаётся, намерения переезжают ---


class _FakeDriver:
    """Минимальный driver для DriverSession: помнит подписки и умеет «умереть»."""

    def __init__(self, intents: Optional[list] = None) -> None:
        self.connection_lost = False
        self.closed = False
        self.imported: Optional[list] = None
        self.replayed = False
        self._intents = intents or []

    def export_subscriptions(self) -> list:
        return list(self._intents)

    def import_subscriptions(self, intents: list) -> None:
        self.imported = list(intents)
        self._intents = list(intents)

    def replay_subscriptions(self) -> list:
        self.replayed = True
        return list(self._intents)

    def close(self) -> None:
        self.closed = True


def test_ensure_recreates_driver_when_connection_lost() -> None:
    """ensure() не отдаёт driver с мёртвым транспортом — сбрасывает и пересоздаёт."""
    created: List[_FakeDriver] = []

    def _factory() -> _FakeDriver:
        drv = _FakeDriver(intents=[{"topic": "state.changed"}] if created else [])
        created.append(drv)
        return drv

    session = DriverSession(driver_factory=_factory, log=lambda _m: None)
    first = session.ensure()
    assert session.ensure() is first, "живой driver обязан переиспользоваться"

    first.connection_lost = True
    second = session.ensure()

    assert second is not first, "мёртвый driver обязан быть заменён"
    assert first.closed, "старый driver обязан быть закрыт"
    assert len(created) == 2


def test_ensure_replays_durable_subscriptions_after_death() -> None:
    """Реконнект по смерти соединения переносит durable-намерения на новый driver."""
    intents = [{"topic": "state.changed", "path": "processes.*"}]
    created: List[_FakeDriver] = []

    def _factory() -> _FakeDriver:
        drv = _FakeDriver(intents=intents if not created else [])
        created.append(drv)
        return drv

    session = DriverSession(driver_factory=_factory, log=lambda _m: None)
    first = session.ensure()
    first.connection_lost = True
    second = session.ensure()

    assert second.imported == intents, "намерения обязаны переехать на новый driver"
    assert second.replayed, "новый driver обязан переподписаться"
    report = session.pop_reconnect_report()
    assert report is not None and report.get("reconnected") is True


def test_pop_reconnect_report_is_delivered_exactly_once() -> None:
    """Task 6.1 ГАП 3 — ``pop_reconnect_report`` доставляет отчёт РОВНО ОДИН РАЗ.

    ``test_ensure_replays_durable_subscriptions_after_death`` выше доказывает, что отчёт
    ЕСТЬ после реконнекта, но не проверяет, что второй ``pop`` не вернёт его повторно.
    Инвариант «доставлен ровно один раз» — это инвариант ОЧИСТКИ состояния
    (``pop_reconnect_report`` возвращает и тут же обнуляет ``self._reconnect_report``,
    ``mcp_driver_session.py:528-531``), а не гонка транспорта — честный уровень
    доказательства здесь unit, не live (в отличие от плеч 1/2 этого гапа, которые
    требуют реального сокета/бэкенда).
    """
    intents = [{"topic": "state.changed", "path": "processes.*"}]
    created: List[_FakeDriver] = []

    def _factory() -> _FakeDriver:
        drv = _FakeDriver(intents=intents if not created else [])
        created.append(drv)
        return drv

    session = DriverSession(driver_factory=_factory, log=lambda _m: None)
    first = session.ensure()
    first.connection_lost = True
    session.ensure()

    first_pop = session.pop_reconnect_report()
    assert first_pop is not None and first_pop.get("reconnected") is True

    second_pop = session.pop_reconnect_report()
    assert second_pop is None, "повторный pop не должен воскрешать уже доставленный отчёт"
