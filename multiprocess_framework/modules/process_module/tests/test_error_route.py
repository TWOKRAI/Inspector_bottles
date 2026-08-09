# -*- coding: utf-8 -*-
"""C2 — куда ведут «ошибочные» разъёмы плагина: тест на МАРШРУТ, не на имя метода.

Основание — major-1 приёмочного ревью 2026-08-09. Ревью считало, что
``ctx.log_error`` уходит в logger-маршрут, а в файлы ``critical/errors/warnings``
ведёт ``ctx.health.report_error``. Прогон
(:mod:`backend_ctl.probes.probe_c2_error_route`, настоящие Logger/Error
менеджеры, настоящие файлы) вторую половину **опроверг**::

    ctx.log_error            → ['system.log']
    ctx.health.report_error  → ['system.log']      # не плоскость ошибок!
    services.track_error     → ['errors.log']      # у PluginContext такого нет

То есть у плагина не было НИ ОДНОЙ дороги в плоскость ошибок, а «report_error»
было названием без обязательства. Решение — ADR-PM-030 (вариант «б» задачи C2,
со второй половиной, сделанной правдой):

* ``ctx.log_error(str)`` — диагностическая СТРОКА, плоскость логов;
* ``ctx.health.report_error(exc)`` — ИНЦИДЕНТ: плоскость ошибок + дросселированная
  строка в журнал + счётчик health.

Проверяется, КАКАЯ ПЛОСКОСТЬ приняла запись (наблюдаемый эффект), а не то, что
вызвался метод с определённым именем: спай на имени сторожит имя.
"""

from __future__ import annotations

from typing import Any, List

from ..plugins.base import PluginContext


class _Plane:
    """Дубль плоскости: помнит, что приняла. Умеет и НЕ принять."""

    def __init__(self) -> None:
        self.records: List[str] = []
        self.incidents: List[tuple] = []

    # плоскость логов
    def debug(self, message: str, **kw: Any) -> None:
        self.records.append(str(message))

    def info(self, message: str, **kw: Any) -> None:
        self.records.append(str(message))

    def warning(self, message: str, **kw: Any) -> None:
        self.records.append(str(message))

    def error(self, message: str, **kw: Any) -> None:
        self.records.append(str(message))

    def critical(self, message: str, **kw: Any) -> None:
        self.records.append(str(message))

    # плоскость ошибок
    def track_error(self, exc: BaseException, context: Any = None) -> None:
        self.incidents.append((type(exc).__name__, str(exc), context))


class _Services:
    """Процесс с ДВУМЯ разными плоскостями — иначе маршрут неразличим.

    Общий дубль на обе плоскости дал бы зелёное при любой маршрутизации: чтобы
    судить «куда», приёмники обязаны быть разными объектами.
    """

    def __init__(self, *, with_error_plane: bool = True) -> None:
        from ...base_manager import ObservableMixin

        self.name = "route_proc"
        self.logs = _Plane()
        self.errors = _Plane() if with_error_plane else None

        managers = {"logger": self.logs}
        if self.errors is not None:
            managers["error"] = self.errors

        class _Host(ObservableMixin):
            def __init__(self, mgrs: dict) -> None:
                ObservableMixin.__init__(self, managers=mgrs)

        self._host = _Host(managers)

    def log_debug(self, message: str, **kw: Any) -> None:
        self._host._log_debug(message, **kw)

    def log_info(self, message: str, **kw: Any) -> None:
        self._host._log_info(message, **kw)

    def log_warning(self, message: str, **kw: Any) -> None:
        self._host._log_warning(message, **kw)

    def log_error(self, message: str, **kw: Any) -> None:
        self._host._log_error(message, **kw)

    def log_critical(self, message: str, **kw: Any) -> None:
        self._host._log_critical(message, **kw)

    def track_error(self, exc: BaseException, context: Any = None) -> None:
        self._host._track_error(exc, context)


def _ctx(**kw: Any) -> tuple:
    services = _Services(**kw)
    return PluginContext(services=services, plugin_name="route_plugin"), services


def test_log_error_is_a_diagnostic_string_and_stays_in_the_log_plane() -> None:
    ctx, svc = _ctx()
    ctx.log_error("парсер не понял кадр")
    assert any("парсер не понял кадр" in line for line in svc.logs.records)
    assert svc.errors.incidents == [], "диагностическая строка уехала в плоскость ошибок"


def test_report_error_is_an_incident_and_reaches_the_error_plane() -> None:
    """Вторая половина пары — и ровно то, чего не было до C2."""
    ctx, svc = _ctx()
    ctx.health.report_error(RuntimeError("камера отвалилась"))
    assert svc.errors.incidents, "инцидент не доехал до плоскости ошибок"
    etype, message, _context = svc.errors.incidents[0]
    assert etype == "RuntimeError" and "камера отвалилась" in message


def test_the_incident_also_leaves_a_line_in_the_log_plane() -> None:
    """Обе плоскости, а не «переехало из одной в другую»: журнал остаётся местом,
    где инцидент виден рядом с тем, что происходило вокруг."""
    ctx, svc = _ctx()
    ctx.health.report_error(ValueError("плохой кадр"))
    assert any("[health]" in line and "плохой кадр" in line for line in svc.logs.records)


def test_repeats_are_throttled_in_both_planes_but_counted_in_full() -> None:
    """Дроссель общий с логом; счётчик health считает ВСЕ — число не теряется."""
    ctx, svc = _ctx()
    for _ in range(5):
        ctx.health.report_error(RuntimeError("одна и та же беда"))
    assert len(svc.errors.incidents) == 1, f"дроссель не сработал: {len(svc.errors.incidents)}"
    assert ctx.health._state.snapshot()["errors"] == 5


def test_a_different_incident_is_not_swallowed_by_the_throttle() -> None:
    """Пара к дросселю: пара (тип, контекст) другая — инцидент едет."""
    ctx, svc = _ctx()
    ctx.health.report_error(RuntimeError("первая"))
    ctx.health.report_error(ValueError("вторая"))
    kinds = [etype for etype, _msg, _ctx in svc.errors.incidents]
    assert kinds == ["RuntimeError", "ValueError"], kinds


def test_no_error_plane_is_a_legal_state_not_a_crash() -> None:
    """Отсутствие плоскости не имеет права стать вторым исключением поверх первого."""
    ctx, svc = _ctx(with_error_plane=False)
    ctx.health.report_error(RuntimeError("некуда писать"))
    assert any("некуда писать" in line for line in svc.logs.records)
