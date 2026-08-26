# -*- coding: utf-8 -*-
"""Ф5 (план ``plans/observation-port/plan.md``) — доработка по блокерам ревью.

Три блокера синхронного ревью (B1/B2/B3), закрытые ЭТОЙ правкой. Автор —
TeamLead (Senior+), не независимый тестер: задача экспресс-реализации по ТЗ
ревью, а не приёмка с нуля. Инъекции — там, где это дёшево (снятие правки
локальным monkeypatch, восстановление в ``finally``).
"""

from __future__ import annotations

from typing import Any, Dict

from ...process_module.heartbeat import telemetry
from .. import StatsManager
from ..observation.observation_manager import (
    ObservationManager,
    ObservationPort,
    bare_port_number_losses,
)


# =========================================================================== #
# B1 — число уходит во 2-ю ступень резолвера и исчезает молча
# =========================================================================== #


class TestB1BarePortNumberLoss:
    """``ObservationPort`` без менеджера (ступень 2) — числа теперь СЧИТАЕМЫ."""

    def test_numbers_sent_through_a_bare_port_are_counted_as_losses(self) -> None:
        store = telemetry.PluginLevels()
        port = ObservationPort(store)

        assert bare_port_number_losses(store) == 0, "до единой записи потерь нет"

        port.record_metric("capture.frames", 7)
        port.gauge("capture.fps", 30.0)
        port.record_timing("capture.dt", 0.01)

        assert bare_port_number_losses(store) == 3, (
            "три числа ушли в бесхозный вид (уровни доступны — declare/publish/"
            "retract работают на этом же хранилище) и обязаны быть посчитаны"
        )

    def test_losses_are_scoped_to_their_own_store_not_global(self) -> None:
        """Дедуп/счёт — ПО ХРАНИЛИЩУ, а не общий на процесс/интерпретатор."""
        store_a = telemetry.PluginLevels()
        store_b = telemetry.PluginLevels()
        ObservationPort(store_a).record_metric("x", 1)

        assert bare_port_number_losses(store_a) == 1
        assert bare_port_number_losses(store_b) == 0, (
            "хранилище, к которому не обращались, не обязано наследовать чужой счёт"
        )

    def test_levels_still_work_on_the_same_bare_port_unaffected(self) -> None:
        """Пара-контроль: плоскость УРОВНЕЙ на той же ступени 2 не тронута B1."""
        store = telemetry.PluginLevels()
        port = ObservationPort(store)
        port.publish("fps", 30.0, "capture")
        assert port.collect_subtree() == {"plugins": {"capture": {"fps": 30.0}}}

    def test_break_injection_reverting_the_count_makes_the_first_test_fail(self) -> None:
        """Инъекция: верни старый silent ``return`` — счёт обязан обнулиться."""
        original = ObservationPort._deliver_number

        def _silent_noop(self: ObservationPort, record: Dict[str, Any]) -> None:  # noqa: ANN001
            return

        ObservationPort._deliver_number = _silent_noop  # type: ignore[method-assign]
        try:
            store = telemetry.PluginLevels()
            port = ObservationPort(store)
            port.record_metric("x", 1)
            assert bare_port_number_losses(store) == 0, (
                "с восстановленным silent no-op счёт обязан остаться нулевым — "
                "это и есть дефект B1, который правка устраняет"
            )
        finally:
            ObservationPort._deliver_number = original  # type: ignore[method-assign]


# =========================================================================== #
# B2 — attach_observation_port врёт об успехе без реальной подписки
# =========================================================================== #


def _make_stats_manager(name: str) -> StatsManager:
    mgr = StatsManager(
        manager_name=name,
        config={
            "enable_logging": False,
            "aggregation_interval": 300.0,
            "flush_interval": 300.0,
            "channels": {"file_stats": {"enabled": False}},
        },
    )
    assert mgr.initialize()
    return mgr


class _PortWithoutAddTap(ObservationPort):
    """Порт БЕЗ ``add_tap`` — ровно репродукция ревью B2 (``bare = ObservationPort(...)``)."""


class TestB2AttachRefusesAHalfConnection:
    def test_attach_without_add_tap_returns_false(self) -> None:
        mgr = _make_stats_manager("b2_no_add_tap")
        bare = _PortWithoutAddTap(telemetry.PluginLevels())
        try:
            assert mgr.attach_observation_port(bare) is False, (
                "порт без add_tap не может вернуть число ЭТОМУ менеджеру — attach "
                "обязан отказать, а не доложить об успехе"
            )
        finally:
            mgr.shutdown()

    def test_after_a_refused_attach_the_manager_stays_on_the_direct_road_and_counts_bypass(self) -> None:
        mgr = _make_stats_manager("b2_bypass_after_refusal")
        bare = _PortWithoutAddTap(telemetry.PluginLevels())
        try:
            assert mgr.attach_observation_port(bare) is False

            mgr.record_metric("frames", 3)
            mgr.flush()

            metric = mgr.get_metric("frames")
            assert metric is not None and metric["count"] == 3.0, (
                "отказ attach не должен ронять запись — прежняя прямая дорога обязана работать"
            )
            assert mgr.observation_bypasses == {"record_metric": 1}, (
                f"обход обязан быть посчитан и назван по методу, получено {mgr.observation_bypasses!r}"
            )
        finally:
            mgr.shutdown()

    def test_a_real_manager_port_still_attaches_successfully(self) -> None:
        """Пара-контроль: живой ``ObservationManager`` (есть add_tap) — attach True."""
        mgr = _make_stats_manager("b2_real_port")
        port = ObservationManager(manager_name="b2_real_port_observation")
        assert port.initialize()
        try:
            assert mgr.attach_observation_port(port) is True
            assert mgr.observation_bypasses == {}
        finally:
            mgr.shutdown()
            port.shutdown()

    def test_get_stats_exposes_observation_bypasses(self) -> None:
        mgr = _make_stats_manager("b2_get_stats")
        try:
            mgr.record_metric("x", 1)
            stats = mgr.get_stats()
            assert stats["observation_bypasses"] == {"record_metric": 1}, (
                f"B2/S2: observation_bypasses обязан выехать наружу через get_stats(), "
                f"получено {stats.get('observation_bypasses')!r}"
            )
        finally:
            mgr.shutdown()


# =========================================================================== #
# B3 — доставка чисел идёт по механизму, чей контракт — глушить отказы
# =========================================================================== #


class _RaisingTap:
    """Приёмник, чей ``write()`` всегда бросает — симулирует «bad-число»."""

    name = "raising_tap"

    def write(self, record: Dict[str, Any]) -> None:
        raise ValueError("не-число")

    def close(self) -> None:  # pragma: no cover — best-effort хук remove_tap
        pass


class _ReentrantTap:
    """Приёмник, чей ``write()`` сам зовёт ``record_metric`` — реентерабельность."""

    name = "reentrant_tap"

    def __init__(self, port: ObservationManager) -> None:
        self._port = port
        self.writes = 0

    def write(self, record: Dict[str, Any]) -> None:
        self.writes += 1
        self._port.record_metric("reentrant.echo", 1)

    def close(self) -> None:  # pragma: no cover
        pass


class TestB3OwnCountersOnTheNumbersPlane:
    def test_a_healthy_number_is_counted_as_delivered(self) -> None:
        port = ObservationManager(manager_name="b3_healthy")
        assert port.initialize()
        try:
            port.record_metric("ok", 1)
            stats = port.get_stats()
            assert stats["numbers_delivered"] == 1
            assert stats["numbers_dropped_by_sink_error"] == 0
            assert stats["numbers_suppressed_reentrant"] == 0
        finally:
            port.shutdown()

    def test_a_raising_sink_is_counted_and_does_not_raise_out(self) -> None:
        port = ObservationManager(manager_name="b3_raising_sink")
        assert port.initialize()
        port.add_tap(_RaisingTap(), min_level="DEBUG", name="raising")
        try:
            # Контракт «tail не роняет эмитента» обязан устоять.
            port.record_metric("bad", "не-число")
            stats = port.get_stats()
            assert stats["numbers_dropped_by_sink_error"] == 1, (
                f"tap бросил при записи — потеря обязана быть посчитана, получено {stats!r}"
            )
        finally:
            port.shutdown()

    def test_reentrant_delivery_is_suppressed_and_counted_not_lost_silently(self) -> None:
        port = ObservationManager(manager_name="b3_reentrant")
        assert port.initialize()
        tap = _ReentrantTap(port)
        port.add_tap(tap, min_level="DEBUG", name="reentrant")
        try:
            for _ in range(5):
                port.record_metric("plugin.frames", 1)

            stats = port.get_stats()
            assert tap.writes == 5, f"внешний вызов обязан дойти до tap'а все 5 раз, дошло {tap.writes}"
            assert stats["numbers_suppressed_reentrant"] == 5, (
                f"КАЖДЫЙ реентерабельный echo обязан быть подавлен и посчитан, получено {stats!r}"
            )
            assert stats["numbers_delivered"] == 5, (
                "внешние 5 вызовов доставлены (не подавлены); реентерабельные echo НЕ "
                f"учтены в delivered — получено {stats!r}"
            )
        finally:
            port.shutdown()

    def test_break_injection_reverting_the_error_counter_hides_the_loss_again(self) -> None:
        """Инъекция: без учёта — потеря СНОВА невидима (но эмитент по-прежнему не падает)."""
        from ...channel_routing_module.core import channel_routing_manager as crm_module

        original = crm_module.ChannelRoutingManager._emit_to_taps

        def _emit_without_counting(self, record_dict, level=None):  # noqa: ANN001
            if not self._tap_sinks:
                return
            for channel, _min_severity in list(self._tap_sinks.values()):
                try:
                    channel.write(record_dict)
                except Exception:  # nosec B110 — воспроизводит ДОФИКСОВОЕ поведение
                    pass

        crm_module.ChannelRoutingManager._emit_to_taps = _emit_without_counting  # type: ignore[method-assign]
        try:
            port = ObservationManager(manager_name="b3_injection")
            assert port.initialize()
            port.add_tap(_RaisingTap(), min_level="DEBUG", name="raising")
            try:
                port.record_metric("bad", "не-число")  # не должно бросить наружу
                stats = port.get_stats()
                assert stats["numbers_dropped_by_sink_error"] == 0, (
                    "без учёта в _emit_to_taps потеря обязана снова стать невидимой — "
                    "ровно дефект, который правка B3 устраняет"
                )
            finally:
                port.shutdown()
        finally:
            crm_module.ChannelRoutingManager._emit_to_taps = original  # type: ignore[method-assign]
