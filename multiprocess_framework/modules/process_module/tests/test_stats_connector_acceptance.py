# -*- coding: utf-8 -*-
"""Приёмочные тесты «разъёма к метрикам» у плагинов (этап 6, 1.1) — НЕЗАВИСИМЫЙ автор.

Пишутся ПО КРИТЕРИЯМ ПРИЁМКИ, без чтения ``plugins/base.py``, ``plugins/interfaces.py``
и ``managers/observability_wiring.py`` — они дёргаются как чёрный ящик через публичный
API. Единственные читанные источники: докстринги/сигнатуры в рантайме (``inspect``),
эталон ``StatsManager`` (существовал ДО этой задачи) и дубли из ``plugins/testing.py``.

Контракт (буквы — из постановки задачи):

  А. У ``PluginContext`` есть четвёрка ``record_metric`` / ``gauge`` / ``record_timing`` /
     ``histogram``.
  Б. Сигнатуры дословно совпадают с ``StatsManager`` — имена параметров, порядок,
     значения по умолчанию. Третьего написания быть не должно.
  В. Фасад пишет в ``stats_manager`` сервисов процесса.
  Г. Атрибуция: контекст с именем плагина штампует тег ``plugin``; явный тег
     ``plugin`` от вызывающего выигрывает у автоштампа; контекст без имени
     плагина автоштампа не ставит.
  Д. Ненастроенная плоскость (``stats_manager is None``) — не роняет вызов, но и не
     молчит: ``stats_plane_report`` считает ``without_plane``, голос звучит РОВНО
     ОДИН РАЗ (WARNING) с именем метрики и именем источника.
  Е. Сбой самого менеджера (``raises=``) не роняет линию, называется ERROR-записью,
     и НЕ считается как «плоскости нет» (``declared`` остаётся ``True``,
     ``without_plane`` не растёт).
  Ж. ``SubPluginContext`` несёт всю четвёрку (вызов без родителя безопасен),
     ``from_parent`` пробрасывает все четыре дороги к менеджеру родителя.
  З. Настоящая связка на ``ProcessModule``: метрика доезжает до ЖИВОГО
     ``StatsManager``, единица ``record_timing`` — СЕКУНДЫ.
  И. ``introspect.observability`` несёт секцию ``stats``.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.managers.observability_wiring import stats_plane_report
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, SubPluginContext
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
    MockStatsManager,
)
from multiprocess_framework.modules.statistics_module.core.stats_manager import StatsManager

QUARTET = ("record_metric", "gauge", "record_timing", "histogram")


def _param_specs(fn: Any) -> list[tuple[str, Any]]:
    """(имя, значение_по_умолчанию) по КАЖДОМУ параметру, кроме ``self``.

    Аннотации намеренно не сравниваются: в ``plugins/base.py`` может стоять
    ``from __future__ import annotations`` (строковые аннотации), а в
    ``stats_manager.py`` — обычные объекты типов; контракт требует дословного
    совпадения ИМЁН, ПОРЯДКА и ДЕФОЛТОВ, не текста аннотации.
    """
    sig = inspect.signature(fn)
    return [(p.name, p.default) for p in sig.parameters.values() if p.name != "self"]


# ==============================================================================
# А + Б — четвёрка есть, и сигнатуры дословны StatsManager
# ==============================================================================


class TestQuartetExistsOnPluginContext:
    """А. У PluginContext обязана быть вся четвёрка — иначе плагин падает AttributeError."""

    @pytest.mark.parametrize("method", QUARTET)
    def test_method_exists_and_is_callable(self, method: str) -> None:
        ctx = PluginContext(services=MockProcessServices(), config={})
        fn = getattr(ctx, method, None)
        assert callable(fn), f"PluginContext не несёт {method} — контракт А нарушен"


class TestSignaturesMatchStatsManagerVerbatim:
    """Б. Третьего написания сигнатуры быть не должно — сверяем с эталоном StatsManager.

    Если здесь красно: имя параметра, его позиция или дефолт у фасада разошлись
    с ``StatsManager``, и вызывающий, привыкший к позиционным/именованным
    аргументам эталона, получит ``TypeError`` на фасаде.
    """

    @pytest.mark.parametrize("method", QUARTET)
    def test_plugin_context_signature_matches_stats_manager(self, method: str) -> None:
        want = _param_specs(getattr(StatsManager, method))
        got = _param_specs(getattr(PluginContext, method))
        assert got == want, f"{method}: сигнатура PluginContext {got} разошлась с эталоном StatsManager {want}"

    @pytest.mark.parametrize("method", QUARTET)
    def test_sub_plugin_context_default_impl_matches_stats_manager(self, method: str) -> None:
        """Та же сверка для БЕЗРОДИТЕЛЬСКОЙ (default no-op) реализации SubPluginContext.

        Контракт Б не делает исключения для суб-контекста: он тоже часть
        разъёма к метрикам (буква Ж требует, чтобы вызов без родителя был
        безопасен, а «безопасен» включает совместимость сигнатуры с эталоном,
        иначе вызывающий код, писавший под StatsManager.record_timing(name,
        duration=...), падает уже на суб-контексте).
        """
        want = _param_specs(getattr(StatsManager, method))
        got = _param_specs(getattr(SubPluginContext, method))
        assert got == want, (
            f"{method}: сигнатура SubPluginContext (default) {got} разошлась с эталоном StatsManager {want}"
        )


# ==============================================================================
# Ж — SubPluginContext: безопасность без родителя + сигнатура-обязательство
# ==============================================================================


class TestSubContextIsSafeWithoutParent:
    """Ж (первая половина). Вызов без родителя не роняет плагин."""

    @pytest.mark.parametrize(
        "method,args",
        [
            ("record_metric", ("m",)),
            ("gauge", ("g", 1)),
            ("record_timing", ("t", 0.1)),
            ("histogram", ("h", 1)),
        ],
    )
    def test_call_without_parent_does_not_raise(self, method: str, args: tuple) -> None:
        bare = SubPluginContext()
        getattr(bare, method)(*args)  # не должно поднять исключение

    def test_record_timing_accepts_the_duration_keyword_like_the_reference(self) -> None:
        """Прямое следствие контракта Б: вызывающий код пишет под сигнатуру StatsManager.

        ``StatsManager.record_timing(name, duration, tags=None)`` — второй
        параметр называется ``duration``. Плагин, написанный против этого
        имени (``ctx.record_timing("frame", duration=0.016)``), обязан
        одинаково работать что на PluginContext, что на голом
        SubPluginContext (Ж требует безопасность БЕЗ родителя — а раз вызов
        разрешён, он обязан принимать тот же контракт вызова, что и эталон).
        """
        bare = SubPluginContext()
        bare.record_timing("frame_period", duration=0.016)  # не должно поднять TypeError


class TestSubContextForwardsAllFourRoadsFromParent:
    """Ж (вторая половина). ``from_parent`` пробрасывает все четыре дороги к менеджеру родителя."""

    @pytest.mark.parametrize(
        "method,args,kind",
        [
            ("record_metric", ("nested_counter", 2), "counter"),
            ("gauge", ("nested_gauge", 7), "gauge"),
            ("record_timing", ("nested_timing", 0.05), "timing"),
            ("histogram", ("nested_hist", 3), "histogram"),
        ],
    )
    def test_nested_metric_reaches_the_parents_manager(self, method: str, args: tuple, kind: str) -> None:
        stats = MockStatsManager()
        parent = PluginContext(services=MockProcessServices(stats_manager=stats), config={}, plugin_name="parent")
        sub = SubPluginContext.from_parent(parent, config={})

        getattr(sub, method)(*args)

        assert stats.records, f"{method}: запись не доехала до менеджера родителя"
        recorded_kind, recorded_name = stats.records[-1][0], stats.records[-1][1]
        assert recorded_kind == kind, f"{method}: род записи {recorded_kind!r} != {kind!r}"
        assert recorded_name == args[0]


# ==============================================================================
# В + Г — куда пишет, и атрибуция
# ==============================================================================


class TestWritesToTheProcessStatsManager:
    """В. Фасад пишет именно в services.stats_manager, а не куда-то ещё."""

    def test_record_metric_reaches_the_configured_manager(self) -> None:
        stats = MockStatsManager()
        ctx = PluginContext(services=MockProcessServices(stats_manager=stats), config={}, plugin_name="checker")
        ctx.record_metric("defects_total", 3)
        assert stats.records == [("counter", "defects_total", 3, {"plugin": "checker"})]


class TestAttribution:
    """Г. Тег ``plugin`` — автоштамп по имени плагина, явный тег выигрывает, без имени — молчание."""

    @pytest.mark.parametrize(
        "method,args",
        [
            ("record_metric", ("m", 1)),
            ("gauge", ("g", 1)),
            ("record_timing", ("t", 0.1)),
            ("histogram", ("h", 1)),
        ],
    )
    def test_named_plugin_context_stamps_the_plugin_tag(self, method: str, args: tuple) -> None:
        stats = MockStatsManager()
        ctx = PluginContext(services=MockProcessServices(stats_manager=stats), config={}, plugin_name="checker")
        getattr(ctx, method)(*args)
        tags = stats.records[-1][3]
        assert tags is not None and tags.get("plugin") == "checker", (
            f"{method}: нет автоштампа plugin=checker, теги={tags}"
        )

    def test_explicit_plugin_tag_wins_over_auto_stamp(self) -> None:
        stats = MockStatsManager()
        ctx = PluginContext(services=MockProcessServices(stats_manager=stats), config={}, plugin_name="checker")
        ctx.record_metric("defects_total", 1, tags={"plugin": "override"})
        tags = stats.records[-1][3]
        assert tags.get("plugin") == "override", f"явный тег не выиграл: {tags}"

    def test_context_without_plugin_name_does_not_auto_stamp(self) -> None:
        stats = MockStatsManager()
        ctx = PluginContext(services=MockProcessServices(stats_manager=stats), config={})
        ctx.record_metric("anon_metric")
        tags = stats.records[-1][3]
        assert not (tags and "plugin" in tags), f"автоштамп без имени плагина: {tags}"


# ==============================================================================
# Д — ненастроенная плоскость: не роняет, но не молчит
# ==============================================================================


class TestUnconfiguredPlaneIsLegalButNotSilent:
    """Д. ``stats_manager is None`` — законное состояние: не исключение, но и не тишина."""

    @pytest.mark.parametrize(
        "method,args",
        [
            ("record_metric", ("m", 1)),
            ("gauge", ("g", 1)),
            ("record_timing", ("t", 0.1)),
            ("histogram", ("h", 1)),
        ],
    )
    def test_call_without_plane_does_not_raise(self, method: str, args: tuple) -> None:
        ctx = PluginContext(services=MockProcessServices(), config={}, plugin_name="checker")
        getattr(ctx, method)(*args)  # не должно поднять исключение

    def test_the_loss_is_counted_in_the_readback(self) -> None:
        services = MockProcessServices()
        ctx = PluginContext(services=services, config={}, plugin_name="checker")
        ctx.record_metric("defects_total")
        ctx.gauge("queue_len", 5)
        report = stats_plane_report(services)["stats"]
        assert report["declared"] is False
        assert report["without_plane"] == 2, report

    def test_the_voice_speaks_exactly_once_and_names_metric_and_source(self) -> None:
        """Голос — РОВНО один раз, даже при нескольких попытках через РАЗНЫЕ контексты
        на одних и тех же сервисах (плоскости нет у процесса — факт один на всех
        плагинов процесса, а не на каждый вызов).
        """
        services = MockProcessServices()
        ctx_a = PluginContext(services=services, config={}, plugin_name="checker_a")
        ctx_b = PluginContext(services=services, config={}, plugin_name="checker_b")

        ctx_a.record_metric("defects_total")
        ctx_a.gauge("queue_len", 5)
        ctx_b.record_metric("other_metric")

        spoken = [e for e in services.logs if e["level"] == "WARNING"]
        assert len(spoken) == 1, f"голос не однократен: {spoken}"
        assert "defects_total" in spoken[0]["msg"], f"нет имени первой метрики: {spoken[0]}"
        assert "checker_a" in spoken[0]["msg"], f"нет имени источника: {spoken[0]}"
        assert stats_plane_report(services)["stats"]["without_plane"] == 3


# ==============================================================================
# Е — сбой менеджера не роняет линию и не путается с «плоскости нет»
# ==============================================================================


class TestManagerFailureDoesNotDropTheLine:
    """Е. ``MockStatsManager(raises=...)`` — фасад переживает сбой самого менеджера."""

    def test_call_survives_the_managers_exception(self) -> None:
        stats = MockStatsManager(raises=RuntimeError("stats упал"))
        ctx = PluginContext(services=MockProcessServices(stats_manager=stats), config={}, plugin_name="checker")
        ctx.record_metric("defects_total")  # не должно поднять исключение наружу

    def test_the_failure_is_named_by_an_error_entry(self) -> None:
        stats = MockStatsManager(raises=RuntimeError("stats упал"))
        services = MockProcessServices(stats_manager=stats)
        ctx = PluginContext(services=services, config={}, plugin_name="checker")
        ctx.record_metric("defects_total")
        said = [e for e in services.logs if "stats упал" in e["msg"]]
        assert said, f"причина сбоя не названа ни одной записью: {services.logs}"
        assert said[0]["level"] == "ERROR", f"сбой менеджера сказан уровнем {said[0]['level']}"

    def test_manager_failure_is_not_confused_with_a_missing_plane(self) -> None:
        stats = MockStatsManager(raises=RuntimeError("stats упал"))
        services = MockProcessServices(stats_manager=stats)
        ctx = PluginContext(services=services, config={}, plugin_name="checker")
        ctx.record_metric("defects_total")
        report = stats_plane_report(services)["stats"]
        assert report["declared"] is True, "объявленная плоскость со сломанным менеджером — не 'плоскости нет'"
        assert report["without_plane"] == 0, "сбой менеджера не должен считаться как отсутствие плоскости"


# ==============================================================================
# З — настоящая связка на живом ProcessModule
# ==============================================================================


class TestRealProcessIntegration:
    """З. Настоящий StatsManager процесса: метрика доезжает, единица timing — секунды."""

    def test_metric_reaches_the_real_stats_manager(self) -> None:
        process = ProcessModule(name="stats_road_probe", config={})
        assert process.initialize() is True
        try:
            ctx = PluginContext(services=process, config={}, plugin_name="checker")
            ctx.record_metric("defects_total", 3)
            ctx.record_metric("defects_total", 2)
            metric = process.stats_manager.get_metric("defects_total")
            assert metric is not None, "метрика не доехала до живого StatsManager"
            assert metric["type"] == "counter"
            assert metric["count"] == pytest.approx(5.0), metric
            assert metric["tags"].get("plugin") == "checker", metric
        finally:
            process.shutdown()

    def test_record_timing_unit_is_seconds_not_milliseconds(self) -> None:
        """Период кадра 1/60 ≈ 0.0167 — секунды и миллисекунды здесь расходятся
        на три порядка, так что перепутанная единица красит тест немедленно.
        """
        process = ProcessModule(name="stats_timing_probe", config={})
        assert process.initialize() is True
        try:
            ctx = PluginContext(services=process, config={}, plugin_name="checker")
            frame_period = 1.0 / 60.0
            ctx.record_timing("frame_period", frame_period)
            metric = process.stats_manager.get_metric("frame_period")
            assert metric is not None
            assert metric["type"] == "timing"
            assert metric["avg"] == pytest.approx(frame_period, rel=1e-6), (
                f"агрегат несёт не секунды: {metric['avg']} != ~{frame_period}"
            )
            # Подстраховка от «случайно совпало»: миллисекундная запись (16.67) была бы
            # на три порядка больше и не прошла бы approx выше — но проверим явно.
            assert metric["avg"] < 1.0, f"похоже на миллисекунды, а не секунды: {metric}"
        finally:
            process.shutdown()

    def test_gauge_overwrites_not_accumulates(self) -> None:
        process = ProcessModule(name="stats_gauge_probe", config={})
        assert process.initialize() is True
        try:
            ctx = PluginContext(services=process, config={}, plugin_name="checker")
            ctx.gauge("queue_len", 10)
            ctx.gauge("queue_len", 20)
            metric = process.stats_manager.get_metric("queue_len")
            assert metric is not None
            assert metric["type"] == "gauge"
            assert metric["value"] == 20, f"gauge обязан ХРАНИТЬ последнее значение, а не суммировать: {metric}"
        finally:
            process.shutdown()


# ==============================================================================
# И — команда introspect.observability несёт секцию stats
# ==============================================================================


class _FakeCommandManager:
    def register_command(self, name, handler, metadata=None, tags=None) -> None:  # noqa: ANN001
        pass


class _FakeServicesForCommand:
    """Минимальный набор атрибутов, каким пользуется ``_cmd_introspect_observability``
    в соседних тестах команд (``test_introspect_observability_after_hierarchy.py``).
    """

    def __init__(self, stats_manager: Any) -> None:
        self.command_manager = _FakeCommandManager()
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = stats_manager
        self.router_manager = None
        self.name = "stats_command_probe"

    def get_config(self, key, default=None):  # noqa: ANN001
        return default

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...


class TestIntrospectObservabilityCarriesStatsSection:
    """И. Ответ ``introspect.observability`` обязан нести секцию ``stats``."""

    def test_response_has_a_stats_section_when_plane_is_configured(self) -> None:
        svc = _FakeServicesForCommand(stats_manager=MockStatsManager())
        bc = BuiltinCommands(svc)
        response = bc._cmd_introspect_observability({})
        assert "stats" in response, f"нет секции stats в ответе команды: {sorted(response)}"
        assert response["stats"]["declared"] is True, response["stats"]

    def test_response_has_a_stats_section_when_plane_is_absent(self) -> None:
        """Пара к предыдущему: секция есть и без плоскости — с declared=False."""
        svc = _FakeServicesForCommand(stats_manager=None)
        bc = BuiltinCommands(svc)
        response = bc._cmd_introspect_observability({})
        assert "stats" in response
        assert response["stats"]["declared"] is False, response["stats"]
