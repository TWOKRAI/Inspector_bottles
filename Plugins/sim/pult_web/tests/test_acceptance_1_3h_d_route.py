# -*- coding: utf-8 -*-
"""RED-приёмка Task 1.3h-d (бэкенд) — маршрут `POST /api/preset/sprite_put` на `pult_web`.

Слепой прогон независимого tester (worktree `d-tester-be`, коммит `b2103448` — коммит спецификации,
реализации нет). Источник контракта — раздел «Маршрут» плана
`plans/line-sim-layer-editor/task-1.3h-d-upload.md`:

- потолок тела маршрута 9 МиБ = 9_437_184 байта: больше -> 413 ДО чтения тела и ДО вызова команды;
  ровно 9_437_184 принимается (общий потолок 4 КБ / потолок commit 256 КБ здесь недостаточны:
  PNG до 6 МиБ в base64 — ~8 МиБ);
- тело форвардится как есть клиенту процесса `layers` командой `preset.sprite_put`;
- код ошибки команды -> HTTP по таблице: `conflict` 409, `invalid` 400 — на НАСТОЯЩЕМ
  `DeviceHubClient` (конверт строит настоящий `reply_to_request`), успех -> 200 с `file` как есть.

Харнесс — техника `test_error_code_through_real_client_acceptance.py` (не импорт из чужого теста):
клиент настоящий, подменён только `ctx.router_manager`. HTTP — в daemon-потоке с дедлайном join
(`pytest-timeout` в окружении не установлен, маркер декоративный); тело ответа читается целиком
до закрытия (Windows, см. `_linger_close` плагина). Ожидаемые значения — литералы.
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
    MockStatsManager,
)
from Plugins.hub.device_hub.tests.test_reply_envelope_acceptance import _FakeSendRouter
from Plugins.sim.pult_web.plugin import PultWebPlugin

_HTTP_DEADLINE_S = 30.0
_ROUTE_CEILING = 9_437_184  # литерал из контракта: 9 МиБ

_PATH = "/api/preset/sprite_put"
_FILE_OK = {"path": "cap.png", "sprite_source": "sprites/cap.png"}


class _StubRouter:
    """`ctx.router_manager`: `request()` отдаёт заданный ответ, вызовы записаны."""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[dict] = []

    def request(self, msg: dict, timeout: float | None = None) -> dict:
        self.calls.append(msg)
        return self.response


def _reply_envelope(result: Any, success: bool) -> dict:
    envelope = _FakeSendRouter().reply_to_request(
        {"request_id": "req-1", "reply_to": "test-caller"}, result, success=success
    )
    assert envelope is not None, "reply_to_request вернул None — request_msg без адресата?"
    return envelope


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _in_deadline(fn, what: str):
    """`fn()` в daemon-потоке с дедлайном: зависание -> падение теста, а не подвисший прогон."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в основной поток
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(_HTTP_DEADLINE_S)
    assert not thread.is_alive(), f"{what}: нет ответа за {_HTTP_DEADLINE_S} с (зависание)"
    if "error" in box:
        raise box["error"]
    return box["result"]


def _post_once(port: int, raw_body: bytes) -> tuple[int, bytes]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{_PATH}",
        data=raw_body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _post(port: int, body: dict) -> tuple[int, dict]:
    status, raw = _in_deadline(lambda: _post_once(port, json.dumps(body).encode("utf-8")), f"POST {_PATH}")
    try:
        return status, json.loads(raw.decode("utf-8"))
    except ValueError:
        return status, {"_raw": raw[:200].decode("utf-8", "replace")}


@pytest.fixture
def start_pult():
    """Фабрика: `pult_web` над настоящими клиентами и `router_manager` с ответом `response`."""
    started: list[tuple[PultWebPlugin, PluginContext]] = []

    def _start(response: dict) -> tuple[int, _StubRouter]:
        port = _free_port()
        router = _StubRouter(response)
        services = MockProcessServices(name="pult", stats_manager=MockStatsManager(), router_manager=router)
        config = {
            "host": "127.0.0.1",
            "port": port,
            "mjpeg_url": "http://127.0.0.1:8091/",
            "robot_process": "robot",
            "timeout_s": 1.0,
        }
        ctx = PluginContext(services=services, config=config)
        plugin = PultWebPlugin()
        plugin.configure(ctx)
        plugin.start(ctx)
        started.append((plugin, ctx))
        return port, router

    yield _start

    for plugin, ctx in started:
        plugin.shutdown(ctx)


def _padded_body_of_size(total: int) -> bytes:
    """Валидный JSON `{"name":"a.png","png_b64":"AAAA..."}` длиной ровно `total` байт."""
    prefix = b'{"name":"a.png","png_b64":"'
    suffix = b'"}'
    pad = total - len(prefix) - len(suffix)
    assert pad > 0
    body = prefix + b"A" * pad + suffix
    assert len(body) == total
    return body


def test_route_over_ceiling_is_413_before_command(start_pult) -> None:
    """Заявленный Content-Length 9_437_185 (потолок + 1) и всего 64 присланных байта -> 413,
    команда не вызвана (router не тронут): решение принято ДО чтения тела."""
    port, router = start_pult(_reply_envelope({"status": "ok", "file": dict(_FILE_OK)}, success=True))
    result: dict[str, Any] = {}

    def attempt() -> None:
        with socket.create_connection(("127.0.0.1", port), timeout=10.0) as sock:
            sock.sendall(
                b"POST " + _PATH.encode("ascii") + b" HTTP/1.1\r\n"
                b"Host: 127.0.0.1:" + str(port).encode("ascii") + b"\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(_ROUTE_CEILING + 1).encode("ascii") + b"\r\n"
                b"\r\n" + b"x" * 64
            )
            sock.settimeout(10.0)
            data = b""
            try:
                while b"\r\n\r\n" not in data:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            except OSError as exc:  # RST после ответа — не отказ теста, если статус-строка уже есть
                result["error"] = repr(exc)
            result["data"] = data

    _in_deadline(attempt, "413 на заявленном теле > потолка")

    status_line = result.get("data", b"").split(b"\r\n", 1)[0]
    assert b" 413 " in status_line, (
        f"ждали 413, статус-строка: {status_line!r} (ошибка сокета: {result.get('error')!r})"
    )
    assert router.calls == [], f"команда вызвана при теле > потолка: {router.calls!r}"


def test_route_body_exactly_at_ceiling_is_accepted_and_forwarded(start_pult) -> None:
    """Тело РОВНО 9_437_184 байта проходит (строго `>` — граница включена) и форвардится команде
    `preset.sprite_put` в клиент процесса `layers`; ответ команды идёт как есть. Кладёт нижнюю
    границу потолка: 256 КБ (потолок commit) или 4 КБ (общий) дали бы 413."""
    port, router = start_pult(_reply_envelope({"status": "ok", "file": dict(_FILE_OK)}, success=True))
    body = _padded_body_of_size(_ROUTE_CEILING)

    status, raw = _in_deadline(lambda: _post_once(port, body), "POST ровно на потолке")

    assert status == 200, f"тело ровно {_ROUTE_CEILING} байт -> {status}: {raw[:200]!r}"
    assert json.loads(raw.decode("utf-8")) == {"status": "ok", "file": _FILE_OK}, raw[:200]
    assert len(router.calls) == 1, router.calls
    sent = router.calls[0]
    assert sent["command"] == "preset.sprite_put", sent.get("command")
    assert sent["targets"] == ["layers"], sent.get("targets")
    assert sent["data"]["name"] == "a.png", sent["data"].get("name")
    assert len(sent["data"]["png_b64"]) == _ROUTE_CEILING - len(b'{"name":"a.png","png_b64":"') - 2, (
        "png_b64 форвардится как есть, без усечения"
    )


@pytest.mark.parametrize(
    ("reply", "expected_status", "expected_code"),
    [
        (
            {"status": "error", "code": "conflict", "message": "файл уже есть: cap.png"},
            409,
            "conflict",
        ),
        (
            {"status": "error", "code": "invalid", "message": "нужен альфа-канал (RGBA)"},
            400,
            "invalid",
        ),
    ],
    ids=["conflict_409", "invalid_400"],
)
def test_route_error_code_reaches_http_through_real_client(
    start_pult, reply: dict, expected_status: int, expected_code: str
) -> None:
    """`conflict` -> 409, `invalid` -> 400 на настоящем `DeviceHubClient`: `code` не теряется в
    клиенте (иначе оба стали бы 504), тело ошибки проходит как есть."""
    port, router = start_pult(_reply_envelope(dict(reply), success=False))

    status, body = _post(port, {"name": "cap.png", "png_b64": "AAAA"})

    assert router.calls, "команда не дошла до router_manager.request — тест не проверяет клиента"
    assert status == expected_status, f"ждали {expected_status}, получили {status}: {body!r}"
    assert body == reply, f"тело ошибки должно пройти как есть: {body!r}"
    assert body["code"] == expected_code


def test_route_success_is_200_with_file_through_real_client(start_pult) -> None:
    """Успех команды -> 200, `file` доходит как есть; форвард в `layers` командой `preset.sprite_put`
    с телом без изменений."""
    port, router = start_pult(_reply_envelope({"status": "ok", "file": dict(_FILE_OK)}, success=True))

    status, body = _post(port, {"name": "cap.png", "png_b64": "AAAA"})

    assert status == 200, f"успех -> {status}: {body!r} (маршрута нет?)"
    assert body == {"status": "ok", "file": _FILE_OK}, body
    assert len(router.calls) == 1, router.calls
    assert router.calls[0]["command"] == "preset.sprite_put", router.calls[0].get("command")
    assert router.calls[0]["targets"] == ["layers"], router.calls[0].get("targets")
    assert router.calls[0]["data"] == {"name": "cap.png", "png_b64": "AAAA"}, router.calls[0].get("data")
