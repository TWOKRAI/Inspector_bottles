# -*- coding: utf-8 -*-
"""Тесты BackendDriver.

Юнит:
- request-id matching: ответ по id будит ожидающего;
- таймаут при отсутствии ответа;
- обёртки строят корректные router-сообщения (через билдеры);
- событийный канал: push без request_id (или не матчащий pending) → очередь +
  подписчики; исключение колбэка не роняет reader-поток (инжекция входящих строк).

Integration (loopback TCP):
- driver → SocketChannel → bridge-adapter → фейковый echo-router → ответ driver'у
  по request_id (полный round-trip без queue_registry);
- unsolicited push через реальный сокет доходит до подписчика driver'а.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any, Dict, List

import pytest

from backend_ctl.driver import GUI_DEFAULT_PATTERNS, BackendDriver
from multiprocess_framework.modules.router_module.adapters.socket_bridge_adapter import (
    SocketBridgeAdapter,
)
from multiprocess_framework.modules.router_module.channels.socket_channel import SocketChannel


# --- Юнит: request/timeout без реального сокета ---


class TestRequestMatching:
    def test_not_connected_returns_error(self) -> None:
        d = BackendDriver()
        res = d.send_command("preprocessor", "introspect.handlers")
        assert res["success"] is False
        assert "not connected" in res["error"]


# --- Юнит: событийный канал (инжекция входящих строк через dispatch_raw) ---


from backend_ctl.tests.conftest import page_events as _page  # noqa: E402 — общий хелпер
from backend_ctl.tests.conftest import wait_for_events as _wait_events  # noqa: E402 — общий хелпер
from backend_ctl.tests.conftest import wire_line as _line  # noqa: E402 — общий хелпер


class TestEventChannel:
    """F.1: события читаются через events_page (legacy-дренаж events() удалён —

    блокирующий timeout/max_items events() тестировался отдельно ниже до F.1;
    курсорная пагинация/лимиты — контракт test_events_page.py, здесь не дублируем.
    """

    def test_push_without_request_id_goes_to_queue(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(_line({"command": "state.changed", "data": {"deltas": [1]}}))
        evts, cursor = _page(d, None)
        assert len(evts) == 1
        assert evts[0]["command"] == "state.changed"
        evts2, _ = _page(d, cursor)
        assert evts2 == []  # курсор догнал хвост

    def test_unmatched_request_id_becomes_event(self) -> None:
        """Ответ с request_id, который никто не ждёт (поздний/чужой), → событие."""
        d = BackendDriver()
        d.dispatch_raw(_line({"request_id": "no-such-id", "result": {"x": 1}}))
        evts, _ = _page(d, None)
        assert len(evts) == 1
        assert evts[0]["request_id"] == "no-such-id"

    def test_subscribe_callback_receives_event(self) -> None:
        d = BackendDriver()
        received: List[Dict[str, Any]] = []
        d.subscribe(received.append)
        d.dispatch_raw(_line({"command": "state.changed", "data": {"n": 42}}))
        assert len(received) == 1
        assert received[0]["data"]["n"] == 42

    def test_callback_exception_does_not_break_others(self) -> None:
        d = BackendDriver()
        seen: List[Dict[str, Any]] = []

        def boom(_msg: Dict[str, Any]) -> None:
            raise RuntimeError("callback failure")

        d.subscribe(boom)
        d.subscribe(seen.append)
        d.dispatch_raw(_line({"command": "state.changed"}))
        # Второй подписчик отработал, событие всё равно в канале, счётчик вырос.
        assert len(seen) == 1
        evts, _ = _page(d, None)
        assert len(evts) == 1
        assert d.event_errors == 1

    def test_unsubscribe_stops_delivery(self) -> None:
        d = BackendDriver()
        received: List[Dict[str, Any]] = []
        cb = d.subscribe(received.append)
        d.unsubscribe(cb)
        d.dispatch_raw(_line({"command": "state.changed"}))
        assert received == []

    def test_bounded_queue_drops_oldest(self) -> None:
        d = BackendDriver(event_queue_maxlen=3)
        for i in range(5):
            d.dispatch_raw(_line({"command": "state.changed", "seq": i}))
        evts, _ = _page(d, None)
        assert [e["seq"] for e in evts] == [2, 3, 4]  # старые (0,1) вытеснены

    def test_malformed_line_ignored(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(b"{not json")
        d.dispatch_raw(_line(["not", "a", "dict"]))
        evts, _ = _page(d, None)
        assert evts == []


# --- Integration: реальный loopback round-trip ---


class EchoRouter:
    """Фейковый router: request() резолвит «внутри системы» и возвращает result;
    send() с channel= кладёт ответ обратно в SocketChannel (как настоящий resolve)."""

    def __init__(self, channel: SocketChannel, handler) -> None:
        self._channel = channel
        self._handler = handler  # (msg) -> result dict

    def request(self, message: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
        # Имитируем доставку в процесс и его ответ.
        return self._handler(message)

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        # channel=-маршрутизация → SocketChannel.send (как _resolve_channels у router).
        if message.get("channel") == self._channel.name:
            return self._channel.send(message)
        return {"status": "error", "reason": "unknown channel"}


def _start_loopback():
    """Поднять SocketChannel + bridge + echo-router + подключённый driver.

    Возвращает (driver, calls, channel). Уборка — на вызывающей фикстуре.
    """
    calls: List[Dict[str, Any]] = []

    def handler(msg: Dict[str, Any]) -> Dict[str, Any]:
        calls.append(msg)
        target = (msg.get("targets") or ["?"])[0]
        return {"success": True, "result": {"target": target, "command": msg.get("command")}}

    channel = SocketChannel("backend_ctl", host="127.0.0.1", port=0)
    router = EchoRouter(channel, handler)
    adapter = SocketBridgeAdapter(router, "backend_ctl")
    channel._on_inbound = adapter.on_inbound  # привязать обработчик
    assert channel.start()

    driver = BackendDriver(host="127.0.0.1", port=channel.port)
    driver.connect()
    # дождаться регистрации клиента
    deadline = time.time() + 2.0
    while channel.get_info()["clients"] < 1 and time.time() < deadline:
        time.sleep(0.01)

    return driver, calls, channel


@pytest.fixture
def loopback():
    """(driver, calls) — реальный loopback round-trip."""
    driver, calls, channel = _start_loopback()
    yield driver, calls
    driver.close()
    channel.close()


@pytest.fixture
def loopback_push():
    """(driver, calls, channel) — с доступом к channel для unsolicited push."""
    driver, calls, channel = _start_loopback()
    yield driver, calls, channel
    driver.close()
    channel.close()


class TestIntegration:
    def test_send_command_round_trip(self, loopback) -> None:
        driver, calls = loopback
        res = driver.send_command("preprocessor", "introspect.handlers", timeout=3.0)
        assert res["success"] is True
        assert res["result"] == {"target": "preprocessor", "command": "introspect.handlers"}
        # router получил GUI-форму сообщения + reply-поля
        assert len(calls) == 1
        sent = calls[0]
        assert sent["type"] == "command"
        assert sent["command"] == "introspect.handlers"
        assert sent["targets"] == ["preprocessor"]
        assert sent["sender"] == "backend_ctl"
        assert sent["reply_to"] == "ProcessManager"
        assert "request_id" in sent

    def test_introspect_handlers_wrapper(self, loopback) -> None:
        driver, calls = loopback
        res = driver.introspect_handlers("camera", timeout=3.0)
        assert res["result"]["target"] == "camera"

    def test_introspect_plugins_wrapper(self, loopback) -> None:
        """Ф2.3: обёртка шлёт introspect.plugins адресату (failed-list плагинов)."""
        driver, calls = loopback
        res = driver.introspect_plugins("camera", timeout=3.0)
        assert res["result"]["command"] == "introspect.plugins"
        assert calls[0]["command"] == "introspect.plugins"
        assert calls[0]["targets"] == ["camera"]

    def test_introspect_telemetry_wrapper(self, loopback) -> None:
        """Ф4.1: обёртка шлёт introspect.telemetry адресату (readback телеметрийного gate)."""
        driver, calls = loopback
        res = driver.introspect_telemetry("camera", timeout=3.0)
        assert res["result"]["command"] == "introspect.telemetry"
        assert calls[0]["command"] == "introspect.telemetry"
        assert calls[0]["targets"] == ["camera"]

    def test_introspect_memory_wrapper(self, loopback) -> None:
        """Ф2 Task 2.4: обёртка шлёт introspect.memory адресату и парсит в MemoryStats.

        Envelope — канонический (command/targets/reply-поля); результат —
        типизированный :class:`MemoryStats` с сохранённым сырым ответом в ``.raw``.
        """
        from backend_ctl.driver import MemoryStats

        driver, calls = loopback
        res = driver.introspect_memory("camera", timeout=3.0)
        # конверт корректен
        assert calls[0]["command"] == "introspect.memory"
        assert calls[0]["targets"] == ["camera"]
        assert calls[0]["reply_to"] == "ProcessManager"
        # типизированный результат + сырой ответ сохранён
        assert isinstance(res, MemoryStats)
        assert res.ok is True  # echo-result.success=True
        assert res.raw["result"]["command"] == "introspect.memory"

    def test_set_register_builds_register_update(self, loopback) -> None:
        """Payload — канонический контракт register_update: {register, field, value}.

        Регресс: исторически driver слал plugin_name — обработчик оркестратора
        (data.get("register") is None) молча выходил, запись была no-op.
        """
        driver, calls = loopback
        driver.set_register("preprocessor", "resize", "target_width", 640, timeout=3.0)
        sent = calls[0]
        assert sent["command"] == "register_update"
        assert sent["data"] == {"register": "resize", "field": "target_width", "value": 640}

    def test_system_command_wraps_process_command(self, loopback) -> None:
        driver, calls = loopback
        driver.system_command({"cmd": "process.start", "process_name": "camera"}, timeout=3.0)
        sent = calls[0]
        assert sent["command"] == "process.command"
        assert sent["targets"] == ["ProcessManager"]
        assert sent["data"] == {"cmd": "process.start", "process_name": "camera"}

    def test_distinct_request_ids_matched(self, loopback) -> None:
        """Два последовательных запроса матчатся по своим id (не путаются)."""
        driver, _ = loopback
        r1 = driver.send_command("p1", "introspect.status", timeout=3.0)
        r2 = driver.send_command("p2", "introspect.status", timeout=3.0)
        assert r1["result"]["target"] == "p1"
        assert r2["result"]["target"] == "p2"


class TestPushEvents:
    def test_state_subscribe_builds_command(self, loopback) -> None:
        """state_subscribe шлёт корректный state.subscribe в ProcessManager."""
        driver, calls = loopback
        driver.state_subscribe("processes.**", timeout=3.0)
        sent = calls[0]
        assert sent["command"] == "state.subscribe"
        assert sent["targets"] == ["ProcessManager"]
        assert sent["data"]["pattern"] == "processes.**"
        # D.1: connected driver подписывается под session-scoped subscriber
        # (<sender>.<session>), не под плоским sender — изоляция и push-плоскости.
        assert sent["data"]["subscriber"] == driver._subscriber
        assert sent["data"]["subscriber"] == f"backend_ctl.{driver._session}"

    def test_unsolicited_push_reaches_subscriber(self, loopback_push) -> None:
        """Реальный сокет: сервер шлёт state.changed (без request_id) → подписчик."""
        driver, _calls, channel = loopback_push
        received: List[Dict[str, Any]] = []
        driver.subscribe(received.append)

        push = {
            "command": "state.changed",
            "channel": "backend_ctl",  # адресуем в наш socket-канал
            "data": {"deltas": [{"path": "processes.camera.fps", "value": 30}]},
        }
        res = channel.send(push)
        assert res.get("status") == "success"

        # reader-поток driver'а должен доставить push подписчику
        evts, _ = _wait_events(driver, timeout=2.0)
        assert len(evts) == 1
        assert evts[0]["command"] == "state.changed"
        assert evts[0]["data"]["deltas"][0]["value"] == 30
        # и синхронный подписчик тоже получил (может прийти чуть позже drain)
        deadline = time.time() + 1.0
        while not received and time.time() < deadline:
            time.sleep(0.01)
        assert len(received) == 1

    def test_reply_path_still_works_alongside_events(self, loopback_push) -> None:
        """Reply-путь не сломан: request/response по request_id + push сосуществуют."""
        driver, _calls, channel = loopback_push
        # push «до» запроса — уйдёт в очередь событий, не в pending
        channel.send({"command": "state.changed", "channel": "backend_ctl", "data": {}})
        # обычный request по-прежнему матчится по request_id
        res = driver.send_command("preprocessor", "introspect.status", timeout=3.0)
        assert res["success"] is True
        assert res["result"]["target"] == "preprocessor"
        # push осел в событиях
        evts, _ = _wait_events(driver, timeout=1.0)
        assert any(e.get("command") == "state.changed" for e in evts)


# --- Юнит: verify-probe set_register_verified (Ф1 Task 1.6) ---


class TestSetRegisterVerified:
    """write → readback → diff; probe не доверяет ack'у записи."""

    @staticmethod
    def _driver_with_fake_backend(registers: Dict[str, Any], monkeypatch) -> BackendDriver:
        d = BackendDriver()

        def fake_send(process, command, args=None, **kw):
            if command == "register_update":
                # имитируем применение записи на бэкенде
                reg = registers.setdefault(args["register"], {})
                if args["field"] in reg:
                    reg[args["field"]] = args["value"]
                return {"success": True}
            if command == "introspect.registers":
                return {"success": True, "process": process, "registers": registers}
            raise AssertionError(f"неожиданная команда: {command}")

        monkeypatch.setattr(d, "send_command", fake_send)
        return d

    def test_verified_true_when_readback_matches(self, monkeypatch) -> None:
        d = self._driver_with_fake_backend({"resize": {"target_width": 0}}, monkeypatch)
        res = d.set_register_verified("preprocessor", "resize", "target_width", 512)
        assert res["verified"] is True
        assert res["success"] is True
        assert res["actual"] == 512

    def test_unknown_field_is_caught(self, monkeypatch) -> None:
        """Молчаливый no-op (нет такого поля) — probe возвращает verified=False."""
        d = self._driver_with_fake_backend({"resize": {"target_width": 0}}, monkeypatch)
        res = d.set_register_verified("preprocessor", "resize", "width", 512)
        assert res["verified"] is False
        assert res["found"] is False
        assert res["known_registers"] == ["resize"]

    def test_unknown_register_is_caught(self, monkeypatch) -> None:
        d = self._driver_with_fake_backend({"resize": {"target_width": 0}}, monkeypatch)
        res = d.set_register_verified("preprocessor", "no_such", "target_width", 512)
        assert res["verified"] is False
        assert res["found"] is False

    def test_wrapped_introspect_response_unwrapped(self, monkeypatch) -> None:
        """Ответ introspect.registers может прийти конвертом {success, result: {...}}."""
        d = BackendDriver()

        def fake_send(process, command, args=None, **kw):
            if command == "register_update":
                return {"success": True}
            return {"success": True, "result": {"success": True, "registers": {"resize": {"target_width": 512}}}}

        monkeypatch.setattr(d, "send_command", fake_send)
        res = d.set_register_verified("preprocessor", "resize", "target_width", 512)
        assert res["verified"] is True


# --- Task 0.2: гонка close()/request() + карантин поздних ответов ---


class _FakeSock:
    """Минимальный сокет-дублёр: sendall/close, опц. падение при закрытии."""

    def __init__(self, *, fail: bool = False) -> None:
        self.closed = False
        self._fail = fail
        self.sent: List[bytes] = []

    def sendall(self, data: bytes) -> None:
        if self.closed or self._fail:
            raise OSError("socket closed")
        self.sent.append(data)

    def close(self) -> None:
        self.closed = True


class _FakeReaderSock:
    """Сокет-дублёр для reader-стресса: recv крутит socket.timeout, close → OSError."""

    def __init__(self) -> None:
        self.closed = False

    def recv(self, _n: int) -> bytes:
        if self.closed:
            raise OSError("socket closed")
        time.sleep(0.0005)
        raise socket.timeout()  # держать reader в цикле, не отдавая данных

    def sendall(self, data: bytes) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _NullingReaderSock:
    """recv() бросает AttributeError — как ``None.recv`` в TOCTOU-окне close()/read_loop."""

    def recv(self, _n: int) -> bytes:
        raise AttributeError("'NoneType' object has no attribute 'recv'")

    def sendall(self, data: bytes) -> None:
        pass

    def close(self) -> None:
        pass


class TestReadLoopThreadSafety:
    """A.3: конкурентные close()/read_loop не роняют reader AttributeError'ом."""

    def test_read_loop_catches_attributeerror_from_nulled_sock(self) -> None:
        # Детерминированно: recv бросает AttributeError (как None.recv в TOCTOU-окне).
        # pre-fix ловит только OSError → пробрасывает и роняет reader; post-fix — break.
        d = BackendDriver()
        d._running = True
        d._sock = _NullingReaderSock()  # type: ignore[assignment]
        d._read_loop()  # не должен бросить — завершается штатно
        assert True

    def test_concurrent_close_during_read_loop_never_crashes(self) -> None:
        for i in range(100):
            d = BackendDriver()
            d._sock = _FakeReaderSock()  # type: ignore[assignment]
            d._running = True
            errors: List[BaseException] = []

            def _run_reader() -> None:
                try:
                    d._read_loop()
                except BaseException as exc:  # noqa: BLE001 — тест ловит ЛЮБУЮ утечку
                    errors.append(exc)

            t = threading.Thread(target=_run_reader)
            t.start()
            time.sleep(0.001)
            d.close()  # обнуляет _sock из другого потока — гонка с recv()
            t.join(timeout=2.0)

            assert not t.is_alive(), f"reader завис на итерации {i}"
            assert not errors, f"reader бросил исключение на итерации {i}: {errors}"


class TestSendRaceAndLateReplies:
    def test_send_raw_raises_connectionerror_when_socket_none(self) -> None:
        # Старое поведение — AssertionError; новое — штатная ConnectionError.
        d = BackendDriver()
        assert d._sock is None
        with pytest.raises(ConnectionError):
            d._send_raw({"command": "x"})

    def test_request_returns_error_dict_on_send_failure(self) -> None:
        # sendall падает (сокет закрыт из другого потока) → request не бросает, а
        # отдаёт error-dict с success=False.
        d = BackendDriver()
        d._sock = _FakeSock(fail=True)  # type: ignore[assignment]
        res = d.request({"command": "x", "request_id": "cid-fail"}, timeout=0.2)
        assert res["success"] is False
        assert res["error"] == "connection closed"
        assert res["request_id"] == "cid-fail"

    def test_concurrent_close_during_request_never_asserts(self) -> None:
        # Стресс: close() из другого потока во время in-flight request() → всегда dict,
        # никогда AssertionError/утечка исключения (Task 0.2, 100 итераций).
        for i in range(100):
            d = BackendDriver()
            d._sock = _FakeSock()  # type: ignore[assignment]
            d._running = True
            results: List[Any] = []
            errors: List[BaseException] = []

            def _do_request() -> None:
                try:
                    results.append(d.request({"command": "x", "request_id": f"cid-{i}"}, timeout=0.3))
                except BaseException as exc:  # noqa: BLE001 — тест ловит ЛЮБУЮ утечку
                    errors.append(exc)

            t = threading.Thread(target=_do_request)
            t.start()
            d.close()  # обнуляет _sock из главного потока — гонка с _send_raw
            t.join(timeout=2.0)

            assert not t.is_alive(), f"request завис на итерации {i}"
            assert not errors, f"request бросил исключение: {errors}"
            assert len(results) == 1 and isinstance(results[0], dict)
            assert results[0]["success"] is False

    def test_late_reply_after_timeout_is_dropped_not_event(self) -> None:
        # request() таймаутит и кладёт cid в карантин; поздний ответ с тем же cid
        # dispatcher дропает (не псевдо-событие) и растит late_replies.
        d = BackendDriver()
        d._sock = _FakeSock()  # type: ignore[assignment]
        res = d.request({"command": "slow", "request_id": "cid-late"}, timeout=0.05)
        assert res["error"] == "timeout"
        assert d.late_replies == 0

        d.dispatch_raw(_line({"request_id": "cid-late", "result": {"value": 1}}))
        evts, _ = _page(d, None)
        assert evts == [], "поздний ответ не должен всплывать событием"
        assert d.late_replies == 1

    def test_unquarantined_request_id_still_becomes_event(self) -> None:
        # Регресс-контроль: cid, который НЕ таймаутили, по-прежнему → событие.
        d = BackendDriver()
        d.dispatch_raw(_line({"request_id": "never-issued", "result": {"x": 1}}))
        evts, _ = _page(d, None)
        assert len(evts) == 1
        assert d.late_replies == 0


class TestCloseStopsApplierThread:
    """A.2: close() гасит applier-поток watch (иначе реконнект плодит зомби-потоки)."""

    def test_close_joins_resub_applier(self) -> None:
        d = BackendDriver()
        d._sock = _FakeSock()  # type: ignore[assignment]
        d._running = True
        # Поднять watch-контур БЕЗ сети (как реконнект после replay durable-намерений).
        d.resume_watch({"active": True, "patterns": ["processes.**"], "processes": []})
        thread = d._watch._resub_thread
        assert thread is not None and thread.is_alive()

        d.close()

        thread.join(timeout=2.0)
        assert not thread.is_alive(), "applier-поток backend-ctl-resub не погашен close()"
        assert d._watch._resub_thread is None
        # Идемпотентность: повторный close не бросает.
        d.close()

    def test_reconnect_cycles_do_not_leak_resub_threads(self) -> None:
        # N реконнект-циклов (watch активен) → ни одного живого applier-потока после.
        d = BackendDriver()
        for _ in range(5):
            d._sock = _FakeSock()  # type: ignore[assignment]
            d._running = True
            d.resume_watch({"active": True, "patterns": ["p.**"], "processes": []})
            d.close()
        alive = [t for t in threading.enumerate() if t.name == "backend-ctl-resub" and t.is_alive()]
        assert alive == [], f"живые applier-потоки после реконнектов: {alive}"


# --- Task 0.3: durable-подписки (реестр намерений + replay) ---


class TestSubscriptionRegistry:
    def _recorder(self, monkeypatch):
        """Driver, у которого send_command только пишет вызовы и отдаёт success."""
        d = BackendDriver()
        calls: List[tuple] = []

        def fake_send(target, command, args=None, *, timeout=None):
            calls.append((target, command, args))
            return {"success": True}

        monkeypatch.setattr(d, "send_command", fake_send)
        return d, calls

    def test_state_subscribe_registers_intent(self, monkeypatch) -> None:
        d, _ = self._recorder(monkeypatch)
        d.state_subscribe("processes.**")
        intents = d.export_subscriptions()
        assert any(i["command"] == "state.subscribe" and i["args"]["pattern"] == "processes.**" for i in intents)

    def test_log_tail_then_untail_removes_intent(self, monkeypatch) -> None:
        d, _ = self._recorder(monkeypatch)
        d.log_tail("preprocessor", level="ERROR")
        assert any(
            i["command"] == "log.tail.subscribe" and i["target"] == "preprocessor" for i in d.export_subscriptions()
        )
        d.log_untail("preprocessor")
        assert not any(i["target"] == "preprocessor" for i in d.export_subscriptions())

    def test_ui_untap_removes_all_for_process(self, monkeypatch) -> None:
        d, _ = self._recorder(monkeypatch)
        d.ui_tap("gui")
        assert any(i["command"] == "ui.tap.subscribe" for i in d.export_subscriptions())
        d.ui_untap("gui")
        assert not any(i["command"] == "ui.tap.subscribe" for i in d.export_subscriptions())

    def test_failed_subscribe_not_registered(self, monkeypatch) -> None:
        d = BackendDriver()

        def failing_send(target, command, args=None, *, timeout=None):
            return {"success": False, "error": "not connected"}

        monkeypatch.setattr(d, "send_command", failing_send)
        d.state_subscribe("processes.**")
        assert d.export_subscriptions() == []

    def test_duplicate_intent_deduped(self, monkeypatch) -> None:
        d, _ = self._recorder(monkeypatch)
        d.state_subscribe("processes.**")
        d.state_subscribe("processes.**")
        same = [i for i in d.export_subscriptions() if i["args"].get("pattern") == "processes.**"]
        assert len(same) == 1

    def test_replay_resends_all_intents(self, monkeypatch) -> None:
        d, calls = self._recorder(monkeypatch)
        d.state_subscribe("processes.**")
        d.log_tail("preprocessor", level="WARNING")
        calls.clear()
        report = d.replay_subscriptions()
        replayed = {(t, c) for t, c, _ in calls}
        assert ("ProcessManager", "state.subscribe") in replayed
        assert ("preprocessor", "log.tail.subscribe") in replayed
        assert all(r["success"] for r in report)

    def test_import_export_roundtrip(self, monkeypatch) -> None:
        d1, _ = self._recorder(monkeypatch)
        d1.state_subscribe("system.**")
        d2 = BackendDriver()
        d2.import_subscriptions(d1.export_subscriptions())
        assert d2.export_subscriptions() == d1.export_subscriptions()


# --- Task 2.1: observability_tail — live ЛОГИ+ОШИБКИ+СТАТИСТИКА ---


def _obs_record(kind: str, message: str = "msg") -> Dict[str, Any]:
    """Синтетическая display-запись наблюдаемости (форма record_display)."""
    return {"kind": kind, "process": "preprocessor", "module": "m", "ts": 1.0, "severity": "", "message": message}


def _obs_event(records: Any = None, record: Any = None) -> Dict[str, Any]:
    """Синтетическое событие observability.record (пачка records и/или одиночная record)."""
    data: Dict[str, Any] = {"process": "preprocessor"}
    if records is not None:
        data["records"] = records
    if record is not None:
        data["record"] = record
    return {"command": "observability.record", "data": data}


class TestObservabilityTail:
    def _recorder(self, monkeypatch):
        d = BackendDriver()
        calls: List[tuple] = []

        def fake_send(target, command, args=None, *, timeout=None):
            calls.append((target, command, args))
            return {"success": True}

        monkeypatch.setattr(d, "send_command", fake_send)
        return d, calls

    def test_tail_sends_canonical_envelope_and_registers_intent(self, monkeypatch) -> None:
        d, calls = self._recorder(monkeypatch)
        d.observability_tail("preprocessor")
        assert ("preprocessor", "observability.tail.subscribe", {"subscriber": "backend_ctl"}) in calls
        assert any(
            i["command"] == "observability.tail.subscribe" and i["target"] == "preprocessor"
            for i in d.export_subscriptions()
        )

    def test_tail_custom_subscriber(self, monkeypatch) -> None:
        d, calls = self._recorder(monkeypatch)
        d.observability_tail("preprocessor", subscriber="watcher")
        assert ("preprocessor", "observability.tail.subscribe", {"subscriber": "watcher"}) in calls

    def test_untail_sends_subscriber_and_removes_intent(self, monkeypatch) -> None:
        # Регресс F1: unsubscribe ОБЯЗАН нести subscriber на проводе — снять форвардер
        # ТОЛЬКО driver'а, не задев per-subscriber-хвост GUI (раньше слался пустой {}).
        d, calls = self._recorder(monkeypatch)
        d.observability_tail("preprocessor")
        d.observability_untail("preprocessor")
        assert ("preprocessor", "observability.tail.unsubscribe", {"subscriber": "backend_ctl"}) in calls
        assert not any(i["command"] == "observability.tail.subscribe" for i in d.export_subscriptions())

    def test_untail_custom_subscriber_on_wire(self, monkeypatch) -> None:
        # F1: явный subscriber доходит до провода (снять именно его форвардер).
        d, calls = self._recorder(monkeypatch)
        d.observability_tail("preprocessor", subscriber="watcher")
        d.observability_untail("preprocessor", subscriber="watcher")
        assert ("preprocessor", "observability.tail.unsubscribe", {"subscriber": "watcher"}) in calls

    def test_failed_tail_not_registered(self, monkeypatch) -> None:
        d = BackendDriver()
        monkeypatch.setattr(d, "send_command", lambda *a, **k: {"success": False, "error": "no receiver"})
        d.observability_tail("preprocessor")
        assert d.export_subscriptions() == []


class TestObservabilityRecords:
    def test_classifies_batch_by_kind(self) -> None:
        d = BackendDriver()
        events = [_obs_event(records=[_obs_record("log"), _obs_record("stats"), _obs_record("error")])]
        assert [r["kind"] for r in d.observability_records(events)] == ["log", "stats", "error"]
        assert [r["kind"] for r in d.observability_records(events, kind="error")] == ["error"]
        assert d.observability_records(events, kind="log")[0]["message"] == "msg"

    def test_flattens_single_and_batch_and_ignores_foreign(self) -> None:
        d = BackendDriver()
        events = [
            _obs_event(records=[_obs_record("log")]),
            _obs_event(record=_obs_record("error")),
            {"command": "state.changed", "data": {"deltas": []}},  # чужое событие — игнор
            {"command": "log.record", "data": {"record": {}}},  # log_tail — не observability
        ]
        kinds = [r["kind"] for r in d.observability_records(events)]
        assert kinds == ["log", "error"]

    def test_none_events_reads_since_last_call(self) -> None:
        """F.1: events=None читает НЕдеструктивно через events_page своим приватным
        курсором — повторный вызов без нового push'а не повторяет уже отданное
        (курсор продвинулся), но НЕ съедает событие у других читателей events_page."""
        d = BackendDriver()
        d.dispatch_raw(_line(_obs_event(records=[_obs_record("stats")])))
        recs = d.observability_records()  # events=None → своя страница events_page
        assert [r["kind"] for r in recs] == ["stats"]
        assert d.observability_records() == [], "повторный вызов не должен повторять уже отданное"
        # Другой читатель events_page по-прежнему видит событие (недеструктивно).
        assert d.events_page("stats")["count"] == 1

    def test_record_without_kind_excluded_by_filter(self) -> None:
        d = BackendDriver()
        rec = {"process": "p", "message": "no kind"}
        events = [_obs_event(record=rec)]
        # Без фильтра запись без kind отдаётся как есть (best-effort по доступным полям).
        assert d.observability_records(events) == [rec]
        # С фильтром сопоставить не с чем → исключается.
        assert d.observability_records(events, kind="log") == []


def _sev_rec(kind: str, severity: str, message: str = "m") -> Dict[str, Any]:
    """Display-запись с явным severity (для F5-фильтра по уровню)."""
    return {"kind": kind, "process": "p", "module": "m", "ts": 1.0, "severity": severity, "message": message}


class TestObservabilityLevelFilter:
    """F5: клиентский severity-фильтр реально отсекает (tail_level больше не пустышка)."""

    def _events(self):
        return [
            _obs_event(
                records=[
                    _sev_rec("log", "debug"),
                    _sev_rec("log", "info"),
                    _sev_rec("log", "warning"),
                    _sev_rec("error", "error"),
                    _sev_rec("stats", "gauge"),  # чужой severity — плоскость независима
                ]
            )
        ]

    def test_level_filter_cuts_below_threshold(self) -> None:
        d = BackendDriver()
        recs = d.observability_records(self._events(), level="WARNING")
        sevs = [r["severity"] for r in recs]
        # debug/info срезаны; warning/error остались; stats (gauge) НЕ режется log-порогом.
        assert "debug" not in sevs and "info" not in sevs
        assert "warning" in sevs and "error" in sevs
        assert "gauge" in sevs

    def test_level_none_no_filter_without_watch(self) -> None:
        d = BackendDriver()
        # Watch не активен, level=None → severity-фильтр не применяется (все 5 записей).
        assert len(d.observability_records(self._events())) == 5

    def test_watch_tail_level_becomes_default_filter(self, monkeypatch) -> None:
        # Регресс F5: tail_level из watch_like_gui теперь реально дефолтит severity-фильтр.
        d = BackendDriver()

        def fake_send(target, command, args=None, *, timeout=None):
            if command == "state.get_subtree":
                return {"success": True, "result": {"subtree": {}}}
            return {"success": True}

        monkeypatch.setattr(d, "send_command", fake_send)
        try:
            d.watch_like_gui(tail_level="ERROR")  # объявлен ERROR
            recs = d.observability_records(self._events())  # level=None → берёт tail_level=ERROR
            sevs = [r["severity"] for r in recs]
            assert sevs == ["error", "gauge"], "ниже ERROR лог-записи срезаны; stats независим"
            # Явный level="DEBUG" перекрывает дефолт watch — вернуть всё.
            assert len(d.observability_records(self._events(), level="DEBUG")) == 5
        finally:
            d.unwatch()


# --- Task 2.2: watch_like_gui — GUI-паритет приёма + авто-переподписка ---


class TestWatchLikeGui:
    def _driver(self, monkeypatch, procs=("gui", "preprocessor", "camera_0")):
        d = BackendDriver()
        calls: List[tuple] = []

        def fake_send(target, command, args=None, *, timeout=None):
            calls.append((target, command, args))
            if command == "state.get_subtree":
                return {"success": True, "result": {"subtree": {p: {} for p in procs}}}
            return {"success": True}

        monkeypatch.setattr(d, "send_command", fake_send)
        return d, calls

    def test_subscribes_all_patterns_and_all_processes(self, monkeypatch) -> None:
        d, calls = self._driver(monkeypatch)
        try:
            summary = d.watch_like_gui()
            state_subs = [args["pattern"] for t, c, args in calls if c == "state.subscribe"]
            assert set(state_subs) == set(GUI_DEFAULT_PATTERNS)
            assert len(state_subs) == len(GUI_DEFAULT_PATTERNS)
            obs = [t for t, c, _ in calls if c == "observability.tail.subscribe"]
            assert set(obs) == {"gui", "preprocessor", "camera_0"}
            assert summary["success"] is True
            assert set(summary["processes"]) == {"gui", "preprocessor", "camera_0"}
            assert summary["tail_level"] == "WARNING"
        finally:
            d.unwatch()

    def test_custom_patterns(self, monkeypatch) -> None:
        d, calls = self._driver(monkeypatch)
        try:
            d.watch_like_gui(patterns=("system.**",))
            state_subs = [args["pattern"] for t, c, args in calls if c == "state.subscribe"]
            assert state_subs == ["system.**"]
        finally:
            d.unwatch()

    def test_recovered_event_resubscribes_exactly_that_process(self, monkeypatch) -> None:
        d, calls = self._driver(monkeypatch)
        try:
            d.watch_like_gui()
            calls.clear()
            # Синтетическое supervisor-recovered для camera_0 (новая инкарнация).
            recovered = {
                "command": "state.changed",
                "data": {
                    "deltas": [
                        {"path": "processes.camera_0.supervisor.event", "new_value": "recovered", "old_value": "x"}
                    ]
                },
            }
            d.dispatch_raw(_line(recovered))
            d._watch._resub_queue.join()  # дождаться применения намерения applier-потоком
            resubs = [t for t, c, _ in calls if c == "observability.tail.subscribe"]
            assert resubs == ["camera_0"], "переподписка ровно затронутого процесса, не других"
        finally:
            d.unwatch()

    def test_non_recovered_delta_does_not_resubscribe_known_process(self, monkeypatch) -> None:
        d, calls = self._driver(monkeypatch)
        try:
            d.watch_like_gui()
            calls.clear()
            # Обычная дельта уже подписанного процесса → без переподписки.
            noise = {
                "command": "state.changed",
                "data": {"deltas": [{"path": "processes.camera_0.status", "new_value": "running"}]},
            }
            d.dispatch_raw(_line(noise))
            d._watch._resub_queue.join()
            assert not any(c == "observability.tail.subscribe" for _, c, _ in calls)
        finally:
            d.unwatch()

    def test_new_process_delta_subscribes_first_time(self, monkeypatch) -> None:
        d, calls = self._driver(monkeypatch)
        try:
            d.watch_like_gui()
            calls.clear()
            # Появился НЕ виденный ранее процесс → первичная подписка (паритет активатора).
            appeared = {
                "command": "state.changed",
                "data": {"deltas": [{"path": "processes.detector.status", "new_value": "running"}]},
            }
            d.dispatch_raw(_line(appeared))
            d._watch._resub_queue.join()
            resubs = [t for t, c, _ in calls if c == "observability.tail.subscribe"]
            assert resubs == ["detector"]
        finally:
            d.unwatch()

    def test_unwatch_untails_all_and_stops_thread(self, monkeypatch) -> None:
        d, calls = self._driver(monkeypatch)
        d.watch_like_gui()
        thread = d._watch._resub_thread
        assert thread is not None and thread.is_alive()
        calls.clear()
        summary = d.unwatch()
        untails = {t for t, c, _ in calls if c == "observability.tail.unsubscribe"}
        assert untails == {"gui", "preprocessor", "camera_0"}
        assert summary["was_active"] is True
        thread.join(timeout=2.0)
        assert not thread.is_alive(), "applier-поток должен остановиться по sentinel"
        # Durable-намерения watch-паттернов сняты (реконнект их не воскресит).
        assert not any(i["command"] == "state.subscribe" for i in d.export_subscriptions())

    def test_unwatch_removes_custom_watch_patterns(self, monkeypatch) -> None:
        """unwatch снимает durable-намерения ИМЕННО тех паттернов, что включал
        watch_like_gui (регресс: раньше хардкодился GUI_DEFAULT_PATTERNS → кастомный
        набор утекал в реестре и воскресал бы при реконнекте)."""
        d, _ = self._driver(monkeypatch)
        custom = ("cameras.**", "renderer.**")  # намеренно НЕ из GUI_DEFAULT_PATTERNS
        try:
            d.watch_like_gui(patterns=custom)
            subs = [i for i in d.export_subscriptions() if i["command"] == "state.subscribe"]
            assert {i["args"].get("pattern") for i in subs} == set(custom)
            d.unwatch()
            assert not any(i["command"] == "state.subscribe" for i in d.export_subscriptions()), (
                "кастомные watch-паттерны должны быть сняты из durable-реестра"
            )
        finally:
            d.unwatch()

    def test_reentrant_watch_restarts_cleanly(self, monkeypatch) -> None:
        d, _ = self._driver(monkeypatch)
        try:
            d.watch_like_gui()
            first = d._watch._resub_thread
            d.watch_like_gui()  # повторный вызов → unwatch + свежий старт
            assert d._watch._resub_thread is not first
            assert d._watch._watch_active is True
        finally:
            d.unwatch()


class TestWatchStartupWindow:
    """F4: слушатель регистрируется ДО первичных подписок — recovered не теряется."""

    def test_recovered_during_startup_subscriptions_is_not_lost(self, monkeypatch) -> None:
        # Регресс F4: раньше listener вешался ПОСЛЕДНИМ (после N×obs_tail до 5с), и
        # recovered, прилетевший в это окно, терялся → процесс оставался без хвоста.
        d = BackendDriver()
        calls: List[tuple] = []
        injected = {"done": False}

        def fake_send(target, command, args=None, *, timeout=None):
            calls.append((target, command, args))
            if command == "state.get_subtree":
                return {"success": True, "result": {"subtree": {p: {} for p in ("gui", "preprocessor")}}}
            # Во время СТАРТОВОЙ obs-подписки первого процесса впрыснуть recovered для
            # процесса, которого нет в топологии — поймает только уже-активный listener.
            if command == "observability.tail.subscribe" and target == "gui" and not injected["done"]:
                injected["done"] = True
                recovered = {
                    "command": "state.changed",
                    "data": {"deltas": [{"path": "processes.latecomer.supervisor.event", "new_value": "recovered"}]},
                }
                d.dispatch_raw(_line(recovered))
            return {"success": True}

        monkeypatch.setattr(d, "send_command", fake_send)
        try:
            d.watch_like_gui()
            d._watch._resub_queue.join()  # дождаться применения намерения applier-потоком
            obs = [t for t, c, _ in calls if c == "observability.tail.subscribe"]
            assert "latecomer" in obs, "recovered в стартовом окне подхвачен (listener активен ДО подписок)"
        finally:
            d.unwatch()


class TestWatchUnwatchRace:
    """F3: unwatch во время медленного in-flight resub → нет воскресших форвардеров/намерений."""

    def test_inflight_resub_self_heals_after_unwatch(self, monkeypatch) -> None:
        d = BackendDriver()
        calls: List[tuple] = []
        release = threading.Event()
        block = {"on": False}
        entered = threading.Event()

        def fake_send(target, command, args=None, *, timeout=None):
            calls.append((target, command, args))
            if command == "state.get_subtree":
                return {"success": True, "result": {"subtree": {p: {} for p in ("gui", "camera_0")}}}
            if command == "observability.tail.subscribe" and block["on"]:
                entered.set()  # applier вошёл в in-flight resub
                release.wait(timeout=5)  # имитируем долгий request() (до 5с)
            return {"success": True}

        monkeypatch.setattr(d, "send_command", fake_send)
        d.watch_like_gui()
        # После стартовой подписки camera_0 durable-намерение обязано существовать.
        assert any(
            i["command"] == "observability.tail.subscribe" and i["target"] == "camera_0"
            for i in d.export_subscriptions()
        )
        block["on"] = True
        # recovered → applier войдёт в observability_tail(camera_0) и заблокируется.
        recovered = {
            "command": "state.changed",
            "data": {"deltas": [{"path": "processes.camera_0.supervisor.event", "new_value": "recovered"}]},
        }
        d.dispatch_raw(_line(recovered))
        assert entered.wait(timeout=3), "applier должен войти в in-flight resub"

        # unwatch в фоне (join заблокируется, пока applier висит в resub).
        done = threading.Event()
        threading.Thread(target=lambda: (d.unwatch(), done.set()), daemon=True).start()
        time.sleep(0.05)  # дать unwatch снять _watch_active + начать join
        release.set()  # отпустить in-flight resub — он завершится ПОСЛЕ untail-цикла
        assert done.wait(timeout=5), "unwatch должен завершиться"
        d._watch._resub_queue.join()  # applier само-исцелился и добрал sentinel

        # Регресс F3: форвардер/намерение НЕ воскресли после teardown.
        assert not any(i["command"] == "observability.tail.subscribe" for i in d.export_subscriptions()), (
            "in-flight resub само-откатился (untail), durable-намерение не воскресло"
        )


class TestWatchDurability:
    """F2: watch переживает реконнект через манифест + resume; unwatch управляем."""

    def _driver(self, monkeypatch, procs=("gui", "preprocessor", "camera_0")):
        d = BackendDriver()
        calls: List[tuple] = []

        def fake_send(target, command, args=None, *, timeout=None):
            calls.append((target, command, args))
            if command == "state.get_subtree":
                return {"success": True, "result": {"subtree": {p: {} for p in procs}}}
            return {"success": True}

        monkeypatch.setattr(d, "send_command", fake_send)
        return d, calls

    def test_manifest_reflects_active_watch(self, monkeypatch) -> None:
        d, _ = self._driver(monkeypatch)
        assert d.watch_manifest() == {"active": False}
        try:
            d.watch_like_gui(tail_level="ERROR")
            m = d.watch_manifest()
            assert m["active"] is True
            assert set(m["patterns"]) == set(GUI_DEFAULT_PATTERNS)
            assert m["tail_level"] == "ERROR"
            assert set(m["processes"]) == {"gui", "preprocessor", "camera_0"}
        finally:
            d.unwatch()

    def test_resume_restores_loop_without_resubscribing(self, monkeypatch) -> None:
        # Регресс F2: реконнект replay'ит серверные подписки, resume поднимает КОНТУР
        # (listener + applier) БЕЗ повторных подписок — auto-resub оживает.
        d, calls = self._driver(monkeypatch)
        d.watch_like_gui()
        manifest = d.watch_manifest()
        d.unwatch()  # эмулируем потерю контура на реконнекте
        assert d._watch._watch_active is False
        calls.clear()

        res = d.resume_watch(manifest)
        try:
            assert res["resumed"] is True
            assert d._watch._watch_active is True
            assert d._watch._resub_thread is not None and d._watch._resub_thread.is_alive()
            # resume НЕ шлёт повторных подписок (их вернул replay durable-намерений).
            assert not any(c in ("state.subscribe", "observability.tail.subscribe") for _, c, _ in calls)
            # Контур жив: recovered → переподписка (unwatch более НЕ no-op).
            recovered = {
                "command": "state.changed",
                "data": {"deltas": [{"path": "processes.camera_0.supervisor.event", "new_value": "recovered"}]},
            }
            d.dispatch_raw(_line(recovered))
            d._watch._resub_queue.join()
            assert any(c == "observability.tail.subscribe" and t == "camera_0" for t, c, _ in calls)
        finally:
            d.unwatch()

    def test_resume_inactive_manifest_is_noop(self, monkeypatch) -> None:
        d, _ = self._driver(monkeypatch)
        assert d.resume_watch({"active": False}) == {"resumed": False}
        assert d.resume_watch(None) == {"resumed": False}
        assert d._watch._watch_active is False

    def test_state_unsubscribe_removes_durable_intent(self) -> None:
        d = BackendDriver()
        d._subscriptions.add("state.subscribe", "ProcessManager", {"pattern": "system.**"})
        res = d.state_unsubscribe("system.**")
        assert res["success"] is True and res["pattern"] == "system.**"
        assert not any(i["command"] == "state.subscribe" for i in d.export_subscriptions())

    def test_unwatch_purges_lingering_intents_when_loop_lost(self) -> None:
        # F2 (б): полу-durable watch (намерения есть, контур потерян при реконнекте без
        # resume) → unwatch ВСЁ РАВНО чистит реестр, профиль не воскресает.
        d = BackendDriver()
        d._subscriptions.add("observability.tail.subscribe", "camera_0", {"subscriber": "backend_ctl"})
        d._subscriptions.add("state.subscribe", "ProcessManager", {"pattern": "processes.**"})
        assert d._watch._watch_active is False
        summary = d.unwatch()
        assert summary["was_active"] is False
        assert not any(i["command"] == "observability.tail.subscribe" for i in d.export_subscriptions())
        assert not any(i["command"] == "state.subscribe" for i in d.export_subscriptions())


class TestObservabilityContract:
    """F7: строка-контракт driver'а совпадает с серверным message-слоем."""

    def test_record_command_matches_forward_channel(self) -> None:
        # driver держит OBSERVABILITY_RECORD_COMMAND строкой (Dict at Boundary, не тянет
        # серверный модуль). Контракт-тест пиннит равенство серверному FORWARD_COMMAND —
        # рассинхрон строки молча оборвал бы приём observability.record.
        from backend_ctl.driver import OBSERVABILITY_RECORD_COMMAND
        from multiprocess_framework.modules.channel_routing_module.observability import FORWARD_COMMAND

        assert OBSERVABILITY_RECORD_COMMAND == FORWARD_COMMAND


class TestWatchSelfSkip:
    """F7: watch_like_gui не тейлит собственный процесс driver'а (убирает шум сводки)."""

    def test_own_process_excluded_from_obs_tail(self, monkeypatch) -> None:
        d = BackendDriver()  # self._sender == "backend_ctl"
        calls: List[tuple] = []

        def fake_send(target, command, args=None, *, timeout=None):
            calls.append((target, command, args))
            if command == "state.get_subtree":
                # Топология содержит сам driver'ский адрес + gui + рабочий процесс.
                return {"success": True, "result": {"subtree": {p: {} for p in ("backend_ctl", "gui", "camera_0")}}}
            return {"success": True}

        monkeypatch.setattr(d, "send_command", fake_send)
        try:
            summary = d.watch_like_gui()
            obs = [t for t, c, _ in calls if c == "observability.tail.subscribe"]
            assert "backend_ctl" not in obs, "собственный процесс driver'а не тейлится"
            assert "gui" in obs and "camera_0" in obs  # gui driver тейлить МОЖЕТ (оставлен)
            assert "backend_ctl" not in summary["observability"]
        finally:
            d.unwatch()


# --- Юнит: локальный telemetry read-model (Task 2.3, 0 IPC) ---


def _delta(path: str, new_value: Any, old_value: Any = None) -> Dict[str, Any]:
    """Дельта в проводной форме Delta.to_dict() (new_value=='__MISSING__' → удаление)."""
    return {
        "path": path,
        "old_value": old_value,
        "new_value": new_value,
        "source": "test",
        "timestamp": 0.0,
        "transaction_id": "t",
        "revision": 0,
    }


def _state_changed(*deltas: Dict[str, Any]) -> bytes:
    return _line({"command": "state.changed", "data": {"deltas": list(deltas)}})


class TestTelemetryReadModel:
    def test_ingest_populates_snapshot(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(_state_changed(_delta("processes.cam.state.fps", 25.0)))
        snap = d.telemetry_snapshot()
        assert snap["success"] is True
        assert snap["count"] == 1
        assert snap["metrics"]["processes.cam.state.fps"]["value"] == 25.0

    def test_snapshot_filters_by_process(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(
            _state_changed(
                _delta("processes.cam.state.fps", 25.0),
                _delta("processes.cam2.state.fps", 9.0),
            )
        )
        snap = d.telemetry_snapshot(process="cam")
        assert set(snap["metrics"]) == {"processes.cam.state.fps"}  # cam2 не течёт

    def test_snapshot_filters_by_metric_suffix_boundary(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(
            _state_changed(
                _delta("processes.cam.state.fps", 25.0),
                _delta("processes.cam.state.max_fps", 60.0),  # не должен матчить metric="fps"
            )
        )
        snap = d.telemetry_snapshot(metric="fps")
        assert set(snap["metrics"]) == {"processes.cam.state.fps"}

    def test_snapshot_correlation_key_process_worker(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(_state_changed(_delta("processes.cam.workers.w0.effective_hz", 12.0)))
        entry = d.telemetry_snapshot()["metrics"]["processes.cam.workers.w0.effective_hz"]
        assert entry["process"] == "cam"
        assert entry["worker"] == "w0"

    def test_deleted_delta_removes_path(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(_state_changed(_delta("processes.cam.state.fps", 25.0)))
        d.dispatch_raw(_state_changed(_delta("processes.cam.state.fps", "__MISSING__", old_value=25.0)))
        assert d.telemetry_snapshot()["count"] == 0

    def test_history_tracked_metric(self) -> None:
        d = BackendDriver()
        for v in (10.0, 20.0, 30.0):
            d.dispatch_raw(_state_changed(_delta("processes.cam.state.fps", v)))
        hist = d.telemetry_history("processes.cam.state.fps")
        assert hist["success"] is True
        assert [val for _ts, val in hist["points"]] == [10.0, 20.0, 30.0]
        assert hist["process"] == "cam"

    def test_history_limit_returns_last_n(self) -> None:
        d = BackendDriver()
        for v in range(5):
            d.dispatch_raw(_state_changed(_delta("processes.cam.state.fps", float(v))))
        hist = d.telemetry_history("processes.cam.state.fps", limit=2)
        assert [val for _ts, val in hist["points"]] == [3.0, 4.0]

    def test_history_limit_zero_returns_empty(self) -> None:
        """limit=0 → пусто («последние 0 точек»), НЕ весь буфер (регресс points[-0:])."""
        d = BackendDriver()
        for v in range(3):
            d.dispatch_raw(_state_changed(_delta("processes.cam.state.fps", float(v))))
        assert d.telemetry_history("processes.cam.state.fps", limit=0)["count"] == 0

    def test_history_negative_limit_returns_empty(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(_state_changed(_delta("processes.cam.state.fps", 1.0)))
        assert d.telemetry_history("processes.cam.state.fps", limit=-1)["count"] == 0

    def test_missing_marker_matches_state_store(self) -> None:
        """Контракт: sentinel удаления в driver == приватный маркер state_store (дрейф → фейл)."""
        from multiprocess_framework.modules.state_store_module.core.delta import _MISSING_MARKER

        assert BackendDriver._MISSING_MARKER == _MISSING_MARKER

    def test_history_untracked_metric_empty(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(_state_changed(_delta("processes.cam.state.status", "running")))
        assert d.telemetry_history("processes.cam.state.status")["count"] == 0

    def test_empty_read_model_is_not_error(self) -> None:
        d = BackendDriver()
        snap = d.telemetry_snapshot()
        assert snap["success"] is True and snap["count"] == 0

    def test_non_state_changed_events_ignored(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(_line({"command": "log.record", "data": {"record": {"x": 1}}}))
        assert d.telemetry_snapshot()["count"] == 0

    def test_snapshot_read_does_not_drain_event_queue(self) -> None:
        """Чтение read-model локально — событийный канал (events_page) не трогается."""
        d = BackendDriver()
        d.dispatch_raw(_state_changed(_delta("processes.cam.state.fps", 25.0)))
        _ = d.telemetry_snapshot()
        # событие state.changed по-прежнему доступно потребителю events_page
        evts, _ = _page(d, None)
        assert any(e.get("command") == "state.changed" for e in evts)


class TestSupervisionStatus:
    """D.1b: supervision_status(process?) шлёт supervision.status в ProcessManager."""

    def test_sends_supervision_status_command(self, monkeypatch) -> None:
        d = BackendDriver()
        calls: List[tuple] = []

        def fake_send(target, command, args=None, *, timeout=None):
            calls.append((target, command, args))
            return {"success": True, "epoch": 5, "processes": {}}

        monkeypatch.setattr(d, "send_command", fake_send)
        res = d.supervision_status()
        assert calls == [("ProcessManager", "supervision.status", {})]
        assert res["epoch"] == 5

    def test_filters_by_process(self, monkeypatch) -> None:
        d = BackendDriver()
        calls: List[tuple] = []

        def fake_send(target, command, args=None, *, timeout=None):
            calls.append((target, command, args))
            return {"success": True}

        monkeypatch.setattr(d, "send_command", fake_send)
        d.supervision_status("camera")
        assert calls == [("ProcessManager", "supervision.status", {"process": "camera"})]


class TestImportRetargetsSubscriber:
    """Ревью-фикс #1: import пере-нацеливает свой subscriber на текущую сессию, чтобы
    ключ durable-намарения совпадал с ним и последующий untail реально снимал его
    (иначе снятая подписка воскресала бы на следующем реконнекте)."""

    def test_import_retargets_own_subscriber_so_untail_matches(self) -> None:
        d = BackendDriver()
        d._subscriber = "backend_ctl.NEW"  # как после connect новой сессии
        d.import_subscriptions(
            [{"command": "observability.tail.subscribe", "target": "cam", "args": {"subscriber": "backend_ctl.OLD"}}]
        )
        # Намерение хранится под ТЕКУЩИМ subscriber.
        assert d.export_subscriptions()[0]["args"]["subscriber"] == "backend_ctl.NEW"
        # Untail по текущему subscriber снимает намерение (не воскресает).
        d._subscriptions.remove("observability.tail.subscribe", "cam", {"subscriber": "backend_ctl.NEW"})
        assert d.export_subscriptions() == []

    def test_import_retargets_plain_sender_subscriber(self) -> None:
        d = BackendDriver()
        d._subscriber = "backend_ctl.NEW"
        d.import_subscriptions(
            [{"command": "log.tail.subscribe", "target": "cam", "args": {"subscriber": "backend_ctl", "level": "info"}}]
        )
        exported = d.export_subscriptions()[0]
        assert exported["args"]["subscriber"] == "backend_ctl.NEW"
        assert exported["args"]["level"] == "info"  # прочие args сохранены

    def test_import_leaves_foreign_subscriber_untouched(self) -> None:
        d = BackendDriver()
        d._subscriber = "backend_ctl.NEW"
        d.import_subscriptions(
            [{"command": "observability.tail.subscribe", "target": "cam", "args": {"subscriber": "watcher"}}]
        )
        assert d.export_subscriptions()[0]["args"]["subscriber"] == "watcher"


# --- Юнит: snapshot/restore + commit-confirmed регистры (D.5) ---


class TestRegisterSnapshotRestore:
    """Снимок регистров → правки → restore возвращает исходное (D.5)."""

    @staticmethod
    def _driver_with_fake_backend(registers: Dict[str, Any], monkeypatch) -> BackendDriver:
        d = BackendDriver()

        def fake_send(process, command, args=None, **kw):
            if command == "register_update":
                reg = registers.setdefault(args["register"], {})
                if args["field"] in reg:  # реальный бэкенд: неизвестное поле = no-op
                    reg[args["field"]] = args["value"]
                return {"success": True}
            if command == "introspect.registers":
                return {"success": True, "process": process, "registers": registers}
            raise AssertionError(f"неожиданная команда: {command}")

        monkeypatch.setattr(d, "send_command", fake_send)
        return d

    def test_series_of_edits_then_restore_returns_original(self, monkeypatch) -> None:
        regs = {"resize": {"target_width": 640, "target_height": 480}}
        d = self._driver_with_fake_backend(regs, monkeypatch)
        snap = d.register_snapshot("preprocessor")

        d.set_register("preprocessor", "resize", "target_width", 100)
        d.set_register("preprocessor", "resize", "target_height", 50)
        assert regs["resize"] == {"target_width": 100, "target_height": 50}

        res = d.register_restore(snap)
        assert res["success"] is True
        assert res["written"] == 2
        assert res["verified"] == 2
        assert res["mismatches"] == []
        assert regs["resize"] == {"target_width": 640, "target_height": 480}

    def test_snapshot_is_detached_deep_copy(self, monkeypatch) -> None:
        regs = {"resize": {"target_width": 640}}
        d = self._driver_with_fake_backend(regs, monkeypatch)
        snap = d.register_snapshot("preprocessor")
        d.set_register("preprocessor", "resize", "target_width", 1)
        # снимок не изменился вслед за живым бэкендом
        assert snap["processes"]["preprocessor"]["resize"]["target_width"] == 640

    def test_snapshot_uniform_shape(self, monkeypatch) -> None:
        regs = {"resize": {"target_width": 640}}
        d = self._driver_with_fake_backend(regs, monkeypatch)
        snap = d.register_snapshot("preprocessor")
        assert snap == {"processes": {"preprocessor": {"resize": {"target_width": 640}}}}

    def test_restore_reports_mismatch_when_field_absent(self, monkeypatch) -> None:
        regs = {"resize": {"target_width": 640}}
        d = self._driver_with_fake_backend(regs, monkeypatch)
        # снимок ссылается на несуществующее поле — restore не сможет записать (no-op)
        bogus = {"processes": {"preprocessor": {"resize": {"phantom": 7}}}}
        res = d.register_restore(bogus)
        assert res["success"] is False
        assert res["mismatches"] == [
            {"process": "preprocessor", "register": "resize", "field": "phantom", "expected": 7, "actual": None}
        ]

    def test_restore_rejects_malformed_snapshot(self, monkeypatch) -> None:
        d = self._driver_with_fake_backend({"resize": {"target_width": 1}}, monkeypatch)
        res = d.register_restore({"nope": {}})
        assert res["success"] is False
        assert "processes" in res["error"]

    def test_snapshot_all_processes_via_topology_no_fanout(self, monkeypatch) -> None:
        """process опущен → список процессов одним introspect.capabilities PM (без per-process fan-out, #6)."""
        regs = {"ProcessManager": {}, "p1": {"resize": {"w": 1}}, "p2": {"crop": {"x": 2}}}
        d = BackendDriver()
        cap_calls: List[str] = []

        def fake_send(process, command, args=None, **kw):
            if command == "introspect.capabilities":
                cap_calls.append(process)
                return {"success": True, "processes": {"p1": {}, "p2": {}}}
            if command == "introspect.registers":
                return {"success": True, "registers": regs[process]}
            raise AssertionError(f"неожиданная команда: {command}")

        monkeypatch.setattr(d, "send_command", fake_send)
        snap = d.register_snapshot()  # process опущен → все процессы
        assert snap == {"processes": {"ProcessManager": {}, "p1": {"resize": {"w": 1}}, "p2": {"crop": {"x": 2}}}}
        assert cap_calls == ["ProcessManager"]  # только карточка PM, НЕ каждого процесса

    def test_restore_skips_unchanged_fields(self, monkeypatch) -> None:
        """restore пишет только дрейфнувшие поля — уже-верные не трогает (#2)."""
        regs = {"resize": {"a": 1, "b": 2}}
        d = self._driver_with_fake_backend(regs, monkeypatch)
        snap = d.register_snapshot("preprocessor")
        d.set_register("preprocessor", "resize", "b", 9)  # дрейфнуло только b

        writes: List[tuple] = []
        orig = d.send_command

        def recording_send(process, command, args=None, **kw):
            if command == "register_update":
                writes.append((args["register"], args["field"], args["value"]))
            return orig(process, command, args, **kw)

        monkeypatch.setattr(d, "send_command", recording_send)
        res = d.register_restore(snap)
        assert res["success"] is True
        assert res["written"] == 1 and res["skipped"] == 1
        assert writes == [("resize", "b", 2)]  # a (уже верное) не переписывалось
        assert regs["resize"] == {"a": 1, "b": 2}


class TestRegisterCommitConfirmed:
    """set_register(confirm_within=N): подтверждение снимает откат, молчание — откатывает (D.5)."""

    @staticmethod
    def _driver_with_fake_backend(registers: Dict[str, Any], monkeypatch, *, write_ok: bool = True) -> BackendDriver:
        d = BackendDriver()

        def fake_send(process, command, args=None, **kw):
            if command == "register_update":
                if not write_ok:
                    return {"success": False, "error": "нет приёмника"}
                reg = registers.setdefault(args["register"], {})
                if args["field"] in reg:
                    reg[args["field"]] = args["value"]
                return {"success": True}
            if command == "introspect.registers":
                return {"success": True, "process": process, "registers": registers}
            raise AssertionError(f"неожиданная команда: {command}")

        monkeypatch.setattr(d, "send_command", fake_send)
        return d

    def test_confirm_cancels_rollback(self, monkeypatch) -> None:
        regs = {"resize": {"target_width": 640}}
        d = self._driver_with_fake_backend(regs, monkeypatch)
        res = d.set_register("preprocessor", "resize", "target_width", 100, confirm_within=0.2)
        assert res["pending"] is True and res["success"] is True
        assert res["pre_value"] == 640 and res["had_field"] is True
        assert res["verified"] is True and res["session_scoped"] is True
        assert regs["resize"]["target_width"] == 100

        conf = d.register_confirm(res["commit_id"])
        assert conf["success"] is True
        time.sleep(0.35)  # окно, в котором таймер бы сработал, если бы не был снят
        assert regs["resize"]["target_width"] == 100  # подтверждено — не откатилось

    def test_confirm_twice_is_unknown(self, monkeypatch) -> None:
        regs = {"resize": {"target_width": 640}}
        d = self._driver_with_fake_backend(regs, monkeypatch)
        res = d.set_register("preprocessor", "resize", "target_width", 100, confirm_within=5.0)
        assert d.register_confirm(res["commit_id"])["success"] is True
        again = d.register_confirm(res["commit_id"])
        assert again["success"] is False
        assert again["known"] == []

    def test_auto_rollback_without_confirm(self, monkeypatch) -> None:
        regs = {"resize": {"target_width": 640}}
        d = self._driver_with_fake_backend(regs, monkeypatch)
        res = d.set_register("preprocessor", "resize", "target_width", 100, confirm_within=0.15)
        assert regs["resize"]["target_width"] == 100  # запись применилась
        time.sleep(0.4)  # даём таймеру сработать
        assert regs["resize"]["target_width"] == 640  # авто-откат к pre-image
        # запись больше не ожидает подтверждения
        assert d.register_confirm(res["commit_id"])["success"] is False

    def test_failed_write_does_not_arm_timer(self, monkeypatch) -> None:
        regs = {"resize": {"target_width": 640}}
        d = self._driver_with_fake_backend(regs, monkeypatch, write_ok=False)
        res = d.set_register("preprocessor", "resize", "target_width", 100, confirm_within=0.15)
        assert res["success"] is False and res["pending"] is False
        assert "commit_id" not in res
        assert d._pending_commits == {}

    def test_silent_noop_field_does_not_arm_timer(self, monkeypatch) -> None:
        """Опечатка в имени поля: ack ok, но readback не находит поле → не армируем (ложная уверенность)."""
        regs = {"resize": {"target_width": 640}}
        d = self._driver_with_fake_backend(regs, monkeypatch)
        # поле "width" не существует — register_update молча no-op, ack=success
        res = d.set_register("preprocessor", "resize", "width", 100, confirm_within=0.15)
        assert res["success"] is False and res["pending"] is False
        assert res["verified"] is False
        assert "commit_id" not in res
        assert d._pending_commits == {}
        time.sleep(0.25)  # таймера нет — ничего не происходит
        assert d._pending_commits == {}

    def test_close_cancels_pending_rollback(self, monkeypatch) -> None:
        regs = {"resize": {"target_width": 640}}
        d = self._driver_with_fake_backend(regs, monkeypatch)
        d.set_register("preprocessor", "resize", "target_width", 100, confirm_within=0.15)
        d.close()  # driver уходит — таймеры сняты, откат по мёртвому сокету не бьёт
        assert d._pending_commits == {}
        time.sleep(0.4)
        assert regs["resize"]["target_width"] == 100  # не откатилось: таймер снят в close()

    def test_successful_rollback_recorded_in_journal(self, monkeypatch) -> None:
        regs = {"resize": {"target_width": 640}}
        d = self._driver_with_fake_backend(regs, monkeypatch)
        res = d.set_register("preprocessor", "resize", "target_width", 100, confirm_within=0.15)
        time.sleep(0.4)  # таймер сработал → откат к 640
        log = d.register_rollback_log()
        assert log["entries"][-1]["commit_id"] == res["commit_id"]
        assert log["entries"][-1]["outcome"] == "ok"

    def test_failed_rollback_surfaced(self, monkeypatch) -> None:
        """Провал авто-отката фиксируется в журнале и виден 'опоздавшему' register_confirm (#4)."""
        regs = {"resize": {"target_width": 640}}
        d = BackendDriver()

        def fake_send(process, command, args=None, **kw):
            if command == "register_update":
                if args["value"] == 640:  # это откат к pre-image — имитируем отказ бэкенда
                    return {"success": False, "error": "backend rejected"}
                reg = regs.setdefault(args["register"], {})
                if args["field"] in reg:
                    reg[args["field"]] = args["value"]
                return {"success": True}
            if command == "introspect.registers":
                return {"success": True, "registers": regs}
            raise AssertionError(f"неожиданная команда: {command}")

        monkeypatch.setattr(d, "send_command", fake_send)
        res = d.set_register("preprocessor", "resize", "target_width", 100, confirm_within=0.15)
        time.sleep(0.4)  # таймер сработал → откат провалился (backend rejected)
        assert regs["resize"]["target_width"] == 100  # не откатилось

        log = d.register_rollback_log(limit=1)
        assert log["entries"][-1]["outcome"] == "failed"
        assert log["entries"][-1]["commit_id"] == res["commit_id"]
        # «опоздавший» confirm узнаёт исход из журнала
        conf = d.register_confirm(res["commit_id"])
        assert conf["success"] is False
        assert conf["rolled_back"]["outcome"] == "failed"
