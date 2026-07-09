# -*- coding: utf-8 -*-
"""
Контракт-тест разделения hub ↔ health (Ф5.17).

Инвариант (vision §5.9, требование владельца): канал наблюдаемости (ДОСТАВКА,
ObservabilityHub) и ``ctx.health`` (АГРЕГАЦИЯ отказов, HealthState) кормятся из
одной точки эмиссии, но живут раздельно — hub НЕ дублирует health-счётчики, а
health НЕ пишет в hub-канал. Одна эмиссия → и в канал, и в health, без двойного
учёта.

Механизмы развязаны по построению: ``health/state.py`` не импортит observability,
``ObservabilityHub`` (channel_routing) не знает про process_module.health. Тест
пиннит эту границу, чтобы будущая правка не спаяла их (двойной учёт / протечка).
"""

from ...channel_routing_module.observability import ObservabilityHub
from ..health.state import HealthState


def _clock() -> float:
    return 100.0  # детерминированное время (throttle/ts не влияют на счётчик)


def _pair():
    health = HealthState(log_only=True, clock=_clock)
    hub = ObservabilityHub("mod", clock=_clock)
    return health, hub


# ---------------------------------------------------------------------------
# Раздельность: механизмы не текут друг в друга
# ---------------------------------------------------------------------------


def test_hub_delivery_does_not_touch_health_counter():
    """hub (доставка) не инкрементит health-счётчик (агрегация)."""
    health, hub = _pair()
    hub.track_error(ValueError("x"))
    assert health.error_count == 0  # hub не кормит health
    assert len(hub.drain_errors()) == 1  # но доставка состоялась


def test_health_aggregation_does_not_touch_hub_channel():
    """health (агрегация) не пишет в hub-канал (доставку)."""
    health, hub = _pair()
    health.report_error(ValueError("x"))
    assert health.error_count == 1
    assert len(hub.drain_errors()) == 0  # health не кормит hub


# ---------------------------------------------------------------------------
# Одна эмиссия → оба механизма, без двойного учёта
# ---------------------------------------------------------------------------


def test_single_emission_feeds_both_without_double_count():
    """Одна эмиссия кормит и канал, и health — каждый учитывает РОВНО один раз."""
    health, hub = _pair()
    exc = ValueError("boom")

    # Точка эмиссии кормит оба механизма (как реальный error-сайт плагина).
    hub.track_error(exc)
    health.report_error(exc)

    assert health.error_count == 1  # health — ровно один
    assert len(hub.drain_errors()) == 1  # канал — ровно один


def test_repeated_emissions_stay_one_to_one():
    """N эмиссий → health.error_count == N и N записей в канале (нет удвоения)."""
    health, hub = _pair()
    for _ in range(5):
        exc = RuntimeError("e")
        hub.track_error(exc)
        health.report_error(exc)
    assert health.error_count == 5
    assert len(hub.drain_errors()) == 5
