# -*- coding: utf-8 -*-
"""``PultWebPlugin`` — веб-пульт ленты: страница + HTTP JSON API на 8092.

Task 2.3b плана ``plans/line-sim/phase-2-belt-truth.md``. Форма сервера —
копия ``MjpegSinkPlugin`` (``Plugins/sim/mjpeg_sink/plugin.py``, Task 1.2b):
``ThreadingHTTPServer`` поднимается в ``try/except OSError`` синхронно в
конструкторе (stdlib биндит порт там же, без пробного сокета — тот же
довод, что в докстринге ``mjpeg_sink``), ``serve_forever`` в daemon-потоке,
занятый порт уходит в ``self._state = "error"`` + ``ctx.health.report_error``
без падения процесса, ``shutdown()`` симметричен.

**Единственный канал к процессу ``robot`` — ``DeviceHubClient``.** У пульта
нет своей логики ленты: каждая ручка страницы — HTTP-запрос к этому плагину,
который форвардит ТЕЛО КАК ЕСТЬ в ``belt.*`` через
``Plugins.hub.device_hub.client.DeviceHubClient.request()`` и возвращает
результат клиенту как есть (см. таблицу DESIGN п.3 плана). Новый клиент не
заводится — импорт по имени ``DeviceHubClient`` в этот модуль — единственный
шов, которым тест подменяет канал (``monkeypatch.setattr(".../plugin.py",
"DeviceHubClient", ...)``).

**Поток вызова — HTTP-обработчик, не приёмный поток.** ``ThreadingHTTPServer``
создаёт поток на каждое соединение (``socketserver.ThreadingMixIn``); ни один
из них не является приёмным циклом процесса ``pult`` — значит блокирующий
``DeviceHubClient.request()`` (внутри — ``router_manager.request()``) из
обработчика легален (разведка плана, п.1). Конкурентные запросы (пример —
20 одновременных ``POST /api/jog`` с зажатой кнопкой на странице) обслуживаются
каждый своим потоком; форвард каждого — отдельный вызов ``client.request``,
общего состояния между запросами нет, гонок формировать нечему.

**HTTP/1.0 без keep-alive (дефолт ``BaseHTTPRequestHandler``, не переопределён,
как и в ``mjpeg_sink``) — то, что даёт право не дочитывать тело при 404/413.**
Соединение закрывается сервером после каждого ответа, поэтому непрочитанные
байты тела (случай 413 — тело не читается вовсе, только заголовок
``Content-Length``) не зависают в сокете следующего запроса — следующего
запроса на этом сокете не будет.

**``do_POST`` читает РОВНО ``Content-Length`` байт.** ``rfile.read()`` без
аргумента ждал бы EOF, которого на keep-alive-подобном соединении браузера
может не быть — зависание вместо ответа (TRAPS плана).

Страница — один строковый constant (``_PAGE_TEMPLATE``, ``str.format`` с
``mjpeg_url`` — не templating-движок и не файл, ровно DESIGN п.4). Опрос
``GET /api/status`` раз в 250 мс, dead-man jog на стороне браузера
(``pointerdown`` → сразу + каждые 200 мс, тик пропускается, пока прошлый
``/api/jog`` в пути; ``pointerup``/``pointercancel``/``pointerleave``/окно
``blur``/``visibilitychange`` → снять таймер и ``POST /api/stop`` — только при
активном jog и только после возврата последнего ``/api/jog``) — независимая, более быстрая копия dead-man'а самого
``robot`` (Task 2.3a, 500 мс по умолчанию): двойная защита, а не замена.
"""

from __future__ import annotations

import http.server
import json
import threading
from typing import Any

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    register_plugin,
)
from Plugins.hub.device_hub.client import DeviceHubClient

#: Дефолты конфига (Task 2.3b плана line-sim; порт 8092 — стенд apps/line_sim).
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8092
_DEFAULT_MJPEG_URL = "http://127.0.0.1:8091/"
_DEFAULT_ROBOT_PROCESS = "robot"
_DEFAULT_TIMEOUT_S = 1.0

#: Тело запроса больше этого — 413, ДО чтения (DESIGN п.3 плана).
_MAX_BODY_BYTES = 4096

#: Путь -> команда ``belt.*`` (DESIGN п.3 плана, HTTP API). Тело форвардится
#: КАК ЕСТЬ — путь не валидирует поля, это дело ``robot`` (Task 2.3a).
_COMMAND_BY_PATH = {
    "/api/run": "belt.run",
    "/api/stop": "belt.stop",
    "/api/jog": "belt.jog",
    "/api/calibrate": "belt.calibrate",
    "/api/journal/reset": "sim_robot.journal_reset",
}

#: Страница пульта — Русские подписи, dead-man на jog-кнопках, опрос статуса.
_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Пульт ленты</title>
<style>
body {{ font-family: sans-serif; margin: 16px; }}
#cam {{ max-width: 480px; display: block; border: 1px solid #888; }}
.row {{ margin: 8px 0; }}
button {{ font-size: 1.2em; padding: 4px 12px; }}
#status {{ font-family: monospace; white-space: pre; }}
</style>
</head>
<body>
<h1>Пульт ленты</h1>
<img id="cam" src="{mjpeg_url}" alt="камера">

<div class="row">
  <label>Частота, Гц:
    <input type="range" id="freq" min="0" max="50" step="0.5" value="25">
    <input type="number" id="freqNum" min="0" max="50" step="0.5" value="25">
  </label>
</div>

<div class="row">
  <label><input type="checkbox" id="reverse"> Реверс</label>
</div>

<div class="row">
  <button id="btnRun">Пуск</button>
  <button id="btnStop">Стоп</button>
</div>

<div class="row">
  <button id="jogRev">◀</button>
  <button id="jogFwd">▶</button>
</div>

<div class="row">
  <label>Калибровка (мм/с на макс. частоте):
    <input type="number" id="calib" step="0.0001" value="101.1311">
  </label>
  <button id="btnCalib">Применить</button>
</div>

<div class="row" id="status">robot не отвечает</div>

<h2>Задания от прототипа</h2>
<div class="row">
  <div id="journal">журнал недоступен</div>
  <button id="btnJournalReset">Сброс счётчиков</button>
</div>

<script>
function post(path, body) {{
  return fetch(path, {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify(body || {{}}),
  }}).then(function (r) {{ return r.json(); }});
}}
function getStatus() {{
  return fetch("/api/status").then(function (r) {{
    return r.ok ? r.json() : Promise.reject(new Error("http " + r.status));
  }});
}}

var freqSlider = document.getElementById("freq");
var freqNum = document.getElementById("freqNum");

// `beltRunning` ведётся опросом статуса: пока лента ЕДЕТ, смена частоты или реверса
// применяется сразу, без «Пуска». До этой правки ползунок только переписывал число в
// поле, а на ленту оно уходило исключительно по кнопке, и пульт показывал одно
// (поле «20»), а лента ехала на другом (статус freq_hz=40, mm_s=240) — владелец,
// 2026-09-23: «гц не регулируются, а шаг регулируется» (джог читал поле в момент
// нажатия, поэтому у него это работало).
var beltRunning = false;
function sendRun() {{
  post("/api/run", {{
    freq_hz: parseFloat(freqNum.value),
    reverse: document.getElementById("reverse").checked,
  }});
}}
function applyIfRunning() {{ if (beltRunning) sendRun(); }}

freqSlider.oninput = function () {{ freqNum.value = freqSlider.value; }};
freqNum.oninput = function () {{ freqSlider.value = freqNum.value; }};
freqSlider.onchange = applyIfRunning;   // change, не input: не слать запрос на каждый пиксель перетаскивания
freqNum.onchange = applyIfRunning;
document.getElementById("reverse").onchange = applyIfRunning;

document.getElementById("btnRun").onclick = sendRun;
document.getElementById("btnStop").onclick = function () {{ post("/api/stop", {{}}); }};
document.getElementById("btnCalib").onclick = function () {{
  post("/api/calibrate", {{mm_s_at_max_freq: parseFloat(document.getElementById("calib").value)}});
}};

// Dead-man jog: pointerdown шлёт сразу и каждые 200 мс; любое из событий
// отпускания/потери фокуса/скрытия вкладки останавливает таймер и шлёт stop.
// jogPending — промис последнего форварда /api/jog: jogStop дожидается его
// перед /api/stop, чтобы стоп не обогнал в пути к robot чуть более ранний
// jog (ревью Task 2.3b, п.4). jogInFlight пропускает тик таймера, пока
// предыдущий /api/jog ещё не вернулся, — очередь форвардов не копится.
var jogTimer = null;
var jogInFlight = false;
var jogPending = Promise.resolve();
function jogSend(direction) {{
  if (jogInFlight) return;
  jogInFlight = true;
  jogPending = post("/api/jog", {{direction: direction, freq_hz: parseFloat(freqNum.value)}})
    .catch(function () {{}})
    .then(function () {{ jogInFlight = false; }});
}}
function jogStart(direction) {{
  if (jogTimer !== null) return;
  jogSend(direction);
  jogTimer = setInterval(function () {{ jogSend(direction); }}, 200);
}}
function jogStop() {{
  if (jogTimer === null) return;
  clearInterval(jogTimer);
  jogTimer = null;
  jogPending.then(function () {{ return post("/api/stop", {{}}); }});
}}
[["jogFwd", 1], ["jogRev", -1]].forEach(function (pair) {{
  var el = document.getElementById(pair[0]);
  var direction = pair[1];
  el.addEventListener("pointerdown", function () {{ jogStart(direction); }});
  el.addEventListener("pointerup", jogStop);
  el.addEventListener("pointercancel", jogStop);
  el.addEventListener("pointerleave", jogStop);
}});
window.addEventListener("blur", jogStop);
document.addEventListener("visibilitychange", function () {{
  if (document.hidden) jogStop();
}});

function pollStatus() {{
  getStatus().then(function (s) {{
    if (s && s.ok !== false) {{
      beltRunning = (s.run === true);
      // Поле калибровки до этой правки было зашито в HTML (101.1311) и врало о текущем
      // значении: симулятор ехал с mm_s_at_max_freq=300. Подтягиваем из статуса, но НЕ
      // перебиваем поле, пока в нём стоит курсор — иначе опрос затрёт набираемое число.
      var calib = document.getElementById("calib");
      if (document.activeElement !== calib && s.mm_s_at_max_freq !== undefined) {{
        calib.value = s.mm_s_at_max_freq;
      }}
      document.getElementById("status").textContent =
        "encoder=" + s.encoder + "  mm_s=" + s.mm_s + "  run=" + s.run +
        "  freq_hz=" + s.freq_hz + "  reverse=" + s.reverse +
        "  jogging=" + s.jogging + "  mm_s_at_max_freq=" + s.mm_s_at_max_freq;
    }} else {{
      beltRunning = false;
      document.getElementById("status").textContent = "robot не отвечает";
    }}
  }}).catch(function () {{
    document.getElementById("status").textContent = "robot не отвечает";
  }});
}}
setInterval(pollStatus, 250);
pollStatus();

// Журнал заданий (Ф5.1) — только показ, никакой логики подсчёта на пульте:
// счётчики и причины повтора считает SimJournal на стороне robot.
function getJournal() {{
  return fetch("/api/journal").then(function (r) {{
    return r.ok ? r.json() : Promise.reject(new Error("http " + r.status));
  }});
}}
function pollJournal() {{
  getJournal().then(function (j) {{
    if (j && j.status === "ok") {{
      var c = j.counters;
      document.getElementById("journal").textContent =
        "принято " + c.jobs +
        " · повтор той же детали " + c.dups +
        " (та же съёмка " + c.dups_same_capture + " / новый кадр " + c.dups_tracked + ")" +
        " · те же X/Y с новым энкодером " + c.repeats_frozen_xy +
        " · выполнено " + c.done;
    }} else {{
      document.getElementById("journal").textContent = "журнал недоступен";
    }}
  }}).catch(function () {{
    document.getElementById("journal").textContent = "журнал недоступен";
  }});
}}
document.getElementById("btnJournalReset").onclick = function () {{
  post("/api/journal/reset", {{}}).then(pollJournal);
}};
setInterval(pollJournal, 1000);
pollJournal();
</script>
</body>
</html>
"""


class _PultHTTPServer(http.server.ThreadingHTTPServer):
    """``ThreadingHTTPServer`` с расширенным accept-backlog.

    Дефолт ``socketserver.TCPServer.request_queue_size`` — 5: пульт держит
    поток на соединение (см. докстринг модуля), но одновременный опрос
    ``GET /api/status`` (250 мс), удержанная jog-кнопка (200 мс) и открытая
    вкладка ``GET /`` — уже три конкурентных клиента одного браузера, а два
    клиента (владелец + приёмка) удваивают это. На backlog=5 короткий всплеск
    (замер: 20 параллельных ``POST /api/jog`` — сценарий хаzard-теста этого
    пакета) ловит ``ECONNRESET`` ДО того, как обработчик вообще стартовал —
    отказ на уровне TCP accept-очереди, а не HTTP. 32 — с запасом под этот
    стенд (счётные единицы клиентов), не тюнинг под нагрузку.
    """

    request_queue_size = 32


def _build_handler(pult: "PultWebPlugin") -> type[http.server.BaseHTTPRequestHandler]:
    """Фабрика класса-обработчика, замкнутого на плагин (см. докстринг ``mjpeg_sink``).

    Обработчик обращается только к ``pult._client``/``pult._page_bytes`` через
    замыкание — доступа к ``PluginContext`` у него нет, звать ``ctx.log_*``/
    ``record_metric`` с чужого потока незачем (тот же довод, что у ``mjpeg_sink``).
    """

    class _PultHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - сигнатура stdlib
            """Подавить дефолтный access-лог в stderr (не наш log-разъём)."""

        def _host_allowed(self) -> bool:
            """127.0.0.1/localhost на порту сервера — иначе чужой Host (DNS rebinding, ревью п.5)."""
            host_header = self.headers.get("Host", "")
            port = self.server.server_address[1]
            return host_header in (f"127.0.0.1:{port}", f"localhost:{port}")

        def _reply_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        def _dispatch(self, command: str, args: dict) -> None:
            """Форвард команды в ``robot`` и ответ клиенту как есть (DESIGN п.3)."""
            result = pult._client.request(command, args, timeout=pult._timeout_s)
            if not isinstance(result, dict):
                result = {"status": "error", "message": "bad_response"}
            if result.get("status") == "error":
                self._reply_json(504, {"ok": False, "error": result.get("message", "robot_error")})
                return
            self._reply_json(200, result)

        def _read_command_body(self) -> tuple[dict | None, tuple[int, dict] | None]:
            """Прочитать РОВНО ``Content-Length`` байт (не до EOF, см. докстринг модуля).

            Возвращает ``(args, None)`` при успехе либо ``(None, (status, payload))``
            для одного из трёх отказов ДО вызова ``robot`` (DESIGN п.3): 413 —
            размер, до чтения тела; 400 ``bad_json`` — кривой JSON/не dict.
            """
            length_header = self.headers.get("Content-Length")
            try:
                length = int(length_header) if length_header is not None else 0
            except ValueError:
                length = 0
            if length > _MAX_BODY_BYTES:
                return None, (413, {"ok": False, "error": "too_large"})
            raw = self.rfile.read(length) if length else b""
            if not raw.strip():
                return {}, None
            try:
                args = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None, (400, {"ok": False, "error": "bad_json"})
            if not isinstance(args, dict):
                return None, (400, {"ok": False, "error": "bad_json"})
            return args, None

        def do_GET(self) -> None:  # noqa: N802 - имя метода задано stdlib
            if not self._host_allowed():
                self._reply_json(403, {"ok": False, "error": "forbidden_host"})
                return
            if self.path == "/":
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(pult._page_bytes)))
                    self.end_headers()
                    self.wfile.write(pult._page_bytes)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
                return
            if self.path == "/api/status":
                self._dispatch("belt.status", {})
                return
            if self.path == "/api/journal":
                self._dispatch("sim_robot.journal", {})
                return
            self._reply_json(404, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802 - имя метода задано stdlib
            if not self._host_allowed():
                self._reply_json(403, {"ok": False, "error": "forbidden_host"})
                return
            command = _COMMAND_BY_PATH.get(self.path)
            if command is None:
                self._reply_json(404, {"ok": False, "error": "not_found"})
                return
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("application/json"):
                self._reply_json(415, {"ok": False, "error": "unsupported_media_type"})
                return
            args, error = self._read_command_body()
            if error is not None:
                status, payload = error
                self._reply_json(status, payload)
                return
            self._dispatch(command, args)

    return _PultHandler


@register_plugin("pult_web", category="control", description="Веб-пульт ленты — страница + JSON API на 8092")
class PultWebPlugin(ProcessModulePlugin):
    """Side-effect плагин: HTTP-страница + JSON API, форвардящий ``belt.*`` в ``robot``."""

    name = "pult_web"
    category = "control"

    inputs: list = []
    outputs: list = []
    commands: dict = {}

    def configure(self, ctx: PluginContext) -> None:
        """READY: разобрать конфиг, завести клиента и страницу. Сеть здесь не трогаем."""
        self._ctx = ctx
        cfg = ctx.config
        self._host: str = cfg.get("host", _DEFAULT_HOST)
        self._port: int = cfg.get("port", _DEFAULT_PORT)
        self._mjpeg_url: str = cfg.get("mjpeg_url", _DEFAULT_MJPEG_URL)
        self._robot_process: str = cfg.get("robot_process", _DEFAULT_ROBOT_PROCESS)
        self._timeout_s: float = float(cfg.get("timeout_s", _DEFAULT_TIMEOUT_S))

        self._client = DeviceHubClient(ctx, target_process=self._robot_process, default_timeout=self._timeout_s)
        self._page_bytes = _PAGE_TEMPLATE.format(mjpeg_url=self._mjpeg_url).encode("utf-8")

        self._server: http.server.ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._state = "configured"
        self._reason = ""

        ctx.log_info(
            f"pult_web: конфиг принят, {self._host}:{self._port}, robot={self._robot_process}, "
            f"mjpeg_url={self._mjpeg_url}"
        )

    def start(self, ctx: PluginContext) -> None:
        """RUNNING: поднять HTTP-сервер. Отказ (порт занят) не роняет процесс."""
        self._start_server(ctx)

    def shutdown(self, ctx: PluginContext) -> None:
        """STOPPED: остановить сервер симметрично ``start()``."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._server_thread is not None:
            self._server_thread.join(timeout=5.0)
            self._server_thread = None
        self._state = "stopped"
        ctx.log_info("pult_web: остановлен")

    # ------------------------------------------------------------------ #
    # Старт сервера
    # ------------------------------------------------------------------ #

    def _start_server(self, ctx: PluginContext) -> None:
        """Поднять ``ThreadingHTTPServer``. Живой сервер — no-op (повторный ``start``)."""
        if self._server is not None:
            return

        try:
            handler_cls = _build_handler(self)
            server = _PultHTTPServer((self._host, self._port), handler_cls)
        except OSError as exc:  # noqa: BLE001 - деградация, не отказ (см. докстринг модуля)
            self._fail(ctx, exc)
            return

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        self._server = server
        self._server_thread = thread
        self._state = "running"
        self._reason = ""
        ctx.log_info(f"pult_web: сервер поднят на {self._host}:{self._port}")

    def _fail(self, ctx: PluginContext, exc: Exception) -> None:
        """Перевести плагин в ``error``: факт в плоскость ошибок + голос, процесс живёт."""
        self._state = "error"
        self._reason = str(exc)
        ctx.health.report_error(exc, context="pult_web.start", host=self._host, port=self._port)
