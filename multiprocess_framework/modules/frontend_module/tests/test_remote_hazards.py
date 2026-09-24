# -*- coding: utf-8 -*-
"""Авторские hazard-тесты ``RemoteCommandSender`` / ``RemoteStateProxy`` (Task 1.2 GREEN).

* Fence: внешний Пульт хосту не известен (его не запускал супервизор) — штамп всё
  равно обязан стоять, с ``inc=0`` и эпохой хоста (решение лида): без него Пульт теряет
  паритет структуры с встроенным GUI. Неудачный refresh — без штампа (F1).
* Реконнект меняет ``session`` → адрес push-получателя. Подписки, зарегистрированные
  на хосте под СТАРЫМ адресом, новому сокету не доставляются: ``on_reconnected`` обязан
  переподписать каждый уникальный паттерн ПОД НОВЫМ адресом, иначе виджеты молча
  замирают после первого же обрыва.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from multiprocess_framework.modules.frontend_module.bridge.remote_command_sender import (
    RemoteCommandSender,
)
from multiprocess_framework.modules.frontend_module.bridge.remote_state_proxy import RemoteStateProxy
from multiprocess_framework.modules.router_module.channels.socket_client import SocketClient
from multiprocess_framework.modules.state_store_module.core.delta import Delta
from multiprocess_framework.modules.router_module.tests.test_socket_client_hazards import (
    _FakeHost,
    _wait,
)


def _reply(result: Dict[str, Any]):
    def _responder(msg: Dict[str, Any]) -> Dict[str, Any]:
        return {"type": "response", "request_id": msg["request_id"], "result": {"success": True, "result": result}}

    return _responder


def _client(host: _FakeHost) -> SocketClient:
    client = SocketClient("127.0.0.1", host.port, sender="gui")
    client.connect()
    assert host.accepted.wait(2.0)
    return client


def _last(host: _FakeHost, command: str) -> Dict[str, Any]:
    assert _wait(lambda: any(m.get("command") == command for m in host.received)), f"{command} не дошёл"
    return [m for m in host.received if m.get("command") == command][-1]


def test_unknown_sender_is_stamped_with_inc_zero_and_host_epoch() -> None:
    """Хост не знает имя Пульта → штамп {sender, inc: 0, epoch: <эпоха хоста>}."""
    host = _FakeHost(responder=_reply({"epoch": 9, "processes": {"camera_0": {"incarnation": 4}}}))
    try:
        client = _client(host)
        sender = RemoteCommandSender(client, name="pult")
        sender.refresh_fence()
        client.send_nowait({"type": "command", "command": "noop"})
        assert _last(host, "noop").get("_fence") == {"sender": "pult", "inc": 0, "epoch": 9}
    finally:
        host.close()


def test_failed_refresh_sends_no_stamp() -> None:
    """Отказ supervision.status → (None, None): сообщение уходит без _fence (F1, явно)."""
    host = _FakeHost(
        responder=lambda m: {
            "type": "response",
            "request_id": m["request_id"],
            "result": {"success": False, "error": "x"},
        }
    )
    try:
        client = _client(host)
        sender = RemoteCommandSender(client, name="pult")
        sender.refresh_fence()
        client.send_nowait({"type": "command", "command": "noop"})
        assert "_fence" not in _last(host, "noop")
    finally:
        host.close()


def test_on_reconnected_resubscribes_every_pattern_at_new_address() -> None:
    """После реконнекта: state.subscribe на КАЖДЫЙ уникальный паттерн под новым адресом."""
    host = _FakeHost(responder=_reply({"sub_id": "srv", "snapshot": {}}))
    try:
        client = _client(host)
        proxy = RemoteStateProxy(client, dispatch=lambda fn: fn())
        proxy.subscribe("a.*", lambda d: None, sync=False)
        proxy.subscribe("b.*", lambda d: None, sync=False)
        proxy.subscribe("a.*", lambda d: None, sync=False)  # дубль паттерна
        old = client.subscriber_address

        client.close()
        client.connect()
        new = client.subscriber_address
        assert new != old
        before = len(host.received)
        proxy.on_reconnected()

        resub = [m for m in host.received[before:] if m.get("command") == "state.subscribe"]
        assert sorted(m["data"]["pattern"] for m in resub) == ["a.*", "b.*"]
        assert all(m["data"]["subscriber"] == new and m["sender"] == new for m in resub)
        assert proxy.process_name == new
    finally:
        host.close()


def test_on_reconnected_without_subscriptions_sends_nothing() -> None:
    """Без активных подписок — только смена имени, ни одного сетевого вызова."""
    host = _FakeHost(responder=_reply({}))
    try:
        client = _client(host)
        proxy = RemoteStateProxy(client, dispatch=lambda fn: fn())
        client.close()
        client.connect()
        before = len(host.received)
        proxy.on_reconnected()
        assert proxy.process_name == client.subscriber_address
        assert host.received[before:] == []
    finally:
        host.close()


def test_other_push_commands_are_ignored_by_proxy() -> None:
    """S3: push не-state.changed прокси не трогает (клиент делят несколько потребителей)."""
    host = _FakeHost()
    try:
        client = _client(host)
        got: List[Any] = []
        proxy = RemoteStateProxy(client, dispatch=lambda fn: fn())
        proxy.subscribe("a.*", got.append, sync=False)
        host.push(
            {
                "command": "telemetry.snapshot",
                "data": {"deltas": [Delta("a.b", old_value=None, new_value=1, source="host").to_dict()]},
            }
        )
        host.push(
            {
                "command": "state.changed",
                "data": {"deltas": [Delta("a.c", old_value=None, new_value=2, source="host").to_dict()]},
            }
        )
        assert _wait(lambda: len(got) == 1)
        assert [d.path for d in got[0]] == ["a.c"]
    finally:
        host.close()


def _counting_subscribe_host() -> _FakeHost:
    """Хост, выдающий на каждый state.subscribe новый серверный sub_id: srv-1, srv-2, ..."""
    counter = {"n": 0}

    def _responder(msg: Dict[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {"status": "ok"}
        if msg.get("command") == "state.subscribe":
            counter["n"] += 1
            result["sub_id"] = f"srv-{counter['n']}"
        return {"type": "response", "request_id": msg["request_id"], "result": {"success": True, "result": result}}

    return _FakeHost(responder=_responder)


def _unsubs(host: _FakeHost, since: int) -> List[str]:
    return [m["data"]["sub_id"] for m in host.received[since:] if m.get("command") == "state.unsubscribe"]


def test_unsubscribe_after_reconnect_sends_new_server_sub_id() -> None:
    """После реконнекта unsubscribe шлёт sub_id НОВОГО соединения, и только за последнюю
    локальную подписку пары (pattern, exclude_self) — до неё серверная ещё нужна."""
    host = _counting_subscribe_host()
    try:
        client = _client(host)
        proxy = RemoteStateProxy(client, dispatch=lambda fn: fn())
        first = proxy.subscribe("a.*", lambda d: None, sync=True)  # серверный srv-1
        second = proxy.subscribe("a.*", lambda d: None, sync=True)  # srv-2
        assert (first, second) == ("srv-1", "srv-2")

        client.close()
        client.connect()
        proxy.on_reconnected()  # одна подписка на пару ("a.*", True) → srv-3
        _wait(lambda: len(host.received) >= 3)

        mark = len(host.received)
        proxy.unsubscribe(first)
        proxy.unsubscribe(second)
        assert _wait(lambda: _unsubs(host, mark)), "state.unsubscribe не дошёл"
        time.sleep(0.1)
        assert _unsubs(host, mark) == ["srv-3"], "ушёл старый id или отписка до последней подписки"
    finally:
        host.close()


def test_resubscribe_keeps_exclude_self() -> None:
    """exclude_self каждой подписки сохраняется при переподписке после реконнекта."""
    host = _counting_subscribe_host()
    try:
        client = _client(host)
        proxy = RemoteStateProxy(client, dispatch=lambda fn: fn())
        proxy.subscribe("mine.*", lambda d: None, exclude_self=False, sync=False)
        proxy.subscribe("theirs.*", lambda d: None, exclude_self=True, sync=False)

        client.close()
        client.connect()
        new = client.subscriber_address
        mark = len(host.received)
        proxy.on_reconnected()

        resub = {
            m["data"]["pattern"]: m["data"]["exclude_sources"]
            for m in host.received[mark:]
            if m.get("command") == "state.subscribe"
        }
        assert resub == {"mine.*": [], "theirs.*": [new]}
    finally:
        host.close()


def test_failed_refresh_after_success_drops_old_stamp() -> None:
    """F1: успешный refresh, затем неудачный — следующее исходящее уходит БЕЗ _fence,
    старая пара (inc=3, epoch=7) не штампуется."""
    ok = {"value": True}

    def _responder(msg: Dict[str, Any]) -> Dict[str, Any]:
        if msg.get("command") == "supervision.status" and ok["value"]:
            result: Dict[str, Any] = {
                "success": True,
                "result": {"epoch": 7, "processes": {"pult": {"incarnation": 3}}},
            }
        elif msg.get("command") == "supervision.status":
            result = {"success": False, "error": "supervisor down"}
        else:
            result = {"success": True, "result": {}}
        return {"type": "response", "request_id": msg["request_id"], "result": result}

    host = _FakeHost(responder=_responder)
    try:
        client = _client(host)
        sender = RemoteCommandSender(client, name="pult")
        sender.refresh_fence()
        client.send_nowait({"type": "command", "command": "first"})
        assert _last(host, "first").get("_fence") == {"sender": "pult", "inc": 3, "epoch": 7}

        ok["value"] = False
        sender.refresh_fence()
        client.send_nowait({"type": "command", "command": "second"})
        assert "_fence" not in _last(host, "second"), "старая пара пережила неудачный refresh (F1)"
    finally:
        host.close()


def _status_host(epoch: Dict[str, int]) -> _FakeHost:
    def _responder(msg: Dict[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if msg.get("command") == "supervision.status":
            v = epoch["v"]
            result = {"epoch": v, "processes": {"pult": {"incarnation": v}, "pult2": {"incarnation": 10 + v}}}
        return {"type": "response", "request_id": msg["request_id"], "result": {"success": True, "result": result}}

    return _FakeHost(responder=_responder)


def test_fence_is_bound_to_session_until_refresh() -> None:
    """Ревью [b]: после connect() (новый session) старая пара не штампуется, пока не
    пройдёт refresh_fence на новом соединении."""
    epoch = {"v": 1}
    host = _status_host(epoch)
    try:
        client = _client(host)
        sender = RemoteCommandSender(client, name="pult")
        sender.refresh_fence()
        client.close()
        epoch["v"] = 2
        client.connect()
        sender.send_command("ProcessManager", "before.refresh", {})
        assert "_fence" not in _last(host, "before.refresh"), "стейл-пара прошлого соединения"
        sender.refresh_fence()
        sender.send_command("ProcessManager", "after.refresh", {})
        assert _last(host, "after.refresh").get("_fence") == {"sender": "pult", "inc": 2, "epoch": 2}
    finally:
        host.close()


def test_two_senders_on_one_client_keep_own_stamps() -> None:
    """Ревью [c] / F2: у каждого отправителя на проводе — свой штамп."""
    host = _status_host({"v": 1})
    try:
        client = _client(host)
        s1 = RemoteCommandSender(client, name="pult")
        s2 = RemoteCommandSender(client, name="pult2")
        s1.refresh_fence()
        s2.refresh_fence()
        s1.send_command("ProcessManager", "from.pult", {})
        s2.send_command("ProcessManager", "from.pult2", {})
        assert _last(host, "from.pult").get("_fence") == {"sender": "pult", "inc": 1, "epoch": 1}
        assert _last(host, "from.pult2").get("_fence") == {"sender": "pult2", "inc": 11, "epoch": 1}
    finally:
        host.close()
