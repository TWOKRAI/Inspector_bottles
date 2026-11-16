# -*- coding: utf-8 -*-
"""Task 1.11 (system-run-state) — слепые приёмочные тесты: сбой оценки готовности не бросает наружу.

Написано ДО реализации по критериям брифа (``plans/**``, ``docs/reviews|reports|handoffs/**``, ``DECISIONS.md``
не читались). Ожидаемые значения — литералы из критериев.

Требование: START, ``ack`` и такт при СБОЕ оценки (``_evaluate_run_readiness`` бросает) отвечают отказом/итогом с кодом
и причиной ``failure`` «оценка готовности не удалась», а не исключением; текст исключения (``eval broken``) наружу —
ни в ответ, ни в лог — не уходит; ``_run_ready`` не остаётся устаревшим после принятых ``settled``/``ack``, поэтому
одиночный сбойный такт сразу после них не переводит в ``fault``.

Какие критерии на ТЕКУЩЕМ коде ожидаются КРАСНЫМИ, какие — охранные (зелёные допустимы):

    1  START из ready при бросающей оценке             КРАСНЫЙ   test_start_eval_failure_refuses_not_ready
    2  ack из fault при бросающей оценке               КРАСНЫЙ   test_ack_eval_failure_accepts_not_ready_with_reason
    3  settled не оставляет устаревший _run_ready      КРАСНЫЙ   test_single_failed_tick_after_settle_does_not_fault
       (+ предусловие литералом и контроль серии)                test_settle_refreshes_run_ready (КРАСНЫЙ)
                                                                 test_long_failed_series_after_settle_faults (контроль)
    4  _evaluation_failed при негодном get_config      КРАСНЫЙ   test_evaluation_failed_*_bad_config*, test_tick_*
    5  отказанная команда _run_ready не меняет         ОХРАННЫЙ  test_refused_start_keeps_run_ready
    6  тот же START через настоящий диспетчер          КРАСНЫЙ   test_dispatcher_start_eval_failure_reply
    7  ack обновляет _run_ready                        КРАСНЫЙ   test_ack_refreshes_run_ready,
                                                                 test_single_failed_tick_after_ack_stays_ready
    8  no-op settled в running _run_ready не меняет    ОХРАННЫЙ  test_noop_settled_keeps_run_ready_in_running

Допущения тестера (ASSUMPTION; список — в отчёте):
  * подмена оценки — функция только с keyword-аргументами ``admission=`` / ``track_restart=`` на экземпляре PM;
  * «такт» — ``monitor._run_iteration()`` под ``monitor._iteration_lock`` (хелпер ``tick`` из test_run_commands падает
    на ERROR-логе, а при сбое оценки ERROR — ожидаем);
  * «лог» = вызовы ``_log_info`` / ``_log_warning`` / ``_log_error`` фейка ``make_pm`` + ``logger_manager``;
  * после ``_run_apply("apply")`` + heartbeat + ``_settle_run_state()`` состояние — ``ready`` (иначе START не пройдёт).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, NoReturn

import pytest

from ..core.stop_budget import stop_budget
from ..process.process_manager_process import ProcessManagerProcess
from .test_run_ack import _to_fault
from .test_run_commands import beat, make_readiness_pm
from .test_run_stop import _DEADLINE_S, _Rig, _bounded

_REASON_TEXT = "оценка готовности не удалась"
_LOG_LINE = "readiness: оценка готовности не удалась (RuntimeError)"
_SECRET = "eval broken"


# --------------------------------------------------------------------------- #
# Хелперы
# --------------------------------------------------------------------------- #


def _broken(*, admission: bool = False, track_restart: bool = False) -> NoReturn:
    """Подмена ``_evaluate_run_readiness``: принимает только keyword-аргументы, всегда бросает."""
    raise RuntimeError(_SECRET)


def _break_eval(pm: ProcessManagerProcess, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pm, "_evaluate_run_readiness", _broken)


def _call(fn: Callable[[], Any], what: str) -> Any:
    """Вызов в daemon-потоке с дедлайном; исключение метода — упавший ассерт «метод бросил», не ошибка стенда."""
    try:
        return _bounded(fn, _DEADLINE_S)
    except AssertionError:
        raise
    except BaseException as exc:  # noqa: BLE001 — критерий «не бросает»
        pytest.fail(f"{what} бросил {type(exc).__name__}: {exc}")


def _failing_tick(monitor: Any) -> None:
    """Один такт монитора под ``_iteration_lock`` (не ``tick()``: тот падает на ERROR-логе)."""

    def run() -> None:
        with monitor._iteration_lock:
            monitor._run_iteration()

    _call(run, "такт монитора")


def _log_text(pm: Any) -> str:
    """Весь текст логов PM-фейка: аргументы вызовов ``_log_*`` и ``logger_manager``."""
    parts: list[str] = []
    for name in ("_log_info", "_log_warning", "_log_error"):
        for c in getattr(pm, name).call_args_list:
            parts.append(" ".join(str(a) for a in c.args) + repr(c.kwargs))
    parts.append(repr(pm.logger_manager.mock_calls))
    return "\n".join(parts)


def _failure_reasons(reasons: list[dict]) -> list[tuple[str, str]]:
    return [(r["severity"], r["reason"]) for r in reasons]


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


def _healthy_running_pm() -> tuple[ProcessManagerProcess, Any]:
    """Здоровый ``cam`` отчитался -> такт -> START -> ``running``; ``_run_ready is True``."""
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    beat(monitor, "cam")
    _failing_tick(monitor)
    assert pm._run_state == "ready"
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}
    return pm, monitor


def _settled_pm_after_silent_tick() -> tuple[ProcessManagerProcess, Any]:
    """Предусловие критерия 3: такт без ``beat`` -> ``_run_ready is False``; ``apply`` + ``beat`` + ``settled``."""
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    _failing_tick(monitor)  # cam молчит
    assert pm._run_ready is False, "стенд: такт без beat должен дать _run_ready False"
    pm._run_apply("apply")
    beat(monitor, "cam")
    pm._settle_run_state()
    return pm, monitor


# --------------------------------------------------------------------------- #
# 1. START из ready, оценка бросает
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_start_eval_failure_refuses_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """Критерий 1 (КРАСНЫЙ на текущем коде): START из ``ready`` при бросающей оценке не бросает, а отказывает
    ``not_ready`` с ровно одной причиной ``failure`` «оценка готовности не удалась»; текст исключения не утекает."""
    pm, _monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    assert pm._run_state == "ready"
    _break_eval(pm, monkeypatch)

    reply = _call(pm._cmd_system_run_start, "_cmd_system_run_start")

    assert {k: v for k, v in reply.items() if k != "reasons"} == {
        "success": False,
        "state": "not_ready",
        "error": "not_ready",
    }, reply
    assert _failure_reasons(reply["reasons"]) == [("failure", _REASON_TEXT)], reply
    assert _SECRET not in repr(reply), reply
    assert _SECRET not in _log_text(pm), _log_text(pm)
    assert _LOG_LINE in _log_text(pm), _log_text(pm)
    assert pm._run_event.is_set() is False


# --------------------------------------------------------------------------- #
# 2. ack из fault, оценка бросает
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_ack_eval_failure_accepts_not_ready_with_reason(rig_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Критерий 2 (КРАСНЫЙ): ``ack`` из ``fault`` с завершённой остановкой при бросающей оценке не бросает;
    ответ принят, состояние ``not_ready``; статус несёт причину сбоя и ``acknowledged_at``; текста исключения нет."""
    rig = rig_factory()
    _to_fault(rig)
    pm = rig.pm
    _break_eval(pm, monkeypatch)

    reply = _call(pm._cmd_system_run_ack, "_cmd_system_run_ack")

    assert reply == {"success": True, "state": "not_ready", "error": None}, reply
    status = pm._cmd_system_run_status()
    assert _failure_reasons(status["reasons"]) == [("failure", _REASON_TEXT)], status
    assert status["last_fault"] is not None, status
    assert status["last_fault"]["acknowledged_at"] is not None, status
    assert _SECRET not in repr(reply) + repr(status), (reply, status)
    assert _SECRET not in _log_text(pm), _log_text(pm)


# --------------------------------------------------------------------------- #
# 3. settled не оставляет устаревший _run_ready
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_single_failed_tick_after_settle_does_not_fault(monkeypatch: pytest.MonkeyPatch) -> None:
    """Критерий 3 (КРАСНЫЙ): такт без beat (``_run_ready False``) -> apply -> beat -> settled -> START -> ``running``;
    ОДИН сбойный такт не переводит в ``fault`` (оценка settled свежая, не устаревшая False)."""
    pm, monitor = _settled_pm_after_silent_tick()
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}
    _break_eval(pm, monkeypatch)

    _failing_tick(monitor)

    assert pm._run_state == "running", f"одиночный сбойный такт дал {pm._run_state!r}"


@pytest.mark.timeout(60)
def test_settle_refreshes_run_ready() -> None:
    """Критерий 3, предусловие литералом (КРАСНЫЙ): после принятого ``settled`` со здоровой оценкой
    ``_run_ready is True`` (до этого такт без beat оставил False)."""
    pm, _monitor = _settled_pm_after_silent_tick()

    assert pm._run_ready is True


@pytest.mark.timeout(60)
def test_long_failed_series_after_settle_faults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Критерий 3, контроль: серия сбоев ДОЛЬШЕ срока молчания (0.3 с = 3 x 0.1) -> ``fault``. Защищает от
    «починки» глухим игнорированием сбоев."""
    pm, monitor = _healthy_running_pm()
    pm.update_config("heartbeat_interval", 0.1)
    pm.update_config("heartbeat_interval_sec", 0.1)
    assert pm._run_stale_s() == pytest.approx(0.3)
    _break_eval(pm, monkeypatch)

    _failing_tick(monitor)  # начало серии
    assert pm._run_state == "running"
    time.sleep(0.4)
    _failing_tick(monitor)
    _failing_tick(monitor)

    assert pm._run_state == "fault", f"серия дольше срока молчания дала {pm._run_state!r}"


# --------------------------------------------------------------------------- #
# 4. _evaluation_failed при негодном get_config
# --------------------------------------------------------------------------- #


def _break_get_config(pm: ProcessManagerProcess) -> None:
    """``get_config`` бросает на ключах интервала heartbeat; остальные ключи — как у фейка."""
    original = pm.get_config

    def bad(key: str, default: Any = None) -> Any:
        if key in ("heartbeat_interval", "heartbeat_interval_sec"):
            raise RuntimeError("config broken")
        return original(key, default)

    pm.get_config = bad


@pytest.mark.timeout(60)
def test_evaluation_failed_bad_config_short_series_keeps_ready() -> None:
    """Критерий 4 (КРАСНЫЙ): серия 10 с, ``get_config`` бросает -> метод не бросает, ``(None, [причина])``
    (срок молчания при негодном конфиге 15.0 с — серия ещё не истекла)."""
    pm, _monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    _break_get_config(pm)
    pm._eval_fail_since = time.monotonic() - 10.0

    ready, reasons = _call(lambda: pm._evaluation_failed(RuntimeError(_SECRET)), "_evaluation_failed")

    assert ready is None
    assert _failure_reasons(reasons) == [("failure", _REASON_TEXT)], reasons


@pytest.mark.timeout(60)
def test_evaluation_failed_bad_config_long_series_not_ready() -> None:
    """Критерий 4 (КРАСНЫЙ): серия 16 с > 15.0 с при негодном конфиге -> ``(False, [причина])``."""
    pm, _monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    _break_get_config(pm)
    pm._eval_fail_since = time.monotonic() - 16.0

    ready, reasons = _call(lambda: pm._evaluation_failed(RuntimeError(_SECRET)), "_evaluation_failed")

    assert ready is False
    assert _failure_reasons(reasons) == [("failure", _REASON_TEXT)], reasons


@pytest.mark.timeout(60)
def test_tick_with_bad_config_does_not_lose_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    """Критерий 4 (КРАСНЫЙ): полный такт ``_run_readiness_tick`` при бросающих оценке и ``get_config`` не теряется:
    не бросает, ``reasons`` статуса не пуст."""
    pm, _monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    _break_eval(pm, monkeypatch)
    _break_get_config(pm)

    _call(pm._run_readiness_tick, "_run_readiness_tick")

    reasons = pm._cmd_system_run_status()["reasons"]
    assert reasons != [], "причины такта потеряны"
    assert _failure_reasons(reasons) == [("failure", _REASON_TEXT)], reasons


# --------------------------------------------------------------------------- #
# 5. Охранный: отказанная команда _run_ready не меняет
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_refused_start_keeps_run_ready(rig_factory) -> None:
    """Критерий 5 (ОХРАННЫЙ, зелёный допустим): START из ``fault`` отказан ``fault_unacknowledged``; при
    ``_run_ready is False`` и свежем beat ``_run_ready`` остаётся False (отказ не освежает флаг)."""
    rig = rig_factory()
    _to_fault(rig)
    pm = rig.pm
    assert pm._run_ready is False
    rig.sim.set("cam", ready=True, reasons=[])
    rig.sim.beat_now()

    reply = _call(pm._cmd_system_run_start, "_cmd_system_run_start")

    assert reply["success"] is False and reply["error"] == "fault_unacknowledged", reply
    assert pm._run_ready is False


# --------------------------------------------------------------------------- #
# 6. Через настоящий PM и диспетчер
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def real_pm():
    """Настоящий PM после ``initialize()`` (как в test_lifecycle_command_classes); закрытие — с дедлайном."""
    pm = ProcessManagerProcess(config={"shutdown_timeout": 5.0})
    pm.attach_stop_budget(stop_budget(1.0))
    box: dict[str, Any] = {}

    def init() -> None:
        box["ok"] = pm.initialize()

    th = threading.Thread(target=init, daemon=True, name="eval-never-raises-pm-initialize")
    th.start()
    th.join(60.0)
    assert not th.is_alive() and box.get("ok") is True, f"PM.initialize() не удался: {box}"
    try:
        yield pm
    finally:
        closer = threading.Thread(target=pm.shutdown, daemon=True, name="eval-never-raises-pm-shutdown")
        closer.start()
        closer.join(30.0)


@pytest.mark.timeout(120)
def test_dispatcher_start_eval_failure_reply(real_pm: ProcessManagerProcess, monkeypatch: pytest.MonkeyPatch) -> None:
    """Критерий 6 (КРАСНЫЙ): ``system.run.start`` через ``command_manager.handle_command`` при бросающей оценке
    возвращает отказ ``not_ready`` с одной причиной ``failure``, а не ``{'status': 'error', 'reason': 'Dispatch failed:
    eval broken'}``; текста исключения в ответе нет."""
    assert real_pm._run_state == "ready", f"предусловие: состояние {real_pm._run_state!r}"
    _break_eval(real_pm, monkeypatch)

    reply = _call(
        lambda: real_pm.command_manager.handle_command({"command": "system.run.start", "data": {}}),
        "handle_command(system.run.start)",
    )

    assert isinstance(reply, dict), reply
    assert {k: v for k, v in reply.items() if k != "reasons"} == {
        "success": False,
        "state": "not_ready",
        "error": "not_ready",
    }, reply
    assert _failure_reasons(reply["reasons"]) == [("failure", _REASON_TEXT)], reply
    assert _SECRET not in repr(reply), reply


# --------------------------------------------------------------------------- #
# 7. ack обновляет _run_ready
# --------------------------------------------------------------------------- #


def _fault_then_recover_and_ack(rig: _Rig) -> None:
    """``_to_fault`` -> ``_run_ready is False`` -> ``cam`` снова готов, beat -> ``ack`` -> ``ready``."""
    _to_fault(rig)
    pm = rig.pm
    assert pm._run_ready is False, "стенд: в fault _run_ready должен быть False"
    rig.sim.set("cam", ready=True, reasons=[])
    rig.sim.beat_now()
    reply = _call(pm._cmd_system_run_ack, "_cmd_system_run_ack")
    assert reply == {"success": True, "state": "ready", "error": None}, reply


@pytest.mark.timeout(60)
def test_ack_refreshes_run_ready(rig_factory) -> None:
    """Критерий 7 (КРАСНЫЙ): принятый ``ack`` со здоровой оценкой обновляет ``_run_ready`` в True."""
    rig = rig_factory()
    _fault_then_recover_and_ack(rig)

    assert rig.pm._run_ready is True


@pytest.mark.timeout(60)
def test_single_failed_tick_after_ack_stays_ready(rig_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Критерий 7 (КРАСНЫЙ): после ``ack`` -> ``ready`` один сбойный такт оставляет ``ready`` (не ``not_ready``)."""
    rig = rig_factory()
    _fault_then_recover_and_ack(rig)
    _break_eval(rig.pm, monkeypatch)

    _failing_tick(rig.monitor)

    assert rig.pm._run_state == "ready", f"одиночный сбойный такт после ack дал {rig.pm._run_state!r}"


# --------------------------------------------------------------------------- #
# 8. Охранный: no-op settled в running
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_noop_settled_keeps_run_ready_in_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """Критерий 8 (ОХРАННЫЙ): ``settled(ready=False)`` в ``running`` — no-op: состояние ``running`` и
    ``_run_ready is True`` не меняются; один сбойный такт — всё ещё ``running``."""
    pm, monitor = _healthy_running_pm()
    assert pm._run_ready is True

    pm._run_apply("settled", ready=False)

    assert pm._run_state == "running"
    assert pm._run_ready is True
    _break_eval(pm, monkeypatch)
    _failing_tick(monitor)
    assert pm._run_state == "running"
