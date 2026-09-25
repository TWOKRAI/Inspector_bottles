# -*- coding: utf-8 -*-
"""Независимая приёмка Task 1.3a (Part B2): EventHub — байт-кап на кольцо (RED).

Написано ДО реализации по дизайну лида. Слепота: читал только ``events.py``
(докстринги/сигнатуры) и ``tests/test_eviction_voice.py`` (идиома голоса
вытеснения, которую здесь ЗЕРКАЛИМ, а не изобретаем новый сигнал) —
реализации фикса нет и не смотрел.

Контракт (литералы фикса лида):
  - новый keyword-only kwarg ``max_bytes_per_ring: int``, дефолт ровно
    16_777_216;
  - каждое кольцо (arrival и КАЖДАЯ плоскость) ограничено И по ``maxlen``, И
    по байтам: ``EventHub(maxlen=1000, max_bytes_per_ring=10_000)`` + 10
    push'ей ~3 КиБ каждый на одной плоскости → кольцо держит НЕ БОЛЬШЕ 3
    (самые новые);
  - потеря по байт-капу видна ТЕМ ЖЕ сигналом, что и maxlen-вытеснение
    сегодня (``stats()[...]['evicted']`` растёт + WARNING на логгере
    ``backend_ctl.events`` — идиома скопирована из
    ``test_eviction_voice.py::test_first_eviction_burst_...``), никакого
    нового сигнала не придумываю.
  - формула оценки размера НЕ фиксируется тестом — только сама граница.
"""

from __future__ import annotations

import inspect
import logging

import pytest

from backend_ctl.events import EventHub


class FakeClock:
    """Управляемые часы для теста — не патчим time.monotonic глобально
    (та же идиома, что в test_eviction_voice.py)."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def __call__(self) -> float:
        return self._t


def _log_event(i: int, pad: str) -> dict:
    """Событие плоскости "logs" (command == "log.record" -> plane logs)."""
    return {"type": "event", "command": "log.record", "data": {"i": i, "pad": pad}}


def _warning_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "backend_ctl.events" and r.levelno == logging.WARNING]


# --- дефолт ---


def test_max_bytes_per_ring_default_is_16_mib() -> None:
    """RED сегодня: kwarg ``max_bytes_per_ring`` отсутствует в сигнатуре."""
    sig = inspect.signature(EventHub.__init__)
    assert "max_bytes_per_ring" in sig.parameters, "конструктору EventHub не хватает kwarg max_bytes_per_ring"
    param = sig.parameters["max_bytes_per_ring"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY, "max_bytes_per_ring обязан быть keyword-only"
    assert param.default == 16_777_216, f"дефолт max_bytes_per_ring должен быть 16_777_216, получено {param.default!r}"


# --- граница по байтам ---


def test_ring_bounded_by_bytes_not_only_maxlen() -> None:
    """RED сегодня: TypeError на неизвестном kwarg max_bytes_per_ring.

    maxlen=1000 (с запасом, чтобы вытеснение случилось ТОЛЬКО из-за байт-капа,
    не из-за maxlen), max_bytes_per_ring=10_000, 10 push'ей по ~3 КиБ на
    плоскости logs → кольцо держит <= 3 (самые новые)."""
    hub = EventHub(maxlen=1000, max_bytes_per_ring=10_000)
    pad = "x" * 2900  # ~3 КиБ на item с небольшим оверхедом конверта
    n = 10
    for i in range(n):
        hub.emit(_log_event(i, pad))

    stats = hub.stats()
    size = stats["planes"]["logs"]["size"]
    assert size < n, f"байт-кап не сработал вовсе: в кольце все {size} из {n} — граница не установлена"
    assert size <= 3, f"ожидал <= 3 item'ов при 10_000 байт капе и ~3 КиБ на item, получено {size}"
    assert size >= 1, "кольцо не должно опустеть полностью — хоть один (самый новый) item обязан остаться"

    # "Самые новые" — оставшиеся индексы это ХВОСТ последовательности 0..9.
    page = hub.page("logs", limit=n)
    kept_indices = [item["event"]["data"]["i"] for item in page["items"]]
    assert kept_indices == list(range(n - len(kept_indices), n)), (
        f"кольцо обязано держать САМЫЕ НОВЫЕ item'ы, получены индексы {kept_indices}"
    )


def test_byte_cap_eviction_visible_like_maxlen_eviction(caplog: pytest.LogCaptureFixture) -> None:
    """RED сегодня: TypeError на неизвестном kwarg max_bytes_per_ring.

    Зеркало test_eviction_voice.py::test_first_eviction_burst_...: потеря по
    байт-капу обязана поднять тот же evicted-счётчик и тот же голос WARNING,
    что и maxlen-вытеснение — не новый, отдельный сигнал."""
    clock = FakeClock(start=5000.0)
    hub = EventHub(maxlen=1000, max_bytes_per_ring=10_000, clock=clock)
    pad = "x" * 2900

    with caplog.at_level(logging.WARNING, logger="backend_ctl.events"):
        for i in range(6):  # 10_000 / ~3_000 ~= 3 помещается, дальше — вытеснение
            hub.emit(_log_event(i, pad))

    stats = hub.stats()
    assert stats["planes"]["logs"]["evicted"] >= 1, (
        "байт-кап обязан вести себя как maxlen: evicted в stats() должен вырасти"
    )
    logs_voices = [r for r in _warning_records(caplog) if "'logs'" in r.getMessage()]
    assert len(logs_voices) >= 1, (
        "потеря по байт-капу обязана звучать тем же WARNING-голосом, что и maxlen-вытеснение "
        "(logger backend_ctl.events) — не новый, отдельный сигнал"
    )
