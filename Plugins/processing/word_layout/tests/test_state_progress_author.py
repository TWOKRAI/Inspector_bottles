"""Task 6.2 word-layout: тесты автора на дыры матрицы инъекций (И2, И4, И8 + cmd_reset до сборки).

Дополняют ``test_state_progress.py`` (слепой тестер, не править). Харнес — свой, как там: записывающий
фейк ``state_proxy.merge(path, dict)``. Диски подаются подряд быстро (в пределах секунды), поэтому
периодическая публикация раз в 1 с в них не срабатывает; единственный тест, которому нужен тик периода
(дубль в тик), честно ждёт реальные 1,1 с. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.processing.word_layout.plugin import WordLayoutPlugin

_PATH = "processes.layout.state.word_layout"
_DOT = "·"  # «·» (U+00B7) — пустая ячейка маски

_BASE = {
    "target_word": "МИР",
    "word_source": "",
    "settle_frames": 1,
    "require_pick": True,
    "first_x": 320.0,
    "first_y": -440.0,
    "place_z_mm": -132.0,
    "pick_z_mm": -132.0,
}
_PICK = {"x_mm": 458.2, "y_mm": -343.0}


class RecordingStateProxy:
    """Фейк state_proxy: сохраняет каждый ``merge(path, dict)`` копией."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def merge(self, path: str, data: dict[str, Any]) -> None:
        self.calls.append((path, dict(data)))

    def payloads(self) -> list[dict[str, Any]]:
        return [d for p, d in self.calls if p == _PATH]

    def last(self) -> dict[str, Any]:
        got = self.payloads()
        assert got, "в прокси нет ни одной публикации"
        return got[-1]


def _make(word: str = "МИР") -> tuple[WordLayoutPlugin, RecordingStateProxy]:
    conf = dict(_BASE)
    conf["target_word"] = word
    proxy = RecordingStateProxy()
    services = MockProcessServices(name="layout", config=conf, state_proxy=proxy)
    plugin = WordLayoutPlugin()
    plugin.configure(PluginContext(services=services, config=conf))
    return plugin, proxy


def _disc(label: str, tid: object, angle: float = 0.0) -> dict:
    pred = {"label": label, "confidence": 0.9, "angle_deg": angle, "angle_valid": True}
    return {"predictions": [pred], "sidecar": {"track_id": tid}, "pick_xy": dict(_PICK)}


def _feed(p: WordLayoutPlugin, item: dict) -> dict:
    return p.process([item])[0]


# --- (а) пропуск диска без смены ячеек публикует state на решении ----------------


def test_skip_without_cell_change_publishes_immediately() -> None:
    p, proxy = _make("МИР")
    _feed(p, _disc("М", 1, 30.0))
    before = len(proxy.payloads())

    out = _feed(p, _disc("П", 2, 0.0))  # «П» нет в слове «МИР» — пропуск, ячейки не меняются
    assert "robot_job" not in out
    after = proxy.payloads()
    assert len(after) == before + 1, "пропуск не опубликовал state на решении"
    last = after[-1]
    assert last["last_label"] == "П"
    assert (last["assembled"], last["slots_filled"], last["done"]) == ("М" + _DOT * 2, 1, False)


# --- (б) возврат на ленту публикует пустую маску -------------------------------


def test_return_publishes_empty_mask_and_zero_filled() -> None:
    p, proxy = _make("МИР")
    _feed(p, _disc("М", 1, 30.0))
    _feed(p, _disc("И", 2, 90.0))
    assert (proxy.last()["assembled"], proxy.last()["slots_filled"]) == ("МИ" + _DOT, 2)

    out = _feed(p, {"predictions": [], "signal_1": True})  # сигнал «вернуть на ленту»
    assert len(out["robot_return_jobs"]) == 2
    last = proxy.last()
    assert (last["assembled"], last["slots_filled"], last["done"]) == (_DOT * 3, 0, False)
    assert last["slots_total"] == 3


# --- (в) cmd_reset до первой сборки ---------------------------------------------


def test_reset_before_first_assembly_publishes_without_crash() -> None:
    p, proxy = _make("МИР")  # ни одного process(): раскладки ещё нет

    assert p.cmd_reset({}) == {"status": "ok"}

    last = proxy.last()
    assert (last["assembled"], last["slots_filled"], last["slots_total"], last["done"]) == ("", 0, 0, False)
    assert p._reg.assembled == ""


# --- (г) в тик после решения нет дубля публикации -------------------------------


@pytest.mark.timeout(15)
def test_no_duplicate_publish_in_tick_after_decision() -> None:
    p, proxy = _make("МИР")
    _feed(p, _disc("М", 1, 30.0))  # первый диск ещё и собирает раскладку (две публикации) — прогрев
    time.sleep(1.1)  # период публикации истёк с момента прогрева
    before = len(proxy.payloads())

    _feed(p, _disc("И", 2, 90.0))  # решение публикует и сдвигает отсчёт периода

    assert len(proxy.payloads()) == before + 1, "после решения тик process() опубликовал повторно"


# --- (д) публикация на пересборке без решения о диске -----------------------------


def test_word_change_publishes_on_rebuild_without_decision() -> None:
    p, proxy = _make("ПЕРЕМИРИЕ")
    _feed(p, _disc("Е", 1, 30.0))
    assert proxy.last()["assembled"] == _DOT + "Е" + _DOT * 7

    ok, _err = p._reg.update_field("target_word", "МИР")
    assert ok is True

    # диск без координаты забора (нет pick_xy, require_pick=True): раскладка пересобирается,
    # но до offer дело не доходит — публикует только пересборка
    item = _disc("М", 2, 30.0)
    del item["pick_xy"]
    out = _feed(p, item)

    assert "robot_job" not in out
    last = proxy.last()
    assert last["word"] == "МИР"
    assert (last["assembled"], last["slots_total"], last["slots_filled"], last["done"]) == (_DOT * 3, 3, 0, False)
