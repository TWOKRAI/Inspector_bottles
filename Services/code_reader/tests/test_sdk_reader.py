# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты Task 6.2: модель кадра и сессия прибора.

Написаны ДО кода, только по контракту Task 6.2 из plans/code-reader-sdk.md
(«Контекст», «Решения» 3-6). Ожидаемые значения — литералы из живой таблицы
5 срабатываний (2026-09-29), а не вывод из тестируемого кода.

Что здесь ПРЕДПОЛОЖЕНО, а не задано контрактом (правится в одном месте — в
таблицах имён полей и в ``make_raw`` ниже):
  * ``RawFrame`` — плоский, по ключевым словам (решение лидера 2026-09-29, см. план 6.1);
  * имена полей C-структур (Венгерская нотация из плана + догадки для остальных).

Импорты проекта — внутри функций (``_m``), чтобы каждый тест падал сам, а не
один общий сбой сбора модуля.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import threading
import time
from collections import deque
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

# --------------------------------------------------------------------------
# Допущения о раскладке структур SDK (одно место правки)
# --------------------------------------------------------------------------

# IMAGE_OUT_INFO_EX2
F_WIDTH = "nWidth"
F_HEIGHT = "nHeight"
F_PIXEL = "enPixelType"
F_FRAME_NUM = "nFrameNum"
F_TRIGGER = "nTriggerIndex"  # ДОГАДКА
F_IS_GET_CODE = "bIsGetCode"
# RESULT_BCR_EX2
F_CODE_NUM = "nCodeNum"
F_ITEMS = "stBcrInfoEx2"
F_NO_READ = "nNoReadNum"  # ДОГАДКА: на уровне RESULT_BCR_EX2 (не записи)
# BCR_INFO_EX2
F_TEXT = "chCode"
F_LEN = "nLen"
F_BAR = "nBarType"
F_PT = "pt"
F_ANGLE = "nAngle"
F_PPM = "sPPM"
F_ALGO = "sAlgoCost"
F_QUALITY = "stCodeQuality"
F_IS_GET_QUALITY = "bIsGetQuality"  # ДОГАДКА: на уровне записи
# POINT_I
F_X = "x"  # MvCodeReaderParams.h: MV_CODEREADER_POINT_I
F_Y = "y"
# stCodeQuality: ключ grades -> имя поля (ВСЕ имена, кроме nOverQuality и nIDRScore, — ДОГАДКА)
F_Q_OVERALL = "nOverQuality"
F_Q_SCORE = "nIDRScore"
F_Q_GRADES = {  # имена полей MV_CODEREADER_CODE_INFO из заголовка (решение лидера)
    "decode": "nDeCode",
    "contrast": "nSCGrade",
    "modulation": "nModGrade",
    "fixed_pattern_damage": "nFPDGrade",
    "axial_nonuniformity": "nANGrade",
    "grid_nonuniformity": "nGNGrade",
    "unused_error_correction": "nUECGrade",
}

PIXEL_MONO8 = 0x01080001
PIXEL_JPEG = 0x80180001
ACCESS_DENIED = 0x80020203
BAR_NOREAD = 1001

# Литералы живой таблицы (строки 1-4)
CORNERS_LIVE = [[489, 471], [568, 486], [584, 406], [505, 391]]
CORNERS_LIVE_T = ((489, 471), (568, 486), (584, 406), (505, 391))


def _m(name: str):
    return importlib.import_module(name)


# --------------------------------------------------------------------------
# Построение входа frame_from_raw
# --------------------------------------------------------------------------


def code(
    text: str = "QR-20MM",
    *,
    bar_type: int = 2,
    corners=CORNERS_LIVE,
    angle10: int = 155,
    ppm10: int = 123,
    algo_ms: int = 25,
    length: int | None = None,
    get_quality: bool = False,
    quality: dict | None = None,
) -> dict:
    return dict(
        text=text,
        bar_type=bar_type,
        corners=corners,
        angle10=angle10,
        ppm10=ppm10,
        algo_ms=algo_ms,
        length=len(text) if length is None else length,
        get_quality=get_quality,
        quality=quality or {},
    )


def bad_code(**kw) -> dict:
    """Строка 4 живой таблицы: chCode пуст, nLen=0, nBarType=1001, 4 угла на месте."""
    kw.setdefault("bar_type", BAR_NOREAD)
    return code("", length=0, **kw)


def _set(obj, name: str, value) -> None:
    """setattr, который падает на опечатке: ctypes молча создаёт атрибут для чужого имени."""
    names = {f[0] for f in type(obj)._fields_}
    assert name in names, f"{type(obj).__name__} не имеет поля {name!r}"
    setattr(obj, name, value)


def make_raw(
    codes: list[dict] | None,
    *,
    width: int = 1280,
    height: int = 1024,
    pixel: int = PIXEL_JPEG,
    frame_num: int = 7,
    trigger: int = 3,
    no_read: int = 0,
    image: bytes = b"\xff\xd8fake\xff\xd9",
    is_get_code: bool | None = None,  # noqa: ARG001 — в RawFrame такого поля нет; оставлен для вызовов
):
    """Собрать RawFrame (плоский, решение лидера). ``codes=None`` — пустой список кодов."""
    st = _m("Services.code_reader.sdk.structures")
    api = _m("Services.code_reader.sdk.api")

    items = []
    for c in codes or []:
        it = st.BCR_INFO_EX2()
        _set(it, F_TEXT, c["text"].encode("utf-8"))
        _set(it, F_LEN, c["length"])
        _set(it, F_BAR, c["bar_type"])
        _set(it, F_ANGLE, c["angle10"])
        _set(it, F_PPM, c["ppm10"])
        _set(it, F_ALGO, c["algo_ms"])
        _set(it, F_IS_GET_QUALITY, c["get_quality"])
        pts = getattr(it, F_PT)
        for j, (x, y) in enumerate(c["corners"]):
            _set(pts[j], F_X, x)
            _set(pts[j], F_Y, y)
        q = getattr(it, F_QUALITY)
        for key, value in c["quality"].items():
            if key == F_Q_SCORE:  # nIDRScore лежит в записи кода, не в CODE_INFO
                _set(it, key, value)
            else:
                _set(q, F_Q_GRADES.get(key, key), value)
        items.append(it)
    return api.RawFrame(
        image=image,
        width=width,
        height=height,
        pixel_type=pixel,
        trigger_index=trigger,
        frame_num=frame_num,
        no_read_num=no_read,
        codes=tuple(items),
    )


def frame(codes, **kw):
    return _m("Services.code_reader.core.sdk_frame").frame_from_raw(make_raw(codes, **kw))


def _status(name: str):
    return getattr(_m("Services.code_reader.core.result").ReadStatus, name)


QUALITY_NUMBERS = {
    "overall": 4,
    "score": 88,
    "decode": 11,
    "contrast": 12,
    "modulation": 13,
    "fixed_pattern_damage": 14,
    "axial_nonuniformity": 15,
    "grid_nonuniformity": 16,
    "unused_error_correction": 17,
}


def _quality_fields() -> dict:
    q = {k: v for k, v in QUALITY_NUMBERS.items() if k not in ("overall", "score")}
    q[F_Q_OVERALL] = QUALITY_NUMBERS["overall"]
    q[F_Q_SCORE] = QUALITY_NUMBERS["score"]
    return q


# --------------------------------------------------------------------------
# frame_from_raw: статус кадра из списка кодов (решение 3)
# --------------------------------------------------------------------------


def test_frame_statuses_ok_bad_code_no_code_from_live_table():
    ok = frame([code("QR-20MM")])
    bad = frame([bad_code()], no_read=1)
    none = frame([], is_get_code=False)
    assert ok.status is _status("OK")
    assert bad.status is _status("BAD_CODE")
    assert none.status is _status("NO_CODE")
    assert ok.codes[0].text == "QR-20MM"
    assert ok.codes[0].status is _status("OK")
    assert ok.codes[0].bar_type == 2
    assert bad.codes[0].status is _status("BAD_CODE")
    assert bad.codes[0].text == ""
    assert bad.codes[0].bar_type == 1001
    assert bad.no_read_num == 1
    assert none.codes == ()
    assert none.no_read_num == 0


def test_frame_with_no_codes_struct_at_all_is_no_code():
    f = frame(None, is_get_code=False)
    assert f.status is _status("NO_CODE")
    assert f.codes == ()


def test_bad_code_keeps_four_corners_from_live_table():
    f = frame([bad_code()], no_read=1)
    assert f.codes[0].corners == CORNERS_LIVE_T


def test_ok_code_keeps_four_corners_as_tuple_of_int_tuples():
    c = frame([code("QR-20MM")]).codes[0]
    assert c.corners == CORNERS_LIVE_T
    assert all(isinstance(p, tuple) for p in c.corners)


def test_frame_with_one_readable_and_one_unreadable_is_ok():
    f = frame([bad_code(), code("QR-15MM")], no_read=1)
    assert f.status is _status("OK")
    assert [c.text for c in f.codes] == ["", "QR-15MM"]
    assert [c.status for c in f.codes] == [_status("BAD_CODE"), _status("OK")]


def test_frame_with_two_unreadable_codes_is_bad_code():
    f = frame([bad_code(), bad_code()], no_read=2)
    assert f.status is _status("BAD_CODE")
    assert len(f.codes) == 2


@pytest.mark.parametrize(
    "readable, expected",
    [
        ((), "NO_CODE"),
        ((False,), "BAD_CODE"),
        ((True,), "OK"),
        ((False, False), "BAD_CODE"),
        ((False, True), "OK"),
        ((True, False), "OK"),
        ((True, True), "OK"),
        ((False, False, True), "OK"),
    ],
)
def test_status_rule_readable_any_then_bad_code_if_any_record_else_no_code(readable, expected):
    codes = [code(f"C{i}") if r else bad_code() for i, r in enumerate(readable)]
    f = frame(codes)
    assert f.status is _status(expected)
    assert len(f.codes) == len(readable)


def test_code_numeric_fields_are_scaled_by_ten():
    c = frame([code("QR-20MM", angle10=155, ppm10=123, algo_ms=25)]).codes[0]
    assert c.angle_deg == pytest.approx(15.5)
    assert c.ppm == pytest.approx(12.3)
    assert c.algo_ms == 25
    assert isinstance(c.angle_deg, float)
    assert isinstance(c.ppm, float)


def test_negative_angle_is_scaled_not_truncated():
    c = frame([code(angle10=-155)]).codes[0]
    assert c.angle_deg == pytest.approx(-15.5)


def test_frame_metadata_and_image_bytes_are_carried():
    jpeg = b"\xff\xd8abc\xff\xd9"
    f = frame([code()], width=1280, height=1024, frame_num=42, trigger=9, image=jpeg)
    assert (f.width, f.height) == (1280, 1024)
    assert f.frame_num == 42
    assert f.trigger_index == 9
    assert f.image == jpeg


def test_pixel_format_names():
    assert frame([], pixel=PIXEL_JPEG).pixel_format == "jpeg"
    assert frame([], pixel=PIXEL_MONO8).pixel_format == "mono8"


def test_pixel_format_unknown_carries_hex():
    fmt = frame([], pixel=0x12345678).pixel_format
    assert fmt.startswith("unknown:0x")
    assert "12345678" in fmt.lower()


# --------------------------------------------------------------------------
# Качество: None, когда прибор его не посчитал
# --------------------------------------------------------------------------


def test_quality_none_when_not_computed_even_with_nonzero_numbers():
    f = frame([code(get_quality=False, quality=_quality_fields())])
    assert f.codes[0].quality is None


def test_quality_none_when_not_computed_and_numbers_zero():
    f = frame([code(get_quality=False)])
    assert f.codes[0].quality is None


def test_quality_present_with_structure_numbers_when_computed():
    q = frame([code(get_quality=True, quality=_quality_fields())]).codes[0].quality
    assert q is not None
    assert q.overall == 4
    assert q.score == 88
    assert q.grades == {
        "decode": 11,
        "contrast": 12,
        "modulation": 13,
        "fixed_pattern_damage": 14,
        "axial_nonuniformity": 15,
        "grid_nonuniformity": 16,
        "unused_error_correction": 17,
    }


def test_quality_computed_with_zero_numbers_is_a_quality_not_none():
    """bIsGetQuality=true и нули — это оценка (нулевая), а не «оценки нет»."""
    q = frame([code(get_quality=True)]).codes[0].quality
    assert q is not None
    assert q.overall == 0
    assert q.score == 0
    assert set(q.grades) == set(F_Q_GRADES)


def test_quality_flag_is_per_code():
    f = frame(
        [
            code("A", get_quality=True, quality=_quality_fields()),
            code("B", get_quality=False, quality=_quality_fields()),
        ]
    )
    assert f.codes[0].quality is not None
    assert f.codes[1].quality is None


# --------------------------------------------------------------------------
# Неизменяемость и to_dict
# --------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["frame", "code", "quality"])
def test_models_are_frozen(which):
    f = frame([code(get_quality=True, quality=_quality_fields())])
    target = {"frame": f, "code": f.codes[0], "quality": f.codes[0].quality}[which]
    field = {"frame": "width", "code": "text", "quality": "overall"}[which]
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(target, field, 1)


def test_to_dict_is_json_safe_without_image_bytes():
    jpeg = b"\xff\xd8\x00\x01\x02\xff\xd9"
    f = frame(
        [code("QR-20MM", get_quality=True, quality=_quality_fields()), bad_code()],
        image=jpeg,
        no_read=1,
    )
    d = f.to_dict()
    json.dumps(d)  # не должно бросать: ни bytes, ни enum, ни tuple-ключей
    assert "image" not in d
    assert d["image_len"] == len(jpeg)


def test_to_dict_statuses_are_plain_strings():
    d = frame([code("QR-20MM"), bad_code()], no_read=1).to_dict()
    assert d["status"] == "ok"
    assert type(d["status"]) is str
    assert [c["status"] for c in d["codes"]] == ["ok", "bad_code"]
    assert all(type(c["status"]) is str for c in d["codes"])


def test_to_dict_carries_scalars_and_code_text():
    d = frame([code("QR-20MM")], frame_num=42, trigger=9).to_dict()
    assert d["frame_num"] == 42
    assert d["trigger_index"] == 9
    assert d["width"] == 1280
    assert d["height"] == 1024
    assert d["pixel_format"] == "jpeg"
    assert d["codes"][0]["text"] == "QR-20MM"


def test_to_dict_no_code_frame_json_safe():
    d = frame([], is_get_code=False).to_dict()
    json.dumps(d)
    assert d["status"] == "no_code"
    assert d["codes"] == []


def test_to_dict_quality_none_survives_json():
    d = frame([code(get_quality=False)]).to_dict()
    json.dumps(d)
    assert d["codes"][0]["quality"] is None


# --------------------------------------------------------------------------
# decode_image
# --------------------------------------------------------------------------


def test_decode_image_jpeg_mono8_and_unknown():
    sf = _m("Services.code_reader.core.sdk_frame")
    h, w = 32, 48
    img = np.zeros((h, w), np.uint8)
    img[:, w // 2 :] = 255
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    jpeg_frame = frame([], pixel=PIXEL_JPEG, width=w, height=h, image=buf.tobytes())
    out = sf.decode_image(jpeg_frame)
    assert out.shape == (h, w)
    assert out.dtype == np.uint8
    assert out[:, : w // 4].mean() < 40
    assert out[:, -w // 4 :].mean() > 215

    raw = (np.arange(h * w) % 251).astype(np.uint8).tobytes()
    mono_frame = frame([], pixel=PIXEL_MONO8, width=w, height=h, image=raw)
    out = sf.decode_image(mono_frame)
    assert out.shape == (h, w)
    assert out.dtype == np.uint8
    assert out.tobytes() == raw

    unknown = frame([], pixel=0x12345678, width=w, height=h, image=raw)
    with pytest.raises(ValueError) as ei:
        sf.decode_image(unknown)
    assert "0x12345678" in str(ei.value).lower()


def test_decode_image_color_jpeg_gives_gray_two_dimensional():
    sf = _m("Services.code_reader.core.sdk_frame")
    h, w = 24, 40
    color = np.zeros((h, w, 3), np.uint8)
    color[:, :, 2] = 255  # красный
    ok, buf = cv2.imencode(".jpg", color)
    assert ok
    out = sf.decode_image(frame([], pixel=PIXEL_JPEG, width=w, height=h, image=buf.tobytes()))
    assert out.shape == (h, w)
    assert out.dtype == np.uint8


def test_decode_image_mono8_is_row_major_width_is_columns():
    sf = _m("Services.code_reader.core.sdk_frame")
    w, h = 4, 2
    raw = bytes([1, 2, 3, 4, 5, 6, 7, 8])
    out = sf.decode_image(frame([], pixel=PIXEL_MONO8, width=w, height=h, image=raw))
    assert out.tolist() == [[1, 2, 3, 4], [5, 6, 7, 8]]


# --------------------------------------------------------------------------
# Фейковый api и рабочее место для SdkCodeReader
# --------------------------------------------------------------------------


class FakeApi:
    """Записывает вызовы; кадры отдаёт из очереди сценария.

    Элемент сценария: RawFrame, None (E_NODATA) или исключение (будет брошено).
    Очередь пуста -> короткая пауза и None, как «кадра за таймаут не было».
    ``block_s`` > 0 -> каждый get_frame спит ровно столько (блокирующий SDK).
    """

    def __init__(self, entries=None, script=(), *, open_error=None, grab_error=None, block_s=0.0):
        self.entries = (
            [SimpleNamespace(ip="10.0.0.1", model="MV-ID3013PM", serial="S1", info=object())]
            if entries is None
            else entries
        )
        self.script = deque(script)
        self.open_error = open_error
        self.grab_error = grab_error
        self.block_s = block_s
        self.calls: list[tuple] = []
        self.handle = object()
        self.in_flight = 0
        self.closed_while_in_flight = None
        self._lock = threading.Lock()

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]

    def count(self, name: str) -> int:
        return self.names().count(name)

    def enum_devices(self):
        self.calls.append(("enum_devices",))
        return list(self.entries)

    def open(self, entry):
        self.calls.append(("open", entry))
        if self.open_error is not None:
            raise self.open_error
        return self.handle

    def start_grabbing(self, h):
        self.calls.append(("start_grabbing", h))
        if self.grab_error is not None:
            raise self.grab_error

    def get_frame(self, h, timeout_ms):
        self.calls.append(("get_frame", h, timeout_ms))
        with self._lock:
            self.in_flight += 1
        try:
            if self.block_s:
                time.sleep(self.block_s)
                return None
            with self._lock:
                item = self.script.popleft() if self.script else None
            if item is None:
                time.sleep(0.01)
                return None
            if isinstance(item, BaseException):
                raise item
            return item
        finally:
            with self._lock:
                self.in_flight -= 1

    def stop_grabbing(self, h):
        self.calls.append(("stop_grabbing", h))

    def close(self, h):
        with self._lock:
            self.closed_while_in_flight = self.in_flight > 0
        self.calls.append(("close", h))


def sdk_error(code_: int, where: str = "GetOneFrameTimeoutEx2"):
    return _m("Services.code_reader.sdk.errors").SdkError(code_, where)


def wait_until(pred, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return pred()


@pytest.fixture
def make_reader():
    """Фабрика читателей + гарантированная остановка (в daemon-потоке, с дедлайном)."""
    created = []

    def factory(api, *, on_frame=None, on_error=None, **kw):
        cls = _m("Services.code_reader.core.sdk_reader").SdkCodeReader
        frames: list = []
        errors: list[str] = []

        def _on_frame(f):
            frames.append(f)
            if on_frame is not None:
                on_frame(f)

        def _on_error(msg):
            errors.append(msg)
            if on_error is not None:
                on_error(msg)

        reader = cls(_on_frame, _on_error, api=api, **kw)
        created.append(reader)
        return SimpleNamespace(reader=reader, frames=frames, errors=errors, api=api)

    yield factory
    for r in created:
        t = threading.Thread(target=r.stop, daemon=True)
        t.start()
        t.join(10.0)


def three_frames():
    return [
        make_raw([code("QR-15MM")], trigger=1, frame_num=1),
        make_raw([code("QR-20MM")], trigger=2, frame_num=2),
        make_raw([code("QR-20MM")], trigger=3, frame_num=3),
    ]


# --------------------------------------------------------------------------
# Жизненный цикл: start / доставка / stop
# --------------------------------------------------------------------------


def test_reader_delivers_frames_in_order_and_stop_closes_once(make_reader):
    api = FakeApi(script=three_frames())
    r = make_reader(api, timeout_ms=20)
    assert r.reader.start() is True
    assert r.reader.state == "running"
    assert wait_until(lambda: len(r.frames) >= 3)

    assert [f.trigger_index for f in r.frames] == [1, 2, 3]
    assert [f.codes[0].text for f in r.frames] == ["QR-15MM", "QR-20MM", "QR-20MM"]
    sdk_frame = _m("Services.code_reader.core.sdk_frame")
    assert all(isinstance(f, sdk_frame.SdkFrame) for f in r.frames)

    r.reader.stop()
    assert r.reader.state == "stopped"
    assert api.count("stop_grabbing") == 1
    assert api.count("close") == 1
    names = api.names()
    assert names.index("stop_grabbing") < names.index("close")

    n = len(api.calls)
    r.reader.stop()
    assert len(api.calls) == n  # второй stop() ничего не зовёт
    assert r.reader.state == "stopped"


def test_start_sequence_is_enum_open_start_grabbing(make_reader):
    api = FakeApi()
    r = make_reader(api, timeout_ms=20)
    assert r.reader.start() is True
    assert api.names()[:3] == ["enum_devices", "open", "start_grabbing"]


def test_handle_from_open_is_used_by_every_later_call(make_reader):
    api = FakeApi(script=three_frames())
    r = make_reader(api, timeout_ms=20)
    r.reader.start()
    assert wait_until(lambda: len(r.frames) >= 3)
    r.reader.stop()
    later = [c for c in api.calls if c[0] in ("start_grabbing", "get_frame", "stop_grabbing", "close")]
    assert later
    assert all(c[1] is api.handle for c in later)


def test_second_start_while_running_returns_true_without_second_open(make_reader):
    api = FakeApi()
    r = make_reader(api, timeout_ms=20)
    assert r.reader.start() is True
    assert r.reader.start() is True
    assert r.reader.state == "running"
    assert api.count("open") == 1
    assert api.count("start_grabbing") == 1


def test_stop_without_start_calls_nothing_and_does_not_raise(make_reader):
    api = FakeApi()
    r = make_reader(api)
    r.reader.stop()
    assert api.calls == []


def test_restart_after_stop_opens_again_and_closes_once_per_open(make_reader):
    api = FakeApi(script=[make_raw([code()], trigger=1)])
    r = make_reader(api, timeout_ms=20)
    assert r.reader.start() is True
    r.reader.stop()
    assert r.reader.start() is True
    assert r.reader.state == "running"
    r.reader.stop()
    assert api.count("open") == 2
    assert api.count("close") == 2


def test_get_frame_receives_timeout_ms_from_constructor(make_reader):
    api = FakeApi()
    r = make_reader(api, timeout_ms=123)
    r.reader.start()
    assert wait_until(lambda: api.count("get_frame") >= 1)
    r.reader.stop()
    assert {c[2] for c in api.calls if c[0] == "get_frame"} == {123}


def test_default_timeout_ms_is_500(make_reader):
    api = FakeApi()
    r = make_reader(api)
    r.reader.start()
    assert wait_until(lambda: api.count("get_frame") >= 1)
    r.reader.stop()
    assert {c[2] for c in api.calls if c[0] == "get_frame"} == {500}


def test_nodata_none_is_not_an_error_and_not_a_frame(make_reader):
    api = FakeApi()
    r = make_reader(api, timeout_ms=10)
    r.reader.start()
    assert wait_until(lambda: api.count("get_frame") >= 5)
    assert r.reader.state == "running"
    assert r.frames == []
    assert r.errors == []
    assert r.reader.stats()["errors"] == 0
    r.reader.stop()


# --------------------------------------------------------------------------
# Поиск прибора
# --------------------------------------------------------------------------


def test_device_not_found_gives_false_and_not_found_state(make_reader):
    api = FakeApi(entries=[])
    r = make_reader(api)
    assert r.reader.start() is False
    assert r.reader.state == "not_found"
    assert api.count("open") == 0


def test_device_ip_selects_matching_device(make_reader):
    e1 = SimpleNamespace(ip="10.0.0.1", model="M1", serial="S1", info=object())
    e2 = SimpleNamespace(ip="10.0.0.2", model="M2", serial="S2", info=object())
    api = FakeApi(entries=[e1, e2])
    r = make_reader(api, device_ip="10.0.0.2", timeout_ms=20)
    assert r.reader.start() is True
    opened = [c[1] for c in api.calls if c[0] == "open"]
    assert opened == [e2]
    dev = r.reader.stats()["device"]
    assert dev == {"ip": "10.0.0.2", "model": "M2", "serial": "S2"}


def test_device_ip_without_match_is_not_found(make_reader):
    e1 = SimpleNamespace(ip="10.0.0.1", model="M1", serial="S1", info=object())
    api = FakeApi(entries=[e1])
    r = make_reader(api, device_ip="10.9.9.9")
    assert r.reader.start() is False
    assert r.reader.state == "not_found"
    assert api.count("open") == 0


def test_without_device_ip_first_device_is_opened(make_reader):
    e1 = SimpleNamespace(ip="10.0.0.1", model="M1", serial="S1", info=object())
    e2 = SimpleNamespace(ip="10.0.0.2", model="M2", serial="S2", info=object())
    api = FakeApi(entries=[e1, e2])
    r = make_reader(api, timeout_ms=20)
    assert r.reader.start() is True
    assert [c[1] for c in api.calls if c[0] == "open"] == [e1]


# --------------------------------------------------------------------------
# Остановка: дедлайн при блокирующем get_frame
# --------------------------------------------------------------------------


def test_stop_returns_within_deadline_when_get_frame_blocks(make_reader):
    timeout_ms = 300
    stop_timeout = 1.0
    api = FakeApi(block_s=timeout_ms / 1000)
    r = make_reader(api, timeout_ms=timeout_ms)
    assert r.reader.start() is True
    assert wait_until(lambda: api.in_flight > 0)

    done = threading.Event()
    box = {}

    def run():
        t0 = time.monotonic()
        r.reader.stop(timeout=stop_timeout)
        box["elapsed"] = time.monotonic() - t0
        done.set()

    threading.Thread(target=run, daemon=True).start()
    assert done.wait(stop_timeout + timeout_ms / 1000 + 2.0), "stop() завис"
    # контракт: <= timeout + timeout_ms; +0.5 c на планировщик
    assert box["elapsed"] <= stop_timeout + timeout_ms / 1000 + 0.5
    assert r.reader.state == "stopped"
    assert api.count("stop_grabbing") == 1
    assert api.count("close") == 1


def test_close_is_never_called_while_get_frame_is_in_flight(make_reader):
    """ДОБАВЛЕНО тестером (в контракте явно нет): закрыть handle под идущим
    GetOneFrame в настоящем SDK — обращение к освобождённому буферу."""
    api = FakeApi(block_s=0.2)
    r = make_reader(api, timeout_ms=200)
    r.reader.start()
    assert wait_until(lambda: api.in_flight > 0)
    done = threading.Event()
    threading.Thread(target=lambda: (r.reader.stop(timeout=2.0), done.set()), daemon=True).start()
    assert done.wait(5.0), "stop() завис"
    assert api.count("close") == 1
    assert api.closed_while_in_flight is False


# --------------------------------------------------------------------------
# Эксклюзивный доступ
# --------------------------------------------------------------------------


def test_access_denied_gives_busy_closes_handle_mentions_idmvs(make_reader):
    """Отказ приходит на start_grabbing: handle уже создан -> его надо закрыть."""
    api = FakeApi(grab_error=sdk_error(ACCESS_DENIED, "StartGrabbing"))
    r = make_reader(api)
    assert r.reader.start() is False
    assert r.reader.state == "busy"
    assert api.count("close") == 1
    assert [c for c in api.calls if c[0] == "close"][0][1] is api.handle
    assert r.errors, "on_error не вызван"
    assert "idmvs" in " ".join(r.errors).lower()


def test_access_denied_on_open_gives_busy_and_mentions_idmvs(make_reader):
    """Отказ прямо на open: handle не вернулся, закрывать нечего — только состояние и подсказка."""
    api = FakeApi(open_error=sdk_error(ACCESS_DENIED, "OpenDevice"))
    r = make_reader(api)
    assert r.reader.start() is False
    assert r.reader.state == "busy"
    assert "idmvs" in " ".join(r.errors).lower()
    assert api.count("start_grabbing") == 0


def test_busy_start_spawns_no_capture(make_reader):
    api = FakeApi(open_error=sdk_error(ACCESS_DENIED, "OpenDevice"))
    r = make_reader(api, timeout_ms=10)
    r.reader.start()
    time.sleep(0.15)
    assert api.count("get_frame") == 0


def test_access_denied_without_on_error_callback_does_not_raise():
    cls = _m("Services.code_reader.core.sdk_reader").SdkCodeReader
    api = FakeApi(open_error=sdk_error(ACCESS_DENIED, "OpenDevice"))
    reader = cls(lambda f: None, api=api)
    assert reader.start() is False
    assert reader.state == "busy"


# --------------------------------------------------------------------------
# Устойчивые ошибки get_frame
# --------------------------------------------------------------------------

ERR = 0x80020001


def test_three_consecutive_errors_give_error_and_close_single_error_does_not(make_reader):
    # 3 подряд -> error и прибор закрыт
    api = FakeApi(script=[sdk_error(ERR), sdk_error(ERR), sdk_error(ERR)])
    r = make_reader(api, timeout_ms=10)
    assert r.reader.start() is True
    assert wait_until(lambda: r.reader.state == "error")
    assert wait_until(lambda: api.count("close") == 1)
    assert "80020001" in " ".join(r.errors).lower()
    n_get = api.count("get_frame")
    time.sleep(0.15)
    assert api.count("get_frame") == n_get, "поток должен завершиться"

    # одна ошибка между удачными — не error
    api2 = FakeApi(script=[make_raw([code()], trigger=1), sdk_error(ERR), make_raw([code()], trigger=2)])
    r2 = make_reader(api2, timeout_ms=10)
    r2.reader.start()
    assert wait_until(lambda: len(r2.frames) == 2)
    assert r2.reader.state == "running"
    assert api2.count("close") == 0


def test_two_consecutive_errors_then_frame_keeps_running_and_counter_resets(make_reader):
    e = sdk_error
    script = [
        e(ERR),
        e(ERR),
        make_raw([code()], trigger=1),
        e(ERR),
        e(ERR),
        make_raw([code()], trigger=2),
    ]
    api = FakeApi(script=script)
    r = make_reader(api, timeout_ms=10)
    r.reader.start()
    assert wait_until(lambda: len(r.frames) == 2)
    assert r.reader.state == "running"
    assert api.count("close") == 0


def test_error_state_keeps_single_close_after_stop(make_reader):
    api = FakeApi(script=[sdk_error(ERR)] * 3)
    r = make_reader(api, timeout_ms=10)
    r.reader.start()
    assert wait_until(lambda: r.reader.state == "error")
    r.reader.stop()
    assert api.count("close") == 1


def test_error_state_reports_last_error_in_stats(make_reader):
    api = FakeApi(script=[sdk_error(ERR)] * 3)
    r = make_reader(api, timeout_ms=10)
    r.reader.start()
    assert wait_until(lambda: r.reader.state == "error")
    s = r.reader.stats()
    assert s["state"] == "error"
    assert s["last_error"]


# --------------------------------------------------------------------------
# Исключение в on_frame
# --------------------------------------------------------------------------


def test_exception_in_on_frame_does_not_kill_capture(make_reader):
    api = FakeApi(script=three_frames())
    seen = []

    def on_frame(f):
        seen.append(f.trigger_index)
        if f.trigger_index == 1:
            raise RuntimeError("boom-in-callback")

    r = make_reader(api, on_frame=on_frame, timeout_ms=10)
    r.reader.start()
    assert wait_until(lambda: len(seen) >= 3)
    assert seen[:3] == [1, 2, 3]  # кадр N+1 доставлен
    assert r.reader.state == "running"
    assert r.reader.stats()["errors"] == 1
    assert "boom-in-callback" in " ".join(r.errors)
    assert api.count("close") == 0


def test_exception_in_on_frame_without_on_error_callback_is_survived():
    cls = _m("Services.code_reader.core.sdk_reader").SdkCodeReader
    api = FakeApi(script=three_frames())
    seen = []

    def on_frame(f):
        seen.append(f.trigger_index)
        raise RuntimeError("boom")

    reader = cls(on_frame, api=api, timeout_ms=10)
    try:
        reader.start()
        assert wait_until(lambda: len(seen) >= 3)
        assert reader.state == "running"
        assert reader.stats()["errors"] == 3
    finally:
        t = threading.Thread(target=reader.stop, daemon=True)
        t.start()
        t.join(10.0)


# --------------------------------------------------------------------------
# stats()
# --------------------------------------------------------------------------


def test_stats_counters_follow_frame_status(make_reader):
    script = [
        make_raw([code("QR-20MM")], trigger=1),
        make_raw([bad_code()], trigger=2, no_read=1),
        make_raw([], trigger=3, is_get_code=False),
        make_raw([code("QR-15MM")], trigger=4),
    ]
    api = FakeApi(script=script)
    r = make_reader(api, timeout_ms=10)
    r.reader.start()
    assert wait_until(lambda: len(r.frames) == 4)
    s = r.reader.stats()
    assert s["frames"] == 4
    assert s["ok"] == 2
    assert s["bad_code"] == 1
    assert s["no_code"] == 1
    assert s["errors"] == 0
    assert s["state"] == "running"


def test_stats_device_reflects_opened_entry_and_is_none_before_start(make_reader):
    api = FakeApi()
    r = make_reader(api, timeout_ms=10)
    assert r.reader.stats()["device"] is None
    r.reader.start()
    assert r.reader.stats()["device"] == {"ip": "10.0.0.1", "model": "MV-ID3013PM", "serial": "S1"}


def test_stats_has_all_contract_keys(make_reader):
    api = FakeApi()
    r = make_reader(api)
    assert {"frames", "ok", "no_code", "bad_code", "errors", "state", "last_error", "device"} <= set(r.reader.stats())


def test_stats_is_json_safe(make_reader):
    api = FakeApi(script=three_frames())
    r = make_reader(api, timeout_ms=10)
    r.reader.start()
    assert wait_until(lambda: len(r.frames) == 3)
    json.dumps(r.reader.stats())
