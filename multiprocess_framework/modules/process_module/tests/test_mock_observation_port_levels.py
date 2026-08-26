# -*- coding: utf-8 -*-
"""Ф5 (план observation-port), ревью-блокер S1 — двойник порта и три дороги уровней.

`_MockObservationPort` (`process_module/plugins/testing.py`) резолвируется
СТУПЕНЬЮ 1 (`services.get_manager("observation")`), когда
`MockProcessServices` построен с непустым `stats_manager`. До правки S1 у
двойника не было `for_plugin` — `PluginContext.declare_metric`/
`publish_metric`/`_retract_metrics` падали `AttributeError` при первом же
вызове ЧЕРЕЗ ЭТУ КОМБИНАЦИЮ. Гейт был зелёным только потому, что ни один тест
не гонял уровни через `MockProcessServices` с непустым `stats_manager` —
`test_plugin_levels_acceptance.py` строит `MockProcessServices` БЕЗ
`stats_manager` (ступень 2, бесхозный вид над `plugin_levels`, дыры там нет и
не было) — эта дыра пряталась за отсутствием пробы.

Автор — TeamLead (Senior+, работа по ТЗ ревью Ф5). Пишется ПОСЛЕ реализации:
задача экспресс-реализации блокеров, не независимая приёмка.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
    MockStatsManager,
)


def _ctx_with_stats(plugin_name: str = "cam") -> tuple[PluginContext, MockProcessServices]:
    services = MockProcessServices(name="p1", stats_manager=MockStatsManager())
    ctx = PluginContext(services=services, config={}, plugin_name=plugin_name)
    return ctx, services


class TestLevelsThroughMockObservationPort:
    """Три дороги уровней обязаны работать, когда резолвер отдаёт СТУПЕНЬ 1 (двойник)."""

    def test_declare_metric_does_not_raise_and_returns_the_name(self) -> None:
        ctx, _services = _ctx_with_stats()
        # ДО правки S1: AttributeError: '_MockObservationPort' object has no
        # attribute 'for_plugin'.
        assert ctx.declare_metric("fps") == "fps"

    def test_publish_metric_lands_in_the_double_own_storage(self) -> None:
        ctx, services = _ctx_with_stats(plugin_name="cam3")
        ctx.declare_metric("fps")
        ctx.publish_metric("fps", 30.0)

        port = services.get_manager("observation")
        subtree = port.collect_subtree()
        assert subtree == {"plugins": {"cam3": {"fps": 30.0}}}, (
            f"публикация не долетела до собственного хранилища двойника: {subtree!r}"
        )

    def test_retract_metrics_removes_exactly_what_this_writer_published(self) -> None:
        ctx, services = _ctx_with_stats(plugin_name="cam4")
        ctx.declare_metric("fps")
        ctx.publish_metric("fps", 25.0)
        port = services.get_manager("observation")
        assert port.collect_subtree() == {"plugins": {"cam4": {"fps": 25.0}}}

        removed = ctx._retract_metrics()

        assert removed == 1, f"ожидалось снять ровно одну запись писателя, снято {removed!r}"
        assert port.collect_subtree() == {}, "поддерево писателя обязано опустеть после retract"

    def test_numbers_still_forward_to_stats_manager_unchanged(self) -> None:
        """Регресс: числовая дорога (ради которой двойник и заводился) не тронута."""
        ctx, services = _ctx_with_stats(plugin_name="cam5")
        ctx.record_metric("frames", 7)
        ctx.gauge("fps", 30.0)
        ctx.record_timing("dt", 0.01)

        records = services.stats_manager.records
        assert ("counter", "frames", 7, {"plugin": "cam5"}) in records
        assert ("gauge", "fps", 30.0, {"plugin": "cam5"}) in records
        assert ("timing", "dt", 0.01, {"plugin": "cam5"}) in records


class TestBreakInjectionForS1:
    """Ломающая инъекция: убери ``for_plugin`` у двойника снова — левый тест обязан покраснеть."""

    def test_removing_for_plugin_reproduces_the_original_attribute_error(self) -> None:
        # ``for_plugin`` унаследован от ``ObservationPort`` (не переопределён у
        # двойника) — снимаем его ТАМ, на классе, а не на подклассе, где его
        # нет в ``__dict__``. Правится глобально, но временно и в finally.
        from multiprocess_framework.modules.statistics_module.observation.observation_manager import (
            ObservationPort,
        )

        original = ObservationPort.for_plugin
        del ObservationPort.for_plugin
        try:
            ctx, _services = _ctx_with_stats()
            with pytest.raises(AttributeError):
                ctx.declare_metric("fps")
        finally:
            # Восстановление в finally, а не в except — упавший ассерт не должен
            # травить соседние тесты порчей общего класса (урок проекта).
            ObservationPort.for_plugin = original
