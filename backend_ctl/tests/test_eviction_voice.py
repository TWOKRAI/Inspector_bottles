"""
Независимые приёмочные тесты на "голос" вытеснения в EventHub.

Контракт (из ТЗ, НЕ из чтения events.py — реализации ещё нет):
  - Вытеснение кольца плоскости обязано звучать через logging (logger
    "backend_ctl.events", уровень WARNING) один раз на ЭПИЗОД.
  - Эпизод = серия вытеснений без затишья дольше EVICTION_VOICE_QUIET_SEC.
  - Часы инъецируются через EventHub(..., clock=callable).

Эти тесты ПАДАЮТ до реализации — это ожидаемо (RED). Форма ожидаемого
падения на текущем коде: TypeError про неизвестный kwarg "clock" (конструктор
ещё не принимает часы) и/или AttributeError/ImportError про
EVICTION_VOICE_QUIET_SEC (константы ещё нет в модуле).
"""

from __future__ import annotations

import logging
import re

import pytest

from backend_ctl.events import EventHub


class FakeClock:
    """Управляемые часы для теста — НЕ патчим time.monotonic глобально."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, dt: float) -> None:
        self._t += dt


def _log_event(seq: int) -> dict:
    """Событие, классифицируемое в плоскость "logs" (проверено вручную
    через hub.stats() на текущем коде — {"command": "log.record"} -> logs)."""
    return {"type": "event", "command": "log.record", "data": {"seq": seq}}


def _quiet_sec() -> float:
    """Читаем модульную константу порога затишья — часть контракта."""
    from backend_ctl import events as events_module

    return events_module.EVICTION_VOICE_QUIET_SEC


def _warning_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "backend_ctl.events" and r.levelno == logging.WARNING]


def _fill_to_capacity(hub: EventHub, maxlen: int, start_seq: int = 0) -> int:
    """Заполнить плоскость logs РОВНО до maxlen — без единого вытеснения."""
    for i in range(maxlen):
        hub.emit(_log_event(start_seq + i))
    return start_seq + maxlen


# ---------------------------------------------------------------------------
# Критерий A: первый бурст вытеснения -> ровно ОДИН голос WARNING,
# в тексте которого есть имя плоскости и число.
# ---------------------------------------------------------------------------


def test_first_eviction_burst_emits_exactly_one_warning_with_plane_and_number(
    caplog: pytest.LogCaptureFixture,
) -> None:
    maxlen = 10
    clock = FakeClock(start=1000.0)
    hub = EventHub(maxlen=maxlen, clock=clock)

    with caplog.at_level(logging.WARNING, logger="backend_ctl.events"):
        seq = _fill_to_capacity(hub, maxlen)
        # 20 вытеснений подряд, без затишья (часы не двигаем).
        for i in range(20):
            hub.emit(_log_event(seq + i))

    warnings = _warning_records(caplog)
    # Единица контракта — КОЛЬЦО/эпизод, а не запись логгера: одно сообщение
    # эвиктит arrival и 'logs' одним append'ом, и реализация вправе как слить их
    # в одну строку, так и развести на две. Считаем голоса ПРО 'logs' — иначе
    # тест сторожил бы форму реализации и краснел на законной правке
    # (находка ревью 2026-08-14, пункт 4).
    logs_voices = [r for r in warnings if "'logs'" in r.getMessage()]
    assert len(logs_voices) == 1

    text = logs_voices[0].getMessage()
    assert "logs" in text
    assert re.search(r"\d+", text), f"голос обязан содержать число вытесненных, текст: {text!r}"


# ---------------------------------------------------------------------------
# Критерий B: второй бурст БЕЗ затишья новых голосов не добавляет.
# Арифметика: 0 -> 20 вытеснений -> 1 голос; +120 подряд -> по-прежнему 1
# голос; stats()[...]['evicted'] == 140.
# ---------------------------------------------------------------------------


def test_second_burst_without_quiet_adds_no_new_voice(
    caplog: pytest.LogCaptureFixture,
) -> None:
    maxlen = 10
    clock = FakeClock(start=2000.0)
    hub = EventHub(maxlen=maxlen, clock=clock)

    with caplog.at_level(logging.WARNING, logger="backend_ctl.events"):
        seq = _fill_to_capacity(hub, maxlen)
        for i in range(20):
            hub.emit(_log_event(seq + i))
        seq += 20

        assert len(_warning_records(caplog)) == 1

        # ещё 120 вытеснений подряд, часы не двигаем — то же затишье
        for i in range(120):
            hub.emit(_log_event(seq + i))

    warnings = _warning_records(caplog)
    assert len(warnings) == 1

    evicted = hub.stats()["planes"]["logs"]["evicted"]
    assert evicted == 140


# ---------------------------------------------------------------------------
# Критерий C: затишье дольше EVICTION_VOICE_QUIET_SEC -> следующее
# вытеснение даёт ВТОРОЙ голос (итого 2). Затишье КОРОЧЕ порога второго
# голоса не даёт (граница проверяется с обеих сторон).
# ---------------------------------------------------------------------------


def test_quiet_shorter_than_threshold_does_not_start_new_episode(
    caplog: pytest.LogCaptureFixture,
) -> None:
    maxlen = 10
    quiet = _quiet_sec()
    clock = FakeClock(start=3000.0)
    hub = EventHub(maxlen=maxlen, clock=clock)

    with caplog.at_level(logging.WARNING, logger="backend_ctl.events"):
        seq = _fill_to_capacity(hub, maxlen)
        hub.emit(_log_event(seq))  # первое вытеснение -> голос №1
        seq += 1
        assert len(_warning_records(caplog)) == 1

        # затишье КОРОЧЕ порога (порог минус 1 секунда)
        clock.advance(quiet - 1.0)
        hub.emit(_log_event(seq))  # ещё вытеснение, но тот же эпизод

    warnings = _warning_records(caplog)
    assert len(warnings) == 1


def test_quiet_longer_than_threshold_starts_new_episode_second_voice(
    caplog: pytest.LogCaptureFixture,
) -> None:
    maxlen = 10
    quiet = _quiet_sec()
    clock = FakeClock(start=4000.0)
    hub = EventHub(maxlen=maxlen, clock=clock)

    with caplog.at_level(logging.WARNING, logger="backend_ctl.events"):
        seq = _fill_to_capacity(hub, maxlen)
        hub.emit(_log_event(seq))  # вытеснение -> голос №1
        seq += 1
        assert len(_warning_records(caplog)) == 1

        # затишье ДОЛЬШЕ порога
        clock.advance(quiet + 1.0)
        hub.emit(_log_event(seq))  # новый эпизод -> голос №2

    warnings = _warning_records(caplog)
    assert len(warnings) == 2


# ---------------------------------------------------------------------------
# Критерий D: контроль-отрицание — кольцо, заполненное РОВНО до maxlen
# (без единого события сверх), не даёт НИ ОДНОГО голоса, evicted == 0.
# ---------------------------------------------------------------------------


def test_filling_exactly_to_capacity_gives_no_voice_and_no_eviction(
    caplog: pytest.LogCaptureFixture,
) -> None:
    maxlen = 10
    clock = FakeClock(start=5000.0)
    hub = EventHub(maxlen=maxlen, clock=clock)

    with caplog.at_level(logging.WARNING, logger="backend_ctl.events"):
        _fill_to_capacity(hub, maxlen)

    warnings = _warning_records(caplog)
    assert len(warnings) == 0

    evicted = hub.stats()["planes"]["logs"]["evicted"]
    assert evicted == 0


# ---------------------------------------------------------------------------
# Критерий E: голос не мешает работе — события продолжают попадать в
# кольцо и читаться после голоса.
# ---------------------------------------------------------------------------


def test_ring_keeps_accepting_and_reporting_events_after_voice(
    caplog: pytest.LogCaptureFixture,
) -> None:
    maxlen = 10
    clock = FakeClock(start=6000.0)
    hub = EventHub(maxlen=maxlen, clock=clock)

    with caplog.at_level(logging.WARNING, logger="backend_ctl.events"):
        seq = _fill_to_capacity(hub, maxlen)
        hub.emit(_log_event(seq))  # вытеснение -> голос
        seq += 1

        # после голоса — ещё события; кольцо продолжает жить
        for i in range(5):
            hub.emit(_log_event(seq + i))

    # Голос обязан прозвучать РОВНО один раз за этот эпизод. Без этой строки
    # тест переживал полное снятие фичи: три утверждения ниже — про арифметику
    # колец, которой 2.4 не касалась, и caplog открывался, но не читался
    # (находка ревью 2026-08-14, пункт 2: инъекция «голос снят» убивала 11 из 13,
    # а этот тест оставался зелёным).
    assert len([r for r in _warning_records(caplog) if "'logs'" in r.getMessage()]) == 1

    stats_after = hub.stats()["planes"]["logs"]
    # кольцо ограничено maxlen, но seq (счётчик поступивших) должен расти
    assert stats_after["seq"] == maxlen + 1 + 5
    assert stats_after["size"] == maxlen
    assert stats_after["evicted"] == 1 + 5
