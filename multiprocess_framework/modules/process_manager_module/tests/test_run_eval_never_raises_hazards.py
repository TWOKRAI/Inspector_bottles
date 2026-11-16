# -*- coding: utf-8 -*-
"""Опасности автора: оценка и итог не бросают (Q2/Q3/A6) при порядке и параллелизме событий.

Приёмку пишет слепой ``test_run_eval_never_raises.py``; здесь — то, что видит автор правки ``_run_ready``:

* сбойный такт и отказанный START между ``apply`` и ``settled`` не портят итог ``settled``;
* два ``settled`` подряд из разных потоков: принят первый, второй — no-op; ``_run_ready`` всегда совпадает с принятым;
* ``ack`` параллельно с тактом (здоровая и бросающая оценка): состояние и ``_run_ready`` согласованы, ничего не бросает.

Ожидаемые значения — литералы. Параллельные вызовы идут в daemon-потоках с join-дедлайном.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

import pytest

from ..process.process_manager_process import ProcessManagerProcess
from .test_run_ack import _to_fault
from .test_run_commands import beat, make_readiness_pm
from .test_run_eval_never_raises import _SECRET, _call, _failing_tick
from .test_run_stop import _DEADLINE_S, _Rig

_ROUNDS = 30


class _SwitchableEval:
    """Подмена ``_evaluate_run_readiness``: бросает, пока ``broken``; иначе зовёт настоящую оценку."""

    def __init__(self, pm: ProcessManagerProcess) -> None:
        self.broken = False
        self._original = pm._evaluate_run_readiness

    def __call__(self, *, admission: bool = False, track_restart: bool = False) -> Any:
        if self.broken:
            raise RuntimeError(_SECRET)
        return self._original(admission=admission, track_restart=track_restart)


def _install_switch(pm: ProcessManagerProcess, monkeypatch: pytest.MonkeyPatch) -> _SwitchableEval:
    switch = _SwitchableEval(pm)
    monkeypatch.setattr(pm, "_evaluate_run_readiness", switch)
    return switch


def _run_in_threads(jobs: list[Callable[[], Any]]) -> list[BaseException]:
    """Запустить ``jobs`` одновременно (барьер), дождаться с дедлайном; вернуть исключения потоков."""
    barrier = threading.Barrier(len(jobs))
    errors: list[BaseException] = []

    def wrap(job: Callable[[], Any]) -> Callable[[], None]:
        def run() -> None:
            try:
                barrier.wait(_DEADLINE_S)
                job()
            except BaseException as exc:  # noqa: BLE001 — собираем для ассерта «не бросает»
                errors.append(exc)

        return run

    threads = [threading.Thread(target=wrap(job), daemon=True, name=f"eval-hazard-{i}") for i, job in enumerate(jobs)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(_DEADLINE_S)
    assert not any(th.is_alive() for th in threads), "поток завис дольше дедлайна"
    return errors


@pytest.fixture
def rig_factory():
    rigs: list[_Rig] = []

    def make(*args: Any, **kwargs: Any) -> _Rig:
        rig = _Rig(*args, **kwargs)
        rigs.append(rig)
        return rig

    yield make
    for rig in rigs:
        rig.close()


# --------------------------------------------------------------------------- #
# Сбойный такт и отказанный START между apply и settled
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_failed_tick_and_refused_start_between_apply_and_settled(monkeypatch: pytest.MonkeyPatch) -> None:
    """``apply`` -> ``booting``; сбойный такт и START при бросающей оценке не бросают и состояние ``booting`` не
    меняют; затем здоровый ``settled`` -> ``ready`` с ``_run_ready is True``, один сбойный такт -> всё ещё ``ready``."""
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    switch = _install_switch(pm, monkeypatch)
    _failing_tick(monitor)  # cam молчит
    assert pm._run_ready is False
    pm._run_apply("apply")
    assert pm._run_state == "booting"

    switch.broken = True
    _failing_tick(monitor)
    reply = _call(pm._cmd_system_run_start, "_cmd_system_run_start")

    assert pm._run_state == "booting"
    assert reply["success"] is False and reply["state"] == "booting", reply
    assert pm._run_ready is False
    assert _SECRET not in repr(reply)  # в логе текст есть: пишет такт (_evaluation_failed), не START

    switch.broken = False
    beat(monitor, "cam")
    pm._settle_run_state()

    assert pm._run_state == "ready"
    assert pm._run_ready is True
    switch.broken = True
    _failing_tick(monitor)
    assert pm._run_state == "ready", f"одиночный сбойный такт после settled дал {pm._run_state!r}"


@pytest.mark.timeout(60)
def test_settle_with_broken_eval_refuses_and_next_tick_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    """``settled`` при бросающей оценке -> ``not_ready``, ``_run_ready is False``; здоровый такт -> ``ready``."""
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    switch = _install_switch(pm, monkeypatch)
    beat(monitor, "cam")
    pm._run_apply("apply")
    switch.broken = True

    _call(pm._settle_run_state, "_settle_run_state")

    assert pm._run_state == "not_ready"
    assert pm._run_ready is False
    switch.broken = False
    beat(monitor, "cam")
    _failing_tick(monitor)
    assert pm._run_state == "ready"
    assert pm._run_ready is True


# --------------------------------------------------------------------------- #
# Два settled подряд из разных потоков
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_concurrent_settled_run_ready_matches_accepted_outcome() -> None:
    """Два ``settled`` (``ready=True`` и ``ready=False``) одновременно из двух потоков после ``apply``: принимается
    ровно один, второй no-op. ``_run_ready`` всегда совпадает с принятым итогом: ``ready`` <=> True, ``not_ready``
    <=> False. Без условия ``new is not prev`` проигравший оставил бы ``_run_ready`` от второго события."""
    pm, _monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    for _ in range(_ROUNDS):
        pm._run_apply("apply")
        assert pm._run_state == "booting"

        errors = _run_in_threads(
            [
                lambda: pm._run_apply("settled", ready=True),
                lambda: pm._run_apply("settled", ready=False),
            ]
        )

        assert errors == [], errors
        state = pm._run_state.value
        assert state in ("ready", "not_ready"), state
        assert pm._run_ready is (state == "ready"), f"состояние {state!r}, _run_ready {pm._run_ready!r}"


@pytest.mark.timeout(120)
def test_concurrent_settle_and_failed_tick_never_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_settle_run_state`` из одного потока и сбойный такт монитора из другого: ничего не бросает, состояние
    допустимо (``booting`` исключён: итог ``settled`` случается всегда), ``_run_ready`` — bool."""
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    switch = _install_switch(pm, monkeypatch)
    beat(monitor, "cam")
    for _ in range(_ROUNDS):
        pm._run_apply("apply")
        switch.broken = True

        def tick() -> None:
            with monitor._iteration_lock:
                monitor._run_iteration()

        errors = _run_in_threads([pm._settle_run_state, tick])

        assert errors == [], errors
        assert pm._run_state in ("ready", "not_ready"), pm._run_state
        assert isinstance(pm._run_ready, bool)


# --------------------------------------------------------------------------- #
# ack при параллельном такте
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_ack_with_parallel_healthy_tick_ends_ready(rig_factory) -> None:
    """``ack`` и здоровый такт одновременно из ``fault`` с завершённой остановкой: в любом порядке итог ``ready``,
    ``_run_ready is True`` (такт в ``fault`` состояние не меняет, ``ack`` после него — ``ready``)."""
    for _ in range(3):
        rig = rig_factory()
        _to_fault(rig)
        rig.sim.set("cam", ready=True, reasons=[])
        rig.sim.beat_now()
        replies: list[dict] = []

        errors = _run_in_threads([lambda: replies.append(rig.pm._cmd_system_run_ack()), rig.tick])

        assert errors == [], errors
        assert replies == [{"success": True, "state": "ready", "error": None}], replies
        assert rig.pm._run_state == "ready"
        assert rig.pm._run_ready is True


@pytest.mark.timeout(120)
def test_ack_with_parallel_failed_tick_ends_not_ready(rig_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """``ack`` и сбойный такт одновременно (оценка бросает): ничего не бросает; итог ``not_ready``,
    ``_run_ready is False`` в любом порядке."""
    for _ in range(3):
        rig = rig_factory()
        _to_fault(rig)
        pm = rig.pm
        with monkeypatch.context() as scope:
            switch = _install_switch(pm, scope)
            switch.broken = True
            replies: list[dict] = []

            def tick(monitor: Any = rig.monitor) -> None:
                with monitor._iteration_lock:
                    monitor._run_iteration()

            errors = _run_in_threads([lambda: replies.append(pm._cmd_system_run_ack()), tick])

        assert errors == [], errors
        assert replies == [{"success": True, "state": "not_ready", "error": None}], replies
        assert pm._run_state == "not_ready"
        assert pm._run_ready is False


# --------------------------------------------------------------------------- #
# Правки по ревью: сбой чтения конфига на путях остановки и срока молчания
# --------------------------------------------------------------------------- #


def _break_config_keys(pm: ProcessManagerProcess, errors_by_key: dict[str, BaseException | None]) -> None:
    """``get_config`` бросает заданное исключение на ключах из ``errors_by_key``; остальные ключи — как у фейка."""
    original = pm.get_config

    def bad(key: str, default: Any = None) -> Any:
        exc = errors_by_key.get(key)
        if exc is not None:
            raise exc
        return original(key, default)

    pm.get_config = bad


@pytest.mark.timeout(60)
def test_fault_stop_completes_when_stop_timeout_config_raises(rig_factory) -> None:
    """``get_config("run_stop_timeout_s")`` бросает: поток остановки в аварии не умирает, ``_fault_stop_done``
    становится True за дедлайн, ``ack`` не отвечает ``fault_stopping``."""
    rig = rig_factory()
    pm = rig.pm
    _break_config_keys(pm, {"run_stop_timeout_s": RuntimeError("config handler broken")})

    _to_fault(rig, wait_done=False)

    deadline = time.monotonic() + _DEADLINE_S
    while time.monotonic() < deadline and not pm._cmd_system_run_status()["ack_allowed"]:
        time.sleep(0.02)
    assert pm._cmd_system_run_status()["ack_allowed"] is True, "остановка в аварии не завершилась"
    reply = _call(pm._cmd_system_run_ack, "_cmd_system_run_ack")
    assert reply["error"] != "fault_stopping", reply
    assert reply["error"] is None and reply["success"] is True, reply


def _stale_warnings(pm: ProcessManagerProcess) -> list[str]:
    return [" ".join(str(a) for a in c.args) for c in pm._log_warning.call_args_list]


@pytest.mark.timeout(60)
def test_stale_config_failure_warns_once_per_exception_type() -> None:
    """Два вызова ``_run_stale_s`` при бросающем ``get_config`` (один тип исключения на обоих ключах): одна строка
    WARNING с типом исключения и именем ключа, без текста исключения; срок молчания — умолчание 15.0 с."""
    pm, _monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    _break_config_keys(
        pm,
        {
            "heartbeat_interval": RuntimeError("secret-config-text"),
            "heartbeat_interval_sec": RuntimeError("secret-config-text"),
        },
    )
    pm._log_warning.reset_mock()

    first = pm._run_stale_s()
    second = pm._run_stale_s()

    assert first == second == pytest.approx(15.0)
    lines = _stale_warnings(pm)
    assert len(lines) == 1, lines
    assert "RuntimeError" in lines[0] and "heartbeat_interval" in lines[0], lines
    assert "secret-config-text" not in lines[0], lines


@pytest.mark.timeout(60)
def test_stale_config_failure_warns_again_for_new_exception_type() -> None:
    """Новый тип исключения — новая строка WARNING (один раз на тип): ``RuntimeError`` на одном ключе и
    ``OverflowError`` (``float(10**400)``) на другом, два вызова -> две строки, по одной на тип."""
    pm, _monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    _break_config_keys(pm, {"heartbeat_interval": RuntimeError("secret-config-text")})
    pm.update_config("heartbeat_interval_sec", 10**400)
    pm._log_warning.reset_mock()

    pm._run_stale_s()
    pm._run_stale_s()

    lines = _stale_warnings(pm)
    assert len(lines) == 2, lines
    assert "RuntimeError" in lines[0] and "OverflowError" in lines[1], lines
    assert all("secret-config-text" not in line for line in lines), lines


# --------------------------------------------------------------------------- #
# Правки по Opus-ревью: отказанный из-за сбоя оценки START не оставляет устаревший _run_ready
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_start_refused_by_eval_failure_keeps_not_ready_after_failed_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    """START из ``ready`` при бросающей оценке -> отказ ``not_ready`` (смена состояния). Следующий сбойный такт
    (серия короче срока, ``ready=None``) состояние не возвращает: остаётся ``not_ready``, ``start_allowed`` False,
    повторный START снова отказан ``not_ready``. Без записи ``_run_ready`` на ``start`` такт брал бы устаревшее True."""
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    switch = _install_switch(pm, monkeypatch)
    beat(monitor, "cam")
    _failing_tick(monitor)
    assert pm._run_state == "ready"
    switch.broken = True

    first = _call(pm._cmd_system_run_start, "_cmd_system_run_start")

    assert first["success"] is False and first["state"] == "not_ready" and first["error"] == "not_ready", first
    _failing_tick(monitor)
    assert pm._run_state == "not_ready", f"сбойный такт после отказа START дал {pm._run_state!r}"
    assert pm._cmd_system_run_status()["start_allowed"] is False
    second = _call(pm._cmd_system_run_start, "_cmd_system_run_start")
    assert second["success"] is False and second["state"] == "not_ready" and second["error"] == "not_ready", second
