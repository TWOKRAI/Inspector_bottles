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

import json
import threading
import time
from typing import Any, Dict, List

import pytest

from backend_ctl.driver import BackendDriver
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


def _line(msg: Dict[str, Any]) -> bytes:
    """Собрать проводную строку так же, как её видит reader-поток."""
    return json.dumps(msg, ensure_ascii=False).encode("utf-8")


class TestEventChannel:
    def test_push_without_request_id_goes_to_queue(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(_line({"command": "state.changed", "data": {"deltas": [1]}}))
        evts = d.events()  # поллинг
        assert len(evts) == 1
        assert evts[0]["command"] == "state.changed"
        assert d.events() == []  # очередь опустошена (drain)

    def test_unmatched_request_id_becomes_event(self) -> None:
        """Ответ с request_id, который никто не ждёт (поздний/чужой), → событие."""
        d = BackendDriver()
        d.dispatch_raw(_line({"request_id": "no-such-id", "result": {"x": 1}}))
        evts = d.events()
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
        # Второй подписчик отработал, событие всё равно в очереди, счётчик вырос.
        assert len(seen) == 1
        assert len(d.events()) == 1
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
        evts = d.events()
        assert [e["seq"] for e in evts] == [2, 3, 4]  # старые (0,1) вытеснены

    def test_events_max_items_leaves_remainder(self) -> None:
        d = BackendDriver()
        for i in range(4):
            d.dispatch_raw(_line({"seq": i}))
        first = d.events(max_items=2)
        assert [e["seq"] for e in first] == [0, 1]
        rest = d.events()
        assert [e["seq"] for e in rest] == [2, 3]

    def test_events_polling_returns_empty(self) -> None:
        d = BackendDriver()
        t0 = time.monotonic()
        assert d.events() == []  # timeout=0.0 не блокирует
        assert time.monotonic() - t0 < 0.5

    def test_events_blocks_until_event_arrives(self) -> None:
        """Клиентский поток ждёт в events(timeout), reader-«поток» кладёт событие."""
        d = BackendDriver()

        def producer() -> None:
            time.sleep(0.05)
            d.dispatch_raw(_line({"command": "state.changed", "late": True}))

        th = threading.Thread(target=producer)
        th.start()
        evts = d.events(timeout=2.0)  # блокируется до появления
        th.join()
        assert len(evts) == 1
        assert evts[0]["late"] is True

    def test_events_timeout_returns_empty_when_silent(self) -> None:
        d = BackendDriver()
        t0 = time.monotonic()
        evts = d.events(timeout=0.1)
        dt = time.monotonic() - t0
        assert evts == []
        assert 0.05 < dt < 1.0  # действительно ждал ~timeout, не вечно

    def test_malformed_line_ignored(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(b"{not json")
        d.dispatch_raw(_line(["not", "a", "dict"]))
        assert d.events() == []


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
        assert sent["data"]["subscriber"] == "backend_ctl"  # = self.sender

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
        evts = driver.events(timeout=2.0)
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
        evts = driver.events(timeout=1.0)
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


# --- Юнит: debug_session — вся отладочная плоскость одним вызовом ---


class TestDebugSession:
    @staticmethod
    def _driver_with_recorder(monkeypatch) -> tuple[BackendDriver, List[tuple]]:
        d = BackendDriver()
        calls: List[tuple] = []

        def fake_send(process, command, args=None, **kw):
            calls.append((process, command, args))
            if command == "state.get_subtree":
                return {"success": True, "result": {"subtree": {"gui": {}, "preprocessor": {}}}}
            return {"success": True}

        monkeypatch.setattr(d, "send_command", fake_send)
        return d, calls

    def test_enables_ui_logs_state_in_one_call(self, monkeypatch) -> None:
        d, calls = self._driver_with_recorder(monkeypatch)
        res = d.debug_session(logs_level="ERROR")
        cmds = [(p, c) for p, c, _ in calls]
        assert ("gui", "ui.tap.subscribe") in cmds
        # log_tail на все процессы из state-топологии
        assert ("gui", "log.tail.subscribe") in cmds
        assert ("preprocessor", "log.tail.subscribe") in cmds
        assert ("ProcessManager", "state.subscribe") in cmds
        assert res["success"] is True
        assert set(res["logs"]) == {"gui", "preprocessor"}

    def test_explicit_process_list_skips_topology_query(self, monkeypatch) -> None:
        d, calls = self._driver_with_recorder(monkeypatch)
        d.debug_session(log_processes=["camera_0"])
        cmds = [(p, c) for p, c, _ in calls]
        assert ("camera_0", "log.tail.subscribe") in cmds
        assert ("ProcessManager", "state.get_subtree") not in cmds

    def test_debug_stop_untaps_everything(self, monkeypatch) -> None:
        d, calls = self._driver_with_recorder(monkeypatch)
        d.debug_stop(log_processes=["gui", "preprocessor"])
        cmds = [(p, c) for p, c, _ in calls]
        assert ("gui", "ui.tap.unsubscribe") in cmds
        assert ("gui", "log.tail.unsubscribe") in cmds
        assert ("preprocessor", "log.tail.unsubscribe") in cmds


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
        assert d.events() == [], "поздний ответ не должен всплывать событием"
        assert d.late_replies == 1

    def test_unquarantined_request_id_still_becomes_event(self) -> None:
        # Регресс-контроль: cid, который НЕ таймаутили, по-прежнему → событие.
        d = BackendDriver()
        d.dispatch_raw(_line({"request_id": "never-issued", "result": {"x": 1}}))
        assert len(d.events()) == 1
        assert d.late_replies == 0


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

    def test_untail_removes_intent(self, monkeypatch) -> None:
        d, calls = self._recorder(monkeypatch)
        d.observability_tail("preprocessor")
        d.observability_untail("preprocessor")
        # На проводе unsubscribe без параметров (NoParams-контракт).
        assert ("preprocessor", "observability.tail.unsubscribe", {}) in calls
        assert not any(i["command"] == "observability.tail.subscribe" for i in d.export_subscriptions())

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

    def test_none_events_drains_channel(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(_line(_obs_event(records=[_obs_record("stats")])))
        recs = d.observability_records()  # events=None → дренирует events()
        assert [r["kind"] for r in recs] == ["stats"]
        assert d.events() == [], "канал должен быть осушён"

    def test_record_without_kind_excluded_by_filter(self) -> None:
        d = BackendDriver()
        rec = {"process": "p", "message": "no kind"}
        events = [_obs_event(record=rec)]
        # Без фильтра запись без kind отдаётся как есть (best-effort по доступным полям).
        assert d.observability_records(events) == [rec]
        # С фильтром сопоставить не с чем → исключается.
        assert d.observability_records(events, kind="log") == []
