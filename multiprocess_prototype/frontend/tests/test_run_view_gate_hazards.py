# -*- coding: utf-8 -*-
"""Опасности 2.10 (``run_view``), тесты автора реализации: H1-H4, порог свежести, replay, пересборка.

Проводка та же, что в слепых тестах ``test_run_view_gate_blind`` (настоящие ``_setup_bridge_callbacks``,
мост, насос, панель); помощники и фикстура берутся оттуда. Ожидаемые значения — литералы.

Запуск (из корня worktree, PYTHONPATH=корень, PYTHONUTF8=1, Qt offscreen), класс ``light``.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from multiprocess_prototype.frontend import app as app_module
from multiprocess_prototype.frontend.state.bindings import DELETED
from multiprocess_prototype.frontend.tests import test_run_view_gate_blind as blind

__all__: list[str] = []

wire = blind.wire
_hang_deadline = blind._hang_deadline  # noqa: SLF001 — автофикстура снятия зависшего теста

_IDLE = "Маска\nЛиния не запущена: обработанный кадр появится после ЗАПУСТИТЬ"
_FAULT = "Маска\nАвария: обработка остановлена"
_NO_DATA = "Маска\nНет данных о состоянии линии"
_WAIT = "Маска\nРаботает: ждём первый обработанный кадр"


def _text(w: SimpleNamespace, slot_id: str) -> str:
    return blind._label(w.panel, slot_id).text()  # noqa: SLF001


def _send(w: SimpleNamespace, message: dict, slot_id: str) -> bool:
    """Кадр ``sm`` и контрольный ``sc``; True — экран под проверкой показал свой."""
    control = f"{slot_id}_ctl"
    before = blind._shown(w.panel, slot_id)  # noqa: SLF001
    control_before = blind._shown(w.panel, control)  # noqa: SLF001
    w.bridge.dispatch(message)
    w.bridge.dispatch(blind._msg("sc"))  # noqa: SLF001
    assert blind._spin_until(lambda: blind._shown(w.panel, control) > control_before, 1.0)  # noqa: SLF001
    blind._spin(0.3)  # noqa: SLF001
    return blind._shown(w.panel, slot_id) > before  # noqa: SLF001


def test_h1_frame_captured_before_second_start_is_not_shown(wire) -> None:
    d = "rv_h1"
    w = wire(blind._recipe(d, run_view="running"))
    blind._enter(w, "running")
    blind._enter(w, "ready")
    stamp = time.time()
    time.sleep(0.05)

    blind._enter(w, "running")

    assert _send(w, blind._msg("sm", stamp), d) is False
    assert _text(w, d) == _WAIT


@pytest.mark.parametrize(("capture_ts", "shown"), [(1000.0, True), (999.999, False)], ids=["at_mark", "below_mark"])
def test_freshness_threshold_is_the_entry_into_running(wire, monkeypatch, capture_ts: float, shown: bool) -> None:
    d = f"rv_thr_{int(shown)}"
    monkeypatch.setattr(app_module, "time", SimpleNamespace(time=lambda: 1000.0, perf_counter=time.perf_counter))
    w = wire(blind._recipe(d, run_view="running"))
    blind._enter(w, "running")

    assert _send(w, blind._msg("sm", capture_ts), d) is shown


@pytest.mark.parametrize(
    "data",
    [{}, None, {"capture_ts": "1.0"}, {"capture_ts": True}],
    ids=["no_key", "no_data", "string", "bool"],
)
def test_frame_without_numeric_capture_ts(wire, data: Any) -> None:
    """В running такой кадр показан (сравнивать не с чем), вне running — нет."""
    d = f"rv_nots_{len(str(data))}"
    w = wire(blind._recipe(d, run_view="running"))
    message = {**blind._msg("sm"), "data": data}

    blind._enter(w, "ready")
    assert _send(w, dict(message), d) is False
    assert _text(w, d) == _IDLE

    blind._enter(w, "running")
    assert _send(w, dict(message), d) is True


@pytest.mark.parametrize("where", ["item", "data"])
def test_replay_frame_follows_the_same_rule(wire, where: str) -> None:
    """Метка replay правило не обходит: старый штамп в running и любой кадр вне running не показаны."""
    d = f"rv_replay_{where}"
    w = wire(blind._recipe(d, run_view="running"))

    def _replay(capture_ts: float) -> dict:
        message = blind._msg("sm", capture_ts)
        if where == "item":
            message["replay"] = True
        else:
            message["data"]["replay"] = True
        return message

    blind._enter(w, "ready")
    assert _send(w, _replay(time.time()), d) is False

    blind._enter(w, "running")
    assert _send(w, _replay(time.time() - 5.0), d) is False
    assert _send(w, _replay(time.time()), d) is True


def test_fresh_frame_after_running_to_fault_is_not_shown(wire) -> None:
    d = "rv_fault_after_run"
    w = wire(blind._recipe(d, run_view="running"))
    blind._enter(w, "running")
    assert _send(w, blind._msg("sm"), d) is True

    blind._enter(w, "fault")

    assert _text(w, d) == _FAULT
    assert _send(w, blind._msg("sm"), d) is False
    assert _text(w, d) == _FAULT


def test_h2_silence_plate_does_not_replace_run_plate(wire) -> None:
    d = "rv_h2"
    w = wire(blind._recipe(d, run_view="running", plate_mode="silence", plate_after_s=1))
    blind._enter(w, "ready")

    blind._spin(2.0)  # after_s + 1: насос сообщает тишину ключа на каждой целой секунде

    assert _text(w, d) == _IDLE


def test_h3_deleted_state_shows_no_data(wire) -> None:
    d = "rv_h3"
    w = wire(blind._recipe(d, run_view="running"))
    blind._enter(w, "ready")
    assert _text(w, d) == _IDLE

    w.bindings.leaf("state", DELETED)

    blind._assert_text(w.panel, d, _NO_DATA)


def test_h4_dropped_frame_is_not_restored_from_shm(wire) -> None:
    d = "rv_h4"
    w = wire(blind._recipe(d, run_view="running"))
    restore = MagicMock(side_effect=w.bridge.restore_for_show)
    w.bridge.restore_for_show = restore
    blind._enter(w, "ready")

    assert _send(w, blind._msg("sm"), d) is False

    assert [call.args[0]["sender"] for call in restore.call_args_list] == ["sc"]


def test_gate_switched_off_at_runtime_removes_the_plate(wire) -> None:
    d = "rv_gate_live"
    w = wire(blind._recipe(d, run_view="running"))
    blind._enter(w, "ready")
    assert _text(w, d) == _IDLE

    w.bindings.leaf("run_gate", False)

    assert _text(w, d) == "Маска"  # обычный placeholder слота без кадра
    assert blind._label(w.panel, d).styleSheet() == ""
    assert _send(w, blind._msg("sm"), d) is True


def test_displays_changed_in_ready_rereads_run_view(wire, monkeypatch) -> None:
    """DisplaysChanged: пересборка снимает все плашки — плашка правила ставится заново по новому рецепту."""
    from multiprocess_prototype.domain.events import DisplaysChanged

    subscribers: list = []
    real = app_module._setup_bridge_callbacks

    def _spy(*args: Any, **kwargs: Any) -> None:
        kwargs["event_bus"] = SimpleNamespace(subscribe=lambda event, cb: subscribers.append((event, cb)))
        real(*args, **kwargs)

    monkeypatch.setattr(app_module, "_setup_bridge_callbacks", _spy)
    d = "rv_changed"
    recipe = blind._recipe(d, run_view="running")
    w = wire(recipe)
    blind._enter(w, "ready")

    def _changed() -> None:
        for event, callback in subscribers:
            if event is DisplaysChanged:
                callback(DisplaysChanged(slug="run_view_blind"))
        blind._spin(0.05)

    _changed()
    assert _text(w, d) == _IDLE

    recipe["displays"][0]["run_view"] = "always"
    _changed()
    assert _text(w, d) != _IDLE
    assert blind._label(w.panel, d).styleSheet() == ""
    assert _send(w, blind._msg("sm"), d) is True

    recipe["displays"][0]["run_view"] = "running"
    _changed()
    assert _text(w, d) == _IDLE


def test_without_bindings_there_is_no_rule(wire, monkeypatch) -> None:
    monkeypatch.setattr(blind, "_Bindings", lambda: None)
    d = "rv_nobind"
    w = wire(blind._recipe(d, run_view="running"))

    assert _text(w, d) != _NO_DATA
    assert _send(w, blind._msg("sm"), d) is True
