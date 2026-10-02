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
  <label><input id="presetGrid" type="checkbox"> Сетка</label>
  <label>шаг, px: <input id="presetGridStep" type="number" min="1" step="1" value="10"></label>
  <button id="btnPresetFit">Вписать</button>
</div>
<div class="row">
  <canvas id="presetCanvas" width="640" height="480" tabindex="0"></canvas>
  <div>ЛКМ — выбрать и тащить слой; Shift+ЛКМ — добавить слой в выбор или убрать; ручки единственного выбранного:
    круг над рамкой — поворот, угол — масштаб; стрелки — 1 px (Shift — 10 px); колесо — масштаб;
    средняя кнопка или пробел+ЛКМ — панорама. Клавиши: Delete/Backspace — удалить выбранные, Ctrl/Cmd+Z — отмена,
    Ctrl/Cmd+A — выбрать все видимые и не запертые, Esc — снять выбор, F — вписать, G — сетка.
    «видим» — слой рисуется и выбирается; «заперт» — слой рисуется, но не выбирается (оба флага только на экране,
    в пресет не пишутся)</div>
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

// Запись стека «Отмена»: {state, row, reorders}. reorders — операция над составом, после которой принадлежность строк
// может смениться (добавить / удалить / выше / ниже / заменить); row — строка выбора в момент записи (-1 — ничего).
// Так «Отмена» знает род правки и не гадает по presetDirty/имени: правка полей и жест строк не меняют.
// row по умолчанию — текущая presetSelectedRow; операция над составом передаёт строку, снятую ДО mutate
// (mutate уже поставил новый выбор). sel — имена выбранных слоёв на тот же момент (5.3): «Отмена» операции над составом
// возвращает весь выбор, а не только главный слой.
function presetPushUndo(state, reorders, row, sel) {
  presetUndoStack.push({ state: state, row: row === undefined ? presetSelectedRow : row, reorders: reorders,
                         sel: sel === undefined ? presetSelection.slice() : sel });
}

function markPresetDirty() {
  if (!presetDirty) {
    presetPushUndo(presetState, false);
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
    // Флаги «видим» / «заперт» (5.3): клиентские, по ИМЕНИ слоя; в presetFieldMap и в тела запросов не попадают
    row.appendChild(presetFlagLabel("видим", "Vis", i, !presetHidden[layer.name]));
    row.appendChild(presetFlagLabel("заперт", "Lock", i, !!presetLocked[layer.name]));
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
  // строку выбора рендер НЕ считает: её ставят до рендера presetSelect, мутации add/delete/выше/ниже и «Отмена»
  // (пересчёт по имени вернул бы первое совпадение имени — чужую строку при дубле)
  presetRowNames = layers.map(function (layer) { return layer.name; });
  // Флаг живёт, пока в пресете есть слой с этим именем: флаги имён, которых нет, отбрасываются
  // (иначе новый слой с именем удалённого рождался скрытым, а слой, получивший «призрачное» имя, пропадал с канвы)
  [presetHidden, presetLocked].forEach(function (flags) {
    Object.keys(flags).forEach(function (name) {
      if (presetRowNames.indexOf(name) < 0) delete flags[name];
    });
  });
  presetUpdateSelection();
}

// Чекбокс-флаг строки (5.3): id presetVis{i} / presetLock{i}, i — индекс в presetState.layers. Событие change
// ловит делегат на #presetLayers (см. ниже) и тут же выходит: флаги не меняют ни presetState, ни «Отмену».
function presetFlagLabel(text, kind, i, checked) {
  var label = document.createElement("label");
  var box = document.createElement("input");
  box.type = "checkbox";
  box.id = "preset" + kind + i;
  box.checked = checked;
  label.appendChild(box);
  label.appendChild(document.createTextNode(" " + text + " "));
  return label;
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
      // пресет пришёл: текст «слой не добавлен: пресет не загружен» устарел — снимается только он (с «; »),
      // отказ списка рядом с ним остаётся: список его так и не обновил
      if (presetOrphanText !== null) {
        var shown = document.getElementById("presetSpritesError").textContent;
        presetShowSpritesError(shown.slice(presetOrphanText.length).replace(/^; /, ""));
      }
      presetSelect(null);
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

function presetUndo() {
  if (!presetUndoStack.length) return;
  var e = presetUndoStack.pop();
  presetState = e.state;
  presetDirty = false;
  // Выбор — СТРОКА. Правка без перестановки строк (поля, жест, стрелка): строки те же, остаётся текущая строка.
  // Операция над составом: возвращается строка, какой она была прямо перед операцией (e.row; -1 — ничего).
  // Имя выбора берётся из восстановленного состояния, а не ищется: строку НЕ считать через presetRowOfName —
  // она читает поля формы, которые до renderPresetLayers ещё старые. Исчезнувшее имя не оживает у чужого слоя
  // (1.3h-c-fix, F2): выбор — строка из записи, а не имя.
  var row = e.reorders ? e.row : presetSelectedRow;
  if (row >= presetState.layers.length) row = -1;
  presetSelectedRow = row;
  presetSelected = row < 0 ? null : presetState.layers[row].name;
  // Переименование откатывается так же, как делалось: флаги и выбор переезжают на имена восстановленного состояния
  presetTrackRenames(presetState.layers);
  // Выбор (5.3): имена из записи (операция над составом) или текущего выбора; исчезнувшие, скрытые и запертые
  // отпадают — главный слой тоже: флаг по имени пережил «Отмену», и такой слой выбирать нельзя
  var names = presetState.layers.map(function (ly) { return ly.name; });
  var keep = (e.reorders && e.sel ? e.sel : presetSelection).filter(function (n) {
    return presetSelectable(n) && names.indexOf(n) >= 0;
  });
  if (presetSelected !== null && !presetSelectable(presetSelected)) {
    presetSelected = null;
    presetSelectedRow = -1;
  } else if (presetSelected !== null && keep.indexOf(presetSelected) < 0) {
    keep = [presetSelected];
  }
  // главного нет (не было или отпал): им становится последний из оставшихся с единственной строкой
  while (presetSelected === null && keep.length) {
    var cand = keep[keep.length - 1], at = names.indexOf(cand);
    if (at >= 0 && at === names.lastIndexOf(cand)) {
      presetSelected = cand;
      presetSelectedRow = at;
    } else {
      keep.pop();
    }
  }
  presetSelection = keep;
  renderPresetLayers();
  requestPresetLayout();
}
document.getElementById("btnPresetUndo").onclick = presetUndo;

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
// Строка формы выбранного слоя (-1 — ничего). Выбор принадлежит СТРОКЕ: имя в форме правится и повторяется,
// строка — нет (правка полей строк не переставляет). Подсветку рисует ТОЛЬКО presetUpdateSelection по этой строке;
// ДЕЙСТВИЯ над данными слоя (стрелки, конец жеста, «Удалить», «Выше»/«Ниже», «Заменить») берут её, не ищут имя.
// КАРТИНКА на канве — запись последней принятой раскладки, у неё есть только имя: связь строка <-> картинка
// есть лишь при ЕДИНСТВЕННОМ таком имени в форме (presetRowOfName / presetSelectedLayoutEntry), иначе её нет вовсе.
var presetSelectedRow = -1;
// Мультивыбор (5.3): имена выбранных слоёв в порядке добавления. ГЛАВНЫЙ слой — последний в списке; он же
// presetSelected / presetSelectedRow (строка главного берётся из presetSelectedRow, не по имени: дубль имени в форме
// не отнимает у него стрелки). Рамка и ручки — только при ровно одном выбранном. Инвариант: presetSelectedRow >= 0 <=>
// список не пуст. Ставят список presetSetSelection и места, где прежде ставились presetSelected/presetSelectedRow.
var presetSelection = [];
// имя слоя -> true: клиентские флаги, в пресет и в тела запросов не попадают
var presetHidden = Object.create(null); // не рисуется и не выбирается
var presetLocked = Object.create(null); // имя слоя -> true: рисуется, но не выбирается и не тащится
var presetRowNames = [];    // имена строк формы на последней сверке: по ним флаги и выбор переезжают при переименовании
var presetGridEl = document.getElementById("presetGrid");
var presetGridStepEl = document.getElementById("presetGridStep");
var presetGesture = null;   // жест указателя: {kind: move|rotate|scale|pan, name, row, rows, id, start, cur, center}
var presetZoom = 1;
var presetPan = [0, 0];
var presetSpaceHeld = false;
var presetDrawPending = false;
var presetLayoutTimer = null; // отложенный запрос раскладки после серии стрелок
var PRESET_KEY_LAYOUT_MS = 200; // пауза после последней стрелки; preset.layout на слое 1200 px — 50-90 мс
var PRESET_HANDLE_PX = 8;   // полуразмер ручки на экране
var PRESET_ROT_ARM_PX = 24; // вынос ручки поворота над рамкой

// Строка формы с этим именем, если оно в форме ЕДИНСТВЕННОЕ; нет такого или дубль — -1.
// Имя ищется в ПОЛЯХ формы (collectPresetFromFields) — тот же источник, что и тело
// запроса раскладки: слой, переименованный в форме, на канве приходит уже с новым
// именем, а presetState ещё со старым (ревью 1.3h-b ит.1, MINOR-3). Дубль — не «первое
// совпадение»: раскладку с дублем бэкенд отвергает, на канве остаётся прежняя, и имя её
// картинки может принадлежать другой строке (R-5 ит.3). Звать только когда форма
// отрисована из presetState (не между pop «Отмены» и renderPresetLayers).
function presetRowOfName(name) {
  return presetRowFinder()(name);
}

// То же для многих имён за одно чтение формы (5.3): функция name -> строка (-1: нет или дубль). Форму читает лениво.
function presetRowFinder() {
  var names = null;
  return function (name) {
    if (names === null) {
      names = (presetState ? collectPresetFromFields().layers : []).map(function (ly) { return ly.name; });
    }
    var row = -1;
    for (var i = 0; i < names.length; i++) {
      if (names[i] !== name) continue;
      if (row >= 0) return -1;
      row = i;
    }
    return row;
  };
}

// Выбор можно сделать только из видимых и не запертых слоёв.
function presetSelectable(name) {
  return !presetHidden[name] && !presetLocked[name];
}

// Строки выбранных слоёв: главный (последний) — по presetSelectedRow, остальные — по имени (дубль имени — не берётся).
function presetSelectionRows() {
  if (!presetSelection.length) return [];
  var find = presetRowFinder(), rows = [], last = presetSelection.length - 1;
  presetSelection.forEach(function (name, i) {
    var r = i === last ? presetSelectedRow : find(name);
    if (r >= 0 && rows.indexOf(r) < 0) rows.push(r);
  });
  return rows;
}

// Новый выбор по именам (порядок = порядок добавления, главный — последний). Берутся только имена, у которых
// в ОТРИСОВАННОЙ форме ровно одна строка (авто-слой base и дубли отпадают).
// Звать, когда форма соответствует presetState.
function presetSetSelection(names) {
  var find = presetRowFinder(), list = [];
  names.forEach(function (n) {
    if (list.indexOf(n) < 0 && find(n) >= 0) list.push(n);
  });
  presetSelection = list;
  presetSelected = list.length ? list[list.length - 1] : null;
  presetSelectedRow = presetSelected === null ? -1 : find(presetSelected);
  presetUpdateSelection();
}

// Переименование в форме (5.3): строка та же, имя новое — флаги и выбор переезжают на новое имя, иначе скрытый слой
// «воскресал» бы, а выбор терял слой. Переименование = «старое имя пропало, новое единственное»;
// перестановки и дубли — не оно.
function presetTrackRenames(layers) {
  var now = layers.map(function (ly) { return ly.name; });
  presetRowNames.forEach(function (old, i) {
    var nu = now[i];
    if (nu === undefined || nu === old || now.indexOf(old) >= 0 || now.indexOf(nu) !== now.lastIndexOf(nu)) return;
    [presetHidden, presetLocked].forEach(function (m) {
      if (m[old]) { m[nu] = true; delete m[old]; }
    });
    presetSelection = presetSelection.map(function (n) { return n === old ? nu : n; });
  });
  presetRowNames = now;
}

// Картинка выбранной строки в раскладке: только если имя этой строки в форме единственное, иначе null
// (рамки, ручек, призрака и сдвига битмапа нет; ответ раскладки перерисует канву сам).
function presetSelectedLayoutEntry() {
  return presetEntryOfRow(presetSelectedRow);
}

// Картинка строки row в раскладке (5.3): тот же закон — только при единственном имени строки в форме, иначе null.
function presetEntryOfRow(row) {
  if (row < 0 || !presetState) return null;
  var ly = collectPresetFromFields().layers[row];
  if (!ly || presetRowOfName(ly.name) !== row) return null;
  return presetLayoutEntry(ly.name);
}

function presetLayoutEntry(name) {
  if (!presetLayout) return null;
  for (var i = 0; i < presetLayout.layers.length; i++) {
    if (presetLayout.layers[i].name === name) return presetLayout.layers[i];
  }
  return null;
}

// Подсветка строк формы выбранных слоёв (строка i <-> presetState.layers[i]).
function presetUpdateSelection() {
  var rows = document.getElementById("presetLayers").children || [];
  var sel = presetSelectionRows();
  for (var i = 0; i < rows.length; i++) rows[i].classList.toggle("selected", sel.indexOf(i) >= 0);
}

// Выбор по имени (клик по канве, сброс при загрузке пресета). Строку считает presetRowOfName по ОТРИСОВАННОЙ
// форме: имя не единственное (дубль) или его нет (авто-слой base) -> ничего не выбрано. Звать только когда форма
// соответствует presetState. Мутации add/delete/выше/ниже и «Отмена» ставят presetSelected + presetSelectedRow сами.
function presetSelect(name) {
  presetSetSelection(name === null ? [] : [name]);
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

// Сдвиг выбранного слоя жестом «перенос» в px объекта (для рисования во время жеста; к какой картинке его
// приложить — решает presetSelectedLayoutEntry, не имя жеста).
// row (необязателен): строка должна входить в жест «перенос» (при групповом переносе сдвиг у всех одинаковый).
function presetMoveShift(row) {
  var g = presetGesture;
  if (!g || g.kind !== "move" || (row !== undefined && g.rows.indexOf(row) < 0)) return [0, 0];
  return [(g.cur[0] - g.start[0]) / presetZoom, (g.cur[1] - g.start[1]) / presetZoom];
}

// Картинки слоёв, которые тащит жест «перенос» (все выбранные на начало жеста; без картинки — пропуск).
function presetMovingEntries() {
  var g = presetGesture;
  if (!g || g.kind !== "move") return [];
  return g.rows.map(presetEntryOfRow).filter(function (en) { return en !== null; });
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
  if (presetSelection.length !== 1) return null; // ручки — только у единственного выбранного (5.3)
  var ly = presetSelectedLayoutEntry();
  if (!ly) return null;
  var d = presetMoveShift(presetSelectedRow);
  var a = presetToScreen(ly.x + d[0], ly.y + d[1]);
  var b = presetToScreen(ly.x + d[0] + ly.w, ly.y + d[1] + ly.h);
  var cx = (a[0] + b[0]) / 2, cy = (a[1] + b[1]) / 2;
  return { x0: a[0], y0: a[1], x1: b[0], y1: b[1], cx: cx, cy: cy,
           rot: [cx, a[1] - PRESET_ROT_ARM_PX], scale: [b[0], b[1]] };
}

function presetNear(p, q) {
  return Math.abs(p[0] - q[0]) <= PRESET_HANDLE_PX && Math.abs(p[1] - q[1]) <= PRESET_HANDLE_PX;
}

// Выбор по альфе: сверху вниз, первый слой с alpha > 0 под курсором (не по bbox). Скрытые и запертые слои пропускаются
// (5.3): клик проходит к слою ниже.
function presetHitLayer(sx, sy) {
  if (!presetLayout) return null;
  var o = presetToObject(sx, sy);
  for (var i = presetLayout.layers.length - 1; i >= 0; i--) {
    var ly = presetLayout.layers[i];
    if (!presetSelectable(ly.name)) continue;
    var u = Math.floor(o[0] - ly.x), v = Math.floor(o[1] - ly.y);
    if (u < 0 || v < 0 || u >= ly.w || v >= ly.h) continue;
    if (ly.hit.getImageData(u, v, 1, 1).data[3] > 0) return ly.name;
  }
  return null;
}

// Шаг сетки в px объекта; 0 — сетка выключена или шаг не число >= 1 (привязки и линий нет).
function presetGridStepPx() {
  if (!presetGridEl.checked) return 0;
  var s = parseFloat(presetGridStepEl.value);
  return s >= 1 ? s : 0;
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
  var moving = presetMovingEntries(), shift = presetMoveShift();
  L.layers.forEach(function (ly) {
    if (presetHidden[ly.name]) return; // скрытый слой не рисуется (5.3)
    var d = moving.indexOf(ly) >= 0 ? shift : [0, 0];
    ctx.drawImage(ly.img, ly.x + d[0], ly.y + d[1]);
  });
  // Сетка (5.3): линии через центр канвы объекта — offset_px считается от него;
  // слишком частую (< 4 экранных px) не рисуем.
  var gs = presetGridStepPx();
  if (gs > 0 && gs * z >= 4) {
    ctx.strokeStyle = "rgba(0, 0, 0, 0.25)";
    ctx.lineWidth = 1 / z;
    ctx.beginPath();
    var gx0 = L.cw / 2 - Math.floor(L.cw / 2 / gs) * gs, gy0 = L.ch / 2 - Math.floor(L.ch / 2 / gs) * gs;
    for (var gx = gx0; gx <= L.cw; gx += gs) { ctx.moveTo(gx, 0); ctx.lineTo(gx, L.ch); }
    for (var gy = gy0; gy <= L.ch; gy += gs) { ctx.moveTo(0, gy); ctx.lineTo(L.cw, gy); }
    ctx.stroke();
  }
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
// Данные слоя задаются СТРОКОЙ (не именем: при дубле имён поиск по имени берёт первое совпадение — чужой слой);
// картинка для сдвига битмапа — presetSelectedLayoutEntry (только при единственном имени в форме, иначе её нет).
// rows (5.3) — одна строка или массив строк: групповая правка (все выбранные) — ОДИН снимок, одна запись «Отмена»,
// один запрос раскладки; mutate(layer, row) зовётся для каждой строки.
function presetApplyEdit(rows, mutate, deferLayout) {
  var snapshot = collectPresetFromFields();
  rows = [].concat(rows).filter(function (r) { return r >= 0 && r < snapshot.layers.length; });
  if (!rows.length) return;
  var next = JSON.parse(JSON.stringify(snapshot));
  rows.forEach(function (r) { mutate(next.layers[r], r); });
  if (JSON.stringify(next) === JSON.stringify(snapshot)) return;
  presetPushUndo(snapshot, false); // жест/стрелка строк не переставляют: «Отмена» оставит текущую строку выбора
  presetState = next;
  presetDirty = false;
  renderPresetLayers();
  // готовый битмап сдвигается сразу, не дожидаясь ответа раскладки (форма уже из next: хелпер читает её);
  // картинки нет (имя не единственное) — сдвиг пропускается, канву перерисует ответ раскладки
  rows.forEach(function (r) {
    var before = snapshot.layers[r].offset_px || [0, 0], after = next.layers[r].offset_px || [0, 0];
    var ly = presetEntryOfRow(r);
    if (ly) {
      ly.x += after[0] - before[0];
      ly.y += after[1] - before[1];
    }
  });
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
// целиком (mutate(layers) может ещё выставить presetSelected и presetSelectedRow — рендер идёт ПОСЛЕ него),
// битмапа для сдвига нет, а запрос раскладки всегда немедленный и снимает висящий таймер
// стрелок: запрос уйдёт с составом, в котором стрелки уже учтены (presetState их хранит),
// а ++presetLayoutSeq в нём глушит ещё летящий ответ на старый состав. Ничего не
// изменившая операция — ни записи «Отмена», ни запроса.
function presetApplyLayersEdit(mutate) {
  if (!presetState) return;
  var snapshot = collectPresetFromFields();
  var next = JSON.parse(JSON.stringify(snapshot));
  var rowBefore = presetSelectedRow; // ДО mutate: он ставит новый выбор, а «Отмена» вернёт прежний
  var selBefore = presetSelection.slice();
  mutate(next.layers);
  if (JSON.stringify(next) === JSON.stringify(snapshot)) return;
  presetPushUndo(snapshot, true, rowBefore, selBefore);
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

// Сдвиг строк rows на (dx, dy) одной правкой. snapRow (только жест «перенос», 5.3): при включённой сетке новое смещение
// слоя snapRow на каждой оси — ближайшее кратное шагу (от АБСОЛЮТНОГО offset_px), остальные получают ту же дельту.
// Стрелки snapRow не передают — не привязываются.
function presetShiftRows(rows, dx, dy, round, deferLayout, snapRow) {
  var step = snapRow === undefined ? 0 : presetGridStepPx();
  if (step > 0) {
    var ref = collectPresetFromFields().layers[snapRow];
    var base = ref && Array.isArray(ref.offset_px) ? ref.offset_px : [0, 0];
    dx = Math.round((base[0] + dx) / step) * step - base[0];
    dy = Math.round((base[1] + dy) / step) * step - base[1];
    round = false; // смещение уже кратно шагу, округлять до целого нельзя (шаг может быть дробным)
  }
  presetApplyEdit(rows, function (layer) {
    var off = Array.isArray(layer.offset_px) ? layer.offset_px : [0, 0];
    var x = off[0] + dx, y = off[1] + dy;
    layer.offset_px = round ? [Math.round(x), Math.round(y)] : [x, y];
  }, deferLayout);
}

function presetFinishGesture(g) {
  if (g.kind === "move") {
    // ponytail: offset_px округляется до целого px — при зуме > 100 % полпикселя мышью не задать (стрелки — 1 px)
    var dx = (g.cur[0] - g.start[0]) / presetZoom, dy = (g.cur[1] - g.start[1]) / presetZoom;
    presetShiftRows(g.rows, dx, dy, true, false, g.row);
    return;
  }
  var t = presetHandleDelta(g);
  presetApplyEdit(g.row, function (layer) {
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
  var kind = null, h = null, hit = null, gRow = presetSelectedRow, gRows = null;
  if (e.button === 1 || (e.button === 0 && presetSpaceHeld)) {
    kind = "pan";
  } else if (e.button === 0 && e.shiftKey) {
    // Shift+ЛКМ (5.3): слой переключает членство в выборе, жеста нет; мимо слоёв — выбор не трогаем
    hit = presetHitLayer(p[0], p[1]);
    if (hit !== null) {
      presetSetSelection(presetSelection.indexOf(hit) >= 0
        ? presetSelection.filter(function (n) { return n !== hit; })
        : presetSelection.concat([hit]));
      presetScheduleDraw();
    }
  } else if (e.button === 0) {
    h = presetHandles();
    if (h && presetNear(p, h.rot)) kind = "rotate";
    else if (h && presetNear(p, h.scale)) kind = "scale";
    else {
      hit = presetHitLayer(p[0], p[1]);
      // слой из выбора — тащится весь выбор; слой вне выбора (или пустое место) — выбор = только он
      if (hit === null || presetSelection.indexOf(hit) < 0) presetSelect(hit); // дубль имени / авто-слой base -> ничего
      presetScheduleDraw();
      if (hit !== null && presetSelection.indexOf(hit) >= 0) {
        kind = "move";
        gRow = presetSelection[presetSelection.length - 1] === hit ? presetSelectedRow : presetRowOfName(hit);
        gRows = presetSelectionRows(); // строки ВСЕХ выбранных — захвачены на начало жеста
      }
    }
  }
  if (!kind) return;
  if (e.preventDefault) e.preventDefault();
  // row — для правки: строка захвачена в начале жеста; name — имя формы на тот момент (правка его не читает).
  // Жест ручкой начинается только на рамке, а рамка есть лишь у единственного имени (presetSelectedLayoutEntry)
  // Жест «перенос»: row — слой под указателем (по нему привязка к сетке), rows — все выбранные.
  presetGesture = { kind: kind, name: kind === "move" ? hit : presetSelected, row: gRow, rows: gRows || [gRow],
                    id: e.pointerId, start: p, cur: p, center: h ? [h.cx, h.cy] : null };
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
  // Горячие клавиши (5.3). Ctrl/Meta/Alt-сочетания, кроме Ctrl/Meta+Z и +A, браузеру (Ctrl+F — поиск, Ctrl+G ...)
  var key = String(e.key || ""), low = key.toLowerCase(), mod = !!(e.ctrlKey || e.metaKey);
  if (mod && low === "z" && !e.shiftKey) { // Ctrl/Meta+Shift+Z — «повторить», его здесь нет
    if (e.preventDefault) e.preventDefault();
    if (presetGesture) presetCancelGesture(); // жест над строками, которые «Отмена» перестроит
    presetUndo();
    return;
  }
  if (mod && low === "a") {
    if (e.preventDefault) e.preventDefault(); // иначе браузер выделит текст страницы
    presetSelectAll();
    return;
  }
  if (!mod && !e.altKey) {
    if (key === "Delete" || key === "Backspace") {
      if (presetSelection.length) {
        if (e.preventDefault) e.preventDefault();
        presetDeleteLayer();
      }
      return;
    }
    if (key === "Escape") {
      if (presetGesture) presetCancelGesture(); // выбор снимают — жест над ним не доводится до правки
      presetSetSelection([]);
      presetScheduleDraw();
      return;
    }
    if (low === "f") { presetFit(); return; }
    if (low === "g") { presetGridEl.checked = !presetGridEl.checked; presetScheduleDraw(); return; }
  }
  if (!Object.prototype.hasOwnProperty.call(PRESET_ARROWS, e.key)) return;
  var rows = presetSelectionRows();
  if (!rows.length) return;
  if (e.preventDefault) e.preventDefault();
  var step = e.shiftKey ? 10 : 1, d = PRESET_ARROWS[e.key];
  presetShiftRows(rows, d[0] * step, d[1] * step, false, true);
});
document.addEventListener("keyup", function (e) {
  if (e.key === " " || e.code === "Space") presetSpaceHeld = false;
});
window.addEventListener("blur", function () { presetSpaceHeld = false; });

// Ввод в поле формы — раскладка по новому состоянию (change всплывает до контейнера).
// Выбор принадлежит строке (R-5 а): переименование выбранного слоя в форме переносит выбор на новое имя.
document.getElementById("presetLayers").addEventListener("change", function (e) {
  // Флаги «видим»/«заперт» (5.3) — не правка пресета: ни запроса, ни presetDirty, ни записи «Отмена»
  var t = e && e.target;
  var flag = t && typeof t.id === "string" ? /^preset(Vis|Lock)([0-9]+)$/.exec(t.id) : null;
  if (flag) {
    presetToggleFlag(flag[1], Number(flag[2]), !!t.checked);
    presetFocusCanvas();
    return;
  }
  if (presetState) {
    var layers = collectPresetFromFields().layers;
    presetTrackRenames(layers);
    if (presetSelectedRow >= 0 && presetSelection.length && layers[presetSelectedRow]) {
      presetSelected = layers[presetSelectedRow].name;
      presetSelection[presetSelection.length - 1] = presetSelected; // главный — последний в выборе, его имя — по строке
    }
  }
  requestPresetLayout();
});

// Переключение флага строки i (kind "Vis" | "Lock"): слой покидает выбор при ЛЮБОМ переключении любого флага.
function presetToggleFlag(kind, i, checked) {
  var name = presetRowNames[i];
  if (name === undefined) return;
  var map = kind === "Vis" ? presetHidden : presetLocked;
  if (kind === "Vis" ? !checked : checked) map[name] = true;
  else delete map[name];
  presetSetSelection(presetSelection.filter(function (n) { return n !== name; }));
  presetScheduleDraw();
}

function presetFocusCanvas() {
  if (presetCanvas.focus) presetCanvas.focus({ preventScroll: true }); // не оставлять фокус на чекбоксе (как F1 1.3h-c)
}

// Ctrl/Meta+A: все видимые и не запертые слои пресета в порядке строк; главный — последний.
function presetSelectAll() {
  if (!presetState) return;
  presetSetSelection(collectPresetFromFields().layers.map(function (ly) { return ly.name; }).filter(presetSelectable));
  presetScheduleDraw();
}

// «Вписать» (кнопка и клавиша F): масштаб, при котором раскладка занимает 95 % холста по более тесной оси; панорама
// в центр. Ни запроса, ни записи «Отмена» — это вид, не правка.
function presetFit() {
  if (!presetLayout || !(presetLayout.cw > 0) || !(presetLayout.ch > 0)) return;
  var z = Math.floor(95 * Math.min(presetCanvas.width / presetLayout.cw, presetCanvas.height / presetLayout.ch));
  z = Math.min(1000, Math.max(10, z));
  presetZoomInput.value = String(z);
  presetSetZoomPct(z);
  presetPan = [0, 0];
  presetScheduleDraw();
}
document.getElementById("btnPresetFit").onclick = presetFit;

// Сетка (5.3): только перерисовка — ни запроса, ни записи «Отмена»; фокус по окончании правки возвращается канве.
presetGridEl.addEventListener("change", function () { presetScheduleDraw(); presetFocusCanvas(); });
presetGridStepEl.addEventListener("input", presetScheduleDraw);
presetGridStepEl.addEventListener("change", function () { presetScheduleDraw(); presetFocusCanvas(); });

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
// Текст «файл сохранён, слой не добавлен: пресет не загружен», стоящий ПРЕФИКСОМ на экране (null — его нет)
var presetOrphanText = null;
var presetSpritesSeq = 0;       // номер запроса списка: ответ не последнего запроса (R-5 б) страница не показывает

// Любой показ текста снимает флаг «сироты»: на экране уже не тот текст, loadPreset его не тронет
// (загрузка без пресета ставит флаг ПОСЛЕ показа своего текста).
function presetShowSpritesError(text) {
  presetOrphanText = null;
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

// Промис: true — принят успешный ответ, false — показан отказ, undefined — ответ устарел (его не показали).
function presetLoadSprites() {
  var seq = ++presetSpritesSeq;
  return post("/api/preset/sprites", {}).then(function (r) {
    if (seq !== presetSpritesSeq) return; // пришёл позже более свежего запроса: он уже показан
    if (!r || r.status !== "ok" || !Array.isArray(r.files)) {
      var why = (r && (r.message || r.error || r.code)) || "ответ без списка";
      presetShowSpritesError("список спрайтов не получен: " + why);
      return false;
    }
    presetSpriteEntries = r.files;
    presetLayerTemplate = r.layer_template || null;
    presetFillSpriteSelect();
    presetShowSpritesError(r.truncated ? "показаны первые " + r.files.length : "");
    return true;
  }).catch(function (err) {
    if (seq !== presetSpritesSeq) return;
    presetShowSpritesError("список спрайтов не получен: " + err);
    return false;
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
    presetSelection = [layer.name];
    presetSelectedRow = layers.length - 1;
  });
}

// Индекс выбранного слоя в ТЕКУЩЕЙ правке — строка выбора (не поиск по имени); -1 — ничего (кнопки — no-op).
function presetSelectedIndex() {
  return presetSelectedRow;
}

// Удаляет ВСЕ выбранные слои одной записью «Отмена» (5.3; кнопка и Delete/Backspace).
function presetDeleteLayer() {
  var rows = presetSelectionRows().sort(function (a, b) { return b - a; }); // с конца: индексы не съезжают
  if (!rows.length) return;
  if (presetGesture) presetCancelGesture(); // тащат слой, который сейчас исчезнет: жест без записи «Отмена»
  presetApplyLayersEdit(function (layers) {
    rows.forEach(function (r) { layers.splice(r, 1); });
    presetSelected = null;
    presetSelection = [];
    presetSelectedRow = -1;
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
    presetSelectedRow = to; // выбранный слой переехал вместе с выбором (имя то же)
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
  // Потолок сервера (6 МиБ): больше — не читаем и не шлём.
  if (file.size > 6291456) { presetUploadFail("файл больше 6 МиБ"); done(); return; }
  var reader = new FileReader();
  reader.onerror = function () { presetUploadFail("файл не прочитан"); done(); };
  reader.onload = function () {
    var url = String(reader.result);
    var png_b64 = url.slice(url.indexOf(",") + 1);
    post("/api/preset/sprite_put", { name: file.name, png_b64: png_b64 }).then(function (r) {
      if (r && r.status === "ok" && r.file) {
        if (presetState) {
          presetLoadSprites();
          presetAddLayer(r.file);
        } else {
          // файл сохранён, слоя нет (пресет не загружен): текст ПОСЛЕ обновления списка, иначе оно его сотрёт.
          // Не true — на экране чужой текст, который терять нельзя: false — отказ ЭТОГО обновления, undefined —
          // строкой владеет более новое обновление (его отказ). Тогда сирота встаёт префиксом: «сирота; текст».
          presetLoadSprites().then(function (ok) {
            var text = "файл " + r.file.path + " сохранён, слой не добавлен: пресет не загружен";
            var shown = document.getElementById("presetSpritesError").textContent;
            presetShowSpritesError(ok !== true && shown ? text + "; " + shown : text);
            presetOrphanText = text; // loadPreset снимет только этот префикс, когда пресет придёт
          });
        }
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
["btnPresetPreview", "btnPresetSave", "btnPresetUndo", "btnPresetFit", "btnLayerAdd", "btnLayerSprite",
 "btnLayerDelete", "btnLayerUp", "btnLayerDown", "btnSpritesRefresh"].forEach(function (id) {
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
