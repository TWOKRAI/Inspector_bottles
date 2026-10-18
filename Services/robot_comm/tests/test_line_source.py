# -*- coding: utf-8 -*-
"""Тесты автора T3.8: опасные места ``LineLink`` / ``LineRobotState``, которые слепая приёмка
(``test_t38_line_view_acceptance.py``, настоящий хост) не покрывает.

Клиент и прокси здесь — макеты: нужны детерминированные порядок и время колбэков (синхронный
колбэк ``request_async``, ответы без успеха, отказ шага возврата связи). Живое соединение
проверяет слепой набор. Часы — фейковые, блокирующего кода нет (потоков тест не заводит).
Ожидаемые значения — литералы.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

import pytest

from multiprocess_framework.modules.router_module.channels.socket_client import SocketConnectionLost
from multiprocess_framework.modules.state_store_module.core.delta import MISSING
from Services.robot_comm.gui import line_source
from Services.robot_comm.gui.line_source import LINE_STATE_PATH, LineLink

_TLM_X = 0x1044
_BAD_MODEL_TEXT = "модель линии не поддерживается видом: нужна ScaraModel"


def _state(x_mm: float, model: str = "ScaraModel") -> dict:
    """Минимальный валидный снимок: нули, кроме ``TLM_X`` (сырое = x × 10)."""
    tlm = [0] * 32
    tlm[_TLM_X - 0x1040] = round(x_mm * 10) & 0xFFFF
    return {
        "pose": {"x_mm": x_mm, "y_mm": 0.0, "z_mm": 0.0, "rz_deg": 0.0},
        "moving": False,
        "hand": 0,
        "joints": None,
        "target": None,
        "model": model,
        "regs": {"res": [0] * 12, "tlm": tlm, "pmir": [0] * 128},
        "t": 5.0,
    }


def _ok(value: dict) -> dict:
    """Ответ клиента на ``state.get_subtree``: конверт хоста с ответом обработчика."""
    return {"success": True, "result": {"status": "ok", "value": value}}


class _FakeClient:
    """Макет ``SocketClient``: ровно то, что зовёт ``LineLink``."""

    subscriber_address = "backend_ctl.fake"

    def __init__(self) -> None:
        self.connection_lost = False
        self.connect_calls = 0
        self.close_calls = 0
        self.reply: Any = _ok({})
        self.fail_connect = False
        self.fail_read = False
        self.fire_sync = False  # request_async зовёт колбэк ВНУТРИ вызова
        self.pending: list[Callable[[Any], None]] = []
        self.async_messages: list[dict] = []

    def connect(self, timeout: float = 5.0) -> None:
        self.connect_calls += 1
        if self.fail_connect:
            raise OSError("отказ соединения")
        self.connection_lost = False

    def close(self) -> None:
        self.close_calls += 1

    def request(self, message: dict, timeout: float | None = None) -> Any:
        if self.fail_read:
            raise SocketConnectionLost("обрыв")
        return self.reply

    def request_async(self, message: dict, on_response: Callable[[Any], None], timeout: float = 5.0, **_: Any) -> str:
        self.async_messages.append(message)
        self.pending.append(on_response)
        if self.fire_sync:
            on_response(self.reply)
        return "id"


class _FakeProxy:
    """Макет ``RemoteStateProxy``: запоминает подписку, возврат связи может отказать."""

    last: "_FakeProxy"

    def __init__(self, client: Any, *, dispatch: Callable) -> None:
        _FakeProxy.last = self
        self.subscriptions: list[tuple[str, Callable, bool]] = []
        self.unsubscribed: list[str] = []
        self.reconnects = 0
        self.fail_reconnect = False

    def subscribe(self, pattern: str, callback: Callable, exclude_self: bool = True, sync: bool = True) -> str:
        self.subscriptions.append((pattern, callback, exclude_self))
        return "sub-1"

    def unsubscribe(self, sub_id: str) -> None:
        self.unsubscribed.append(sub_id)

    def on_reconnected(self) -> None:
        self.reconnects += 1
        if self.fail_reconnect:
            raise SocketConnectionLost("обрыв при переподписке")


def _link(monkeypatch: pytest.MonkeyPatch, mode: str, now: list[float], **kw: Any) -> tuple[LineLink, _FakeClient]:
    monkeypatch.setattr(line_source, "RemoteStateProxy", _FakeProxy)
    link = LineLink("127.0.0.1", 1, mode=mode, clock=lambda: now[0], **kw)
    client = _FakeClient()
    link._client = client  # макет вместо настоящего SocketClient (конструктор сети не открывает)
    return link, client


def _x_raw(link: LineLink) -> int:
    return link.source.read(_TLM_X)[0]


# --------------------------------------------------------------------------- #
# (a) синхронный колбэк request_async не встаёт опрос                          #
# --------------------------------------------------------------------------- #


def test_poll_survives_synchronous_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    link, client = _link(monkeypatch, "poll", now, poll_ms=100)
    client.reply = _ok(_state(350.0))
    client.fire_sync = True
    link.open()

    for t in (0.0, 0.05, 0.1, 0.2):
        now[0] = t
        link.tick()

    assert len(client.async_messages) == 3, "запросы на тиках 0.0, 0.1, 0.2 (на 0.05 — рано)"
    assert client.async_messages[0]["command"] == "state.get_subtree"
    assert client.async_messages[0]["data"]["path"] == LINE_STATE_PATH
    assert _x_raw(link) == 3500


# --------------------------------------------------------------------------- #
# (b) пустой / неуспешный ответ: флаг снят, снимок не тронут                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "response",
    [
        {"success": False, "error": "timeout"},
        {"success": True, "result": {"status": "error", "error": "нет пути"}},
        _ok({}),
    ],
    ids=["no-success", "status-not-ok", "empty-value"],
)
def test_poll_bad_response_clears_flag_without_update(monkeypatch: pytest.MonkeyPatch, response: dict) -> None:
    now = [0.0]
    link, client = _link(monkeypatch, "poll", now, poll_ms=100)
    link.open()

    link.tick()
    assert len(client.pending) == 1
    link.tick()  # запрос ещё в полёте — второго нет, даже когда срок вышел
    now[0] = 0.5
    link.tick()
    assert len(client.pending) == 1

    client.pending[0](response)  # ответ приходит позже, как с reader-потока
    assert link.source.age_s() is None, "снимок появился из неуспешного ответа"
    assert link.last_error is None

    now[0] = 0.6
    link.tick()
    assert len(client.pending) == 2, "флаг «в полёте» не снят — опрос встал"


# --------------------------------------------------------------------------- #
# (c) push: берётся последняя дельта узла, листья пропускаются                  #
# --------------------------------------------------------------------------- #


def test_push_takes_last_node_delta_and_ignores_leaves(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    link, client = _link(monkeypatch, "push", now)
    link.open()
    pattern, callback, exclude_self = _FakeProxy.last.subscriptions[0]
    assert (pattern, exclude_self) == ("sim.robot.state.**", True)

    leaf = SimpleNamespace(path="sim.robot.state.pose.x_mm", new_value=999.0)
    callback([leaf])
    assert link.source.age_s() is None, "лист обновил снимок"

    first = SimpleNamespace(path="sim.robot.state", new_value=_state(350.0))
    second = SimpleNamespace(path="sim.robot.state", new_value=_state(400.0))
    leaf_after = SimpleNamespace(path="sim.robot.state.moving", new_value=True)
    leaf_dict = SimpleNamespace(path="sim.robot.state.pose", new_value={"x_mm": 999.0})  # лист-словарь, не узел
    callback([leaf, first, second, leaf_after, leaf_dict])
    assert _x_raw(link) == 4000, "взят не последний узел"
    assert link.last_error is None, "словарь с листового пути принят за снимок"

    garbage = SimpleNamespace(path="sim.robot.state", new_value="не словарь")
    removed = SimpleNamespace(path="sim.robot.state", new_value=MISSING)
    callback([first, garbage, removed])
    assert _x_raw(link) == 3500, "узел не со словарём перекрыл словарь"
    assert link.last_error is None


# --------------------------------------------------------------------------- #
# (d) возврат связи: lost снимается только после всех шагов                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("failing_step", ["connect", "on_reconnected", "read"])
def test_reconnect_keeps_lost_until_every_step_passes(monkeypatch: pytest.MonkeyPatch, failing_step: str) -> None:
    now = [10.0]
    link, client = _link(monkeypatch, "push", now, retry_ms=1000)
    link.open()
    assert client.connect_calls == 1
    proxy = _FakeProxy.last

    client.connection_lost = True
    client.reply = _ok(_state(400.0))
    if failing_step == "connect":
        client.fail_connect = True
    elif failing_step == "on_reconnected":
        proxy.fail_reconnect = True
    else:
        client.fail_read = True

    link.tick()  # попытка 1: обрыв замечен, шаг отказывает
    assert link.lost is True
    assert client.connect_calls == 2
    assert client.close_calls == 1  # close() перед connect() — протокол реконнекта
    assert link.source.age_s() is None  # последний снимок не чистится; здесь его и не было

    now[0] = 10.5
    link.tick()  # раньше retry_ms — попытки нет
    assert client.connect_calls == 2
    assert link.lost is True

    client.fail_connect = False
    proxy.fail_reconnect = False
    client.fail_read = False
    now[0] = 11.0
    link.tick()  # попытка 2 — через retry_ms от попытки 1
    assert client.connect_calls == 3
    assert proxy.reconnects >= 1
    assert link.lost is False
    assert _x_raw(link) == 4000


def test_lost_keeps_last_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    link, client = _link(monkeypatch, "poll", now)
    client.reply = _ok(_state(350.0))
    link.open()
    client.connection_lost = True
    client.fail_connect = True
    now[0] = 1.0
    link.tick()
    assert link.lost is True
    assert _x_raw(link) == 3500, "при потере связи снимок обязан остаться"


# --------------------------------------------------------------------------- #
# (e) ValueError из update: last_error ставится и снимается                     #
# --------------------------------------------------------------------------- #


def test_update_value_error_sets_and_clears_last_error(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    link, client = _link(monkeypatch, "poll", now, poll_ms=100)
    client.reply = _ok(_state(350.0, model="OtherModel"))
    client.fire_sync = True
    link.open()  # начальное чтение отвергнуто
    assert link.last_error == _BAD_MODEL_TEXT
    assert link.source.age_s() is None

    client.reply = _ok(_state(350.0))
    now[0] = 1.0
    link.tick()
    assert link.last_error is None
    assert _x_raw(link) == 3500


# --------------------------------------------------------------------------- #
# Жизненный цикл                                                               #
# --------------------------------------------------------------------------- #


def test_close_unsubscribes_and_stops_ticking(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    link, client = _link(monkeypatch, "push", now)
    link.open()
    link.close()
    link.close()  # идемпотентна
    assert _FakeProxy.last.unsubscribed == ["sub-1"]

    client.connection_lost = True
    now[0] = 5.0
    link.tick()
    assert client.connect_calls == 1, "после close() tick не должен переподключаться"


def test_open_propagates_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    link, client = _link(monkeypatch, "poll", [0.0])
    client.fail_connect = True
    with pytest.raises(OSError):
        link.open()
