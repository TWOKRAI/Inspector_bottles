# -*- coding: utf-8 -*-
# ruff: noqa: F811 - фикстура start_pult импортирована из приёмки и принимается тестами по имени
"""Хазарды автора Task 1.3h-b — канва редактора слоёв на `pult_web`.

Дополняют слепую приёмку `test_acceptance_1_3h_canvas.py` (её стенд, двойники и харнесс
переиспользуются импортом) там, где она по контракту молчит: ручки поворота/масштаба,
колесо, панорама, жест поверх ответа раскладки в полёте, устаревший ответ раскладки,
отмена жеста системой, уход указателя за канву, снимок «Отмены» с несохранённым вводом,
потолок тела маршрутов `/api/preset/layout` и `/api/preset/preview`.

Что именно может сломаться в ЭТОМ механизме (так он устроен):
- жест считается от состояния правки + экранной дельты, а раскладка приходит асинхронно —
  ответ, прилетевший посреди жеста или после более нового запроса, не должен ни сбить
  жест, ни откатить картинку к старому состоянию (номер запроса `presetLayoutSeq`);
- панорама и масштаб — вид, не правка: ни записи «Отмена», ни запроса раскладки;
- снимок «Отмены» берётся из ПОЛЕЙ (несохранённый ввод), а после жеста форма
  синхронизирована — следующий ввод в поле кладёт свой снимок (markPresetDirty 1.2h);
- угол: CCW при оси Y вниз (как `_rotate` в `line_sim`) — экранный поворот по часовой
  стрелке УМЕНЬШАЕТ `angle_deg`.

Всё проверено только в харнессе `page_offline.mjs` (node:vm, программный 2D-контекст):
настоящего браузера здесь нет — захват указателя (`setPointerCapture`), всплытие `change`
до `#presetLayers`, `passive: false` у колеса в харнессе не исполняются.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

import pytest

from Plugins.sim.pult_web.tests.test_acceptance_1_3h_canvas import (
    _IDS,
    _WAIT2,
    _client_for,
    _data_url,
    _layer,
    _run_canvas,
    _screen,
    _snap,
    _Stand,
    _stand,
    _xy,
    start_pult,  # noqa: F401 - фикстура, pytest находит её по имени в модуле
)

_ANGLE = "layer0_angle_deg"
_SCALE = "layer0_scale"


def _cap_draws(out: dict) -> list[list[float]]:
    """bbox каждого drawImage слоя cap на #presetCanvas, по порядку."""
    return [d["bbox"] for d in out["draws"] if d["src"] == _data_url("cap")]


def _delay_layout(stand: _Stand, when: Callable[[dict], bool], seconds: float) -> None:
    """Ответ `preset.layout` на тело, для которого `when(args)` истинно, задерживается."""
    original = stand.layers.handlers["preset.layout"]

    def slow(args: dict) -> dict:
        if when(args):
            time.sleep(seconds)
        return original(args)

    stand.layers.handlers["preset.layout"] = slow


def _offset0(args: dict) -> list:
    return args.get("preset", {}).get("layers", [{}])[0].get("offset_px")


def _click_cap() -> list[dict]:
    return [{"op": "click", "at": _screen((105, 105))}, {"op": "sleep", "ms": 60}]


# Геометрия cap с offset [5,5] при 100 %: рамка на экране (305,225)-(345,265), центр (325,245).
# Ручка поворота — на 24 px над серединой верхней стороны, ручка масштаба — правый нижний угол.
_ROT_HANDLE = [5, -39]
_SCALE_HANDLE = [25, 25]
_CENTER = [5, 5]


# --------------------------------------------------------------------------- #
# Ручки: поворот -> angle_deg, угол -> scale                                  #
# --------------------------------------------------------------------------- #
def test_rotate_handle_sets_angle_deg_ccw_positive(start_pult) -> None:
    """Ручку поворота увели из «над центром» в «справа от центра» — экранный поворот на 90°
    ПО часовой стрелке -> `angle_deg` 0 -> -90 (CCW положителен, ось Y вниз). offset_px цел,
    ровно одна запись «Отмена», ровно один новый запрос раскладки с новым углом."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    ids = _IDS + [_ANGLE, _SCALE]
    steps = [
        _WAIT2,
        *_click_cap(),
        {"op": "snap", "tag": "sel", "ids": ids},
        {"op": "drag", "from": _ROT_HANDLE, "to": [_CENTER[0] + 44, _CENTER[1]], "steps": 4},
        {"op": "sleep", "ms": 300},
        {"op": "snap", "tag": "rot", "ids": ids},
        {"op": "press_button", "id": "btnPresetUndo"},
        {"op": "snap", "tag": "u1", "ids": ids},
        {"op": "press_button", "id": "btnPresetUndo"},
        {"op": "snap", "tag": "u2", "ids": ids},
    ]
    out = _run_canvas(stand.port, steps)
    s = out["snaps"]
    assert s["sel"]["selected"] == ["cap"], s["sel"]
    assert float(s["rot"]["fields"][_ANGLE]) == pytest.approx(-90, abs=0.2), s["rot"]["fields"]
    assert _xy(s["rot"]) == [5.0, 5.0] and float(s["rot"]["fields"][_SCALE]) == 1.0, s["rot"]["fields"]
    assert float(s["u1"]["fields"][_ANGLE]) == 0.0 and s["u2"]["fields"] == s["u1"]["fields"], (
        f"одна запись «Отмена» на жест ручкой: {s['u1']['fields']} / {s['u2']['fields']}"
    )
    assert s["rot"]["layoutCount"] == s["sel"]["layoutCount"] + 1
    rot_request = stand.layout_requests()[s["rot"]["layoutCount"] - 1]  # последний до «Отмены»
    assert rot_request["preset"]["layers"][0]["angle_deg"] == pytest.approx(-90, abs=0.2), rot_request


def test_scale_handle_sets_scale(start_pult) -> None:
    """Ручку масштаба увели вдвое дальше от центра рамки -> `scale` 1 -> 2; offset/угол целы."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    ids = _IDS + [_ANGLE, _SCALE]
    steps = [
        _WAIT2,
        *_click_cap(),
        {"op": "drag", "from": _SCALE_HANDLE, "to": [45, 45], "steps": 3},
        {"op": "sleep", "ms": 300},
        {"op": "snap", "tag": "sc", "ids": ids},
        {"op": "press_button", "id": "btnPresetUndo"},
        {"op": "snap", "tag": "u1", "ids": ids},
    ]
    out = _run_canvas(stand.port, steps)
    s = out["snaps"]
    assert float(s["sc"]["fields"][_SCALE]) == pytest.approx(2.0, abs=0.01), s["sc"]["fields"]
    assert _xy(s["sc"]) == [5.0, 5.0] and float(s["sc"]["fields"][_ANGLE]) == 0.0, s["sc"]["fields"]
    assert float(s["u1"]["fields"][_SCALE]) == 1.0, s["u1"]["fields"]


# --------------------------------------------------------------------------- #
# Колесо и панорама — вид, не правка                                          #
# --------------------------------------------------------------------------- #
def test_wheel_zooms_syncs_field_and_scales_drag(start_pult) -> None:
    """Колесо от себя: 100 -> 125 % в #presetZoom, без запроса раскладки и без правки; жест после
    него делит экранную дельту на 1.25 (50 px экрана -> 40 px объекта); cap рисуется 50x50;
    колесо на себя возвращает 100."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    ids = _IDS + ["presetZoom"]
    at = [(105 - 100) * 1.25, (105 - 100) * 1.25]
    steps = [
        _WAIT2,
        {"op": "sleep", "ms": 200},
        {"op": "snap", "tag": "s0", "ids": ids},
        {"op": "wheel", "at": [0, 0], "deltaY": -100},
        {"op": "sleep", "ms": 60},
        {"op": "snap", "tag": "z", "ids": ids},
        {"op": "drag", "from": at, "to": [at[0] + 50, at[1]], "steps": 3},
        {"op": "sleep", "ms": 300},
        {"op": "snap", "tag": "d", "ids": ids},
    ]
    out = _run_canvas(stand.port, steps)
    s = out["snaps"]
    assert s["z"]["fields"]["presetZoom"] == "125", s["z"]["fields"]
    assert s["z"]["layoutCount"] == s["s0"]["layoutCount"] and _xy(s["z"]) == [5.0, 5.0], s["z"]
    assert _xy(s["d"]) == pytest.approx([45, 5], abs=1), s["d"]["fields"]
    bbox = _cap_draws(out)[-1]
    assert bbox[2] - bbox[0] == pytest.approx(50, abs=0.01), f"cap при 125 % — 50 px: {bbox}"
    back = _run_canvas(
        stand.port,
        [
            _WAIT2,
            {"op": "wheel", "at": [0, 0], "deltaY": -100},
            {"op": "wheel", "at": [0, 0], "deltaY": 100},
            {"op": "snap", "tag": "b", "ids": ["presetZoom"]},
        ],
    )
    assert back["snaps"]["b"]["fields"]["presetZoom"] == "100", back["snaps"]["b"]


def test_pan_middle_button_and_space_drag_are_view_only(start_pult) -> None:
    """Средняя кнопка (+20,+10) и пробел+ЛКМ (+10,+10): картинка сдвинута на (+30,+20) экрана,
    поля/«Отмена»/раскладка не тронуты, выбор по альфе считает с учётом панорамы; после
    отпускания пробела ЛКМ снова тащит слой."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    steps = [
        _WAIT2,
        {"op": "sleep", "ms": 200},
        _snap("s0"),
        {"op": "drag", "from": [-90, -90], "to": [-70, -80], "steps": 3, "button": 1},
        {"op": "key", "key": " "},
        {"op": "drag", "from": [-60, -60], "to": [-50, -50], "steps": 3},
        {"op": "keyup", "key": " "},
        {"op": "sleep", "ms": 60},
        _snap("panned"),
        {"op": "press_button", "id": "btnPresetUndo"},
        _snap("undo"),
        {"op": "click", "at": [5 + 30, 5 + 20]},
        {"op": "sleep", "ms": 60},
        _snap("sel"),
        {"op": "drag", "from": [5 + 30, 5 + 20], "to": [15 + 30, 5 + 20], "steps": 3},
        {"op": "sleep", "ms": 300},
        _snap("moved"),
    ]
    out = _run_canvas(stand.port, steps)
    s = out["snaps"]
    assert _xy(s["panned"]) == [5.0, 5.0] and s["panned"]["layoutCount"] == s["s0"]["layoutCount"], s["panned"]
    assert _xy(s["undo"]) == [5.0, 5.0], "панорама не кладёт запись «Отмена»"
    assert s["sel"]["selected"] == ["cap"], f"выбор по альфе с учётом панорамы: {s['sel']}"
    assert _xy(s["moved"]) == pytest.approx([15, 5], abs=1), s["moved"]["fields"]
    cx, cy = out["canvas"][0] / 2, out["canvas"][1] / 2
    bbox = _cap_draws(out)[-1]  # origin (95,85) после сдвига на +10
    assert bbox == pytest.approx([cx - 5 + 30, cy - 15 + 20, cx + 35 + 30, cy + 25 + 20], abs=0.01), bbox


# --------------------------------------------------------------------------- #
# Асинхронная раскладка                                                       #
# --------------------------------------------------------------------------- #
def test_gesture_survives_layout_reply_arriving_mid_gesture(start_pult) -> None:
    """Ответ раскладки жеста A (задержан на 0.5 с) приходит, пока жест B удержан: жест B не
    сбит (итог A+B = [55,15]), пока кнопка зажата — новых запросов нет, после — ровно один."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    _delay_layout(stand, lambda a: _offset0(a) == [35, -5], 0.5)
    steps = [
        _WAIT2,
        {"op": "sleep", "ms": 200},
        _snap("s0"),
        {"op": "drag", "from": _screen((105, 105)), "to": [35, -5], "steps": 3},
        {"op": "press", "at": _screen((120, 100))},
        {"op": "move", "at": [30, 5]},
        {"op": "sleep", "ms": 700},
        _snap("held"),
        {"op": "move", "at": [40, 20]},
        {"op": "release", "at": [40, 20]},
        {"op": "sleep", "ms": 400},
        _snap("end"),
    ]
    out = _run_canvas(stand.port, steps)
    s = out["snaps"]
    n0 = s["s0"]["layoutCount"]
    assert s["held"]["layoutCount"] == n0 + 1, s["held"]
    assert _xy(s["end"]) == pytest.approx([55, 15], abs=1), s["end"]["fields"]
    assert s["end"]["layoutCount"] == n0 + 2, s["end"]
    cx, cy = out["canvas"][0] / 2, out["canvas"][1] / 2
    assert _cap_draws(out)[-1] == pytest.approx([cx + 35, cy - 5, cx + 75, cy + 35], abs=1)


def test_stale_layout_reply_does_not_overwrite_newer(start_pult) -> None:
    """Два жеста подряд: ответ на первый ([15,5]) задержан на 0.6 с и приходит ПОСЛЕ ответа на
    второй ([25,5]) — картинка остаётся на [25,5] (origin 105), ошибки нет. Жесты, а не стрелки:
    стрелки с 1.3h-b ит.2 просят раскладку одним отложенным запросом на серию."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    _delay_layout(stand, lambda a: _offset0(a) == [15, 5], 0.6)
    steps = [
        _WAIT2,
        {"op": "drag", "from": _screen((105, 105)), "to": [15, 5], "steps": 2},
        {"op": "drag", "from": [15, 5], "to": [25, 5], "steps": 2},
        {"op": "sleep", "ms": 1000},
        _snap("end"),
    ]
    out = _run_canvas(stand.port, steps)
    assert _xy(out["snaps"]["end"]) == [25.0, 5.0], out["snaps"]["end"]
    assert out["snaps"]["end"]["error"] == ""
    offsets = [_offset0(a) for a in stand.layout_requests()]
    assert [15, 5] in offsets and offsets[-1] == [25, 5], offsets
    cx, cy = out["canvas"][0] / 2, out["canvas"][1] / 2
    assert _cap_draws(out)[-1] == pytest.approx([cx + 5, cy - 15, cx + 45, cy + 25], abs=0.01)


def test_stale_error_does_not_overwrite_fresh_success(start_pult) -> None:
    """K11a: ответ на первый жест — медленный `invalid` (0.6 с), на второй — быстрый успех;
    запоздалая ошибка НЕ затирает пустую строку `#presetLayoutError` (номер запроса проверяется
    и на ветке отказа, не только после декодирования картинок)."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    original = stand.layers.handlers["preset.layout"]

    def slow_invalid_for_first(args: dict) -> dict:
        if _offset0(args) == [6, 5]:
            time.sleep(0.6)
            return {"status": "error", "code": "invalid", "message": "устаревший отказ"}
        return original(args)

    stand.layers.handlers["preset.layout"] = slow_invalid_for_first
    steps = [
        _WAIT2,
        {"op": "drag", "from": _screen((105, 105)), "to": [6, 5], "steps": 1},
        {"op": "drag", "from": [6, 5], "to": [16, 5], "steps": 2},
        {"op": "sleep", "ms": 1000},
        _snap("end"),
    ]
    out = _run_canvas(stand.port, steps)
    end = out["snaps"]["end"]
    assert _xy(end) == [16.0, 5.0], end
    assert [6, 5] in [_offset0(a) for a in stand.layout_requests()], "контроль: медленный запрос ушёл"
    assert end["error"] == "", f"запоздалая ошибка затёрла успех: {end['error']!r}"


# --------------------------------------------------------------------------- #
# Жизненный цикл указателя                                                    #
# --------------------------------------------------------------------------- #
def test_pointercancel_aborts_gesture(start_pult) -> None:
    """pointercancel посреди жеста: правки нет, записи «Отмена» нет, раскладку не просят;
    запоздалый pointerup ничего не применяет; следующий жест работает как обычно."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    steps = [
        _WAIT2,
        {"op": "sleep", "ms": 200},
        _snap("s0"),
        {"op": "press", "at": _screen((105, 105))},
        {"op": "move", "at": [25, 5]},
        {"op": "fire", "type": "pointercancel", "at": [25, 5], "clears": True},
        {"op": "release", "at": [25, 5]},
        {"op": "sleep", "ms": 200},
        _snap("cancelled"),
        {"op": "press_button", "id": "btnPresetUndo"},
        _snap("undo"),
        {"op": "drag", "from": _screen((105, 105)), "to": [15, 5], "steps": 2},
        {"op": "sleep", "ms": 300},
        _snap("next"),
    ]
    out = _run_canvas(stand.port, steps)
    s = out["snaps"]
    assert _xy(s["cancelled"]) == [5.0, 5.0] and s["cancelled"]["layoutCount"] == s["s0"]["layoutCount"], s
    assert _xy(s["undo"]) == [5.0, 5.0]
    assert _xy(s["next"]) == [15.0, 5.0], s["next"]


def test_pointer_leaving_canvas_keeps_gesture(start_pult) -> None:
    """Указатель ушёл за край канвы (pointerleave, x > width) и отпущен там: жест не обрывается и
    не обрезается — дельта целиком (+395 px), одна запись «Отмена»."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    steps = [
        _WAIT2,
        {"op": "press", "at": _screen((105, 105))},
        {"op": "move", "at": [100, 5]},
        {"op": "fire", "type": "pointerleave", "at": [340, 5]},
        {"op": "move", "at": [400, 5]},
        {"op": "release", "at": [400, 5]},
        {"op": "sleep", "ms": 300},
        _snap("out"),
        {"op": "press_button", "id": "btnPresetUndo"},
        _snap("undo"),
    ]
    out = _run_canvas(stand.port, steps)
    assert out["canvas"][0] / 2 + 400 > out["canvas"][0], "контроль: точка отпускания вне канвы"
    assert _xy(out["snaps"]["out"]) == [400.0, 5.0], out["snaps"]["out"]
    assert _xy(out["snaps"]["undo"]) == [5.0, 5.0], out["snaps"]["undo"]


# --------------------------------------------------------------------------- #
# «Отмена»: снимок из полей, после жеста ввод кладёт свой снимок               #
# --------------------------------------------------------------------------- #
def test_gesture_snapshot_keeps_unsaved_typing_and_next_typing_gets_own_undo(start_pult) -> None:
    """Ввод y=9 без «Сохранить» -> жест +30 по x: [35,9] (ввод не потерян, раскладка просит [35,9]);
    ввод y=12 после жеста -> три «Отмены»: [35,9] -> [5,9] -> [5,5]."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    steps = [
        _WAIT2,
        {"op": "set_field", "id": "layer0_offset_y", "value": 9},
        {"op": "drag", "from": _screen((105, 105)), "to": [35, 5], "steps": 3},
        {"op": "sleep", "ms": 300},
        _snap("g"),
        {"op": "set_field", "id": "layer0_offset_y", "value": 12},
        _snap("typed"),
        {"op": "press_button", "id": "btnPresetUndo"},
        _snap("u1"),
        {"op": "press_button", "id": "btnPresetUndo"},
        _snap("u2"),
        {"op": "press_button", "id": "btnPresetUndo"},
        _snap("u3"),
    ]
    out = _run_canvas(stand.port, steps)
    s = out["snaps"]
    assert _xy(s["g"]) == [35.0, 9.0], s["g"]["fields"]
    assert stand.layout_requests()[1]["preset"]["layers"][0]["offset_px"] == [35, 9]
    assert _xy(s["typed"]) == [35.0, 12.0]
    assert [_xy(s["u1"]), _xy(s["u2"]), _xy(s["u3"])] == [[35.0, 9.0], [5.0, 9.0], [5.0, 5.0]], [
        s[t]["fields"] for t in ("u1", "u2", "u3")
    ]


# --------------------------------------------------------------------------- #
# Потолок тела layout/preview — 262144, как у commit                          #
# --------------------------------------------------------------------------- #
_CAP = 262144


def _post_exact(port: int, path: str, size: int) -> tuple[int, bytes]:
    head = b'{"preset": {"layers": []}, "pad": "'
    body = head + b"x" * (size - len(head) - 2) + b'"}'
    assert len(body) == size and json.loads(body)
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _declared_only(port: int, path: str, length: int) -> bytes:
    """Заявить Content-Length и прислать 64 байта — ответ до чтения тела (daemon + join)."""
    result: dict[str, Any] = {}

    def attempt() -> None:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
                sock.sendall(
                    f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                    f"Content-Type: application/json\r\nContent-Length: {length}\r\n\r\n".encode()
                    + b"x" * 64
                )
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                result["data"] = data
        except OSError as exc:
            result["error"] = repr(exc)

    thread = threading.Thread(target=attempt, daemon=True)
    thread.start()
    thread.join(timeout=8.0)
    assert not thread.is_alive(), "ответ не пришёл за 8 с"
    return result.get("data", b"")


@pytest.mark.parametrize(
    "path, command", [("/api/preset/layout", "preset.layout"), ("/api/preset/preview", "preset.preview")]
)
def test_layout_and_preview_body_cap_is_262144(start_pult, path: str, command: str) -> None:
    """Тело ровно 262144 байт доходит до `layers` (раньше — 413 на общих 4096); 262145 -> 413."""
    port = start_pult()
    layers = _client_for("layers")
    status, raw = _post_exact(port, path, _CAP)
    assert status == 200, f"{path}: тело {_CAP} байт -> {status} {raw[:200]!r}"
    assert [c for c, _a in layers.calls] == [command], layers.calls
    data = _declared_only(port, path, _CAP + 1)
    assert b" 413 " in data.split(b"\r\n", 1)[0], f"{path}: {_CAP + 1} байт -> {data[:100]!r}"
    assert len(layers.calls) == 1, "на 413 команда не зовётся"


# --------------------------------------------------------------------------- #
# Клавиатура: серия стрелок, пробел, поле ввода (Task 1.3h-b ит.2)            #
# --------------------------------------------------------------------------- #
_KEY_DEBOUNCE_MS = 200  # PRESET_KEY_LAYOUT_MS страницы; пауза в тесте заведомо больше


def test_arrow_burst_requests_layout_once(start_pult) -> None:
    """20 стрелок → подряд (без пауз): смещение [5,5] -> [25,5], в «Отмене» 20 записей (по одной на
    нажатие), а раскладку просят ОДИН раз — после паузы > 200 мс, во время серии ни разу. Цена
    `preset.layout` 50-90 мс на слое 1200 px: запрос на каждое нажатие копил бы очередь."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    steps = [
        _WAIT2,
        *_click_cap(),
        _snap("s0"),
        {"op": "key", "key": "ArrowRight", "times": 20, "gap": 0},
        _snap("burst"),
        {"op": "sleep", "ms": _KEY_DEBOUNCE_MS * 3},
        _snap("end"),
    ]
    steps += [{"op": "press_button", "id": "btnPresetUndo"} for _ in range(19)]
    steps += [_snap("undo19"), {"op": "press_button", "id": "btnPresetUndo"}, _snap("undo20")]
    out = _run_canvas(stand.port, steps)
    s = out["snaps"]
    n0 = s["s0"]["layoutCount"]
    assert _xy(s["burst"]) == [25.0, 5.0], "форма идёт за каждым нажатием, не за таймером"
    assert s["burst"]["layoutCount"] == n0, f"во время серии раскладку не просят: {s['burst']}"
    assert s["end"]["layoutCount"] == n0 + 1, f"после серии — ровно один запрос: {s['end']}"
    assert _offset0(stand.layout_requests()[n0]) == [25, 5], "запрос несёт итог серии"
    assert _xy(s["undo19"]) == [6.0, 5.0] and _xy(s["undo20"]) == [5.0, 5.0], (
        f"20 нажатий = 20 записей «Отмена»: {s['undo19']['fields']} / {s['undo20']['fields']}"
    )


def test_late_gesture_reply_does_not_roll_back_arrow_shift(start_pult) -> None:
    """F1 (ревью ит.2): жест до [15,5], его ответ раскладки задержан на 0,1 с, за это время идут
    4 стрелки с паузой 60 мс. Ответ на жест, пришедший ПОСЛЕ первой стрелки, не должен откатить
    битмап к смещению жеста: x рамки cap на канве не убывает. На старом коде x рамки — `[305, 310, 315, 316,
    317, 316, 317, 319]` (317 -> 316: запоздалый ответ), номер запроса стрелка не двигала."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    _delay_layout(stand, lambda a: _offset0(a) == [15, 5], 0.1)
    out = _run_canvas(
        stand.port,
        [
            _WAIT2,
            {"op": "drag", "from": _screen((105, 105)), "to": [15, 5], "steps": 2},
            {"op": "key", "key": "ArrowRight", "times": 4, "gap": 60},
            {"op": "sleep", "ms": _KEY_DEBOUNCE_MS * 3},
            _snap("end"),
        ],
    )
    xs = [b[0] for b in _cap_draws(out)]
    assert len(xs) >= 5, f"вакуумная проверка: рисовать было нечего: {xs}"
    assert xs == sorted(xs), f"битмап откатился назад после запоздалого ответа жеста: {xs}"
    assert _xy(out["snaps"]["end"]) == [19.0, 5.0], out["snaps"]["end"]["fields"]


def test_gesture_clears_pending_arrow_timer(start_pult) -> None:
    """F2 (ревью ит.2): 2 стрелки, до истечения 200 мс — жест до [17,5]. Жест просит раскладку сам и
    обязан снять висящий таймер стрелок: после паузы всего один запрос (жеста), а не два. Охраняет
    clearTimeout в пути без deferLayout: без него таймер стрелок стрельнул бы вторым запросом."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    out = _run_canvas(
        stand.port,
        [
            _WAIT2,
            *_click_cap(),
            _snap("s0"),
            {"op": "key", "key": "ArrowRight", "times": 2, "gap": 0},
            {"op": "drag", "from": _screen((107, 105)), "to": [17, 5], "steps": 2},
            {"op": "sleep", "ms": _KEY_DEBOUNCE_MS * 3},
            _snap("end"),
        ],
    )
    n0 = out["snaps"]["s0"]["layoutCount"]
    reqs = stand.layout_requests()[n0:]
    assert len(reqs) == 1, f"после стрелок и жеста ждём один запрос раскладки: {[_offset0(a) for a in reqs]}"
    assert _offset0(reqs[0]) == [17, 5], "единственный запрос несёт итог жеста"
    assert _xy(out["snaps"]["end"]) == [17.0, 5.0], out["snaps"]["end"]["fields"]


def test_space_on_canvas_prevents_default_and_on_button_is_ignored(start_pult) -> None:
    """Пробел над канвой: preventDefault (страница не прокручивается) и флаг панорамы — ЛКМ-жест
    после него не двигает слой. Пробел на кнопке/поле: ни preventDefault (кнопка нажимается
    пробелом), ни флага — жест двигает слой как обычно."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    drag = {"op": "drag", "from": _screen((105, 105)), "to": [25, 5], "steps": 2}
    on_canvas = _run_canvas(
        stand.port,
        [
            _WAIT2,
            *_click_cap(),
            {"op": "key", "key": " ", "code": "Space"},
            drag,
            {"op": "sleep", "ms": 200},
            _snap("e"),
        ],
    )
    assert on_canvas["pd"] == [" "], f"пробел над канвой обязан звать preventDefault: {on_canvas['pd']}"
    assert _xy(on_canvas["snaps"]["e"]) == [5.0, 5.0], "пробел+ЛКМ — панорама, слой не сдвинут"
    for tag in ("BUTTON", "INPUT"):
        on_control = _run_canvas(
            stand.port,
            [
                _WAIT2,
                *_click_cap(),
                {"op": "key", "key": " ", "code": "Space", "target": tag},
                drag,
                {"op": "sleep", "ms": 200},
                _snap("e"),
            ],
        )
        assert on_control["pd"] == [], f"пробел на {tag}: preventDefault не звать: {on_control['pd']}"
        assert _xy(on_control["snaps"]["e"]) == [25.0, 5.0], f"пробел на {tag} не включает панораму"


def test_space_with_target_body_prevents_default_and_pans(start_pult) -> None:
    """F3 (ревью ит.2): пробел, у которого источник — сам `document.body` (фокус ни на чём, страница
    сфокусирована), — та же панорама, что и над канвой: preventDefault (страница не прокручивается),
    ЛКМ-жест при зажатом пробеле не двигает слой. Харнесс раньше не имел `document.body`, и ветка
    `e.target === document.body` не исполнялась вовсе."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    out = _run_canvas(
        stand.port,
        [
            _WAIT2,
            *_click_cap(),
            {"op": "key", "key": " ", "code": "Space", "target": "BODY"},
            {"op": "drag", "from": _screen((105, 105)), "to": [25, 5], "steps": 2},
            {"op": "sleep", "ms": 200},
            _snap("e"),
        ],
    )
    assert out["pd"] == [" "], f"пробел на body обязан звать preventDefault: {out['pd']}"
    assert _xy(out["snaps"]["e"]) == [5.0, 5.0], "пробел на body + ЛКМ — панорама, слой не сдвинут"


def test_arrow_from_input_does_not_move_layer(start_pult) -> None:
    """K20: стрелка в поле ввода (target INPUT) — правка текста, не слоя: смещение [5,5],
    preventDefault не звали (каретка в поле должна двигаться)."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    out = _run_canvas(
        stand.port,
        [
            _WAIT2,
            *_click_cap(),
            {"op": "key", "key": "ArrowRight", "target": "INPUT"},
            {"op": "sleep", "ms": 300},
            _snap("e"),
        ],
    )
    assert _xy(out["snaps"]["e"]) == [5.0, 5.0], out["snaps"]["e"]
    assert out["pd"] == [], out["pd"]


# --------------------------------------------------------------------------- #
# Указатель и форма (Task 1.3h-b ит.2)                                        #
# --------------------------------------------------------------------------- #
def test_pointerup_of_foreign_pointer_ignored(start_pult) -> None:
    """K19: pointerup ДРУГОГО указателя (pointerId 2) посреди жеста не завершает его: итог считается
    по pointerup своего указателя — [25,5], не по чужой точке (100,100)."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    steps = [
        _WAIT2,
        {"op": "press", "at": _screen((105, 105))},
        {"op": "move", "at": [15, 5]},
        {"op": "fire", "type": "pointerup", "at": [100, 100], "pointerId": 2},
        {"op": "move", "at": [25, 5]},
        {"op": "release", "at": [25, 5]},
        {"op": "sleep", "ms": 300},
        _snap("end"),
    ]
    out = _run_canvas(stand.port, steps)
    assert _xy(out["snaps"]["end"]) == [25.0, 5.0], out["snaps"]["end"]


def test_field_change_rerequests_layout_with_typed_value(start_pult) -> None:
    """K9b + обработчик change на #presetLayers: ввод 50 в поле x и всплывший `change` -> ровно
    один новый запрос раскладки (всего 2), и его тело несёт набранное [50,5], а не старое
    состояние presetState."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    steps = [
        _WAIT2,
        {"op": "sleep", "ms": 200},
        {"op": "set_field", "id": "layer0_offset_x", "value": 50},
        {"op": "fire_el", "id": "presetLayers", "type": "change"},
        {"op": "sleep", "ms": 400},
        _snap("end"),
    ]
    out = _run_canvas(stand.port, steps)
    offsets = [_offset0(a) for a in stand.layout_requests()]
    assert len(offsets) == 2, offsets
    assert offsets[-1] == [50, 5], offsets
    assert out["snaps"]["end"]["layoutCount"] == 2


def test_rename_in_form_keeps_layer_editable(start_pult) -> None:
    """Слой переименовали в форме (layer0_name=cap2) и раскладка перезапрошена: имя слоя на канве —
    новое, состояние `presetState` ещё со старым. Клик выбирает слой, жест +20 двигает его."""
    stand = _stand(start_pult, [_layer("cap", 5, 5)])
    tolerant = stand.layers.handlers["preset.layout"]

    def any_name(args: dict) -> dict:
        layers = args["preset"]["layers"]
        reply = tolerant({"preset": {"layers": [dict(ly, name="cap") for ly in layers]}})
        for entry, ly in zip(reply["layers"][1:], layers):
            entry["name"] = ly["name"]  # спрайт cap под новым именем: _SPRITES других имён не знает
        return reply

    stand.layers.handlers["preset.layout"] = any_name
    steps = [
        _WAIT2,
        {"op": "sleep", "ms": 200},
        {"op": "set_field", "id": "layer0_name", "value": "cap2"},
        {"op": "fire_el", "id": "presetLayers", "type": "change"},
        {"op": "sleep", "ms": 400},
        *_click_cap(),
        _snap("clicked"),
        {"op": "drag", "from": _screen((105, 105)), "to": [25, 5], "steps": 2},
        {"op": "sleep", "ms": 300},
        _snap("dragged"),
    ]
    out = _run_canvas(stand.port, steps)
    s = out["snaps"]
    assert stand.layout_requests()[-1]["preset"]["layers"][0]["name"] == "cap2", "контроль: имя ушло в раскладку"
    assert len(s["clicked"]["selected"]) == 1, f"клик по переименованному слою не выбрал строку: {s['clicked']}"
    assert _xy(s["dragged"]) == [25.0, 5.0], s["dragged"]
