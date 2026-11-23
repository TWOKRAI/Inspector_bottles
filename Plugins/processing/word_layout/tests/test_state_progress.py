"""Task 6.2 word-layout: прогресс раскладки публикуется в state сразу на решении + поле ``assembled``.

Приёмочные тесты Д1-Д7, написаны слепым тестером до реализации по критериям приёмки.
Публичный путь: ``configure`` / ``process`` / ``cmd_reset`` / ``_reg``; наблюдаемое — последний
payload, записанный в ЗАПИСЫВАЮЩИЙ фейк ``state_proxy.merge(path, dict)`` (не MagicMock),
и регистры. Ожидаемые значения — литералы.

Ячейки слов (шаг 110 мм, без разрывов):
    «МИР»       М0 И1 Р2
    «ПЕРЕМИРИЕ» П0 Е1 Р2 Е3 М4 И5 Р6 И7 Е8

Маска ``assembled``: длина slots_total, буква заполненной ячейки, ``·`` (U+00B7) — пустая.

Диски подаются подряд быстро (в пределах одной секунды монотонного времени): периодическая
публикация раз в 1 с (как до правки) за это время не срабатывает ни разу, поэтому любой
payload в прокси после диска — публикация на решении. Время не патчится: единственный тест,
которому нужен тик периода (Д6), честно ждёт реальные 1,1 с.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.processing.word_layout.plugin import WordLayoutPlugin
from Plugins.processing.word_layout.registers import WordLayoutRegisters

_PATH = "processes.layout.state.word_layout"
_DOT = "·"  # «·» — пустая ячейка маски

_BASE = {
    "target_word": "ПЕРЕМИРИЕ",
    "word_source": "",
    "settle_frames": 1,
    "require_pick": True,
    "first_x": 320.0,
    "first_y": -440.0,
    "place_z_mm": -132.0,
    "pick_z_mm": -132.0,
}
_PICK = {"x_mm": 458.2, "y_mm": -343.0}


# --- харнес ------------------------------------------------------------------


class RecordingStateProxy:
    """Фейк state_proxy: сохраняет каждый ``merge(path, dict)`` (копией), ничего не угадывает."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def merge(self, path: str, data: dict[str, Any]) -> None:
        self.calls.append((path, dict(data)))

    def payloads(self, path: str = _PATH) -> list[dict[str, Any]]:
        return [d for p, d in self.calls if p == path]

    def last(self, path: str = _PATH) -> dict[str, Any]:
        got = self.payloads(path)
        assert got, f"в прокси нет ни одной публикации по пути {path!r}; все пути: {[p for p, _ in self.calls]}"
        return got[-1]


def _make(
    word: str = "ПЕРЕМИРИЕ", extra: dict | None = None
) -> tuple[WordLayoutPlugin, MockProcessServices, RecordingStateProxy]:
    conf = dict(_BASE)
    conf["target_word"] = word
    conf.update(extra or {})
    proxy = RecordingStateProxy()
    services = MockProcessServices(name="layout", config=conf, state_proxy=proxy)
    plugin = WordLayoutPlugin()
    plugin.configure(PluginContext(services=services, config=conf))
    return plugin, services, proxy


def _disc(label: str, tid: object, angle: float = 0.0) -> dict:
    pred = {"label": label, "confidence": 0.9, "angle_deg": angle, "angle_valid": True}
    return {"predictions": [pred], "sidecar": {"track_id": tid}, "pick_xy": dict(_PICK)}


def _feed(p: WordLayoutPlugin, item: dict) -> dict:
    return p.process([item])[0]


def _view(payload: dict[str, Any]) -> tuple[Any, Any, Any]:
    return payload.get("assembled"), payload.get("slots_filled"), payload.get("done")


# --- Д1 ----------------------------------------------------------------------


def test_publish_on_decision_without_next_tick() -> None:
    p, _s, proxy = _make("МИР")

    _feed(p, _disc("М", 1, 30.0))
    assert _view(proxy.last()) == ("М" + _DOT * 2, 1, False)

    _feed(p, _disc("И", 2, 90.0))
    assert _view(proxy.last()) == ("МИ" + _DOT, 2, False)

    _feed(p, _disc("Р", 3, 300.0))
    # последний диск; БЕЗ следующего вызова process() — состояние уже в прокси
    assert _view(proxy.last()) == ("МИР", 3, True)


# --- Д2 ----------------------------------------------------------------------


def test_assembled_mask_case_c() -> None:
    p, _s, proxy = _make("ПЕРЕМИРИЕ")
    for tid, ang in ((1, 0.0), (2, 30.0), (3, 60.0)):
        _feed(p, _disc("Е", tid, ang))

    mask = _DOT + "Е" + _DOT + "Е" + _DOT * 4 + "Е"
    assert len(mask) == 9
    assert _view(proxy.last()) == (mask, 3, False)

    # четвёртый Е: «ячейки заняты» — состояние не меняется
    out = _feed(p, _disc("Е", 4, 90.0))
    assert "robot_job" not in out, "четвёртый Е не должен получить задание"
    assert _view(proxy.last()) == (mask, 3, False)


# --- Д3 ----------------------------------------------------------------------


def test_word_change_resets_assembled() -> None:
    p, _s, proxy = _make("ПЕРЕМИРИЕ")
    _feed(p, _disc("Е", 1, 30.0))
    assert proxy.last()["assembled"] == _DOT + "Е" + _DOT * 7  # до смены слова: ячейка 1 занята

    ok, _err = p._reg.update_field("target_word", "МИР")
    assert ok is True

    # следующий диск «П» (нет в слове «МИР») пересобирает раскладку и сам ячейку не занимает
    out = _feed(p, _disc("П", 2, 0.0))
    assert "robot_job" not in out
    last = proxy.last()
    assert _view(last) == (_DOT * 3, 0, False)
    assert last["word"] == "МИР"
    assert last["slots_total"] == 3


# --- Д4 ----------------------------------------------------------------------


def test_reset_publishes_state() -> None:
    p, _s, proxy = _make("МИР")
    for tid, (ch, ang) in enumerate((("М", 30.0), ("И", 90.0), ("Р", 300.0)), start=1):
        _feed(p, _disc(ch, tid, ang))
    assert _view(proxy.last()) == ("МИР", 3, True)

    assert p.cmd_reset({}) == {"status": "ok"}

    # без какого-либо process() после команды
    last = proxy.last()
    assert _view(last) == (_DOT * 3, 0, False)
    assert last["slots_total"] == 3


# --- Д5 ----------------------------------------------------------------------


def test_assembled_register_exists_and_readonly() -> None:
    assert "assembled" in WordLayoutRegisters.model_fields, "в регистрах нет поля assembled"
    meta = WordLayoutRegisters.get_field_meta("assembled")
    assert meta is not None and meta.readonly is True
    assert WordLayoutRegisters.model_fields["assembled"].annotation is str

    p, _s, proxy = _make("МИР")
    assert p._reg.assembled == ""  # до первой сборки — пустая строка

    # запись снаружи (update_field) readonly-поле отвергает, значение не меняется
    ok, err = p._reg.update_field("assembled", "ХХХ")
    assert ok is False and err
    assert p._reg.assembled == ""

    _feed(p, _disc("М", 1, 30.0))
    _feed(p, _disc("И", 2, 90.0))
    assert p._reg.assembled == "МИ" + _DOT
    assert proxy.last()["assembled"] == p._reg.assembled


# --- Д6 ----------------------------------------------------------------------


@pytest.mark.timeout(15)
def test_periodic_publish_keeps_all_fields() -> None:
    p, _s, proxy = _make("МИР")
    _feed(p, _disc("М", 1, 30.0))

    time.sleep(1.1)  # период публикации — 1 с
    before = len(proxy.payloads())
    _feed(p, {"predictions": []})  # item без решения: публикует только период
    after = proxy.payloads()
    assert len(after) > before, "периодическая публикация раз в секунду пропала"

    expected = {
        "word": "МИР",
        "slots_total": 3,
        "slots_filled": 1,
        "next_letter": "И",
        "last_label": "М",
        "last_angle_deg": 30.0,
        "last_correction_deg": -30.0,
        "jobs_emitted": 1,
        "done": False,
        "spacing_warn": False,
    }
    last = after[-1]
    assert {k: last.get(k, "<нет поля>") for k in expected} == expected


# --- Д7 ----------------------------------------------------------------------


def test_last_label_published_on_decision() -> None:
    p, _s, proxy = _make("МИР")
    seen = []
    for tid, (ch, ang) in enumerate((("М", 30.0), ("И", 90.0), ("Р", 300.0)), start=1):
        _feed(p, _disc(ch, tid, ang))
        seen.append(proxy.last().get("last_label"))
    assert seen == ["М", "И", "Р"]
