# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты: плохая подпись из регистра `labels` не роняет `produce()`.

Написаны ДО правки, по брифу лидера; `sdk_plugin.py` автор не читал. Путь боевой: настоящий
`CodeReaderSdkPlugin` на `FakeApi` (фабрика читателя подменена фикстурой `make_plugin`) ->
`take_device` -> `produce()` -> `item["overlay"]["points"]`. Статус — `commands["get_status"]`.

Контракт:
  * плохая подпись (неверный тип `dx`/`scale`/`xy`) пропускается, остальные подписи и ВСЕ кадры доходят;
  * плохой шаблон (`str.format` падает) остаётся в `label` как есть (как сломанный шаблон и раньше);
  * про плохие подписи оператор узнаёт ОДИН раз — в `last_error` при `configure`, как `labels[<индекс>]`;
    `produce()` ни `last_error`, ни `errors` не раздувает.

ПРЕДПОЛОЖЕНО о публичном API (одно место правки — хелперы ниже):
  * `last_error` после `configure` виден в `get_status` сразу после `make_plugin` (configure + start);
  * пустой `last_error` — `""` или `None`;
  * `produce()` за один вызов отдаёт всю очередь (как в test_overflow_counts_dropped...).
"""

from __future__ import annotations

import pytest

from Services.code_reader.tests import test_sdk_plugin as _base
from Services.code_reader.tests.test_sdk_plugin import _bounded, _cmd, _collect, _raw, _status
from Services.code_reader.tests.test_sdk_reader import FakeApi, code as _code, wait_until

make_plugin = _base.make_plugin  # фикстура плагина на FakeApi (pytest берёт её по имени из этого модуля)

SQUARE = [[100, 100], [300, 100], [300, 300], [100, 300]]

GOOD = {"per": "frame", "template": "A", "xy": [10, 20]}  # соседняя валидная подпись

# Плохие подписи: (id, подпись, текст, который в points ДОЛЖЕН отсутствовать)
BAD_DROPPED = [
    pytest.param({"per": "frame", "template": "BAD", "xy": [1, 2], "dx": "5"}, id="dx_str"),
    pytest.param({"per": "frame", "template": "BAD", "xy": [1, 2], "scale": "big"}, id="scale_str"),
    pytest.param({"per": "frame", "template": "BAD", "anchor": "frame", "xy": "ab"}, id="xy_str"),
    pytest.param({"per": "frame", "template": "BAD", "anchor": "frame", "xy": [1]}, id="xy_len1"),
    pytest.param({"per": "frame", "template": "BAD", "anchor": "frame", "xy": None}, id="xy_none"),
]


# --------------------------------------------------------------------------
# Хелперы
# --------------------------------------------------------------------------


def _produce(w) -> list[dict]:
    """produce() в daemon-потоке с дедлайном: исключение пробрасывается, зависание — fail."""
    return _bounded(w.plugin.produce, 10.0)


def _points(item: dict) -> list[dict]:
    assert "overlay" in item, f"в item нет overlay; ключи: {sorted(item)}"
    return list(item["overlay"]["points"])


def _labelled(item: dict, label: str) -> list[dict]:
    return [p for p in _points(item) if p.get("label") == label]


def _one_item(make_plugin, labels: list | None, codes: list | None = None, trig: int = 1):
    """Плагин с `labels` -> один кадр -> (стенд, item). `labels=None`: поле в конфиге не задаём."""
    cfg = {} if labels is None else {"labels": labels}
    w = make_plugin(FakeApi(script=[_raw([] if codes is None else codes, trig)]), timeout_ms=20, **cfg)
    assert _cmd(w, "take_device")["status"] == "ok"
    items = _collect(w, 1)
    assert len(items) == 1, f"кадр не дошёл: {items}"
    return w, items[0]


def _last_error(w) -> str:
    return _status(w)["last_error"] or ""


# --------------------------------------------------------------------------
# 1. Шаблон, на котором падает format: подпись остаётся, label == шаблон как есть
# --------------------------------------------------------------------------


def test_template_with_index_on_int_does_not_raise_and_shows_itself(make_plugin):
    labels = [{"per": "frame", "template": "{ok[0]}", "xy": [5, 6]}]

    _w, item = _one_item(make_plugin, labels)  # _collect зовёт produce(): исключение = красный тест

    assert [(p["label"], p["xy"]) for p in _points(item)] == [("{ok[0]}", [5, 6])]


# --------------------------------------------------------------------------
# 2-4. Плохие числа/координаты: подпись пропущена, соседняя на месте, produce() не бросает
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", BAD_DROPPED)
def test_bad_frame_label_is_skipped_and_neighbour_survives(make_plugin, bad):
    _w, item = _one_item(make_plugin, [bad, GOOD])

    assert _labelled(item, "BAD") == []
    assert [(p["label"], p["xy"]) for p in _labelled(item, "A")] == [("A", [10, 20])]


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param({"per": "code", "template": "BAD", "anchor": "corner0", "dx": "5"}, id="code_dx_str"),
        pytest.param({"per": "code", "template": "BAD", "anchor": "corner0", "scale": "big"}, id="code_scale_str"),
    ],
)
def test_bad_code_label_is_skipped_and_neighbour_survives(make_plugin, bad):
    # ПРЕДПОЛОЖЕНО: тот же контракт для подписей per=code (бриф называет per=frame; код с рамкой даёт per-code ветку)
    _w, item = _one_item(make_plugin, [bad, GOOD], [_code("QR-A", corners=SQUARE)])

    assert _labelled(item, "BAD") == []
    assert [p["xy"] for p in _labelled(item, "A")] == [[10, 20]]


# --------------------------------------------------------------------------
# 5. Пачка из 3 кадров: ни один не потерян, соседняя подпись в каждом
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", BAD_DROPPED)
def test_batch_of_three_frames_all_delivered_with_bad_label(make_plugin, bad):
    api = _base.GatedApi(script=[_raw([], t) for t in (1, 2, 3)])
    w = make_plugin(api, timeout_ms=20, labels=[bad, GOOD])
    assert _cmd(w, "take_device")["status"] == "ok"
    api.gate.set()
    # produce() НЕ зовём, пока все три кадра не легли в очередь: пачка уходит одним вызовом
    assert wait_until(lambda: not api.script, 5.0), "сценарий кадров не выбран"
    wait_until(lambda: False, 0.3)  # дать последнему колбэку дойти до очереди

    items = _produce(w)

    assert [i["trigger_index"] for i in items] == [1, 2, 3]
    for item in items:
        assert [p["xy"] for p in _labelled(item, "A")] == [[10, 20]]
        assert _labelled(item, "BAD") == []


# --------------------------------------------------------------------------
# 6. Регрессия: подписи по умолчанию дают прежние точки
# --------------------------------------------------------------------------


def test_default_labels_give_single_status_point_for_empty_frame(make_plugin):
    _w, item = _one_item(make_plugin, None)  # поле labels в конфиге не задано

    assert item["status"] == "no_code"
    assert [(p["xy"], p["label"]) for p in _points(item)] == [([10, 70], "no_code | ok 0 / no 1 / bad 0")]


# --------------------------------------------------------------------------
# 7. configure сообщает про плохие подписи по индексам, прибор берётся, кадры идут
# --------------------------------------------------------------------------


def test_configure_reports_only_bad_label_indexes_and_device_still_works(make_plugin):
    labels = [
        {"per": "frame", "template": "G", "xy": [10, 20]},  # [0] валидна
        {"per": "frame", "template": "B1", "xy": [1, 2], "dx": "5"},  # [1] плохая
        {"per": "frame", "template": "B2", "xy": [3, 4], "scale": "big"},  # [2] плохая
    ]
    w = make_plugin(FakeApi(script=[_raw([], 1)]), timeout_ms=20, labels=labels)

    err = _last_error(w)
    assert "labels[1]" in err, err
    assert "labels[2]" in err, err
    assert "labels[0]" not in err, err

    assert _cmd(w, "take_device")["status"] == "ok"
    assert _status(w)["device_state"] == "running"
    (item,) = _collect(w, 1)
    assert [(p["label"], p["xy"]) for p in _points(item)] == [("G", [10, 20])]


# --------------------------------------------------------------------------
# 8. Регрессия: без плохих подписей last_error пуст
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "labels",
    [
        pytest.param(None, id="default_labels"),
        pytest.param(
            [
                {"per": "frame", "template": "A", "xy": [10, 20], "dx": 1, "dy": -2.5, "scale": 1.5},
                {"per": "code", "template": "{code}", "anchor": "corner0", "group": "g_{state}"},
            ],
            id="explicit_valid",
        ),
        pytest.param([], id="empty_list"),
    ],
)
def test_configure_without_bad_labels_leaves_last_error_empty(make_plugin, labels):
    cfg = {} if labels is None else {"labels": labels}
    w = make_plugin(FakeApi(), timeout_ms=20, **cfg)

    assert _status(w)["last_error"] in ("", None)


# --------------------------------------------------------------------------
# 9. Элемент labels не dict: configure сообщает labels[<индекс>] (или отклоняет регистр), produce() не бросает
# --------------------------------------------------------------------------


def test_non_dict_label_item_is_reported_at_configure(make_plugin):
    """ПРЕДПОЛОЖЕНО: на сегодня регистр (list[dict]) отклоняет строку уже в configure — pydantic ValidationError
    с путём `labels.1`. Допустимы оба исхода: configure бросает ошибку, называющую `labels`, либо
    принимает и пишет `labels[1]` в last_error. Молча принять и промолчать нельзя."""
    try:
        w = make_plugin(FakeApi(), timeout_ms=20, labels=[GOOD, "oops"])
    except Exception as exc:  # noqa: BLE001 — важно, что ошибка называет поле и индекс
        assert "labels" in str(exc) and "1" in str(exc), str(exc)
        return
    err = _last_error(w)
    assert "labels[1]" in err, err
    assert "labels[0]" not in err, err


def test_non_dict_label_item_injected_past_register_does_not_break_produce(make_plugin):
    """Рубеж глубже регистра: если не-dict всё же попал в `labels` (в обход валидации), produce() не бросает.

    ПРЕДПОЛОЖЕНО: список подменяем через `plugin._reg.__dict__["labels"]` (приватный доступ, pydantic v2
    хранит поля в __dict__); других способов обойти validate_assignment без правки кода нет.
    """
    w = make_plugin(FakeApi(script=[_raw([], 1)]), timeout_ms=20)
    w.plugin._reg.__dict__["labels"] = [GOOD, "oops", None, 7]
    assert _cmd(w, "take_device")["status"] == "ok"
    (item,) = _collect(w, 1)

    assert [p["xy"] for p in _labelled(item, "A")] == [[10, 20]]


# --------------------------------------------------------------------------
# 10. Повтор: 100 вызовов produce() с плохой подписью не раздувают errors/last_error
# --------------------------------------------------------------------------


def test_hundred_produce_calls_do_not_grow_errors_or_last_error(make_plugin):
    bad = {"per": "frame", "template": "BAD", "xy": [1, 2], "dx": "5"}
    api = FakeApi()
    w = make_plugin(api, timeout_ms=20, labels=[GOOD, bad])
    assert _cmd(w, "take_device")["status"] == "ok"

    reported = _last_error(w)
    assert "labels[1]" in reported, f"configure не сообщил про плохую подпись: {reported!r}"
    errors_before = _status(w)["errors"]

    for trig in range(1, 101):
        api.script.append(_raw([], trig))
        items = _collect(w, 1)
        assert len(items) == 1, f"кадр {trig} не дошёл"
        assert [p["xy"] for p in _labelled(items[0], "A")] == [[10, 20]]

    after = _status(w)
    assert after["last_error"] == reported
    assert after["errors"] == errors_before
