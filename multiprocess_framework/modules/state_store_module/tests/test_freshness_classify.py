"""Unit-тесты конверта свежести (Task 0.2, ADR-SS-025): stamp, classify, read_value.

Ожидания — литералы из ACCEPTANCE Task 0.2, не выводятся из кода. Метка
``S = stamp(3, 100.0, "a", 5.0)``: два такта — 10.0 с, граница ``100.0 + 10.0``.
``age_s`` сравнивается через ``pytest.approx``: ``(100.0 + 10.1) - 100.0 != 10.1``.
"""

from __future__ import annotations

import threading

import pytest

from multiprocess_framework.modules.state_store_module import (
    FRESH_KEY,
    classify,
    read_value,
    stamp,
)

S = {"seq": 3, "src_ts": 100.0, "incarnation": "a", "tick_sec": 5.0}
NO_DATA = {"class": "no_data", "value": None, "age_s": None}


def _call_with_deadline(fn, *args, timeout: float = 5.0):
    """Вызвать ``fn`` в daemon-потоке с дедлайном: зависание — красный тест, не зависший прогон."""
    box: dict = {}

    def _run() -> None:
        try:
            box["result"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001 — тест различает исключение и результат
            box["error"] = exc

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), f"{fn.__name__}{args!r} завис дольше {timeout} с"
    return box


def test_fresh_key_literal():
    assert FRESH_KEY == "_fresh"


def test_stamp_returns_exactly_four_keys():  # u1
    result = stamp(3, 100.0, "a", 5.0)
    assert result == {"seq": 3, "src_ts": 100.0, "incarnation": "a", "tick_sec": 5.0}
    assert set(result) == {"seq", "src_ts", "incarnation", "tick_sec"}


def test_classify_fresh_before_two_ticks():  # u2
    assert classify({"fps": 1, "_fresh": S}, 109.9, None) == "fresh"


def test_classify_stale_after_two_ticks():  # u3
    assert classify({"fps": 1, "_fresh": S}, 110.1, None) == "stale"


def test_classify_boundary_exact_is_fresh():  # u4
    assert classify({"fps": 1, "_fresh": S}, 110.0, None) == "fresh"


def test_order_writer_gone_before_stale():  # u5
    # и устарело (200.0 - 100.0 > 10.0), и чужое воплощение: «ушёл» раньше «давно не писал»
    assert classify({"fps": 1, "_fresh": S}, 200.0, "b") == "writer_gone"


def test_classify_none_alive_skips_incarnation_check():  # u6
    assert classify({"fps": 1, "_fresh": S}, 101.0, None) == "fresh"


def _without(key: str) -> dict:
    return {k: v for k, v in S.items() if k != key}


BAD_INPUTS = [
    pytest.param(None, 101.0, id="subtree-none"),
    pytest.param([S], 101.0, id="subtree-list"),
    pytest.param("_fresh", 101.0, id="subtree-str"),
    pytest.param({}, 101.0, id="subtree-empty"),
    pytest.param({"fps": 1, "_fresh": None}, 101.0, id="fresh-none"),
    pytest.param({"fps": 1, "_fresh": [1, 2]}, 101.0, id="fresh-list"),
    pytest.param({"fps": 1, "_fresh": "S"}, 101.0, id="fresh-str"),
    pytest.param({"fps": 1, "_fresh": _without("seq")}, 101.0, id="no-seq"),
    pytest.param({"fps": 1, "_fresh": _without("src_ts")}, 101.0, id="no-src_ts"),
    pytest.param({"fps": 1, "_fresh": _without("incarnation")}, 101.0, id="no-incarnation"),
    pytest.param({"fps": 1, "_fresh": _without("tick_sec")}, 101.0, id="no-tick_sec"),
    pytest.param({"fps": 1, "_fresh": {**S, "src_ts": float("nan")}}, 101.0, id="src_ts-nan"),
    pytest.param({"fps": 1, "_fresh": {**S, "src_ts": float("inf")}}, 101.0, id="src_ts-inf"),
    pytest.param({"fps": 1, "_fresh": {**S, "src_ts": True}}, 101.0, id="src_ts-bool"),
    pytest.param({"fps": 1, "_fresh": {**S, "src_ts": "100"}}, 101.0, id="src_ts-str"),
    pytest.param({"fps": 1, "_fresh": {**S, "tick_sec": None}}, 101.0, id="tick-none"),
    pytest.param({"fps": 1, "_fresh": {**S, "tick_sec": 0}}, 101.0, id="tick-zero"),
    pytest.param({"fps": 1, "_fresh": {**S, "tick_sec": -5.0}}, 101.0, id="tick-negative"),
    pytest.param({"fps": 1, "_fresh": {**S, "tick_sec": float("nan")}}, 101.0, id="tick-nan"),
    pytest.param({"fps": 1, "_fresh": {**S, "tick_sec": True}}, 101.0, id="tick-bool"),
    pytest.param({"fps": 1, "_fresh": S}, None, id="now-none"),
    pytest.param({"fps": 1, "_fresh": S}, float("nan"), id="now-nan"),
    pytest.param({"fps": 1, "_fresh": S}, True, id="now-bool"),
    # int вне диапазона float: math.isfinite бросает OverflowError, ответ — no_data
    pytest.param({"fps": 1, "_fresh": {**S, "src_ts": 10**400}}, 101.0, id="src_ts-bigint"),
    pytest.param({"fps": 1, "_fresh": {**S, "src_ts": -(10**400)}}, 101.0, id="src_ts-negbigint"),
    pytest.param({"fps": 1, "_fresh": {**S, "tick_sec": 10**400}}, 101.0, id="tick-bigint"),
    pytest.param({"fps": 1, "_fresh": S}, 10**400, id="now-bigint"),
]


@pytest.mark.parametrize(("subtree", "now"), BAD_INPUTS)
def test_classify_bad_input_is_no_data(subtree, now):  # u7
    # исключений нет, класс — no_data; чужое воплощение не должно превратить мусор в writer_gone
    box = _call_with_deadline(classify, subtree, now, "b")
    assert "error" not in box, f"classify бросил {box.get('error')!r}"
    assert box["result"] == "no_data"


@pytest.mark.parametrize(("subtree", "now"), BAD_INPUTS)
def test_read_value_bad_input_is_no_data(subtree, now):  # u7b
    # чужое воплощение "b" не превращает мусор в writer_gone; ключ "fps" в subtree есть
    box = _call_with_deadline(read_value, subtree, "fps", now, "b")
    assert "error" not in box, f"read_value бросил {box.get('error')!r}"
    assert box["result"] == NO_DATA


def test_classify_negative_age_is_fresh():  # u8
    sub = {"fps": 1, "_fresh": S}
    assert classify(sub, 99.0, None) == "fresh"
    assert read_value(sub, "fps", 99.0, None)["age_s"] == pytest.approx(-1.0)
    # часы писателя сильно впереди: возраст отрицателен и отдаётся как есть
    assert classify(sub, 50.0, None) == "fresh"
    assert read_value(sub, "fps", 50.0, None)["age_s"] == pytest.approx(-50.0)


def test_read_value_four_answers():  # u9
    sub = {"state": {"fps": 0, "lat": 25.0}, "_fresh": S}
    zero = read_value({"fps": 0, "_fresh": S}, "fps", 101.0, None)
    assert zero == {"class": "fresh", "value": 0, "age_s": 1.0}
    assert zero["value"] is not None  # ноль — значение, не «нет данных»

    absent = read_value({"fps": 0, "_fresh": S}, "absent", 101.0, None)
    assert absent == NO_DATA

    stale = read_value({"lat": 25.0, "_fresh": S}, "lat", 110.1, None)
    assert stale["class"] == "stale"
    assert stale["value"] == 25.0
    assert stale["age_s"] == pytest.approx(10.1)

    gone = read_value({"lat": 25.0, "_fresh": S}, "lat", 101.0, "b")
    assert gone["class"] == "writer_gone"
    assert gone["value"] == 25.0
    assert gone["age_s"] == pytest.approx(1.0)

    # пути через точку дают те же четыре ответа на корне процесса
    assert read_value(sub, "state.fps", 101.0, None)["class"] == "fresh"
    # четыре пары (класс, значение) попарно разные
    pairs = {(r["class"], r["value"]) for r in (zero, absent, stale, gone)}
    assert len(pairs) == 4


def test_read_value_missing_none_or_dotted_key():  # u10
    # ключа нет; ключ со значением None; пустое поддерево
    assert read_value({"fps": 1, "_fresh": S}, "absent", 101.0, None) == NO_DATA
    assert read_value({"fps": None, "_fresh": S}, "fps", 101.0, None) == NO_DATA
    assert read_value({}, "fps", 101.0, None) == NO_DATA

    # путь через точку найден
    found = read_value({"state": {"lat": 25.0}, "_fresh": S}, "state.lat", 101.0, None)
    assert found["class"] == "fresh"
    assert found["value"] == 25.0
    assert found["age_s"] == pytest.approx(1.0)

    deep = read_value(
        {"workers": {"w": {"effective_hz": 5.0}}, "_fresh": S},
        "workers.w.effective_hz",
        110.1,
        None,
    )
    assert deep["class"] == "stale"
    assert deep["value"] == 5.0

    # нет сегмента; посреди пути не dict; key не строка
    assert read_value({"state": {"lat": 25.0}, "_fresh": S}, "state.nope", 101.0, None) == NO_DATA
    assert read_value({"state": {"lat": 25.0}, "_fresh": S}, "nope.lat", 101.0, None) == NO_DATA
    assert read_value({"state": 7, "_fresh": S}, "state.lat", 101.0, None) == NO_DATA
    assert read_value({"state": {"lat": 25.0}, "_fresh": S}, None, 101.0, None) == NO_DATA
    assert read_value({"state": {"lat": 25.0}, "_fresh": S}, 5, 101.0, None) == NO_DATA


def test_read_value_result_is_independent_and_exact():  # u11
    # мутация ответа no_data не портит следующий ответ (константа не общая)
    first = read_value({}, "fps", 101.0, None)
    first["class"] = "fresh"
    first["value"] = 1
    first["age_s"] = 0.0
    assert read_value({}, "fps", 101.0, None) == NO_DATA

    # age_s — ровно now - src_ts, без округления; значение — тот же объект, без копии
    leaf = {"a": [1, 2]}
    mark = stamp(1, 100.123456789, "a", 5.0)
    result = read_value({"leaf": leaf, "_fresh": mark}, "leaf", 110.0, None)
    assert result["class"] == "fresh"
    assert result["age_s"] == 110.0 - 100.123456789
    assert result["value"] is leaf
