# -*- coding: utf-8 -*-
"""Приёмка C-66: у деградации процесса несколько владельцев (слепые тесты).

Здоровье процесса — один агрегат, но деградацию могут заявлять плагины и
автомат ошибок (breaker). Источник снимает только свою деградацию: закрытие
breaker снимает только причину breaker, ``ok()`` плагина — только причину этого
плагина, ``failed`` важнее ``degraded`` любого источника.

Наблюдаем только публичный снимок: ``status``, ``degraded_reason``, ``breaker``.
Объекты настоящие (``HealthState`` + ``HealthReporter``), часы подставные.
Ожидаемые значения — литералы. Порог breaker (5) и cooldown (30 с) — по умолчанию.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.health import (
    HealthReporter,
    HealthState,
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _make() -> tuple[HealthState, FakeClock, HealthReporter, HealthReporter]:
    clk = FakeClock()
    hs = HealthState(clock=clk)
    return hs, clk, HealthReporter(hs, source="A"), HealthReporter(hs, source="B")


def _trip(hs: HealthState) -> None:
    """Пять подряд report_error — порог по умолчанию, breaker открывается."""
    for i in range(5):
        hs.report_error(RuntimeError(f"x{i}"), context="load")


def _close_by_silence(hs: HealthState, clk: FakeClock) -> None:
    """+62 с, poll (half_open), +62 с, poll (closed): сдвиг перед КАЖДЫМ poll."""
    clk.advance(62.0)
    hs.poll()
    clk.advance(62.0)
    hs.poll()


def _view(hs: HealthState) -> tuple[str, str | None, str]:
    snap = hs.snapshot()
    return snap["status"], snap["degraded_reason"], snap["breaker"]


def _assert_open_breaker_view(hs: HealthState) -> None:
    status, reason, breaker = _view(hs)
    assert status == "degraded"
    assert reason is not None and "breaker open" in reason
    assert breaker == "open"


# --- R: красные на main -------------------------------------------------------


def test_plugin_degraded_survives_breaker_close_by_silence() -> None:
    hs, clk, a, _ = _make()
    a.degraded("assets")
    _trip(hs)
    _assert_open_breaker_view(hs)

    _close_by_silence(hs, clk)
    assert _view(hs) == ("degraded", "assets", "closed")

    a.ok()
    assert _view(hs) == ("ok", None, "closed")


def test_plugin_degraded_survives_breaker_close_by_success() -> None:
    hs, _, a, _ = _make()
    a.degraded("assets")
    _trip(hs)

    hs.record_success()
    assert _view(hs) == ("degraded", "assets", "closed")


def test_degraded_after_breaker_open_survives_close() -> None:
    hs, clk, a, _ = _make()
    _trip(hs)
    a.degraded("assets")
    assert _view(hs) == ("degraded", "assets", "open")

    _close_by_silence(hs, clk)
    assert _view(hs) == ("degraded", "assets", "closed")


def test_failed_not_lowered_by_breaker() -> None:
    hs, clk, a, _ = _make()
    a.failed("fatal")
    _trip(hs)
    assert _view(hs) == ("failed", "fatal", "open")

    _close_by_silence(hs, clk)
    assert _view(hs) == ("failed", "fatal", "closed")


def test_plugin_ok_does_not_hide_open_breaker() -> None:
    hs, clk, a, _ = _make()
    _trip(hs)
    a.ok()
    _assert_open_breaker_view(hs)

    _close_by_silence(hs, clk)
    assert _view(hs) == ("ok", None, "closed")


def test_plugin_ok_does_not_clear_neighbour() -> None:
    hs, _, a, b = _make()
    a.degraded("a-reason")
    b.ok()
    assert _view(hs) == ("degraded", "a-reason", "closed")

    a.ok()
    assert _view(hs) == ("ok", None, "closed")


def test_published_snapshot_after_close_keeps_reason() -> None:
    hs, clk, a, _ = _make()
    a.degraded("assets")
    _trip(hs)
    _assert_open_breaker_view(hs)
    hs.take_dirty()  # слить опубликованное до закрытия

    _close_by_silence(hs, clk)
    dirty = hs.take_dirty()
    assert dirty is not None
    assert dirty["status"] == "degraded"
    assert dirty["degraded_reason"] == "assets"
    assert dirty["breaker"] == "closed"


# --- S: стражи, зелёные до и после -------------------------------------------


def test_breaker_only_degradation_clears_on_close() -> None:
    hs, clk, _, _ = _make()
    _trip(hs)

    _close_by_silence(hs, clk)
    assert _view(hs) == ("ok", None, "closed")


def test_own_ok_clears_own_degraded() -> None:
    hs, _, a, _ = _make()
    a.degraded("x")
    a.ok()
    assert _view(hs) == ("ok", None, "closed")
