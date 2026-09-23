# -*- coding: utf-8 -*-
"""Task 2.3b — независимый RED по приёмке (тестер, worktree на пред-2.3a коммите).

Слепые тесты HTTP-контракта ``PultWebPlugin`` (см. плана
``plans/line-sim/phase-2-belt-truth.md``, Task 2.3b, блок REDS): настоящий
``urllib`` против поднятого плагина на свободном порту, ``robot`` подменён
записывающим двойником ``DeviceHubClient``. Диффа с реализацией нет — брифу
запрещён `_impl/`/диф разработчика, только DESIGN-блок задачи и HTTP-таблица.

**Шов подмены (ДОГАДКА, не подтверждено чтением ``plugin.py`` — его нет).**
DESIGN п.2 говорит прямым текстом: "IPC —
``Plugins.hub.device_hub.client.DeviceHubClient(ctx, target_process=...,
default_timeout=...)``" — значит плагин обязан импортировать класс по имени
``DeviceHubClient`` в свой модуль (``Plugins.sim.pult_web.plugin``), иначе
конструктор с такой сигнатурой негде звать. Патчим ИМЕННО это имя в модуле
плагина (``monkeypatch.setattr("Plugins.sim.pult_web.plugin.DeviceHubClient",
...)``) — бриф прямо называет этот шов ожидаемым. Если разработчик создаст
клиента иначе (например, через фабрику модуля ``device_hub.client`` без
привязки имени в ``plugin.py``, или отложенным импортом внутри метода
каждый раз заново) — патч не сработает, и это диагностируется по тексту
ошибки (``AssertionError: клиент не создан`` / пустой ``instances``), не по
тихому проходу мимо handler'а.

**Второй ДОГАДАННЫЙ символ** — приватный атрибут состояния ``plugin._state``
в тесте ``test_port_busy_degrades_not_crashes``: не подтверждён чтением (файла
нет), а выведен из идиомы репозитория — DESIGN п.1 прямым текстом требует
"копия ``MjpegSinkPlugin`` … отдельного пробного bind'а … не нужно", а
``MjpegSinkPlugin`` (см. ``Plugins/sim/mjpeg_sink/plugin.py``) хранит статус
именно в ``self._state`` (``"configured"``/``"running"``/``"error"``/``"stopped"``),
и его же тест (``test_port_busy_reports_error_not_crash``) проверяет
``plugin._state == "error"``. Если у ``PultWebPlugin`` имя атрибута другое —
это единственный тест файла, который сломается по СВОЕЙ причине (AttributeError),
не по отсутствию модуля, и требует правки после того, как разработчик назовёт
своё имя.

Остальные тесты не гадают приватные имена — судят только по HTTP-ответу и по
вызовам двойника ``DeviceHubClient.request``.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
    MockStatsManager,
)

# Импорт самого плагина — ДО реализации 2.3b кидает ModuleNotFoundError
# (ImportError) при сборе файла: это приёмный RED-повод брифа ("ImportError
# плагина допустим"). Все тесты этого файла окажутся ошибками сбора по ОДНОЙ
# причине, см. отчёт.
from Plugins.sim.pult_web.plugin import PultWebPlugin

pytestmark = pytest.mark.timeout(30)

_MJPEG_URL = "http://127.0.0.1:8091/"
_TIMEOUT_S = 1.0


# --------------------------------------------------------------------------- #
# Двойник DeviceHubClient — записывает вызовы, отвечает по командной таблице  #
# --------------------------------------------------------------------------- #


class _FakeDeviceHubClient:
    """Повторяет сигнатуру конструктора ``DeviceHubClient`` (DESIGN п.2).

    ``instances`` — способ теста достать созданный ЭКЗЕМПЛЯР изнутри плагина
    (плагин строит клиента сам, тест до него не достаёт напрямую).
    """

    instances: list["_FakeDeviceHubClient"] = []

    def __init__(self, ctx: Any, target_process: str = "robot", default_timeout: float = 2.0) -> None:
        self.ctx = ctx
        self.target_process = target_process
        self.default_timeout = default_timeout
        self.calls: list[tuple[str, dict]] = []
        #: command -> response dict; по умолчанию эхо-успех.
        self.responses: dict[str, dict] = {}
        _FakeDeviceHubClient.instances.append(self)

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        args = dict(args or {})
        self.calls.append((command, args))
        return dict(self.responses.get(command, {"status": "ok", "echo": args}))


# --------------------------------------------------------------------------- #
# HTTP-хелпер                                                                  #
# --------------------------------------------------------------------------- #


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http(port: int, method: str, path: str, body: Any = None) -> tuple[int, bytes, dict]:
    """POST/GET на пульт. ``body`` — bytes (как есть) или dict (сериализуется в JSON)."""
    url = f"http://127.0.0.1:{port}{path}"
    data = None
    headers = {}
    if body is not None:
        data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, resp.read(), dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items()) if exc.headers else {}


@pytest.fixture
def pult(monkeypatch: pytest.MonkeyPatch):
    """Плагин на свободном порту + записывающий двойник ``robot``."""
    _FakeDeviceHubClient.instances.clear()
    monkeypatch.setattr("Plugins.sim.pult_web.plugin.DeviceHubClient", _FakeDeviceHubClient)

    port = _free_port()
    stats = MockStatsManager()
    services = MockProcessServices(name="pult", stats_manager=stats)
    ctx = PluginContext(
        services=services,
        config={
            "host": "127.0.0.1",
            "port": port,
            "mjpeg_url": _MJPEG_URL,
            "robot_process": "robot",
            "timeout_s": _TIMEOUT_S,
        },
    )
    plugin = PultWebPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    assert _FakeDeviceHubClient.instances, "плагин не создал DeviceHubClient через ожидаемый шов (DESIGN п.2)"
    # С 5.3a плагин строит второго клиента (процесс сцены) — берём клиента robot по адресату.
    client = next(c for c in _FakeDeviceHubClient.instances if c.target_process == "robot")
    try:
        yield plugin, ctx, services, client, port
    finally:
        plugin.shutdown(ctx)


# --------------------------------------------------------------------------- #
# RED 1 — GET / отдаёт страницу с MJPEG и ручками                             #
# --------------------------------------------------------------------------- #


def test_index_has_controls_and_mjpeg(pult) -> None:
    _plugin, _ctx, _services, _client, port = pult

    status, raw, headers = _http(port, "GET", "/")
    body = raw.decode("utf-8")

    assert status == 200, f"GET / -> {status}, тело: {raw[:300]!r}"
    content_type = headers.get("Content-Type", "")
    assert content_type.startswith("text/html"), f"Content-Type не text/html: {content_type!r}"
    assert f'src="{_MJPEG_URL}"' in body, "картинка не указывает на mjpeg_url из конфига"
    assert 'type="range"' in body, "нет ползунка частоты (input type=range)"
    assert "Пуск" in body, "нет кнопки «Пуск»"
    assert "Стоп" in body, "нет кнопки «Стоп»"
    assert "◀" in body and "▶" in body, "нет кнопок jog (◀/▶)"
    assert "калибр" in body.lower(), "нет поля/подписи калибровки"


# --------------------------------------------------------------------------- #
# RED 2 — POST /api/run форвардит ТУ ЖЕ команду belt.run                      #
# --------------------------------------------------------------------------- #


def test_run_forwards_same_command(pult) -> None:
    _plugin, _ctx, _services, client, port = pult

    status, raw, _headers = _http(port, "POST", "/api/run", {"freq_hz": 25, "reverse": True})

    assert client.calls == [("belt.run", {"freq_hz": 25, "reverse": True})], (
        f"двойник получил не ровно один belt.run с тем же телом: {client.calls!r}"
    )
    assert status == 200, f"POST /api/run -> {status}, тело: {raw[:300]!r}"
    body = json.loads(raw.decode("utf-8"))
    assert body == {"status": "ok", "echo": {"freq_hz": 25, "reverse": True}}, (
        f"тело ответа не равно ответу двойника как есть (DESIGN п.3, «ответ — результат команды как есть»): {body!r}"
    )


# --------------------------------------------------------------------------- #
# RED 3 — /api/jog, /api/stop, /api/calibrate, GET /api/status -> команды     #
# --------------------------------------------------------------------------- #


def test_jog_stop_calibrate_status_map(pult) -> None:
    _plugin, _ctx, _services, client, port = pult

    jog_body = {"direction": "fwd"}
    status_jog, raw_jog, _h = _http(port, "POST", "/api/jog", jog_body)
    assert status_jog == 200, f"POST /api/jog -> {status_jog}, тело: {raw_jog[:300]!r}"

    status_stop, raw_stop, _h = _http(port, "POST", "/api/stop", {})
    assert status_stop == 200, f"POST /api/stop -> {status_stop}, тело: {raw_stop[:300]!r}"

    calib_body = {"mm_s_at_max_freq": 200}
    status_calib, raw_calib, _h = _http(port, "POST", "/api/calibrate", calib_body)
    assert status_calib == 200, f"POST /api/calibrate -> {status_calib}, тело: {raw_calib[:300]!r}"

    status_get, raw_get, _h = _http(port, "GET", "/api/status")
    assert status_get == 200, f"GET /api/status -> {status_get}, тело: {raw_get[:300]!r}"

    assert client.calls == [
        ("belt.jog", jog_body),
        ("belt.stop", {}),
        ("belt.calibrate", calib_body),
        ("belt.status", {}),
    ], f"карта путь->команда не совпала: {client.calls!r}"


# --------------------------------------------------------------------------- #
# RED 4 — три отказа до вызова robot: bad_json 400, unknown 404, oversize 413 #
# --------------------------------------------------------------------------- #


def test_bad_json_400_unknown_404_oversize_413(pult) -> None:
    _plugin, _ctx, _services, client, port = pult

    status_bad, raw_bad, _h = _http(port, "POST", "/api/run", b"{not-valid-json")
    assert status_bad == 400, f"кривой JSON -> {status_bad}, тело: {raw_bad[:300]!r}"
    assert json.loads(raw_bad.decode("utf-8")) == {"ok": False, "error": "bad_json"}, (
        f"тело 400 не совпало с литералом DESIGN п.3: {raw_bad!r}"
    )

    status_404, _raw_404, _h = _http(port, "GET", "/api/nope")
    assert status_404 == 404, f"неизвестный путь -> {status_404}"

    oversize_body = json.dumps({"freq_hz": 1, "pad": "x" * 4200}).encode("utf-8")
    assert len(oversize_body) > 4096, "тестовое тело должно реально превышать 4 КБ"
    status_413, _raw_413, _h = _http(port, "POST", "/api/run", oversize_body)
    assert status_413 == 413, f"тело > 4КБ -> {status_413}"

    assert client.calls == [], f"двойник не должен был получить ни одного вызова: {client.calls!r}"


# --------------------------------------------------------------------------- #
# RED 5 — ответ robot status=error -> 504                                     #
# --------------------------------------------------------------------------- #


def test_robot_timeout_504(pult) -> None:
    _plugin, _ctx, _services, client, port = pult
    client.responses["belt.run"] = {"status": "error", "message": "timeout"}

    status, raw, _h = _http(port, "POST", "/api/run", {"freq_hz": 10, "reverse": False})

    assert status == 504, f"ответ клиента status=error -> ожидали 504, получили {status}, тело: {raw[:300]!r}"
    assert json.loads(raw.decode("utf-8")) == {"ok": False, "error": "timeout"}, (
        f"тело 504 не совпало с литералом DESIGN п.3 (ok:false, error:<сообщение клиента>): {raw!r}"
    )


# --------------------------------------------------------------------------- #
# RED 6 — занятый порт: start() не бросает, деградация в error, health видит  #
# --------------------------------------------------------------------------- #


def test_port_busy_degrades_not_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeDeviceHubClient.instances.clear()
    monkeypatch.setattr("Plugins.sim.pult_web.plugin.DeviceHubClient", _FakeDeviceHubClient)

    port = _free_port()
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", port))
    occupied.listen(1)
    try:
        stats = MockStatsManager()
        services = MockProcessServices(name="pult", stats_manager=stats)
        ctx = PluginContext(
            services=services,
            config={
                "host": "127.0.0.1",
                "port": port,
                "mjpeg_url": _MJPEG_URL,
                "robot_process": "robot",
                "timeout_s": _TIMEOUT_S,
            },
        )
        plugin = PultWebPlugin()
        plugin.configure(ctx)

        plugin.start(ctx)  # не должно бросить

        # ДОГАДАННЫЙ атрибут — см. докстринг модуля ("Второй догаданный символ").
        assert plugin._state == "error", f"ожидали state='error' при занятом порту, получили {plugin._state!r}"

        health_state = getattr(services, "_health_state", None)
        assert health_state is not None, "ctx.health.report_error должен был создать HealthState на services"
        assert health_state.error_count >= 1, f"report_error не учтён: error_count={health_state.error_count}"
    finally:
        occupied.close()


# --------------------------------------------------------------------------- #
# RED 7 — dead-man на странице: события ведут к /api/stop, интервал 200 мс    #
# --------------------------------------------------------------------------- #


def test_page_jog_is_dead_man(pult) -> None:
    """Слабая проверка (текст страницы, не поведение браузера) — так и названо
    в плане (REDS п.7, «Открыто»). Судит присутствие имён событий и цели
    ``/api/stop`` в тексте, не то, что обработчик реально сработает."""
    _plugin, _ctx, _services, _client, port = pult

    _status, raw, _h = _http(port, "GET", "/")
    body = raw.decode("utf-8")

    for event_name in ("pointerup", "pointercancel", "blur", "visibilitychange"):
        assert event_name in body, f"нет обработчика {event_name!r} на странице (dead-man, DESIGN п.4)"
    assert "/api/stop" in body, "нет ни одного обращения к /api/stop на странице"
    assert "200" in body, "не найден интервал подкачки jog (200 мс, DESIGN п.4)"
