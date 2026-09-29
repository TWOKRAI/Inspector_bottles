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

**Task 5.3a — «правда сцены».** Второй ``DeviceHubClient`` (``target_process=
scene_process``, дефолт ``"camera"``) — ``GET /api/truth`` → ``truth.status``,
``POST /api/truth/reset`` → ``truth.reset``, оба ТОЛЬКО в процесс сцены;
``belt.*``/``sim_robot.*`` по-прежнему в ``robot``. Ответ — то же правило, что
у ``/api/journal`` (dict без ``status: "error"`` → 200 как есть, иначе 504).

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
import socket
import threading
import time
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
_DEFAULT_SCENE_PROCESS = "camera"
_DEFAULT_LAYERS_PROCESS = "layers"
_DEFAULT_TIMEOUT_S = 1.0

#: Тело запроса больше этого — 413, ДО чтения (DESIGN п.3 плана).
_MAX_BODY_BYTES = 4096

#: Потолок «доотдачи» тела после РАННЕГО отказа (400/403/404/413/415 — ответ ушёл, тело
#: не читалось), байт. Нужен ТОЛЬКО чтобы закрытие сокета не оборвало уже отправленный
#: ответ RST'ом (Windows: WinError 10053/10054) — не чтобы дочитывать заявленный
#: `Content-Length` (ревью Task 1.2h ит.1, Н1: гигабайт заявлен — ответ не получен).
#: 1 МиБ = вчетверо больше самого большого потолка маршрута (256 КБ у `/api/preset/commit`):
#: байты сверх потолка снова дают RST (замер: потолок 64 КБ при теле 600 КБ — 12 из 100
#: обменов без ответа, при 1 МиБ — 0), а время держит `_DRAIN_TIMEOUT_S`.
_MAX_DRAIN_BYTES = 1_048_576

#: Общий дедлайн «доотдачи» (`_linger_close`), секунды: за это время клиент обязан
#: закрыть свою сторону (обычный клиент делает это сразу после чтения ответа), иначе
#: сокет закрывается как есть. Дедлайн ОБЩИЙ, а не на каждый `recv`: медленная струйка
#: байт не продлевает его. На класс обработчика таймаут НЕ вешается (ревью Task 1.2h
#: ит.2): он резал бы и чтение валидного тела команды.
_DRAIN_TIMEOUT_S = 2.0

#: Путь -> команда ``belt.*`` (DESIGN п.3 плана, HTTP API). Тело форвардится
#: КАК ЕСТЬ — путь не валидирует поля, это дело ``robot`` (Task 2.3a).
_COMMAND_BY_PATH = {
    "/api/run": "belt.run",
    "/api/stop": "belt.stop",
    "/api/jog": "belt.jog",
    "/api/calibrate": "belt.calibrate",
    "/api/journal/reset": "sim_robot.journal_reset",
}

#: Путь -> команда ``truth.*``/``scene.*`` (Task 5.3a §1, Task 6.1b шаг 9) —
#: адресат ТОЛЬКО процесс сцены, не ``robot``. Отдельная карта, чтобы
#: ``do_POST`` мог выбрать правильный клиент (``pult._scene_client``, а не
#: ``pult._client``) по тому, в какой из двух карт нашёлся путь. Тело
#: форвардится КАК ЕСТЬ — та же дисциплина, что у ``_COMMAND_BY_PATH``, вся
#: валидация полей — в плагине сцены (``Plugins/sim/scene_source``).
_SCENE_COMMAND_BY_PATH = {
    "/api/truth/reset": "truth.reset",
    "/api/scene/pause": "scene.pause",
    "/api/scene/flow": "scene.flow",
    "/api/scene/defect_rate": "scene.defect_rate",
    "/api/scene/defect_now": "scene.defect_now",
}

#: POST-маршруты редактора пресета (Task 1.2h) — путь -> (команда, имя атрибута
#: клиента на ``PultWebPlugin``, потолок тела маршрута в байтах (``None`` = общий
#: ``_MAX_BODY_BYTES``), таймаут маршрута в секундах (``None`` = общий
#: ``pult._timeout_s``)). Отдельная таблица НИЖЕ ``_SCENE_COMMAND_BY_PATH`` —
#: ``do_POST`` ищет в ней ПОСЛЕ обеих существующих таблиц. ``preset.commit``
#: несёт пресет целиком (диапазоны по каждому слою) — общий потолок 4 КБ его
#: режет, поднят до 256 КБ только на этот маршрут. ``preset.preview`` рендерит
#: сетку образцов (~88 мс на README ``layer_preview``, до ~1.3 с на крупных
#: спрайтах) — общий таймаут 1.0 с его режет, поднят до 5.0 с только на этот
#: маршрут. ``preset.layout`` (Task 1.3h-a) раскладывает слои пресета по картинкам
#: тем же процессом ``layers`` — тот же таймаут 5.0 с. ``preview`` и ``layout`` с
#: канвы 1.3h-b шлют ТЕКУЩИЙ пресет целиком (``{preset: ...}``), как ``commit``, —
#: тот же потолок 256 КБ (общие 4 КБ резали бы пресет из нескольких слоёв с диапазонами).
#: ``preset.sprites`` (Task 1.3h-c) — список PNG каталога спрайтов, тело ``{}`` (общий
#: потолок 4 КБ), тот же процесс ``layers`` и таймаут 5.0 с, что у ``layout``.
#: ``preset.sprite_put`` (Task 1.3h-d) — загрузка PNG из браузера в base64: потолок 9 МиБ тела (6 МиБ PNG ×4/3 +
#: обвязка), 413 до чтения тела; тот же процесс ``layers`` и таймаут 5.0 с (запись + ``fsync`` + проверка RGBA).
#: Тело форвардится КАК ЕСТЬ — та же дисциплина, что у двух таблиц выше.
_PRESET_ROUTES: dict[str, tuple[str, str, int | None, float | None]] = {
    "/api/preset/commit": ("preset.commit", "_scene_client", 262144, None),
    "/api/preset/preview": ("preset.preview", "_layers_client", 262144, 5.0),
    "/api/preset/layout": ("preset.layout", "_layers_client", 262144, 5.0),
    "/api/preset/sprites": ("preset.sprites", "_layers_client", 4096, 5.0),
    "/api/preset/sprite_put": ("preset.sprite_put", "_layers_client", 9_437_184, 5.0),
}

#: Код ответа команды (``code``) -> HTTP-статус (Находка 2, Task 1.2h). Ответ
#: команды без поля ``code`` (``belt.*``/``sim_robot.*`` — типизированных кодов
#: не отдают) не подпадает под эту таблицу и идёт прежним путём: 504
#: ``{ok: false, error: ...}`` (см. ``_dispatch``). Код вне таблицы -> 400.
_ERROR_CODE_TO_HTTP = {
    "invalid": 400,
    "bad_request": 400,
    "overloaded": 400,
    "conflict": 409,
    "io_error": 500,
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
#presetLayers .selected {{ background: #ffe08a; }}
#presetCanvas {{ border: 1px solid #888; background: #ddd; touch-action: none; cursor: crosshair; }}
#presetCanvas:focus {{ outline: 1px dotted #888; }}
#wire {{ font-family: monospace; font-size: 0.9em; white-space: pre; max-height: 360px;
        overflow-y: auto; border: 1px solid #888; padding: 4px; }}
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

<h2>Что дошло до робота</h2>
<div class="row" id="wire">пока ничего</div>

<h2>Правда сцены</h2>
<div class="row">
  <div id="truth">правда недоступна</div>
  <button id="btnTruthReset">Сброс правды</button>
</div>

<h2>Сцена</h2>
<div class="row">
  <label><input type="checkbox" id="scenePause"> Пауза спавна</label>
</div>
<div class="row">
  <label>Доля брака (0..1):
    <input type="number" id="sceneDefectRate" min="0" max="1" step="0.01" value="0">
  </label>
  <button id="btnSceneDefectRate">Применить</button>
</div>
<div class="row">
  <button id="btnSceneDefectNow">Выпусти брак</button>
</div>
<div class="row">
  <label>Поток:
    <select id="sceneFlowMode">
      <option value="interval_s">interval_s</option>
      <option value="spacing_mm">spacing_mm</option>
    </select>
  </label>
  <label>lo: <input type="number" id="sceneFlowLo" step="0.1" value="2"></label>
  <label>hi: <input type="number" id="sceneFlowHi" step="0.1" value="4"></label>
  <button id="btnSceneFlow">Применить</button>
</div>
<div class="row" id="sceneStatus">сцена недоступна</div>

{preset_section}
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
        " · выполнено " + c.done;
      renderWire(j.wire || []);
    }} else {{
      journalUnavailable();
    }}
  }}).catch(journalUnavailable);
}}
function journalUnavailable() {{
  document.getElementById("journal").textContent = "журнал недоступен";
  document.getElementById("wire").textContent = "журнал недоступен";
}}
// Лента обмена: ◀ записи от ПК (имена регистров из карты), ▶ события робота.
// Свежие сверху; время — секунды назад от самой свежей строки (часы журнала монотонные).
function renderWire(rows) {{
  if (!rows.length) {{ document.getElementById("wire").textContent = "пока ничего"; return; }}
  var last = rows[rows.length - 1].t, lines = [];
  for (var i = rows.length - 1; i >= 0; i--) {{
    var r = rows[i];
    var dir = r.side === "in" ? "◀ " : "▶ ";
    lines.push("-" + (last - r.t).toFixed(2) + " с  " + dir + r.text + (r.n > 1 ? "  ×" + r.n : ""));
  }}
  document.getElementById("wire").textContent = lines.join("\\n");
}}
document.getElementById("btnJournalReset").onclick = function () {{
  post("/api/journal/reset", {{}}).then(pollJournal);
}};
setInterval(pollJournal, 1000);
pollJournal();

// Правда сцены (Ф5.3a) — только показ, никакой логики подсчёта на пульте:
// счётчики считает TruthLedger на стороне camera, пульт показывает counters как есть.
function fmtErr(v) {{
  return (v === null || v === undefined) ? "—" : v.toFixed(2);
}}
function getTruth() {{
  return fetch("/api/truth").then(function (r) {{
    return r.ok ? r.json() : Promise.reject(new Error("http " + r.status));
  }});
}}
function pollTruth() {{
  getTruth().then(function (t) {{
    if (t && t.status === "ok") {{
      var c = t.counters;
      document.getElementById("truth").textContent =
        "поймано " + c.caught + " (брак " + c.caught_defect + " / годных " + c.caught_ok + ")" +
        " · пропущено " + c.missed + " (брак " + c.missed_defect + " / годных " + c.missed_ok + ")" +
        " · лишних заданий " + c.dup_jobs +
        " · ложных тревог " + c.false_alarm + " (повтор кадра " + c.false_alarm_frozen_xy + ")" +
        " · на ленте " + c.on_belt +
        " · ошибка захвата ср " + fmtErr(c.pick_error_mean_mm) + " / макс " + fmtErr(c.pick_error_max_mm) + " мм";
    }} else {{
      document.getElementById("truth").textContent = "правда недоступна";
    }}
  }}).catch(function () {{
    document.getElementById("truth").textContent = "правда недоступна";
  }});
}}
document.getElementById("btnTruthReset").onclick = function () {{
  post("/api/truth/reset", {{}}).then(pollTruth);
}};

// Сцена (Ф6.1b) — четыре ручки командами scene_source готовым механизмом маршрутов
// (_SCENE_COMMAND_BY_PATH -> pult._scene_client -> _dispatch), тот же опрос, что и
// /api/truth (см. ниже, общий setInterval, свой таймер не заводим). Пульт поля не
// валидирует — это дело плагина сцены, тело форвардится как есть.
// Ответ с типизированным code (invalid/overloaded) `_dispatch()` отдаёт как есть
// (1.2h), а с R-4 (2026-09-29) code доходит и живьём — до того `DeviceHubClient`
// терял его, и любой status=="error" схлопывался в HTTP 504 {{ok: false, error}}.
// `isSceneOverloaded` смотрит сперва `code`, резервом — литерал сообщения `_push_control`
// (Plugins/sim/scene_source/plugin.py) на случай отказа без code. overloaded значит
// «не принято» (README scene_source) — страница обязана повторить ту же
// заявку РОВНО один раз, иначе ручка встанет не на последнее значение.
function isSceneOverloaded(resp) {{
  if (!resp || (resp.ok !== false && resp.status !== "error")) {{ return false; }}
  // Три признака: `code` напрямую (Task 1.2h, Находка 2 — `_dispatch()` теперь проносит
  // типизированный код наружу как есть, без обёртки {{ok:false}}), слово "overloaded" в
  // тексте и русский литерал сообщения `_push_control` (резерв на случай отказа без code).
  // Связка literal<->текст закреплена тестом `test_overloaded_literal_matches_scene_source`,
  // поэтому переименование сообщения в scene_source ломает тест, а не молча гасит повтор.
  if (resp.code === "overloaded") {{ return true; }}
  return typeof resp.error === "string" &&
    (resp.error.indexOf("overloaded") !== -1 || resp.error.indexOf("переполнена") !== -1);
}}
var sceneError = "";
function postScene(path, body) {{
  // Повтор РОВНО один и РОВНО на overloaded («заявка не принята»). Любой другой отказ —
  // в том числе таймаут транспорта, где заявка МОГЛА дойти — не повторяем: `defect_now`
  // не идемпотентна, повтор на таймауте выпустил бы два брака вместо одного
  // (находка ревью 6.1b, закреплено test_page_scene_no_retry_on_other_errors).
  return post(path, body).then(function (r) {{
    return isSceneOverloaded(r) ? post(path, body) : r;
  }}).then(function (r) {{
    // Отказ обязан быть ВИДЕН оператору и НЕ пропадать на ближайшем опросе: держим его
    // в `sceneError`, пока не пройдёт следующая заявка. Форма отказа — одна из двух
    // (Task 1.2h, Находка 2): «не дошло» -> {{ok:false, error}}, типизированный отказ ->
    // {{status:"error", code, message}} как есть — читаем текст из того поля, что есть.
    var errText = (r && r.ok === false && r.error) ? String(r.error)
      : (r && r.status === "error" && r.message) ? String(r.message)
      : "";
    sceneError = errText;
    return r;
  }});
}}
function getScene() {{
  return fetch("/api/scene").then(function (r) {{
    return r.ok ? r.json() : Promise.reject(new Error("http " + r.status));
  }});
}}
function sceneUnavailable() {{
  // Отказ обязан быть виден и когда САМА сцена не отвечает: иначе `sceneError` молча
  // ждёт восстановления и всплывает минутами позже, про давно забытое нажатие
  // (находка ревью 6.1b, итерация 2).
  return sceneError ? ("сцена недоступна   отказ сцены: " + sceneError) : "сцена недоступна";
}}
function pollScene() {{
  getScene().then(function (s) {{
    if (s && s.status === "ok") {{
      var mode = Object.keys(s.flow || {{}})[0];
      var flowText = mode ? (mode + " [" + s.flow[mode][0] + ", " + s.flow[mode][1] + "]") : "—";
      document.getElementById("sceneStatus").textContent =
        "пауза=" + s.paused + "  поток=" + flowText +
        "  доля_брака=" + s.defect_probability + "  брак_в_очереди=" + s.force_defect_pending;
      // Галка обязана идти за ДВИЖКОМ, а не за нажатием: отвергнутая заявка иначе
      // оставляла бы пульт в противоречии с самим собой (находка ревью 6.1b).
      document.getElementById("scenePause").checked = !!s.paused;
      if (sceneError) {{
        document.getElementById("sceneStatus").textContent += "   отказ сцены: " + sceneError;
      }}
    }} else {{
      document.getElementById("sceneStatus").textContent = sceneUnavailable();
    }}
  }}).catch(function () {{
    document.getElementById("sceneStatus").textContent = sceneUnavailable();
  }});
}}
document.getElementById("scenePause").onchange = function () {{
  postScene("/api/scene/pause", {{paused: document.getElementById("scenePause").checked}}).then(pollScene);
}};
document.getElementById("btnSceneDefectRate").onclick = function () {{
  postScene("/api/scene/defect_rate", {{
    probability: parseFloat(document.getElementById("sceneDefectRate").value),
  }}).then(pollScene);
}};
document.getElementById("btnSceneDefectNow").onclick = function () {{
  postScene("/api/scene/defect_now", {{}}).then(pollScene);
}};
document.getElementById("btnSceneFlow").onclick = function () {{
  var mode = document.getElementById("sceneFlowMode").value;
  var lo = parseFloat(document.getElementById("sceneFlowLo").value);
  var hi = parseFloat(document.getElementById("sceneFlowHi").value);
  var body = {{}};
  body[mode] = [lo, hi];
  postScene("/api/scene/flow", body).then(pollScene);
}};

// Общий таймер с /api/truth (DESIGN п.4 — свой интервал не заводим).
function pollTruthAndScene() {{
  pollTruth();
  pollScene();
}}
setInterval(pollTruthAndScene, 1000);
pollTruthAndScene();
{preset_script}
</script>
</body>
</html>
"""

#: Раздел «Редактор слоёв» (Task 1.2h) — отдельной константой, не внутри чужих
#: блоков «Правда сцены»/«Сцена» (DESIGN п.4 задачи). Литералы id закреплены
#: планом («Закреплено после слепого тестировщика», 2026-09-28): presetRev,
#: presetLayers, presetEngineWarn, btnPresetPreview, btnPresetSave,
#: btnPresetUndo, presetPreviewImg; канва 1.3h-b — presetCanvas, presetZoom (масштаб
#: в процентах), presetLayoutError (контракт в докстринге
#: ``tests/test_acceptance_1_3h_canvas.py``); список слоёв 1.3h-c — presetSpriteSelect,
#: btnLayerAdd, btnLayerSprite, btnLayerDelete, btnLayerUp, btnLayerDown,
#: btnSpritesRefresh, presetSpritesError (контракт в докстринге
#: ``tests/test_acceptance_1_3h_c_layers.py``). Значение подставляется в ``_PAGE_TEMPLATE``
#: КАК ``.format()``-аргумент (не часть текста, который сам форматируется) —
#: фигурные скобки JS в ``_PRESET_SCRIPT`` ниже удваивать не нужно.
_PRESET_SECTION = """<h2>Редактор слоёв</h2>
<div class="row" id="presetRev">рев.: —</div>
<div class="row" id="presetEngineWarn"></div>
<div class="row" id="presetLayers"></div>
<div class="row">
  <button id="btnPresetPreview">Превью</button>
  <button id="btnPresetSave">Сохранить</button>
  <button id="btnPresetUndo">Отмена</button>
</div>
<div class="row">
  <select id="presetSpriteSelect"></select>
  <input type="file" id="presetSpriteFile" accept="image/png">
  <button id="btnLayerAdd">Добавить слой</button>
  <button id="btnLayerSprite">Заменить картинку</button>
  <button id="btnLayerDelete">Удалить</button>
  <button id="btnLayerUp">Выше</button>
  <button id="btnLayerDown">Ниже</button>
  <button id="btnSpritesRefresh">Обновить список</button>
  <span id="presetSpritesError" style="color: #b00"></span>
</div>
<div class="row">
  <label>Масштаб, %: <input id="presetZoom" type="number" min="10" max="1000" step="10" value="100"></label>
  <span id="presetLayoutError" style="color: #b00"></span>
</div>
<div class="row">
  <canvas id="presetCanvas" width="640" height="480" tabindex="0"></canvas>
  <div>ЛКМ — выбрать и тащить слой; ручки выбранного: круг над рамкой — поворот, угол — масштаб;
    стрелки — 1 px (Shift — 10 px); колесо — масштаб; средняя кнопка или пробел+ЛКМ — панорама</div>
</div>
<div class="row"><img id="presetPreviewImg" alt="превью пресета"></div>"""

#: JS редактора слоёв — тонкий клиент трёх команд ``preset.*`` (1.2a), своего
#: рендера нет: превью — картинка ``png_b64`` от бэкенда как есть. Форма строится
#: из словаря ``preset.get`` по типу значения поля (DESIGN п.4): числа/строки/
#: булевы — обычные поля, поле ``<база>_px`` из двух чисел — два поля ``_x``/``_y``
#: (id первого слоя по X — литерал плана ``layer0_offset_x``), всё остальное
#: (``null``, вложенные объекты вроде ``augment``/``color_rgb``, произвольные
#: массивы) — известный потолок: поле только для чтения, без Pydantic-схемы в
#: ответе команды форму для них не построить (ponytail: путь наверх —
#: ``model_json_schema()`` в ``preset.get``, когда ``scene_source`` освободится).
#: Ответ ``preset.get`` бэкенда несёт 6 ключей (``status, preset, rev, path,
#: class_names, engine``), тестовые двойники — 3 (``status, rev, preset``):
#: код ниже НЕ считает отсутствие ``engine``/``path``/``class_names`` отказом.
_PRESET_SCRIPT = """
var presetState = null;
var presetBaseRev = null;
var presetEngine = undefined;
var presetUndoStack = [];
var presetFieldMap = [];
// Снимок кладётся в стек при ПЕРВОМ изменении формы после последней
// синхронизации (ревью Task 1.2h ит.1, Н2: раньше стек пополнялся только
// перед commit, поэтому «Отмена» без единого сохранения не отменяла ничего —
// зонд ревью: before=0, afterUndo=15). presetDirty сбрасывается в false в
// каждой точке синхронизации формы с состоянием: после начальной загрузки,
// после успешного commit, после самой «Отмены».
var presetDirty = false;

function markPresetDirty() {
  if (!presetDirty) {
    presetUndoStack.push(presetState);
    presetDirty = true;
  }
}

function presetFieldKind(value) {
  if (typeof value === "number") return "number";
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "string") return "string";
  return "json";
}

function presetFieldMarkup(i, key, value) {
  if (key.slice(-3) === "_px" && Array.isArray(value) && value.length === 2) {
    var base = key.slice(0, -3);
    return (
      '<label>' + base + '_x: <input id="layer' + i + '_' + base + '_x" type="number"></label> ' +
      '<label>' + base + '_y: <input id="layer' + i + '_' + base + '_y" type="number"></label> '
    );
  }
  var kind = presetFieldKind(value);
  var type = kind === "boolean" ? "checkbox" : (kind === "number" ? "number" : "text");
  return '<label>' + key + ': <input id="layer' + i + '_' + key + '" type="' + type + '"' +
    (kind === "json" ? " readonly" : "") + '></label> ';
}

// Значения полей читаются заново через getElementById (не хранятся в замыкании
// markup-строки): в браузере innerHTML создаёт реальные элементы под этими id,
// а офлайн-харнесс тестов (page_offline.mjs) создаёт фиктивный элемент под
// ЛЮБОЙ id при первом обращении (находка ревью 5.3a) — обе среды видят одну
// и ту же функцию без разветвления по среде исполнения.
function presetBindField(i, key, value) {
  if (key.slice(-3) === "_px" && Array.isArray(value) && value.length === 2) {
    var base = key.slice(0, -3);
    ["x", "y"].forEach(function (axis, idx) {
      var id = "layer" + i + "_" + base + "_" + axis;
      var el = document.getElementById(id);
      el.value = String(value[idx]);
      el.addEventListener("change", markPresetDirty);
      presetFieldMap.push({ id: id, layerIndex: i, key: key, subIndex: idx, kind: "number" });
    });
    return;
  }
  var kind = presetFieldKind(value);
  var id = "layer" + i + "_" + key;
  var el = document.getElementById(id);
  if (kind === "boolean") {
    el.checked = !!value;
  } else if (kind === "json") {
    el.value = JSON.stringify(value === undefined ? null : value);
  } else {
    el.value = (value === null || value === undefined) ? "" : String(value);
  }
  el.addEventListener("change", markPresetDirty);
  presetFieldMap.push({ id: id, layerIndex: i, key: key, subIndex: null, kind: kind });
}

function renderPresetLayers() {
  presetFieldMap = [];
  var container = document.getElementById("presetLayers");
  var layers = (presetState && presetState.layers) || [];
  container.innerHTML = "";
  layers.forEach(function (layer, i) {
    // Имя слоя — данные пресета, которые страница сама даёт править и
    // коммитит в YAML (петля замкнута) — через textContent, НЕ innerHTML
    // (ревью Task 1.2h ит.1, Н3: конкатенация строки пускала <img
    // onerror=...> в разметку сырым). Остальная часть строки (лейблы полей,
    // ключи схемы) — не данные пресета, свои имена задаёт не оператор,
    // поэтому остаётся строкой через presetFieldMarkup.
    var row = document.createElement("div");
    row.className = "row";
    var nameEl = document.createElement("b");
    nameEl.textContent = layer.name || ("слой " + i);
    row.appendChild(nameEl);
    row.appendChild(document.createTextNode(" "));
    var fieldsHtml = "";
    Object.keys(layer).forEach(function (key) {
      fieldsHtml += presetFieldMarkup(i, key, layer[key]);
    });
    var fields = document.createElement("span");
    fields.innerHTML = fieldsHtml;
    row.appendChild(fields);
    container.appendChild(row);
  });
  layers.forEach(function (layer, i) {
    Object.keys(layer).forEach(function (key) {
      presetBindField(i, key, layer[key]);
    });
  });
  presetUpdateSelection();
}

function updatePresetRevDisplay() {
  var haveRev = presetBaseRev !== null && presetBaseRev !== undefined;
  document.getElementById("presetRev").textContent = haveRev
    ? "рев.: " + presetBaseRev
    : "рев.: нет (пресет собран из каталога \\u2014 сохранение недоступно)";
  document.getElementById("btnPresetSave").disabled = !haveRev;
}

function updatePresetEngineWarn() {
  // engine === false -> собран старый движок, commit запишет файл, но правка
  // приедет на ленту только после перезапуска (DESIGN, закреплено планом
  // 2026-09-28). engine отсутствует (двойники тестов) -> "неизвестно", не
  // предупреждаем — иначе редактор врал бы о состоянии, которого не проверял.
  document.getElementById("presetEngineWarn").textContent =
    presetEngine === false
      ? "движок не собран: правка запишется в файл, но на ленте появится только после перезапуска"
      : "";
}

function getPreset() {
  return fetch("/api/preset").then(function (r) { return r.json(); });
}

function loadPreset() {
  return getPreset().then(function (resp) {
    if (resp && resp.status === "ok") {
      presetState = resp.preset;
      presetBaseRev = (resp.rev === undefined) ? null : resp.rev;
      presetEngine = resp.engine;
      presetUndoStack = [];
      presetDirty = false;
      presetSelected = null;
      renderPresetLayers();
      updatePresetRevDisplay();
      updatePresetEngineWarn();
      requestPresetLayout();
    } else {
      document.getElementById("presetRev").textContent = "пресет недоступен";
    }
  }).catch(function () {
    document.getElementById("presetRev").textContent = "пресет недоступен";
  });
}

// Undo — стек словарей в браузере (DESIGN): на бэкенд при отмене ничего не
// уходит, откат — это повторный рендер presetState из стека.
function collectPresetFromFields() {
  var next = JSON.parse(JSON.stringify(presetState));
  presetFieldMap.forEach(function (f) {
    var layer = next.layers[f.layerIndex];
    var el = document.getElementById(f.id);
    var parsed = f.kind === "boolean" ? el.checked : el.value;
    if (f.kind === "number") parsed = parseFloat(parsed);
    if (f.kind === "json") {
      try {
        parsed = JSON.parse(parsed);
      } catch (e) {
        parsed = f.subIndex === null ? layer[f.key] : layer[f.key][f.subIndex];
      }
    }
    if (f.subIndex === null) {
      layer[f.key] = parsed;
    } else {
      layer[f.key][f.subIndex] = parsed;
    }
  });
  return next;
}

document.getElementById("btnPresetPreview").onclick = function () {
  post("/api/preset/preview", { preset: collectPresetFromFields() }).then(function (r) {
    if (r && r.png_b64) {
      document.getElementById("presetPreviewImg").src = "data:image/png;base64," + r.png_b64;
    }
  });
};

document.getElementById("btnPresetSave").onclick = function () {
  if (presetBaseRev === null || presetBaseRev === undefined) return; // rev==null -> писать некуда
  var nextPreset = collectPresetFromFields();
  post("/api/preset/commit", { preset: nextPreset, base_rev: presetBaseRev }).then(function (r) {
    if (r && r.code === "conflict") {
      // П5: правку НЕ теряем (поля не перерисовываем), current_rev запоминаем
      // как новый base_rev для повторного «Сохранить».
      presetBaseRev = r.current_rev;
      document.getElementById("presetRev").textContent =
        "конфликт: пресет изменили параллельно, правка на экране сохранена, повторите «Сохранить»";
      return;
    }
    if (r && r.status === "ok" && r.rev) {
      // Снимок в стек кладёт markPresetDirty при правке поля (Н2), не здесь —
      // сохранение лишь двигает точку синхронизации вперёд.
      presetState = nextPreset;
      presetBaseRev = r.rev;
      presetDirty = false;
      updatePresetRevDisplay();
      return;
    }
    document.getElementById("presetRev").textContent =
      "ошибка сохранения: " + ((r && (r.message || r.error)) || "неизвестно");
  });
};

document.getElementById("btnPresetUndo").onclick = function () {
  if (!presetUndoStack.length) return;
  presetState = presetUndoStack.pop();
  presetDirty = false;
  // «Добавить» -> «Отмена» убирает выбранный слой: выбор на исчезнувшее имя молча «оживёт» у слоя, которому
  // потом дадут это имя (1.3h-c-fix, F2). Сверка — по presetState, НЕ presetLayerIndex: та накладывает поля
  // формы (ещё старой, длиннее состояния) по индексу и упала бы до renderPresetLayers.
  if (presetSelected !== null && !presetState.layers.some(function (ly) { return ly.name === presetSelected; })) {
    presetSelected = null;
  }
  renderPresetLayers();
  requestPresetLayout();
};

// ---------------------------------------------------------------------------
// Канва редактора слоёв (Task 1.3h-b). Своего рендера нет: слои — PNG бэкенда из
// POST /api/preset/layout (тело — ТЕКУЩЕЕ состояние правки), каждый ставится левым
// верхним углом в origin_px (из center_px не пересчитывается). Контракт — докстринг
// tests/test_acceptance_1_3h_canvas.py. Экран <-> объект:
//   экран = центр канвы + (объект - canvas_px/2 + пан) * z
// Пан хранится в px ОБЪЕКТА — поэтому масштаб всегда вокруг центра канвы.
// Во время жеста сдвиг — готовый битмап со смещением; поворот/масштаб — пунктирная
// рамка-призрак, перерисовку слоя делает бэкенд после отпускания.
// ---------------------------------------------------------------------------
var presetCanvas = document.getElementById("presetCanvas");
var presetZoomInput = document.getElementById("presetZoom");
var presetLayout = null;    // последняя ПРИНЯТАЯ раскладка: {cw, ch, layers: [{name, img, hit, x, y, w, h}]}
var presetLayoutSeq = 0;    // номер правки/запроса (растёт и на стрелке, F1): старый ответ не принят
var presetSelected = null;  // имя выбранного слоя пресета (null — ничего)
var presetGesture = null;   // жест указателя: {kind: move|rotate|scale|pan, name, id, start, cur, center}
var presetZoom = 1;
var presetPan = [0, 0];
var presetSpaceHeld = false;
var presetDrawPending = false;
var presetLayoutTimer = null; // отложенный запрос раскладки после серии стрелок
var PRESET_KEY_LAYOUT_MS = 200; // пауза после последней стрелки; preset.layout на слое 1200 px — 50-90 мс
var PRESET_HANDLE_PX = 8;   // полуразмер ручки на экране
var PRESET_ROT_ARM_PX = 24; // вынос ручки поворота над рамкой

// Имя ищется в ПОЛЯХ формы (collectPresetFromFields) — тот же источник, что и тело
// запроса раскладки: слой, переименованный в форме, на канве приходит уже с новым
// именем, а presetState ещё со старым (ревью 1.3h-b ит.1, MINOR-3).
function presetLayerIndex(name) {
  var layers = presetState ? collectPresetFromFields().layers : [];
  for (var i = 0; i < layers.length; i++) {
    if (layers[i].name === name) return i;
  }
  return -1;
}

function presetLayoutEntry(name) {
  if (!presetLayout) return null;
  for (var i = 0; i < presetLayout.layers.length; i++) {
    if (presetLayout.layers[i].name === name) return presetLayout.layers[i];
  }
  return null;
}

// Подсветка строки формы выбранного слоя (строка i <-> presetState.layers[i]).
function presetUpdateSelection() {
  var rows = document.getElementById("presetLayers").children || [];
  var idx = presetSelected === null ? -1 : presetLayerIndex(presetSelected);
  for (var i = 0; i < rows.length; i++) rows[i].classList.toggle("selected", i === idx);
}

function presetShowLayoutError(text) {
  document.getElementById("presetLayoutError").textContent = text;
}

function presetToScreen(ox, oy) {
  var L = presetLayout;
  return [
    presetCanvas.width / 2 + (ox - L.cw / 2 + presetPan[0]) * presetZoom,
    presetCanvas.height / 2 + (oy - L.ch / 2 + presetPan[1]) * presetZoom,
  ];
}

function presetToObject(sx, sy) {
  var L = presetLayout;
  return [
    (sx - presetCanvas.width / 2) / presetZoom - presetPan[0] + L.cw / 2,
    (sy - presetCanvas.height / 2) / presetZoom - presetPan[1] + L.ch / 2,
  ];
}

// offsetX/Y — CSS px; если канву растянули стилем, приводим к px битмапа.
function presetPointerXY(e) {
  var kx = presetCanvas.width / (presetCanvas.clientWidth || presetCanvas.width);
  var ky = presetCanvas.height / (presetCanvas.clientHeight || presetCanvas.height);
  return [e.offsetX * kx, e.offsetY * ky];
}

// Сдвиг слоя жестом «перенос» в px объекта (для рисования во время жеста).
function presetMoveShift(name) {
  var g = presetGesture;
  if (!g || g.kind !== "move" || g.name !== name) return [0, 0];
  return [(g.cur[0] - g.start[0]) / presetZoom, (g.cur[1] - g.start[1]) / presetZoom];
}

// Поворот (градусы, CCW при оси Y вниз — как _rotate в line_sim) и множитель
// масштаба жеста ручкой — относительно центра рамки на момент нажатия.
function presetHandleDelta(g) {
  var sx = g.start[0] - g.center[0], sy = g.start[1] - g.center[1];
  var cx = g.cur[0] - g.center[0], cy = g.cur[1] - g.center[1];
  var d = -(Math.atan2(cy, cx) - Math.atan2(sy, sx)) * 180 / Math.PI;
  while (d > 180) d -= 360;
  while (d <= -180) d += 360;
  var r0 = Math.sqrt(sx * sx + sy * sy);
  var k = r0 > 0 ? Math.sqrt(cx * cx + cy * cy) / r0 : 1;
  return { angle: g.kind === "rotate" ? d : 0, k: g.kind === "scale" ? k : 1 };
}

// Рамка выбранного слоя и ручки в экранных px (null — нечего показывать).
function presetHandles() {
  var ly = presetSelected === null ? null : presetLayoutEntry(presetSelected);
  if (!ly) return null;
  var d = presetMoveShift(ly.name);
  var a = presetToScreen(ly.x + d[0], ly.y + d[1]);
  var b = presetToScreen(ly.x + d[0] + ly.w, ly.y + d[1] + ly.h);
  var cx = (a[0] + b[0]) / 2, cy = (a[1] + b[1]) / 2;
  return { x0: a[0], y0: a[1], x1: b[0], y1: b[1], cx: cx, cy: cy,
           rot: [cx, a[1] - PRESET_ROT_ARM_PX], scale: [b[0], b[1]] };
}

function presetNear(p, q) {
  return Math.abs(p[0] - q[0]) <= PRESET_HANDLE_PX && Math.abs(p[1] - q[1]) <= PRESET_HANDLE_PX;
}

// Выбор по альфе: сверху вниз, первый слой с alpha > 0 под курсором (не по bbox).
function presetHitLayer(sx, sy) {
  if (!presetLayout) return null;
  var o = presetToObject(sx, sy);
  for (var i = presetLayout.layers.length - 1; i >= 0; i--) {
    var ly = presetLayout.layers[i];
    var u = Math.floor(o[0] - ly.x), v = Math.floor(o[1] - ly.y);
    if (u < 0 || v < 0 || u >= ly.w || v >= ly.h) continue;
    if (ly.hit.getImageData(u, v, 1, 1).data[3] > 0) return ly.name;
  }
  return null;
}

function presetDraw() {
  presetDrawPending = false;
  var ctx = presetCanvas.getContext("2d");
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, presetCanvas.width, presetCanvas.height);
  if (!presetLayout) return;
  var L = presetLayout, z = presetZoom;
  ctx.setTransform(z, 0, 0, z,
    presetCanvas.width / 2 + (presetPan[0] - L.cw / 2) * z,
    presetCanvas.height / 2 + (presetPan[1] - L.ch / 2) * z);
  L.layers.forEach(function (ly) {
    var d = presetMoveShift(ly.name);
    ctx.drawImage(ly.img, ly.x + d[0], ly.y + d[1]);
  });
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  var h = presetHandles();
  if (!h) return;
  ctx.strokeStyle = "#f80";
  ctx.lineWidth = 1;
  ctx.strokeRect(h.x0, h.y0, h.x1 - h.x0, h.y1 - h.y0);
  ctx.beginPath();
  ctx.moveTo(h.cx, h.y0);
  ctx.lineTo(h.rot[0], h.rot[1]);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(h.rot[0], h.rot[1], PRESET_HANDLE_PX, 0, 2 * Math.PI);
  ctx.stroke();
  var hs = PRESET_HANDLE_PX;
  ctx.strokeRect(h.scale[0] - hs, h.scale[1] - hs, 2 * hs, 2 * hs);
  var g = presetGesture;
  if (g && (g.kind === "rotate" || g.kind === "scale")) {
    var t = presetHandleDelta(g);
    ctx.save();
    ctx.translate(g.center[0], g.center[1]);
    ctx.rotate(-t.angle * Math.PI / 180);
    ctx.scale(t.k, t.k);
    ctx.setLineDash([4, 4]);
    ctx.strokeRect(h.x0 - h.cx, h.y0 - h.cy, h.x1 - h.x0, h.y1 - h.y0);
    ctx.setLineDash([]);
    ctx.restore();
  }
}

function presetScheduleDraw() {
  if (presetDrawPending) return;
  presetDrawPending = true;
  requestAnimationFrame(presetDraw);
}

function requestPresetLayout() {
  if (!presetState) return;
  var seq = ++presetLayoutSeq;
  fetch("/api/preset/layout", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ preset: collectPresetFromFields() }),
  }).then(function (r) {
    return r.json().then(
      function (data) { return { http: r.status, data: data }; },
      function () { return { http: r.status, data: null }; });
  }).then(function (res) {
    if (seq !== presetLayoutSeq) return;
    var d = res.data;
    if (res.http !== 200 || !d || d.status !== "ok" || !Array.isArray(d.layers) || !Array.isArray(d.canvas_px)) {
      presetShowLayoutError("раскладка не получена (HTTP " + res.http + "): " +
        ((d && (d.message || d.error || d.code)) || "ответ без раскладки"));
      return;
    }
    var entries = d.layers.map(function (ly) {
      var img = new Image();
      img.src = "data:image/png;base64," + ly.png_b64;
      return { name: ly.name, img: img, x: ly.origin_px[0], y: ly.origin_px[1] };
    });
    return Promise.all(entries.map(function (en) { return en.img.decode(); })).then(function () {
      if (seq !== presetLayoutSeq) return;
      entries.forEach(function (en) {
        en.w = en.img.naturalWidth || en.img.width;
        en.h = en.img.naturalHeight || en.img.height;
        var hitCanvas = document.createElement("canvas");
        hitCanvas.width = en.w;
        hitCanvas.height = en.h;
        en.hit = hitCanvas.getContext("2d");
        en.hit.drawImage(en.img, 0, 0);
      });
      presetLayout = { cw: d.canvas_px[0], ch: d.canvas_px[1], layers: entries };
      presetShowLayoutError("");
      presetScheduleDraw();
    });
  }).catch(function (err) {
    if (seq === presetLayoutSeq) presetShowLayoutError("раскладка не получена: " + err);
  });
}

// Правка слоя с канвы: снимок ТЕКУЩЕЙ правки (с ненажатым «Сохранить» вводом в
// полях) — ровно одна запись «Отмена» на жест/нажатие, затем форма из нового
// состояния. presetDirty = false: форма только что синхронизирована с presetState,
// значит следующий ввод в поле положит СВОЙ снимок (markPresetDirty 1.2h как есть).
// Правка без изменения (клик без движения) — ни записи, ни запроса раскладки.
// deferLayout (стрелки): запись «Отмена», форма и битмап — на каждое нажатие, а раскладку
// просят ОДИН раз после паузы PRESET_KEY_LAYOUT_MS (серия из 20 нажатий = 1 запрос, не 20).
// Жест (deferLayout не задан) просит сразу и снимает висящий таймер стрелок.
function presetApplyEdit(name, mutate, deferLayout) {
  var idx = presetLayerIndex(name);
  if (idx < 0) return;
  var snapshot = collectPresetFromFields();
  var next = JSON.parse(JSON.stringify(snapshot));
  mutate(next.layers[idx]);
  if (JSON.stringify(next) === JSON.stringify(snapshot)) return;
  presetUndoStack.push(snapshot);
  presetState = next;
  presetDirty = false;
  renderPresetLayers();
  // готовый битмап сдвигается сразу, не дожидаясь ответа раскладки
  var before = snapshot.layers[idx].offset_px || [0, 0], after = next.layers[idx].offset_px || [0, 0];
  var ly = presetLayoutEntry(name);
  if (ly) {
    ly.x += after[0] - before[0];
    ly.y += after[1] - before[1];
  }
  presetScheduleDraw();
  if (presetLayoutTimer !== null) {
    clearTimeout(presetLayoutTimer);
    presetLayoutTimer = null;
  }
  // ответ раскладки на прошлый жест, ещё летящий, не должен затереть битмап, уже сдвинутый стрелкой
  if (deferLayout) ++presetLayoutSeq;
  if (deferLayout) presetLayoutTimer = setTimeout(function () {
    presetLayoutTimer = null;
    requestPresetLayout();
  }, PRESET_KEY_LAYOUT_MS);
  else requestPresetLayout();
}

// Правка СОСТАВА слоёв (Task 1.3h-c: добавить / удалить / выше / ниже / заменить картинку) —
// брат presetApplyEdit: та же одна запись «Отмена» (снимок ТЕКУЩЕЙ правки, с полями формы),
// та же форма из нового состояния и тот же запрос раскладки. Отличия: правится массив слоёв
// целиком (mutate(layers) может ещё выставить presetSelected — рендер идёт ПОСЛЕ него),
// битмапа для сдвига нет, а запрос раскладки всегда немедленный и снимает висящий таймер
// стрелок: запрос уйдёт с составом, в котором стрелки уже учтены (presetState их хранит),
// а ++presetLayoutSeq в нём глушит ещё летящий ответ на старый состав. Ничего не
// изменившая операция — ни записи «Отмена», ни запроса.
function presetApplyLayersEdit(mutate) {
  if (!presetState) return;
  var snapshot = collectPresetFromFields();
  var next = JSON.parse(JSON.stringify(snapshot));
  mutate(next.layers);
  if (JSON.stringify(next) === JSON.stringify(snapshot)) return;
  presetUndoStack.push(snapshot);
  presetState = next;
  presetDirty = false;
  renderPresetLayers();
  presetScheduleDraw();
  if (presetLayoutTimer !== null) {
    clearTimeout(presetLayoutTimer);
    presetLayoutTimer = null;
  }
  requestPresetLayout();
}

function presetShiftLayer(name, dx, dy, round, deferLayout) {
  presetApplyEdit(name, function (layer) {
    var off = Array.isArray(layer.offset_px) ? layer.offset_px : [0, 0];
    var x = off[0] + dx, y = off[1] + dy;
    layer.offset_px = round ? [Math.round(x), Math.round(y)] : [x, y];
  }, deferLayout);
}

function presetFinishGesture(g) {
  if (g.kind === "move") {
    // ponytail: offset_px округляется до целого px — при зуме > 100 % полпикселя мышью не задать (стрелки — 1 px)
    presetShiftLayer(g.name, (g.cur[0] - g.start[0]) / presetZoom, (g.cur[1] - g.start[1]) / presetZoom, true);
    return;
  }
  var t = presetHandleDelta(g);
  presetApplyEdit(g.name, function (layer) {
    if (g.kind === "rotate") {
      var a = (typeof layer.angle_deg === "number" ? layer.angle_deg : 0) + t.angle;
      while (a > 180) a -= 360;
      while (a <= -180) a += 360;
      layer.angle_deg = Math.round(a * 10) / 10;
    } else {
      var s = (typeof layer.scale === "number" ? layer.scale : 1) * t.k;
      layer.scale = Math.max(0.05, Math.round(s * 1000) / 1000);
    }
  });
}

function presetTrack(g, p) {
  if (g.kind === "pan") {
    presetPan = [presetPan[0] + (p[0] - g.cur[0]) / presetZoom, presetPan[1] + (p[1] - g.cur[1]) / presetZoom];
  }
  g.cur = p;
}

presetCanvas.addEventListener("pointerdown", function (e) {
  // preventDefault ниже гасит и смену фокуса: без явного focus() пробел (панорама) нажал бы кнопку формы
  if (presetCanvas.focus) presetCanvas.focus({ preventScroll: true });
  if (!presetLayout || presetGesture) return;
  var p = presetPointerXY(e);
  var kind = null, h = null;
  if (e.button === 1 || (e.button === 0 && presetSpaceHeld)) {
    kind = "pan";
  } else if (e.button === 0) {
    h = presetHandles();
    if (h && presetNear(p, h.rot)) kind = "rotate";
    else if (h && presetNear(p, h.scale)) kind = "scale";
    else {
      var hit = presetHitLayer(p[0], p[1]);
      presetSelected = hit !== null && presetLayerIndex(hit) >= 0 ? hit : null; // авто-слой base не правится
      presetUpdateSelection();
      presetScheduleDraw();
      if (presetSelected !== null) kind = "move";
    }
  }
  if (!kind) return;
  if (e.preventDefault) e.preventDefault();
  presetGesture = { kind: kind, name: presetSelected, id: e.pointerId, start: p, cur: p,
                    center: h ? [h.cx, h.cy] : null };
  try { presetCanvas.setPointerCapture(e.pointerId); } catch (err) { /* указатель уже ушёл */ }
});

presetCanvas.addEventListener("pointermove", function (e) {
  var g = presetGesture;
  if (!g || e.pointerId !== g.id) return;
  presetTrack(g, presetPointerXY(e));
  presetScheduleDraw();
});

presetCanvas.addEventListener("pointerup", function (e) {
  var g = presetGesture;
  if (!g || e.pointerId !== g.id) return;
  presetTrack(g, presetPointerXY(e));
  presetGesture = null;
  try { presetCanvas.releasePointerCapture(e.pointerId); } catch (err) { /* уже отпущен */ }
  if (g.kind !== "pan" && (g.cur[0] !== g.start[0] || g.cur[1] !== g.start[1])) presetFinishGesture(g);
  presetScheduleDraw();
});

// Отмена жеста системой (pointercancel) или потеря захвата до pointerup: правка не применяется.
function presetCancelGesture(e) {
  var g = presetGesture;
  if (!g || (e && e.pointerId !== undefined && e.pointerId !== g.id)) return;
  presetGesture = null;
  presetScheduleDraw();
}
presetCanvas.addEventListener("pointercancel", presetCancelGesture);
presetCanvas.addEventListener("lostpointercapture", presetCancelGesture);

function presetSetZoomPct(pct) {
  if (!(pct > 0)) return; // пусто/0/мусор — масштаб прежний
  presetZoom = Math.min(1000, Math.max(10, pct)) / 100;
  presetScheduleDraw();
}
presetZoomInput.addEventListener("input", function () { presetSetZoomPct(parseFloat(presetZoomInput.value)); });
presetZoomInput.addEventListener("change", function () { presetSetZoomPct(parseFloat(presetZoomInput.value)); });

// Колесо — масштаб вокруг центра канвы (как поле presetZoom), поле идёт следом.
presetCanvas.addEventListener("wheel", function (e) {
  if (!e.deltaY) return;
  if (e.preventDefault) e.preventDefault();
  var pct = Math.round(Math.min(1000, Math.max(10, presetZoom * 100 * (e.deltaY < 0 ? 1.25 : 0.8))));
  presetZoomInput.value = String(pct);
  presetSetZoomPct(pct);
}, { passive: false });

// Пробел — панорама только когда источник — канва или страница: на кнопке/ссылке/поле
// пробел принадлежит элементу (нажатие кнопки, ввод) — флаг не ставим, preventDefault не зовём.
function presetSpaceOnCanvas(e) {
  return !e.target || e.target === presetCanvas || e.target === document.body;
}

function presetKeyFromField(e) {
  var tag = e && e.target && e.target.tagName ? String(e.target.tagName).toUpperCase() : "";
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

var PRESET_ARROWS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

document.addEventListener("keydown", function (e) {
  if (presetKeyFromField(e)) return; // стрелки в поле ввода — поля, не слоя
  if (e.key === " " || e.code === "Space") {
    if (!presetSpaceOnCanvas(e)) return;
    if (e.preventDefault) e.preventDefault(); // без этого пробел прокручивает страницу
    presetSpaceHeld = true;
    return;
  }
  if (!Object.prototype.hasOwnProperty.call(PRESET_ARROWS, e.key) || presetSelected === null) return;
  if (e.preventDefault) e.preventDefault();
  var step = e.shiftKey ? 10 : 1, d = PRESET_ARROWS[e.key];
  presetShiftLayer(presetSelected, d[0] * step, d[1] * step, false, true);
});
document.addEventListener("keyup", function (e) {
  if (e.key === " " || e.code === "Space") presetSpaceHeld = false;
});
window.addEventListener("blur", function () { presetSpaceHeld = false; });

// Ввод в поле формы — раскладка по новому состоянию (change всплывает до контейнера).
document.getElementById("presetLayers").addEventListener("change", function () { requestPresetLayout(); });

// ---------------------------------------------------------------------------
// Состав слоёв (Task 1.3h-c): список PNG от POST /api/preset/sprites и пять операций над
// presetState (каждая — одна запись «Отмена» и один запрос раскладки, presetApplyLayersEdit).
// Имена файлов — ДАННЫЕ: в <option> они идут через textContent/value, не через innerHTML.
// ---------------------------------------------------------------------------
var PRESET_CLASS_SOURCE = "class://";
var PRESET_CLASS_ENTRY = { path: PRESET_CLASS_SOURCE, sprite_source: PRESET_CLASS_SOURCE };
var PRESET_RESERVED_NAMES = ["base", "damaged"]; // имена авто-слоёв раскладки
var presetSpriteEntries = [];   // файлы последнего принятого списка: [{path, sprite_source}]
var presetLayerTemplate = null; // layer_template последнего принятого списка

function presetShowSpritesError(text) {
  document.getElementById("presetSpritesError").textContent = text;
}

// Пересобирает <select>: пункт class:// и файлы; прежний выбор сохраняется, если пункт остался.
function presetFillSpriteSelect() {
  var sel = document.getElementById("presetSpriteSelect");
  var keep = sel.value;
  sel.textContent = "";
  function add(value, text) {
    var opt = document.createElement("option");
    opt.value = value;
    opt.textContent = text;
    sel.appendChild(opt);
  }
  add(PRESET_CLASS_SOURCE, "спрайт класса (class://)");
  presetSpriteEntries.forEach(function (en) { add(en.sprite_source, en.path); });
  for (var i = 0; i < sel.options.length; i++) {
    if (sel.options[i].value === keep) sel.selectedIndex = i;
  }
}

function presetLoadSprites() {
  return post("/api/preset/sprites", {}).then(function (r) {
    if (!r || r.status !== "ok" || !Array.isArray(r.files)) {
      var why = (r && (r.message || r.error || r.code)) || "ответ без списка";
      presetShowSpritesError("список спрайтов не получен: " + why);
      return;
    }
    presetSpriteEntries = r.files;
    presetLayerTemplate = r.layer_template || null;
    presetFillSpriteSelect();
    presetShowSpritesError(r.truncated ? "показаны первые " + r.files.length : "");
  }).catch(function (err) {
    presetShowSpritesError("список спрайтов не получен: " + err);
  });
}

// Запись списка, выбранная в <select> (по value = sprite_source); null — пусто/неизвестно.
function presetSelectedSpriteEntry() {
  var value = document.getElementById("presetSpriteSelect").value;
  if (value === PRESET_CLASS_SOURCE) return PRESET_CLASS_ENTRY;
  for (var i = 0; i < presetSpriteEntries.length; i++) {
    if (presetSpriteEntries[i].sprite_source === value) return presetSpriteEntries[i];
  }
  return null;
}

// Основа имени файла (последний компонент path без расширения); `class` для class://.
function presetLayerStem(entry) {
  if (entry.sprite_source === PRESET_CLASS_SOURCE) return "class";
  var file = String(entry.path).split("/").pop();
  var dot = file.lastIndexOf(".");
  return (dot > 0 ? file.slice(0, dot) : file) || "layer";
}

// Занято (слой пресета или авто-слой) -> _2, _3, ... Массив, не объект: имя может быть "constructor".
function presetUniqueLayerName(stem, layers) {
  var taken = PRESET_RESERVED_NAMES.concat(layers.map(function (ly) { return ly.name; }));
  var name = stem;
  for (var n = 2; taken.indexOf(name) >= 0; n++) name = stem + "_" + n;
  return name;
}

// Принимает ЗАПИСЬ СПИСКА {path, sprite_source}, не <select>: загрузка PNG (1.3h-d) отдаст ответ той же формы.
function presetAddLayer(entry) {
  if (!presetState) return;
  if (!presetLayerTemplate) {
    presetShowSpritesError("нет шаблона слоя: обновите список спрайтов");
    return;
  }
  presetApplyLayersEdit(function (layers) {
    var layer = JSON.parse(JSON.stringify(presetLayerTemplate));
    layer.name = presetUniqueLayerName(presetLayerStem(entry), layers);
    layer.sprite_source = entry.sprite_source;
    layers.push(layer); // в конец = рисуется поверх
    presetSelected = layer.name;
  });
}

// Индекс выбранного слоя в ТЕКУЩЕЙ правке; -1 — ничего не выбрано (тогда кнопки — no-op).
function presetSelectedIndex() {
  return presetSelected === null ? -1 : presetLayerIndex(presetSelected);
}

function presetDeleteLayer() {
  var idx = presetSelectedIndex();
  if (idx < 0) return;
  if (presetGesture) presetCancelGesture(); // тащат слой, который сейчас исчезнет: жест без записи «Отмена»
  presetApplyLayersEdit(function (layers) {
    layers.splice(idx, 1);
    presetSelected = null;
  });
}

// delta +1 — «Выше» (к концу списка, рисуется поверх), -1 — «Ниже». У края — no-op.
function presetMoveLayer(delta) {
  var idx = presetSelectedIndex();
  if (idx < 0) return;
  presetApplyLayersEdit(function (layers) {
    var to = idx + delta;
    if (to < 0 || to >= layers.length) return;
    var moved = layers.splice(idx, 1)[0];
    layers.splice(to, 0, moved);
  });
}

function presetReplaceSprite(entry) {
  var idx = presetSelectedIndex();
  if (idx < 0 || !entry) return;
  presetApplyLayersEdit(function (layers) {
    layers[idx].sprite_source = entry.sprite_source;
  });
}

document.getElementById("btnLayerAdd").onclick = function () {
  var entry = presetSelectedSpriteEntry();
  if (entry) presetAddLayer(entry);
};
document.getElementById("btnLayerSprite").onclick = function () { presetReplaceSprite(presetSelectedSpriteEntry()); };
document.getElementById("btnLayerDelete").onclick = presetDeleteLayer;
document.getElementById("btnLayerUp").onclick = function () { presetMoveLayer(1); };
document.getElementById("btnLayerDown").onclick = function () { presetMoveLayer(-1); };
document.getElementById("btnSpritesRefresh").onclick = function () { presetLoadSprites(); };

// Загрузка PNG (1.3h-d): файл -> base64 без префикса data:...;base64, -> sprite_put -> слой из ответа.
// Успех — только `ok` И `file`; всё прочее — текст в presetSpritesError, слой не добавляется.
function presetUploadFail(text) { presetShowSpritesError("загрузка не удалась: " + text); }
var presetSpriteFileInput = document.getElementById("presetSpriteFile");
presetSpriteFileInput.addEventListener("change", function () {
  var file = presetSpriteFileInput.files && presetSpriteFileInput.files[0];
  if (!file) return;
  function done() {
    presetSpriteFileInput.value = ""; // тот же файл можно выбрать снова
    if (presetCanvas.focus) presetCanvas.focus({ preventScroll: true }); // не оставлять фокус на контроле (F1 1.3h-c)
  }
  var reader = new FileReader();
  reader.onerror = function () { presetUploadFail("файл не прочитан"); done(); };
  reader.onload = function () {
    var url = String(reader.result);
    var png_b64 = url.slice(url.indexOf(",") + 1);
    post("/api/preset/sprite_put", { name: file.name, png_b64: png_b64 }).then(function (r) {
      if (r && r.status === "ok" && r.file) {
        presetLoadSprites();
        presetAddLayer(r.file);
      } else {
        presetUploadFail((r && (r.message || r.error || r.code)) || "ответ без файла");
      }
    }).catch(function (err) {
      presetUploadFail(String(err));
    }).then(done);
  };
  reader.readAsDataURL(file);
});

// После кнопки редактора фокус — канве (1.3h-c-fix, F1; родня B1): браузер оставляет его на нажатой кнопке,
// и пробел (панорама) или Enter нажали бы её ещё раз — лишний слой, лишний сдвиг, повторная запись «Сохранить».
// Отдельный слушатель, не onclick: те уже заняты действиями кнопок. Кнопки пульта ленты фокус не трогают.
["btnPresetPreview", "btnPresetSave", "btnPresetUndo", "btnLayerAdd", "btnLayerSprite", "btnLayerDelete",
 "btnLayerUp", "btnLayerDown", "btnSpritesRefresh"].forEach(function (id) {
  document.getElementById(id).addEventListener("click", function () {
    if (presetCanvas.focus) presetCanvas.focus({ preventScroll: true });
  });
});

loadPreset();
presetLoadSprites();
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

    Обработчик обращается только к ``pult._client``/``pult._scene_client``/
    ``pult._page_bytes`` через замыкание — доступа к ``PluginContext`` у него
    нет, звать ``ctx.log_*``/``record_metric`` с чужого потока незачем (тот же
    довод, что у ``mjpeg_sink``).
    """

    class _PultHandler(http.server.BaseHTTPRequestHandler):
        # Таймаут сокета НЕ задаётся атрибутом `timeout` класса (ревью Task 1.2h
        # ит.2): `socketserver.StreamRequestHandler.setup()` повесил бы его на
        # КАЖДОЕ чтение этого обработчика, и легитимный клиент, шлющий 256 КБ
        # `commit` с паузой длиннее таймаута, получал бы обрыв (`WinError 10053`)
        # вместо ответа — замер ревью: пауза 2.8 с посреди валидного тела, ни
        # 413, ни 408, ни какого-либо HTTP-ответа. Таймаут нужен ровно там, где
        # мы читаем байты, которые никому не нужны, — см. `_linger_close` (там таймаут
        # ставится на время «доотдачи» и снимается вместе с соединением).

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

        def _dispatch(self, command: str, args: dict, client: DeviceHubClient, timeout: float | None = None) -> None:
            """Форвард команды выбранному клиенту и ответ (DESIGN п.3; Находки 2-3 Task 1.2h).

            ``timeout`` — таймаут МАРШРУТА (``None`` -> общий ``pult._timeout_s``,
            прежнее поведение для всех маршрутов до 1.2h). Ответ команды с полем
            ``code`` отдаётся КАК ЕСТЬ, HTTP-статус — по ``_ERROR_CODE_TO_HTTP``
            (код вне таблицы -> 400); ответ БЕЗ ``code`` в ошибке — прежнее
            поведение: 504 ``{ok: false, error: ...}``. 504 остаётся только за
            «не дошло» (клиент не смог получить ответ вовсе).
            """
            result = client.request(command, args, timeout=timeout if timeout is not None else pult._timeout_s)
            if not isinstance(result, dict):
                result = {"status": "error", "message": "bad_response"}
            if result.get("status") == "error":
                code = result.get("code")
                if code is not None:
                    self._reply_json(_ERROR_CODE_TO_HTTP.get(code, 400), result)
                    return
                if client is pult._client:
                    fallback = "robot_error"
                elif client is pult._scene_client:
                    fallback = "scene_error"
                else:
                    fallback = "layers_error"
                self._reply_json(504, {"ok": False, "error": result.get("message", fallback)})
                return
            self._reply_json(200, result)

        #: Тело запроса прочитано командой (``_read_command_body``) — иначе после ответа
        #: в приёмном буфере или в пути могут остаться его байты (см. ``_linger_close``).
        _body_consumed = False

        def handle(self) -> None:
            super().handle()
            self._linger_close()

        def _linger_close(self) -> None:
            """Закрыть соединение так, чтобы уже отправленный ответ дошёл (ЕДИНЫЙ механизм
            для ВСЕХ ранних отказов: 400/403/404/413/415, где тело не читалось).

            Причина (замер pult-flake, 2026-09-29): ``close()`` сокета с непрочитанными
            байтами в приёмном буфере Windows завершает RST'ом, и клиент, ещё не
            успевший прочитать ответ, получает WinError 10053/10054 вместо кода.
            Клиент шлёт заголовки и тело ДВУМЯ ``send``, так что тело может прийти и
            ПОСЛЕ ответа сервера — точное чтение ``Content-Length`` тут не помогло бы
            (для ``-1``/гигабайта его и нет). Поэтому: полузакрытие на запись
            (клиент получает EOF после ответа) и чтение с отбрасыванием, пока клиент
            не закроет свою сторону, — не более ``_MAX_DRAIN_BYTES`` байт и
            ``_DRAIN_TIMEOUT_S`` секунд СУММАРНО (потолок 413 остаётся потолком).

            Опора на HTTP/1.0 (``protocol_version`` по умолчанию у stdlib): один запрос
            на соединение. Поэтому флаг ``_body_consumed`` на экземпляре обработчика —
            флаг ЗАПРОСА, а «доотдача» после цикла ``handle()`` не задевает следующий
            запрос. Переход на HTTP/1.1 (keep-alive) сломал бы оба допущения — его
            сторожит ``test_handler_closes_connection_after_response_http10``."""
            headers = getattr(self, "headers", None)
            if self._body_consumed or headers is None:
                return
            lengths = headers.get_all("Content-Length") or []
            if all(v.strip() == "0" for v in lengths) and headers.get("Transfer-Encoding") is None:
                return
            deadline = time.monotonic() + _DRAIN_TIMEOUT_S
            remaining = _MAX_DRAIN_BYTES
            try:
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_WR)
                while remaining > 0:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        return
                    self.connection.settimeout(left)
                    chunk = self.connection.recv(min(remaining, 65536))
                    if not chunk:
                        return
                    remaining -= len(chunk)
            except OSError:
                return

        def _read_command_body(self, max_bytes: int = _MAX_BODY_BYTES) -> tuple[dict | None, tuple[int, dict] | None]:
            """Прочитать РОВНО ``Content-Length`` байт (не до EOF, см. докстринг модуля).

            Возвращает ``(args, None)`` при успехе либо ``(None, (status, payload))``
            для одного из отказов ДО вызова команды (DESIGN п.3): 413 — размер
            больше ``max_bytes`` (потолок МАРШРУТА, Находка 1 Task 1.2h; дефолт —
            прежний общий ``_MAX_BODY_BYTES``), до чтения тела; 400 ``bad_length`` —
            отрицательный ``Content-Length`` (иначе ``rfile.read(-1)`` читал бы до
            EOF в обход 413, ревью 5.3a п.3) либо нечисловой/противоречивый (несколько
            разных значений) — тело нельзя ни прочитать, ни отбросить по длине, а молча
            принять его за «пустое» нельзя: команда ушла бы с ``{}`` (ревью pult-flake
            2026-09-29); 501 ``transfer_encoding_not_supported`` — любой
            ``Transfer-Encoding`` (RFC 9112 §6.1: кодирование, которого сервер не
            понимает, — SHOULD 501; HTTP/1.0-сервер не понимает ни одного кодирования,
            включая chunked; 411 тоже законен, выбран 501 как буква §6.1); 400 ``bad_json`` —
            кривой JSON/не dict. Ни один из этих отказов до команды не доходит и
            ``_body_consumed`` не выставляет — ``_linger_close`` доотдаёт тело.

            ``(None, (413, None))`` — особый случай (ревью Task 1.2h ит.1, Н1):
            для 413 ответ клиенту уже отправлен ВНУТРИ этого метода (см. ниже),
            вызывающий ``do_POST`` не должен отвечать повторно — ``payload is
            None`` в паре отказа сигналит именно это, а не «отказа не было»
            (для «не было» первый элемент пары — ``None`` целиком).
            """
            if self.headers.get("Transfer-Encoding") is not None:
                return None, (501, {"ok": False, "error": "transfer_encoding_not_supported"})
            # Все значения всех заголовков Content-Length (RFC 9110 §8.6: список через запятую
            # допустим, если значения одинаковы). Строго ASCII-цифры: ``int()`` принял бы
            # "+5", "1_0" и юникодные цифры; ``-1`` и пустая строка — тоже отказ.
            values = [v.strip() for h in (self.headers.get_all("Content-Length") or []) for v in h.split(",")]
            if any(not (v.isascii() and v.isdigit()) for v in values) or len(set(values)) > 1:
                return None, (400, {"ok": False, "error": "bad_length"})
            length = int(values[0]) if values else 0
            if length > max_bytes:
                # Решение отказать принимается ДО обращения к телу: эти байты никуда не
                # форвардятся и не парсятся. Ответ уходит СНАЧАЛА (ревью Task 1.2h ит.1,
                # Н1: вычитывание заявленного Content-Length ДО ответа держало клиента,
                # заявившего гигабайт, без ответа вовсе). Доставку ответа при закрытии
                # обеспечивает общий `_linger_close` (ограниченный, для всех ранних отказов).
                self._reply_json(413, {"ok": False, "error": "too_large"})
                return None, (413, None)
            raw = self.rfile.read(length) if length else b""
            self._body_consumed = True
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
                self._dispatch("belt.status", {}, pult._client)
                return
            if self.path == "/api/journal":
                self._dispatch("sim_robot.journal", {}, pult._client)
                return
            if self.path == "/api/truth":
                self._dispatch("truth.status", {}, pult._scene_client)
                return
            if self.path == "/api/scene":
                self._dispatch("scene.status", {}, pult._scene_client)
                return
            if self.path == "/api/preset":
                self._dispatch("preset.get", {}, pult._scene_client)
                return
            self._reply_json(404, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802 - имя метода задано stdlib
            if not self._host_allowed():
                self._reply_json(403, {"ok": False, "error": "forbidden_host"})
                return
            command = _COMMAND_BY_PATH.get(self.path)
            client = pult._client
            max_bytes = _MAX_BODY_BYTES
            timeout: float | None = None
            if command is None:
                command = _SCENE_COMMAND_BY_PATH.get(self.path)
                client = pult._scene_client
            if command is None:
                preset_route = _PRESET_ROUTES.get(self.path)
                if preset_route is not None:
                    command, client_attr, route_max_bytes, timeout = preset_route
                    client = getattr(pult, client_attr)
                    max_bytes = route_max_bytes if route_max_bytes is not None else _MAX_BODY_BYTES
            if command is None:
                self._reply_json(404, {"ok": False, "error": "not_found"})
                return
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("application/json"):
                self._reply_json(415, {"ok": False, "error": "unsupported_media_type"})
                return
            args, error = self._read_command_body(max_bytes)
            if error is not None:
                status, payload = error
                if payload is not None:
                    self._reply_json(status, payload)
                # payload is None -> 413 уже отправлен внутри _read_command_body
                # (ревью Task 1.2h ит.1, Н1) — отвечать здесь второй раз нельзя.
                return
            self._dispatch(command, args, client, timeout)

    return _PultHandler


@register_plugin("pult_web", category="control", description="Веб-пульт ленты — страница + JSON API на 8092")
class PultWebPlugin(ProcessModulePlugin):
    """Side-effect плагин: HTTP-страница + JSON API.

    ``belt.*``/``sim_robot.*`` уходят в ``robot``, ``truth.*`` — в процесс сцены.
    """

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
        self._scene_process: str = cfg.get("scene_process", _DEFAULT_SCENE_PROCESS)
        self._layers_process: str = cfg.get("layers_process", _DEFAULT_LAYERS_PROCESS)
        self._timeout_s: float = float(cfg.get("timeout_s", _DEFAULT_TIMEOUT_S))

        self._client = DeviceHubClient(ctx, target_process=self._robot_process, default_timeout=self._timeout_s)
        self._scene_client = DeviceHubClient(ctx, target_process=self._scene_process, default_timeout=self._timeout_s)
        self._layers_client = DeviceHubClient(ctx, target_process=self._layers_process, default_timeout=self._timeout_s)
        self._page_bytes = _PAGE_TEMPLATE.format(
            mjpeg_url=self._mjpeg_url,
            preset_section=_PRESET_SECTION,
            preset_script=_PRESET_SCRIPT,
        ).encode("utf-8")

        self._server: http.server.ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._state = "configured"
        self._reason = ""

        ctx.log_info(
            f"pult_web: конфиг принят, {self._host}:{self._port}, robot={self._robot_process}, "
            f"scene={self._scene_process}, layers={self._layers_process}, mjpeg_url={self._mjpeg_url}"
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
