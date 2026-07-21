# -*- coding: utf-8 -*-
"""Юнит-тесты примитива HealthState / HealthReporter / publish_health (Ф2 Task 2.1).

Проверяют: честный счётчик, дросселирование логов, запись last_error, статусы,
throttle, откат в лог-only, снапшот-контракт, take_dirty (rate-limit на публикацию)
и leaf-wise публикацию через фейковый proxy.
"""

from __future__ import annotations

import threading

import pytest

from multiprocess_framework.modules.process_module.health import (
    HEALTH_FIELDS,
    HealthReporter,
    HealthState,
    HealthStatus,
    get_or_create_health_state,
    health_path,
    publish_health,
)
from multiprocess_framework.modules.process_module.health.schema import LastErrorKey


class _Clock:
    """Управляемое время для детерминизма throttle-тестов."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class _FakeProxy:
    """Фейковый StateProxy: копит set(path, value) для проверки публикации."""

    def __init__(self) -> None:
        self.sets: list[tuple[str, object]] = []

    def set(self, path: str, value: object) -> None:
        self.sets.append((path, value))


# --- счётчик / last_error ---------------------------------------------------


def test_report_error_increments_counter() -> None:
    hs = HealthState()
    hs.report_error(ValueError("boom"), context="site")
    hs.report_error(ValueError("boom2"), context="site")
    assert hs.error_count == 2


def test_report_error_records_last_error() -> None:
    clock = _Clock()
    hs = HealthState(clock=clock)
    hs.report_error(ValueError("boom"), context="camera.grab")
    snap = hs.snapshot()
    last = snap["last_error"]
    assert last[LastErrorKey.TYPE] == "ValueError"
    assert last[LastErrorKey.MESSAGE] == "boom"
    assert last[LastErrorKey.CONTEXT] == "camera.grab"
    assert last[LastErrorKey.TS] == 1000.0


def test_long_message_truncated() -> None:
    hs = HealthState()
    hs.report_error(RuntimeError("x" * 5000), context="c")
    assert len(hs.snapshot()["last_error"]["message"]) == 500


# --- throttle логирования ---------------------------------------------------


def test_throttle_suppresses_repeated_logs_but_not_counter() -> None:
    clock = _Clock()
    logs: list[str] = []
    hs = HealthState(log=logs.append, clock=clock)

    # Первый лог проходит.
    hs.report_error(ValueError("e"), context="s", throttle=5.0)
    # Повтор той же (тип, context) в окне throttle → лог подавлен, счётчик растёт.
    hs.report_error(ValueError("e"), context="s", throttle=5.0)
    assert len(logs) == 1
    assert hs.error_count == 2

    # За окном throttle — снова логируем.
    clock.t += 6.0
    hs.report_error(ValueError("e"), context="s", throttle=5.0)
    assert len(logs) == 2
    assert hs.error_count == 3


def test_throttle_is_per_key() -> None:
    clock = _Clock()
    logs: list[str] = []
    hs = HealthState(log=logs.append, clock=clock)
    # Разные context → разные ключи → оба логируются даже в одном окне.
    hs.report_error(ValueError("e"), context="a", throttle=100.0)
    hs.report_error(ValueError("e"), context="b", throttle=100.0)
    assert len(logs) == 2


# --- статусы ----------------------------------------------------------------


def test_set_status_and_degraded() -> None:
    hs = HealthState()
    assert hs.status == HealthStatus.OK
    hs.degraded("neighbor down")
    snap = hs.snapshot()
    assert snap["status"] == "degraded"
    assert snap["degraded_reason"] == "neighbor down"
    assert hs.status == HealthStatus.DEGRADED


def test_status_recovery_clears_reason() -> None:
    hs = HealthState()
    hs.degraded("x")
    hs.ok()
    snap = hs.snapshot()
    assert snap["status"] == "ok"
    assert snap["degraded_reason"] is None


def test_set_status_accepts_string() -> None:
    hs = HealthState()
    hs.set_status("failed", reason="give-up")
    assert hs.status == HealthStatus.FAILED


def test_set_status_invalid_raises() -> None:
    hs = HealthState()
    with pytest.raises(ValueError):
        hs.set_status("nonsense")


# --- take_dirty / snapshot-контракт ----------------------------------------


def test_snapshot_has_exact_contract_keys() -> None:
    hs = HealthState()
    snap = hs.snapshot()
    assert set(snap.keys()) == set(HEALTH_FIELDS)


def test_take_dirty_returns_once_then_none() -> None:
    hs = HealthState()
    # Стартовый снапшот грязный (публикуем начальный ok один раз).
    first = hs.take_dirty()
    assert first is not None
    assert first["status"] == "ok"
    assert hs.take_dirty() is None  # без изменений — нечего публиковать

    hs.report_error(ValueError("e"), context="s")
    dirty = hs.take_dirty()
    assert dirty is not None
    assert dirty["errors"] == 1
    assert hs.take_dirty() is None


# --- лог-only откат ---------------------------------------------------------


def test_log_only_logs_but_never_publishes() -> None:
    logs: list[str] = []
    hs = HealthState(log=logs.append, log_only=True)
    # Сбросить стартовый dirty (в лог-only он не должен подниматься повторно).
    hs.take_dirty()

    hs.report_error(ValueError("boom"), context="s")
    hs.degraded("down")

    # Счётчик честный, лог идёт, но state-дерево не трогается (dirty не поднят).
    assert hs.error_count == 1
    assert logs  # что-то залогировано
    assert hs.take_dirty() is None


def test_log_only_env(monkeypatch) -> None:
    monkeypatch.setenv("INSPECTOR_HEALTH_LOG_ONLY", "1")
    hs = HealthState()
    assert hs.log_only is True


# --- publish_health (leaf-wise через proxy) ---------------------------------


def test_publish_health_sets_all_leaves() -> None:
    proxy = _FakeProxy()
    hs = HealthState()
    hs.report_error(ValueError("boom"), context="site")

    published = publish_health(hs, proxy, "cam0")
    assert published is True

    paths = {p for p, _ in proxy.sets}
    for field in HEALTH_FIELDS:
        assert health_path("cam0", field) in paths
    # errors-лист несёт число.
    errors_val = dict(proxy.sets)[health_path("cam0", "errors")]
    assert errors_val == 1


def test_publish_health_noop_when_clean() -> None:
    proxy = _FakeProxy()
    hs = HealthState()
    assert publish_health(hs, proxy, "cam0") is True  # стартовый ok
    proxy.sets.clear()
    assert publish_health(hs, proxy, "cam0") is False  # нечего публиковать
    assert proxy.sets == []


def test_publish_health_guards() -> None:
    hs = HealthState()
    assert publish_health(hs, None, "cam0") is False
    assert publish_health(None, _FakeProxy(), "cam0") is False
    assert publish_health(hs, _FakeProxy(), "") is False


# --- C-2: mark_dirty / ретрай публикации при провале proxy.set --------------


class _FailingThenOkProxy:
    """Фейковый proxy: пока ``fail`` True — каждый set() бросает; после "починки"
    (``fail = False``) — работает нормально и копит вызовы, как _FakeProxy."""

    def __init__(self) -> None:
        self.sets: list[tuple[str, object]] = []
        self.fail = True

    def set(self, path: str, value: object) -> None:
        if self.fail:
            raise RuntimeError("proxy недоступен")
        self.sets.append((path, value))


def test_mark_dirty_forces_dirty_true() -> None:
    """mark_dirty() поднимает _dirty напрямую — следующий take_dirty() отдаст снапшот."""
    hs = HealthState()
    hs.take_dirty()  # снять стартовый dirty
    assert hs.take_dirty() is None  # без изменений — нечего публиковать

    hs.mark_dirty()
    assert hs.take_dirty() is not None


def test_publish_health_retries_after_proxy_failure() -> None:
    """C-2: провал ВСЕХ proxy.set() не должен терять health-снапшот безвозвратно.

    take_dirty() сбрасывает _dirty ДО того, как снапшот реально ушёл в
    state-дерево. Без mark_dirty() при провале следующий такт heartbeat увидел
    бы take_dirty() -> None ("изменений нет"), хотя переход в degraded так и не
    опубликовался — дерево навсегда осталось бы на последнем удачном ok.
    """
    proxy = _FailingThenOkProxy()
    hs = HealthState()
    hs.take_dirty()  # снять стартовый dirty снапшот, начинаем с чистого состояния

    hs.degraded("boom")  # поднимает dirty

    # Первая публикация: proxy сломан — ни один set() не проходит.
    published = publish_health(hs, proxy, "cam0")
    assert published is False
    assert proxy.sets == []

    # proxy "починили" — следующий такт heartbeat должен забрать снапшот повторно,
    # а не молчать (dirty не должен быть потерян провалом первой публикации).
    proxy.fail = False
    published_retry = publish_health(hs, proxy, "cam0")
    assert published_retry is True

    paths = {p for p, _ in proxy.sets}
    assert health_path("cam0", "status") in paths
    status_val = dict(proxy.sets)[health_path("cam0", "status")]
    assert status_val == "degraded"


# --- get_or_create_health_state (привязка к процессу) -----------------------


class _FakeServices:
    def __init__(self) -> None:
        self.name = "cam0"
        self.logged: list[str] = []

    def log_warning(self, msg, **kw) -> None:
        self.logged.append(msg)


def test_get_or_create_is_idempotent_per_process() -> None:
    svc = _FakeServices()
    a = get_or_create_health_state(svc)
    b = get_or_create_health_state(svc)
    assert a is b
    assert svc._health_state is a


def test_reporter_shares_process_state() -> None:
    svc = _FakeServices()
    state = get_or_create_health_state(svc)
    r1 = HealthReporter(state, source="pluginA")
    r2 = HealthReporter(state, source="pluginB")
    r1.report_error(ValueError("e"))
    r2.report_error(ValueError("e"))
    # Оба reporter'а бьют в один агрегат процесса.
    assert state.error_count == 2
    # default source используется как context, если не передан явный.
    assert state.snapshot()["last_error"]["context"] == "pluginB"


# --- thread-safety smoke ----------------------------------------------------


def test_concurrent_report_error_counter_consistent() -> None:
    hs = HealthState()

    def worker() -> None:
        for _ in range(200):
            hs.report_error(ValueError("e"), context="t", throttle=0.0)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert hs.error_count == 8 * 200
