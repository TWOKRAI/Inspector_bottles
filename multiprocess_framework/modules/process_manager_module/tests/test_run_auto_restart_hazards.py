# -*- coding: utf-8 -*-
"""Task 1.8 (system-run-state) — hazard-тесты автоперезапуска процесса в работе (автор реализации).

Слепые приёмочные тесты — ``test_run_state_auto_restart.py`` (чистая ``evaluate``) и ``test_run_auto_restart.py``
(PM + настоящий монитор). Здесь — то, что они не фиксируют: сброс записи окна при смене состояния, потокобезопасность
записи, приоритет «супервизор отказался» над истёкшим окном, негодный ``run_restart_grace_s``, независимость
процессов, флаг вне ``running``, утечка записи, сбой снимка супервизора.

Обвязка — как в ``test_run_auto_restart.py``: ``make_readiness_pm`` (PM + настоящий ``ProcessMonitor``), падение —
``_alive = False`` у двойника процесса. Возраст окна задаётся записью ``pm._run_down_since`` (не ``sleep``).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from pydantic import ValidationError

from ..core.restart_policy import RestartPolicy
from ..process import process_manager_process as pm_mod
from ..process import run_state as run_state_mod
from .test_run_commands import beat, make_readiness_pm

_FLAGGED = {"enabled": True, "run_auto_restart": True, "backoff_sec": 600.0}  # рестарт монитором не диспатчится
_RESTART = "перезапуск cam"
_JOIN_S = 20.0


def _pm(
    *names: str, flagged: set[str] | None = None, grace_s: float | None = None, run_gate: bool = True
) -> tuple[Any, Any]:
    """PM с процессами ``names``: из ``flagged`` — с флагом, остальные — без политики. ``run_gate=False`` — остановка
    в аварии «завершена» сразу (без потока, ждущего ``paused`` живых соседей)."""
    flagged = set(names) if flagged is None else flagged
    configs = {
        n: ({"class": "pkg.P", "restart_policy": dict(_FLAGGED)} if n in flagged else {"class": "pkg.P"}) for n in names
    }
    pm, monitor = make_readiness_pm(configs, run_gate=run_gate)
    if grace_s is not None:
        pm.update_config("run_restart_grace_s", grace_s)
    return pm, monitor


def _running(pm: Any, monitor: Any, *names: str) -> None:
    """Все ``names`` отчитались -> такт -> START -> ``running``."""
    for name in names:
        beat(monitor, name)
    _tick(monitor)
    assert pm._run_state == "ready", pm._cmd_system_run_status()
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}


def _tick(monitor: Any) -> None:
    """Такт монитора (``_log_error`` у настоящего «сдался» монитора допустим — проверки ошибок здесь нет)."""
    with monitor._iteration_lock:
        monitor._run_iteration()


def _crash(pm: Any, name: str) -> None:
    proc = pm._process_registry.get_process_by_name(name)
    proc._alive = False
    proc.exitcode = -9


def _revive(pm: Any, monitor: Any, name: str) -> None:
    proc = pm._process_registry.get_process_by_name(name)
    proc._alive = True
    proc.exitcode = None
    beat(monitor, name)


def _reason_texts(pm: Any) -> list[str]:
    return [r["reason"] for r in pm._cmd_system_run_status()["reasons"]]


# --------------------------------------------------------------------------- #
# 1. Запись окна не переживает running -> stopping -> ready
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_window_record_does_not_survive_running_stopping_ready() -> None:
    """``running``, ``cam`` упал, запись окна устарела (3600 с назад) -> STOP -> такт в ``stopping`` -> итог ``ready``
    -> START -> ``running``: запись снята тактом вне ``running``, и новое окно начинается заново (``running`` с причиной
    «перезапуск», не ``fault`` по устаревшей записи)."""
    pm, monitor = _pm("cam", grace_s=30.0)
    _running(pm, monitor, "cam")

    _crash(pm, "cam")
    _tick(monitor)
    assert list(pm._run_down_since) == ["cam"]
    pm._run_down_since = {"cam": time.time() - 3600.0}  # окно давно истекло

    pm._run_apply("stop")
    _tick(monitor)  # такт в stopping

    assert pm._run_state == "stopping"
    assert pm._run_down_since == {}, pm._run_down_since

    pm._run_apply("settled", ready=True)  # итог STOP: ready без такта (как гонка допуска)
    pm._run_apply("start", ready=True)
    _tick(monitor)

    assert pm._run_state == "running", pm._cmd_system_run_status()
    assert _reason_texts(pm) == [_RESTART]


# --------------------------------------------------------------------------- #
# 2. Параллельные такты: запись окна пишется под замком
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_parallel_ticks_keep_one_window_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Много потоков ведут окно одновременно (``restart_window`` замедлена — окно гонки «прочёл-записал» широкое):
    у упавшего ``cam`` ровно одно начало окна, оно не «прыгает» между тактами (иначе окно никогда бы не истекло)."""
    pm, monitor = _pm("cam")
    _running(pm, monitor, "cam")
    _crash(pm, "cam")

    real = run_state_mod.restart_window

    def slow(*args: Any, **kwargs: Any) -> dict:
        result = real(*args, **kwargs)
        time.sleep(0.002)  # другой поток успевает прочесть ту же старую запись
        return result

    monkeypatch.setattr(pm_mod, "restart_window", slow)
    seen: set[float] = set()
    seen_lock = threading.Lock()
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        try:
            barrier.wait(_JOIN_S)
            for _ in range(15):
                pm._evaluate_run_readiness(track_restart=True)
                started = pm._run_down_since.get("cam")
                if started is not None:
                    with seen_lock:
                        seen.add(started)
        except BaseException as exc:  # noqa: BLE001 — в поток теста
            errors.append(exc)

    threads = [threading.Thread(target=worker, daemon=True, name=f"window-tick-{i}") for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(_JOIN_S)
        assert not thread.is_alive(), f"поток {thread.name} завис дольше {_JOIN_S} с"

    assert errors == []
    assert len(seen) == 1, sorted(seen)


# --------------------------------------------------------------------------- #
# 3. «Супервизор отказался» выигрывает у истёкшего окна
# --------------------------------------------------------------------------- #


def test_given_up_wins_over_expired_window() -> None:
    """Окно истекло И супервизор отказался -> итоговая причина «cam: супервизор отказался от перезапуска» (не «не
    завершён за N с»: авария называет настоящую причину, а не следствие); за ней — деталь «процесс не жив»."""
    ready, reasons = run_state_mod.evaluate(
        ["cam"],
        {},
        {"cam": False},
        1000.0,
        3.0,
        running=True,
        auto_restart=frozenset({"cam"}),
        down_since={"cam": 1000.0 - 3600.0},
        grace_s=5.5,
        given_up=frozenset({"cam"}),
    )

    assert ready is False
    assert [(r["node"], r["severity"], r["source"], r["reason"]) for r in reasons] == [
        ("cam", "failure", "liveness", "cam: супервизор отказался от перезапуска"),
        ("cam", "failure", "liveness", "процесс не жив"),
    ]


# --------------------------------------------------------------------------- #
# 4. Негодный run_restart_grace_s -> умолчание 30 с
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    "bad",
    [0, -1.0, "10", True, float("nan"), float("inf"), [1]],
    ids=["zero", "negative", "str", "bool", "nan", "inf", "list"],
)
def test_bad_restart_grace_falls_back_to_default(bad: Any) -> None:
    """Негодное значение (0, <0, строка, bool, NaN, inf, список) -> окно 30 с и WARNING: запись окна возрастом 10 с
    держит ``running``; допустимое 5 с на той же записи даёт ``fault``."""
    pm, monitor = _pm("cam", grace_s=bad)
    _running(pm, monitor, "cam")
    _crash(pm, "cam")
    _tick(monitor)
    pm._run_down_since = {"cam": time.time() - 10.0}

    assert pm._run_restart_grace() == 30.0
    assert pm._log_warning.called
    _tick(monitor)
    assert pm._run_state == "running", pm._cmd_system_run_status()

    pm.update_config("run_restart_grace_s", 5.0)
    _tick(monitor)
    assert pm._run_state == "fault", pm._cmd_system_run_status()


# --------------------------------------------------------------------------- #
# 5. Несколько процессов с флагом — независимые окна
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_flagged_processes_have_independent_windows() -> None:
    """``a`` и ``b`` с флагом упали; ``a`` вернулся -> запись только у ``b``, и её начало не сдвинулось; у ``a``
    следующее падение открывает новое окно; ``c`` без флага упал бы в ``fault`` по своей причине, не по окну соседей."""
    pm, monitor = _pm("a", "b", "c", flagged={"a", "b"}, grace_s=30.0, run_gate=False)
    _running(pm, monitor, "a", "b", "c")

    _crash(pm, "a")
    _crash(pm, "b")
    _tick(monitor)
    assert sorted(pm._run_down_since) == ["a", "b"]
    b_started = pm._run_down_since["b"]
    assert pm._run_state == "running"

    _revive(pm, monitor, "a")
    beat(monitor, "c")
    _tick(monitor)
    assert pm._run_down_since == {"b": b_started}, pm._run_down_since
    assert pm._run_state == "running"

    pm._run_down_since = {"b": time.time() - 3600.0}  # окно b истекло, у a его нет
    _tick(monitor)
    assert pm._run_state == "fault"
    texts = [r["reason"] for r in pm._cmd_system_run_status()["last_fault"]["reasons"]]
    assert texts == ["b: перезапуск не завершён за 30 с", "процесс не жив"], texts  # у a и c причин нет


# --------------------------------------------------------------------------- #
# 6. Вне running флаг не действует: процесс без листа — failure, как без флага
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize("state", ["booting", "not_ready"])
def test_flag_is_inert_outside_running_for_process_without_leaf(state: str) -> None:
    """``cam`` без листа в ``booting`` / ``not_ready``: оценка с флагом (``enabled``) даёт те же причины, что без
    флага, — ``failure`` «нет отчёта о готовности», и записи окна нет."""
    results = []
    for flagged in (True, False):
        pm, monitor = _pm("cam", flagged={"cam"} if flagged else set())
        if state == "booting":
            pm._run_apply("apply")
        else:
            _tick(monitor)  # листа нет -> not_ready
        assert pm._run_state == state, pm._run_state
        results.append(pm._evaluate_run_readiness(track_restart=True))
        assert pm._run_down_since == {}, pm._run_down_since

    assert results[0] == results[1]
    ready, reasons = results[0]
    assert ready is False
    assert [(r["severity"], r["reason"]) for r in reasons] == [("failure", "нет отчёта о готовности")]


# --------------------------------------------------------------------------- #
# 7. Запись не растёт для вышедших из рецепта процессов
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_window_record_forgets_processes_gone_from_recipe_or_flag() -> None:
    """Упали ``a``, ``b``, ``c`` с флагом -> запись из трёх. ``b`` исчез из топологии, у ``c`` флаг снят: такт —
    запись только у ``a`` (утечки нет)."""
    pm, monitor = _pm("a", "b", "c", grace_s=30.0)
    _running(pm, monitor, "a", "b", "c")
    for name in ("a", "b", "c"):
        _crash(pm, name)
    _tick(monitor)
    assert sorted(pm._run_down_since) == ["a", "b", "c"]

    del pm._process_configs["b"]
    pm._process_configs["c"]["restart_policy"] = {"enabled": True, "run_auto_restart": False}
    _tick(monitor)

    assert sorted(pm._run_down_since) == ["a"], pm._run_down_since


# --------------------------------------------------------------------------- #
# 8. Сбой снимка супервизора не роняет тик
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_supervision_snapshot_error_does_not_break_tick() -> None:
    """``get_supervision_snapshot`` бросает: тик не падает, ошибка громкая (``_log_error``), «сдался» не виден, окно
    держит ``running`` с причиной «перезапуск»; предохранитель — по истечении окна тот же тик даёт ``fault``."""
    pm, monitor = _pm("cam", grace_s=30.0)
    _running(pm, monitor, "cam")

    def broken() -> dict:
        raise RuntimeError("снимок недоступен")

    monitor.get_supervision_snapshot = broken
    _crash(pm, "cam")
    pm._log_error.reset_mock()

    pm._run_readiness_tick()  # не бросает

    assert pm._run_state == "running"
    assert _reason_texts(pm) == [_RESTART]
    assert any("снимок супервизора" in str(c.args[0]) for c in pm._log_error.call_args_list)

    pm._run_down_since = {"cam": time.time() - 3600.0}
    pm._run_readiness_tick()

    assert pm._run_state == "fault"


# --------------------------------------------------------------------------- #
# 9. Истёкшее окно: last_fault объясняет, почему процесс не поднялся
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_last_fault_after_expired_window_keeps_leaf_detail() -> None:
    """``cam`` с флагом поднялся, но лист говорит «модель не загружена», окно истекло -> ``fault``: ``last_fault``
    содержит итоговую «cam: перезапуск не завершён за 30 с» и деталь листа «модель не загружена» (в этом порядке)."""
    pm, monitor = _pm("cam", grace_s=30.0, run_gate=False)
    _running(pm, monitor, "cam")
    detail = {"node": "cam.detect", "severity": "failure", "reason": "модель не загружена", "source": "plugin"}
    pm._run_down_since = {"cam": time.time() - 3600.0}  # окно истекло; процесс жив, лист свежий, но с failure
    beat(monitor, "cam", ready=False, reasons=[detail])

    _tick(monitor)

    assert pm._run_state == "fault", pm._cmd_system_run_status()
    texts = [r["reason"] for r in pm._cmd_system_run_status()["last_fault"]["reasons"]]
    assert texts == ["cam: перезапуск не завершён за 30 с", "модель не загружена"], texts


# --------------------------------------------------------------------------- #
# 10. Окно ведёт только тик монитора; остальные оценки его читают
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_only_monitor_tick_moves_restart_window() -> None:
    """Оценки вне тика (``_evaluate_run_readiness()``, START, ``ack``, итог подъёма) запись окна не пишут и не снимают:
    ``cam`` упал, такта не было -> записи нет, после оценок записи всё ещё нет; ``cam`` вернулся при записи
    ``{cam: 1.0}`` -> оценки её не снимают; снимает только тик."""
    pm, monitor = _pm("cam", grace_s=30.0, run_gate=False)
    _running(pm, monitor, "cam")

    def evaluations_outside_tick() -> None:
        pm._evaluate_run_readiness()
        pm._evaluate_run_readiness(admission=True)
        pm._cmd_system_run_start()
        pm._cmd_system_run_ack()
        pm._settle_run_state()

    _crash(pm, "cam")
    evaluations_outside_tick()
    assert pm._run_down_since == {}, pm._run_down_since  # падение без тика окна не открывает

    _tick(monitor)
    assert list(pm._run_down_since) == ["cam"]
    _revive(pm, monitor, "cam")
    pm._run_down_since = {"cam": 1.0}
    evaluations_outside_tick()
    assert pm._run_down_since == {"cam": 1.0}, pm._run_down_since  # возвращение без тика окна не закрывает

    _tick(monitor)
    assert pm._run_down_since == {}, pm._run_down_since


# --------------------------------------------------------------------------- #
# 11. Умолчание окна — 30 с (литерал, не через константу)
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_default_restart_grace_is_thirty_seconds() -> None:
    """Без ключа ``run_restart_grace_s`` окно 30.0 с: запись возрастом 10 с держит ``running``, возрастом 40 с даёт
    ``fault`` с «cam: перезапуск не завершён за 30 с». Чистая ``evaluate`` без ``grace_s`` — то же умолчание."""
    pm, monitor = _pm("cam", run_gate=False)
    _running(pm, monitor, "cam")
    _crash(pm, "cam")
    _tick(monitor)

    assert pm._run_restart_grace() == 30.0
    pm._run_down_since = {"cam": time.time() - 10.0}
    _tick(monitor)
    assert pm._run_state == "running", pm._cmd_system_run_status()

    pm._run_down_since = {"cam": time.time() - 40.0}
    _tick(monitor)
    assert pm._run_state == "fault"
    assert _reason_texts(pm)[0] == "cam: перезапуск не завершён за 30 с"

    kwargs: dict[str, Any] = {"running": True, "auto_restart": frozenset({"cam"})}
    ready_in, _ = run_state_mod.evaluate(["cam"], {}, {"cam": False}, 1000.0, 3.0, down_since={"cam": 990.0}, **kwargs)
    ready_out, _ = run_state_mod.evaluate(["cam"], {}, {"cam": False}, 1000.0, 3.0, down_since={"cam": 960.0}, **kwargs)
    assert (ready_in, ready_out) == (True, False)


# --------------------------------------------------------------------------- #
# Модель RestartPolicy: поле run_auto_restart (решение лида: объявлено в модели)
# --------------------------------------------------------------------------- #


def test_restart_policy_declares_run_auto_restart_default_false() -> None:
    """Поле объявлено: умолчание ``False``; ``True`` принимается из dict рецепта (как строит монитор), попадает в
    ``model_dump``; не-bool значение — ``ValidationError`` (не молча включённый флаг)."""
    assert "run_auto_restart" in RestartPolicy.model_fields
    assert RestartPolicy().run_auto_restart is False
    assert RestartPolicy().model_dump()["run_auto_restart"] is False

    policy = RestartPolicy(**{"enabled": True, "run_auto_restart": True})

    assert policy.run_auto_restart is True
    assert policy.model_dump()["run_auto_restart"] is True
    with pytest.raises(ValidationError):
        RestartPolicy(run_auto_restart="maybe")
