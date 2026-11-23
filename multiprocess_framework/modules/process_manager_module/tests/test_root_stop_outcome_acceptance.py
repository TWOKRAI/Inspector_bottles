# -*- coding: utf-8 -*-
"""Task 1.2 (gui-graceful-close) — слепая приёмка: итог по процессам на пути корня.

Написано ДО реализации по критериям A1-A6 брифа; реализация и документы плана не читались.

Контракт: пока PM закрывает детей на пути корня (системный стоп), запись процесса в ответе
``supervision.status`` несёт ``stop_outcome`` (``exited`` / ``terminated`` / ``killed`` / ``None`` — ещё жив),
``stop_deadline_at`` (``time.time()``: момент сигнала стопа ребёнку + окно его стопа) и ``stop_wave``
(``"main"`` у всех). После закрытия корня итог читается и через ``registry.stop_outcome(name)``.

Обвязка: ``Rig`` и ``FakeChild`` из ``test_pm_responsive_during_children_stop.py`` (настоящие PM-оркестратор,
``SharedResourcesManager``, ``ProcessRegistry.children_stop``; дети — фейковые, без spawn). Запросы идут настоящими
сообщениями ``supervision.status`` в системную очередь PM; после закрытия корня очередь уже не обслуживается, поэтому
там зовётся настоящий ``pm._cmd_supervision_status`` напрямую.
Окно стопа имени (``stop_window_s``) в реестре без spawn задаётся единственной точкой входа, не требующей процесса:
``ProcessRegistry._register_stop_window(name, {"stop_window_s": X})`` — той самой, что зовёт ``create_and_register``.

Ключи записи читаются ИНДЕКСОМ (``rec["stop_deadline_at"]``, не ``.get``): отсутствие ключа обязано краснить тест.
Ожидаемые значения — литералы. Всё, что может блокироваться, идёт в daemon-потоке с дедлайном join.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ..core.process_registry import ProcessRegistry
from ..process.process_manager_process import ProcessManagerProcess
from .test_pm_responsive_during_children_stop import FakeChild, Rig, _bounded

REPLY_DEADLINE_S = 8.0
ROOT_CLOSED_DEADLINE_S = 40.0
INFRA_S = 1.0  # сегмент infra ребёнка (INFRA_STOP_S): верхняя граница допуска срока
TOL_S = 1.0  # допуск срока: [сигнал + окно - 1 с; сигнал + окно + infra_s + 1 с]
FORCE_TOL_S = 1e-3  # «не позже system_stop.deadline_at»: только округление float


# --------------------------------------------------------------------------- #
# Помощники
# --------------------------------------------------------------------------- #


@pytest.fixture
def make_rig():
    rigs: list[Rig] = []

    def factory(graceful_s: float) -> Rig:
        rig = Rig(graceful_s)
        rigs.append(rig)
        rig.start()
        return rig

    try:
        yield factory
    finally:
        for rig in rigs:
            rig.close()


def _live_status(rig: Rig) -> dict:
    """Настоящий ``supervision.status`` через системную очередь PM: ``result`` ответа."""
    reply = rig.wait_reply(rig.send("supervision.status"), REPLY_DEADLINE_S)
    assert reply is not None, "supervision.status не получил ответа"
    result = reply.result
    assert isinstance(result, dict) and result.get("success") is True, reply.message
    return result


def _direct_status(pm: ProcessManagerProcess) -> dict:
    """Настоящий ``_cmd_supervision_status`` напрямую (после закрытия корня очередь PM не обслуживается)."""
    done, result, error = _bounded(pm._cmd_supervision_status, 10.0)
    assert done and error is None, repr(error)
    assert isinstance(result, dict) and result.get("success") is True, result
    return result


def _wall(rig: Rig, child: FakeChild) -> float:
    """Момент сигнала стопа ребёнку в ``time.time()`` (ребёнок пишет ``time.monotonic()``)."""
    assert child.t_stop_signal is not None, f"{child.name}: сигнала стопа ещё не было"
    return child.t_stop_signal + (time.time() - time.monotonic())


def _wait_listed(rig: Rig, *names: str) -> None:
    """Предусловие стенда: монитор (опрос 0,5 с) уже занёс имена в ``supervision.status``; на стопе монитор на паузе,
    и ребёнок, добавленный за один опрос до стопа, в ответе не появился бы вовсе."""
    assert rig.wait_until(lambda: set(names) <= set(_live_status(rig)["processes"]), 10.0), f"нет в статусе: {names}"


def _begin_stop(rig: Rig, *children: FakeChild, data: dict | None = None) -> None:
    """``system.shutdown`` и ожидание сигнала стопа каждому ребёнку: окно стопа открыто."""
    _wait_listed(rig, *(child.name for child in children))
    rig.send("system.shutdown", data)
    for child in children:
        assert rig.wait_until(lambda c=child: c.t_stop_signal is not None, 15.0), f"{child.name}: нет сигнала стопа"


def _close_root(rig: Rig) -> None:
    """Закрытие корня как у раннера (``stop_event`` -> ``stop()`` + ``close_root()``) и ожидание его конца."""
    rig.pm.stop_event.set()
    assert rig.wait_root_closed(ROOT_CLOSED_DEADLINE_S), "корень PM не закрылся за дедлайн"


def _assert_in_range(value: Any, lo: float, hi: float, what: str) -> None:
    assert isinstance(value, float), f"{what}: ожидался float (time.time()), получено {value!r}"
    assert lo <= value <= hi, f"{what}: {value:.3f} вне допуска [{lo:.3f}, {hi:.3f}]"


# --------------------------------------------------------------------------- #
# A1: посреди стопа умерший ребёнок — exited, живой упрямый — None
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(90)
def test_dead_child_shows_exited_while_neighbour_still_stops(make_rig) -> None:
    """Быстрый ребёнок вышел на сигнал, упрямый ещё жив (окно 5,0 с): в ответе первый ``exited``, второй ``None``."""
    rig = make_rig(5.0)
    quick = rig.add_child("quick", mode="slow", exit_after_s=0.2)
    stubborn = rig.add_child("stubborn", mode="terminate")
    _begin_stop(rig, quick, stubborn)
    assert rig.wait_until(lambda: quick.dead.is_set(), 5.0), "быстрый ребёнок не вышел"
    time.sleep(0.5)  # ход стопа и снимок монитора
    assert stubborn.is_alive(), "предусловие: упрямый ребёнок уже мёртв — окно стопа не воспроизведено"

    processes = _live_status(rig)["processes"]

    assert processes["quick"]["stop_outcome"] == "exited", processes["quick"]
    assert processes["stubborn"]["stop_outcome"] is None, processes["stubborn"]


# --------------------------------------------------------------------------- #
# A2: итоги после закрытия корня: terminated / killed (и exited как контроль)
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_stubborn_child_terminated_after_root_close(make_rig) -> None:
    """Окно 1,0 с. Упрямый (умирает на ``terminate``) -> ``terminated``; переживший terminate (умирает на ``kill``) ->
    ``killed``; вышедший сам -> ``exited``. Читаем через реестр и через ответ ``supervision.status``."""
    rig = make_rig(1.0)
    polite = rig.add_child("polite", mode="slow", exit_after_s=0.2)
    stubborn = rig.add_child("stubborn", mode="terminate")
    hard = rig.add_child("hard", mode="kill")
    _wait_listed(rig, "polite", "stubborn", "hard")

    _close_root(rig)

    assert stubborn.terminate_calls >= 1, "предусловие: terminate упрямому не понадобился"
    assert hard.dead.is_set() and polite.dead.is_set() and stubborn.dead.is_set(), "предусловие: не все дети мертвы"
    registry = rig.pm._process_registry
    assert registry.stop_outcome("stubborn") == "terminated", registry.stop_outcome("stubborn")
    assert registry.stop_outcome("hard") == "killed", registry.stop_outcome("hard")
    assert registry.stop_outcome("polite") == "exited", registry.stop_outcome("polite")

    processes = _direct_status(rig.pm)["processes"]
    assert processes["stubborn"]["stop_outcome"] == "terminated", processes["stubborn"]
    assert processes["hard"]["stop_outcome"] == "killed", processes["hard"]
    assert processes["polite"]["stop_outcome"] == "exited", processes["polite"]
    assert processes[rig.pm.name]["stop_outcome"] is None, processes[rig.pm.name]  # сам PM не ребёнок


# --------------------------------------------------------------------------- #
# A3: stop_deadline_at = реальный сигнал + окно имени
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_stop_deadline_at_uses_window_and_real_signal_time(make_rig) -> None:
    """``g`` = 4,0 с. Имя ``win`` с окном 2,0 с и ``plain`` без окна: до сигнала оба ``None``; после сигнала сроки
    в допуске и различаются; после смерти ``win`` срок не обнуляется; в режиме force срок не позже
    ``system_stop.deadline_at`` того же ответа."""
    rig = make_rig(4.0)
    win = rig.add_child("win", mode="terminate")
    plain = rig.add_child("plain", mode="terminate")
    rig.pm._process_registry._register_stop_window("win", {"stop_window_s": 2.0})

    _wait_listed(rig, "win", "plain")
    before = _live_status(rig)
    assert before["system_stop"] is None, before["system_stop"]
    assert before["processes"]["win"]["stop_deadline_at"] is None, before["processes"]["win"]
    assert before["processes"]["plain"]["stop_deadline_at"] is None, before["processes"]["plain"]

    _begin_stop(rig, win, plain)
    sig_win, sig_plain = _wall(rig, win), _wall(rig, plain)
    mid = _live_status(rig)["processes"]
    d_win, d_plain = mid["win"]["stop_deadline_at"], mid["plain"]["stop_deadline_at"]
    _assert_in_range(d_win, sig_win + 2.0 - TOL_S, sig_win + 2.0 + INFRA_S + TOL_S, "win (окно 2,0 с)")
    _assert_in_range(d_plain, sig_plain + 4.0 - TOL_S, sig_plain + 4.0 + INFRA_S + TOL_S, "plain (окно g = 4,0 с)")
    assert d_plain - d_win > 1.0, f"окна 2,0 и 4,0 с дали почти равные сроки: win={d_win:.3f}, plain={d_plain:.3f}"

    # win выходит на terminate (~2 с); plain ещё жив, PM отвечает.
    assert rig.wait_until(lambda: win.dead.is_set(), 10.0), "win не умер"
    assert plain.is_alive(), "предусловие: plain уже мёртв"
    after = _live_status(rig)["processes"]
    assert isinstance(after["win"]["stop_deadline_at"], float), f"срок обнулён после смерти: {after['win']}"
    assert abs(after["win"]["stop_deadline_at"] - d_win) <= 0.05, f"срок сдвинут после смерти: {after['win']}"

    # force: срок не позже system_stop.deadline_at
    frig = make_rig(4.0)
    fwin = frig.add_child("win", mode="terminate")
    fplain = frig.add_child("plain", mode="terminate")
    frig.pm._process_registry._register_stop_window("win", {"stop_window_s": 2.0})
    _begin_stop(frig, fwin, fplain, data={"mode": "force", "deadline_s": 1.5})
    result = _live_status(frig)
    stop_deadline = result["system_stop"]["deadline_at"]
    assert result["system_stop"]["mode"] == "force", result["system_stop"]
    for name in ("win", "plain"):
        value = result["processes"][name]["stop_deadline_at"]
        assert isinstance(value, float), f"force, {name}: срок не число: {value!r}"
        assert value <= stop_deadline + FORCE_TOL_S, (
            f"force, {name}: срок {value:.3f} позже deadline_at {stop_deadline:.3f}"
        )
        assert value > stop_deadline - 3.0, (
            f"force, {name}: срок {value:.3f} нереально ранний (deadline_at {stop_deadline:.3f})"
        )


# --------------------------------------------------------------------------- #
# A4: stop_wave
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(90)
def test_stop_wave_main_for_all(make_rig) -> None:
    """Каждая запись процесса имеет ``stop_wave == "main"``: и до стопа, и посреди стопа."""
    rig = make_rig(5.0)
    quick = rig.add_child("quick", mode="slow", exit_after_s=0.2)
    stubborn = rig.add_child("stubborn", mode="terminate")

    for label, processes in (("до стопа", _live_status(rig)["processes"]),):
        waves = {name: rec["stop_wave"] for name, rec in processes.items()}
        assert waves and set(waves.values()) == {"main"}, f"{label}: {waves}"

    _begin_stop(rig, quick, stubborn)
    processes = _live_status(rig)["processes"]
    waves = {name: rec["stop_wave"] for name, rec in processes.items()}
    assert {"quick", "stubborn"} <= set(waves), waves
    assert set(waves.values()) == {"main"}, f"посреди стопа: {waves}"


# --------------------------------------------------------------------------- #
# A5: без стопа / PM через __new__ / реестр без стопа
# --------------------------------------------------------------------------- #


def _bare_pm(registry: Any = None) -> ProcessManagerProcess:
    """PM как в ``test_supervision_status_system_stop``: ``__new__`` без ``__init__``, только поля supervision."""
    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pm.name = "ProcessManager"
    pm._routing_epoch = 3
    pm._incarnations = {"camera": 2}
    monitor = MagicMock()
    monitor.get_supervision_snapshot.return_value = {
        "camera": {"status": "running", "last_exit": None, "restart_count": 1}
    }
    pm._process_monitor = monitor
    if registry is not None:
        pm._process_registry = registry
    return pm


@pytest.mark.timeout(90)
def test_no_stop_gives_null_and_new_pm_does_not_crash(make_rig) -> None:
    """Без стопа ``stop_outcome`` и ``stop_deadline_at`` есть в каждой записи и равны ``None``: на живом PM, на PM
    через ``__new__`` (без ``__init__``, без реестра) и на PM с реестром, где стопа не было; запись самого PM —
    ``stop_outcome`` ``None``."""
    # 1. живой PM без стопа
    rig = make_rig(5.0)
    rig.add_child("kid", mode="terminate")
    _wait_listed(rig, "kid")
    live = _live_status(rig)
    assert live["system_stop"] is None, live["system_stop"]
    for name, rec in live["processes"].items():
        assert rec["stop_outcome"] is None, f"живой PM, {name}: {rec}"
        assert rec["stop_deadline_at"] is None, f"живой PM, {name}: {rec}"
    assert "kid" in live["processes"] and rig.pm.name in live["processes"], sorted(live["processes"])

    # 2. PM через __new__: нет ни реестра, ни атрибутов __init__ — не падает, ключи есть
    bare = _direct_status(_bare_pm())["processes"]["camera"]
    assert bare["stop_outcome"] is None, bare
    assert bare["stop_deadline_at"] is None, bare

    # 3. PM с настоящим реестром без стопа (процесс в реестре есть, стопа не было)
    registry = ProcessRegistry()
    child = FakeChild("camera", [], mode="terminate")
    registry.add_process(child)
    plain = _direct_status(_bare_pm(registry))["processes"]["camera"]
    assert plain["stop_outcome"] is None, plain
    assert plain["stop_deadline_at"] is None, plain
    own = _direct_status(_bare_pm(registry))["processes"]
    assert "stop_outcome" in own["camera"] and "stop_deadline_at" in own["camera"], own


# --------------------------------------------------------------------------- #
# A6: умерший ДО стопа ребёнок — exited
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(90)
def test_child_dead_before_stop_gets_exited(make_rig) -> None:
    """Ребёнок умер до ``system.shutdown``; посреди стопа (упрямый сосед жив) его ``stop_outcome == "exited"``."""
    rig = make_rig(5.0)
    gone = rig.add_child("gone", mode="slow", exit_after_s=0.0)
    stubborn = rig.add_child("stubborn", mode="terminate")
    _wait_listed(rig, "gone", "stubborn")
    gone._die(0)  # умер до начала системного стопа
    assert not gone.is_alive(), "предусловие: ребёнок жив до стопа"
    _begin_stop(rig, stubborn)
    time.sleep(0.5)  # ход стопа и снимок монитора
    assert stubborn.is_alive(), "предусловие: упрямый ребёнок уже мёртв — окно стопа не воспроизведено"
    assert rig.pm._process_registry.get_process_by_name("gone") is gone, "предусловие: умерший ребёнок заменён"

    processes = _live_status(rig)["processes"]

    assert processes["gone"]["stop_outcome"] == "exited", processes["gone"]
    assert processes["stubborn"]["stop_outcome"] is None, processes["stubborn"]
